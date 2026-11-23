"""SCRUM-41 · Monitoreo del webhook de WhatsApp: enterarse si falla o deja de recibir mensajes.

Cada 5 minutos (Celery beat) `vigilar()`:
  1. Lee rumbo.estado_webhook() como 'sistema'.
  2. `evaluar()` decide las alertas (función pura, se prueba sin base):
       · atascados    → hay mensajes válidos sin procesar hace más de 5 min (worker caído o error).
       · agotados     → algún mensaje agotó los 10 reintentos: no entró al sistema.
       · silencio     → en horario de atención no llega ningún mensaje hace más de N minutos
                         (WEBHOOK_MINUTOS_SILENCIO, 180 por defecto: con 10-15 leads al día, 2 h sin mensajes puede ser normal). Cuenta desde la apertura del turno.
       · firmas       → muchas firmas inválidas en 1 h (clave secreta de Meta mal configurada o ataque).
  3. Cada alerta: log ERROR en "rumbo.monitoreo" (llega a Sentry si SENTRY_DSN está configurado),
     notificación en la campana de los administradores y correo a RUMBO_ALERTAS_CORREO (si hay EMAIL_HOST).
     La misma alerta se repite como mucho una vez por hora.
  4. Deja un latido en Redis: /salud/?completo=1 responde 503 si la vigilancia dejó de correr
     (worker o beat caídos), así lo detecta el monitor de disponibilidad externo.
"""
import datetime as dt
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .db import como_sistema

logger = logging.getLogger("rumbo.monitoreo")

CLAVE_LATIDO = "rumbo:latido:vigilancia"
LATIDO_VENCE = dt.timedelta(minutes=15)     # beat corre cada 5 min: 3 vueltas perdidas = algo está caído


def leer_estado(cursor=None):
    sql = "SELECT * FROM rumbo.estado_webhook()"
    if cursor is None:
        with como_sistema() as c:
            c.execute(sql)
            columnas = [x.name for x in c.description]
            return dict(zip(columnas, c.fetchone()))
    cursor.execute(sql)
    columnas = [x.name for x in cursor.description]
    return dict(zip(columnas, cursor.fetchone()))


def evaluar(estado, ahora, minutos_silencio=180, max_firmas_invalidas=20):
    """[(clave, titulo, mensaje)] de las alertas que corresponden a este estado."""
    alertas = []
    if estado.get("atascados"):
        n = estado["atascados"]
        alertas.append(("webhook_atascados", "WhatsApp: mensajes sin procesar",
                        f"{n} mensaje{'s' if n != 1 else ''} de clientes lleva{'n' if n != 1 else ''} más de 5 minutos "
                        "sin entrar a Rumbo. Revise que el worker de Celery esté funcionando."
                        + (f" Último error: {estado['ultimo_error']}" if estado.get("ultimo_error") else "")))
    if estado.get("agotados_24h"):
        n = estado["agotados_24h"]
        alertas.append(("webhook_agotados", "WhatsApp: mensajes que no entraron",
                        f"{n} mensaje{'s' if n != 1 else ''} agotó los 10 reintentos en las últimas 24 h y no creó "
                        "ni actualizó el lead. Revise el error en la bandeja del webhook."
                        + (f" Último error: {estado['ultimo_error']}" if estado.get("ultimo_error") else "")))
    if estado.get("en_horario"):
        # Dentro del turno: el silencio cuenta desde lo último que llegó, pero nunca desde antes de abrir.
        desde = max(filter(None, [estado.get("ultimo_valido_en"), estado.get("abierto_desde")]), default=None)
        if desde and ahora - desde > dt.timedelta(minutes=minutos_silencio):
            horas = int((ahora - desde).total_seconds() // 3600)
            hace = f"{horas} h" if horas else f"{int((ahora - desde).total_seconds() // 60)} min"
            alertas.append(("webhook_silencio", "WhatsApp: no llegan mensajes",
                            f"No llega ningún mensaje de clientes hace {hace}, en horario de atención. Revise en Meta "
                            "que el webhook siga suscrito y que el token no haya vencido."))
    if (estado.get("firmas_invalidas_1h") or 0) >= max_firmas_invalidas:
        alertas.append(("webhook_firmas", "WhatsApp: firmas inválidas",
                        f"{estado['firmas_invalidas_1h']} peticiones al webhook con firma inválida en la última hora. "
                        "Puede ser la clave secreta de la app (WHATSAPP_APP_SECRET) mal configurada o alguien "
                        "intentando enviar mensajes falsos."))
    return alertas


def _redis():
    import redis

    return redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)


def latir(ahora=None):
    try:
        _redis().set(CLAVE_LATIDO, (ahora or timezone.now()).isoformat(), ex=int(LATIDO_VENCE.total_seconds() * 4))
    except Exception:  # noqa: BLE001 — sin Redis no hay latido; /salud/?completo=1 lo reportará
        logger.exception("No se pudo guardar el latido de la vigilancia en Redis")


def ultimo_latido():
    """datetime del último latido, o None (nunca corrió o Redis no responde)."""
    try:
        valor = _redis().get(CLAVE_LATIDO)
    except Exception:  # noqa: BLE001
        return None
    return dt.datetime.fromisoformat(valor.decode()) if valor else None


def _avisar(alertas, ahora):
    hora = timezone.localtime(ahora).strftime("%Y-%m-%dT%H")       # una vez por hora por alerta
    nuevas = []
    with como_sistema() as c:
        for clave, titulo, mensaje in alertas:
            c.execute("SELECT rumbo.alertar_admins(%s, %s, %s, %s)", [f"{clave}:{hora}", titulo, mensaje, "/leads/metricas/"])
            if c.fetchone()[0]:
                nuevas.append((clave, titulo, mensaje))
    destinatarios = [x.strip() for x in getattr(settings, "RUMBO_ALERTAS_CORREO", []) if x.strip()]
    if nuevas and destinatarios and settings.EMAIL_HOST:
        try:
            send_mail("Rumbo · " + "; ".join(t for _c, t, _m in nuevas),
                      "\n\n".join(f"{t}\n{m}" for _c, t, m in nuevas), None, destinatarios, fail_silently=False)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo enviar el correo de alerta")
    return nuevas


def vigilar(ahora=None):
    ahora = ahora or timezone.now()
    estado = leer_estado()
    alertas = evaluar(estado, ahora, minutos_silencio=settings.WEBHOOK_MINUTOS_SILENCIO)
    for clave, titulo, mensaje in alertas:
        logger.error("Alerta %s · %s · %s", clave, titulo, mensaje)
    nuevas = _avisar(alertas, ahora) if alertas else []
    latir(ahora)
    return {"alertas": [a[0] for a in alertas], "avisadas": [a[0] for a in nuevas]}
