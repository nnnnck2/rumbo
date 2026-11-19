"""SCRUM-88 · WhatsApp automático cuando el cliente no contesta la llamada.

Al registrar "No contesta / buzón", la vista encola el envío (al confirmar la transacción). El envío:
  1. Lee la clave aviso_no_contesta de rumbo.configuracion (activo, texto, plantilla, idioma, horas_entre).
  2. No envía si está desactivado, si ya se avisó a este cliente hace menos de `horas_entre` horas o si
     el lead ya no está abierto.
  3. Ventana de 24 h abierta (el cliente escribió hace menos de 24 h): envía el texto, con {nombre} y
     {asesor} reemplazados. Ventana cerrada: Meta solo acepta plantillas aprobadas → usa la plantilla
     configurada o, si no hay, no envía (queda en el log).
  4. Lo registra como mensaje saliente automático del lead (sale por el número al que escribió el cliente).
"""
import datetime as dt
import json
import logging
import re

from django.utils import timezone
from psycopg.types.json import Jsonb

from core.db import como_sistema

from . import cliente
from .respuesta_automatica import LIMITE, EnvioFallido

logger = logging.getLogger("rumbo.whatsapp")

VENTANA = dt.timedelta(hours=24)


def componer(texto, nombre, asesor):
    """Reemplaza {nombre} y {asesor}. Llaves sueltas o desconocidas se dejan como están."""
    nombre = (nombre or "").strip()
    reemplazos = {"{nombre}": nombre.split()[0] if nombre else "", "{asesor}": (asesor or "su asesor").strip()}
    for clave, valor in reemplazos.items():
        texto = texto.replace(clave, valor)
    texto = re.sub(r"[ \t]+", " ", texto)             # sin nombre: "Hola , le saluda" → "Hola, le saluda"
    texto = re.sub(r" +([,.!?])", r"\1", texto)
    return texto.strip()[:LIMITE]


_SQL_ESTADO = (
            """SELECT l.telefono, l.nombre_perfil, n.meta_phone_number_id, l.estado_asignacion::text,
                      (SELECT max(m.ocurrido_en) FROM rumbo.mensaje_whatsapp m
                       WHERE m.lead_id = l.id AND m.direccion = 'entrante') AS ultimo_entrante,
                      (SELECT max(m.ocurrido_en) FROM rumbo.mensaje_whatsapp m
                       WHERE m.lead_id = l.id AND m.direccion = 'saliente' AND m.payload ? 'aviso_no_contesta') AS ultimo_aviso,
                      (SELECT u.nombre FROM rumbo.usuario u WHERE u.id = %s) AS asesor,
                      (SELECT c.valor FROM rumbo.configuracion c WHERE c.clave = 'aviso_no_contesta') AS config
               FROM rumbo.lead l LEFT JOIN rumbo.numero_whatsapp n ON n.id = l.numero_whatsapp_id
               WHERE l.id = %s""")


def _leer_estado(lead_id, usuario_id, cursor=None):
    """Datos para decidir el aviso. Sin cursor: como 'sistema' (worker). Con cursor: el del request,
    con el contexto RLS del usuario (nunca se cambia el contexto del request a 'sistema')."""
    if cursor is None:
        with como_sistema() as c:
            c.execute(_SQL_ESTADO, [usuario_id, lead_id])
            fila = c.fetchone()
    else:
        cursor.execute(_SQL_ESTADO, [usuario_id, lead_id])
        fila = cursor.fetchone()
    if fila is None:
        return None
    columnas = ("telefono", "nombre", "pnid", "estado", "ultimo_entrante", "ultimo_aviso", "asesor", "config")
    estado = dict(zip(columnas, fila))
    if isinstance(estado["config"], str):
        estado["config"] = json.loads(estado["config"])
    estado["config"] = estado["config"] or {}
    return estado


def decidir(estado, ahora):
    """Qué enviar: ("texto", cuerpo) | ("plantilla", None) | ("nada", motivo). Sin efectos (se prueba solo)."""
    config = estado["config"]
    if not config.get("activo"):
        return "nada", "desactivado"
    if estado["estado"] == "cerrado":
        return "nada", "lead cerrado"
    horas = int(config.get("horas_entre") or 24)
    if estado["ultimo_aviso"] and ahora - estado["ultimo_aviso"] < dt.timedelta(hours=horas):
        return "nada", f"ya se avisó hace menos de {horas} h"
    if estado["ultimo_entrante"] and ahora - estado["ultimo_entrante"] < VENTANA:
        return "texto", componer(config.get("texto") or "", estado["nombre"], estado["asesor"])
    if config.get("plantilla"):
        return "plantilla", None
    return "nada", "ventana de 24 h cerrada y sin plantilla configurada"


MOTIVOS = {
    "desactivado": "el aviso automático está desactivado",
    "lead cerrado": "el cliente ya no está abierto",
}


def _estado_del_request(lead_id, usuario_id):
    from django.db import connection

    with connection.cursor() as cursor:
        return _leer_estado(lead_id, usuario_id, cursor)


def prever(lead_id, usuario_id):
    """SCRUM-104 · Qué va a pasar con el aviso, para decírselo al asesor al registrar la llamada.
    Devuelve (se_envia: bool, texto). Usa la conexión del request (RLS del asesor)."""
    estado = _estado_del_request(lead_id, usuario_id)
    if estado is None:
        return False, ""
    tipo, contenido = decidir(estado, timezone.now())
    nombre = (estado["nombre"] or "").split()
    quien = nombre[0] if nombre else "el cliente"
    if tipo == "texto":
        return True, f"Rumbo le envía un WhatsApp a {quien} avisando que lo llamó."
    if tipo == "plantilla":
        return True, f"Rumbo le envía a {quien} la plantilla de WhatsApp «{estado['config'].get('plantilla')}»."
    if contenido.startswith("ya se avisó"):
        return False, f"No se envió WhatsApp: a {quien} ya se le avisó hace poco."
    if contenido.startswith("ventana"):
        return False, (f"No se envió WhatsApp: {quien} no escribe hace más de 24 h y no hay plantilla de Meta "
                       "configurada.")
    return False, f"No se envió WhatsApp: {MOTIVOS.get(contenido, contenido)}."


def enviar(lead_id, usuario_id=None):
    """Envía el aviso. Devuelve qué pasó (para el log/resultado de Celery)."""
    estado = _leer_estado(lead_id, usuario_id)
    if estado is None:
        return "lead inexistente"
    tipo, contenido = decidir(estado, timezone.now())
    if tipo == "nada":
        return f"no enviado: {contenido}"
    if not estado["pnid"]:
        logger.warning("Aviso de no contesta no enviado: el número de entrada del lead %s no tiene meta_phone_number_id",
                       lead_id)
        return "sin phone_number_id"

    config = estado["config"]
    if tipo == "texto":
        cuerpo, registro = cliente.cuerpo_texto(estado["telefono"], contenido), contenido
    else:
        cuerpo = cliente.cuerpo_plantilla(estado["telefono"], config["plantilla"], config.get("idioma") or "es")
        registro = f"[plantilla {config['plantilla']}]"
    try:
        status, respuesta = cliente.llamar_api(estado["pnid"], cuerpo)
    except cliente.SinToken:
        logger.warning("Aviso de no contesta no enviado al lead %s: falta WHATSAPP_ACCESS_TOKEN", lead_id)
        return "sin token"
    except OSError as e:
        raise EnvioFallido(f"Error de red al enviar: {e}", reintentar=True) from e

    wamid = cliente.wamid(respuesta)
    if status != 200 or not wamid:
        error = respuesta.get("error", {})
        raise EnvioFallido(f"Meta respondió {status}: {error.get('message')} (código {error.get('code')})",
                           reintentar=status == 429 or status >= 500)

    with como_sistema() as cursor:
        cursor.execute("SELECT rumbo.registrar_mensaje_automatico(%s, %s, %s, %s, %s)",
                       [lead_id, wamid, registro, "text" if tipo == "texto" else "template",
                        Jsonb({"aviso_no_contesta": True})])
    logger.info("Aviso de no contesta (%s) enviado al lead %s · %s", tipo, lead_id, wamid)
    return f"enviado ({tipo})"
