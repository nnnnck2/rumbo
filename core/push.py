"""SCRUM-122 · Notificaciones push (Web Push) para Rumbo instalado en el celular o abierto en segundo plano.

Las notificaciones las crea la base (rumbo.notificacion). Celery, cada 20 s, toma las nuevas que tienen
alguna suscripción (rumbo.tomar_notificaciones_push, como mucho una vez cada una) y las envía con pywebpush.
Una suscripción que el navegador dio de baja (404/410) se borra.

Claves VAPID por variables de entorno (generarlas con: python manage.py generar_claves_push):
    WEBPUSH_VAPID_PUBLIC_KEY, WEBPUSH_VAPID_PRIVATE_KEY, WEBPUSH_CONTACTO (mailto:…)
"""
import json
import logging

from django.conf import settings

from .db import como_sistema

logger = logging.getLogger("rumbo.push")


def configurado():
    return bool(settings.WEBPUSH_VAPID_PUBLIC_KEY and settings.WEBPUSH_VAPID_PRIVATE_KEY)


def armar_aviso(titulo, mensaje, url):
    return json.dumps({"titulo": titulo, "mensaje": mensaje or "", "url": url or "/notificaciones/"}, ensure_ascii=False)


def enviar_pendientes():
    if not configurado():
        return {"omitido": "faltan las claves VAPID"}
    from pywebpush import WebPushException, webpush

    with como_sistema() as cursor:
        cursor.execute("SELECT id, titulo, mensaje, url, suscripciones FROM rumbo.tomar_notificaciones_push(50)")
        filas = cursor.fetchall()
    enviados = fallidos = 0
    vencidas = []
    for _id, titulo, mensaje, url, suscripciones in filas:
        if isinstance(suscripciones, str):
            suscripciones = json.loads(suscripciones)
        datos = armar_aviso(titulo, mensaje, url)
        for s in suscripciones or []:
            try:
                webpush(subscription_info={"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                        data=datos, vapid_private_key=settings.WEBPUSH_VAPID_PRIVATE_KEY,
                        vapid_claims={"sub": settings.WEBPUSH_CONTACTO}, ttl=600, timeout=10)
                enviados += 1
            except WebPushException as e:
                codigo = getattr(e.response, "status_code", None)
                if codigo in (404, 410):
                    vencidas.append(s["endpoint"])
                else:
                    fallidos += 1
                    logger.warning("Push no enviado (%s): %s", codigo, e)
            except Exception:  # noqa: BLE001 — red u otro error: no detener el resto
                fallidos += 1
                logger.exception("Push no enviado")
    if vencidas:
        with como_sistema() as cursor:
            for endpoint in vencidas:
                cursor.execute("SELECT rumbo.borrar_suscripcion_push(%s)", [endpoint])
    return {"notificaciones": len(filas), "enviados": enviados, "fallidos": fallidos, "bajas": len(vencidas)}
