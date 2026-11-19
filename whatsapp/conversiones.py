"""SCRUM-92 · Conversiones para Meta (Conversions API, eventos de mensajería de WhatsApp).

Cuando un lead que llegó desde un anuncio Click-to-WhatsApp pasa a "Cita agendada" o "Cerrado (venta)",
la base deja un evento pendiente en rumbo.evento_conversion (018). Este módulo los envía a Meta para que
optimice los anuncios hacia clientes que agendan y compran, no solo hacia los que escriben.

    POST https://graph.facebook.com/{versión}/{META_DATASET_ID}/events
    {"data": [{"event_name": "Purchase", "event_time": …, "action_source": "business_messaging",
               "messaging_channel": "whatsapp", "event_id": "rumbo-15",
               "user_data": {"whatsapp_business_account_id": …, "ctwa_clid": …, "ph": [sha256]},
               "custom_data": {"currency": "USD", "value": 350}}]}

Privacidad (LOPDP): a Meta solo va el teléfono con hash SHA-256, el id del clic y el valor.
Sin META_DATASET_ID / META_CAPI_TOKEN / META_WABA_ID no se envía nada y los eventos esperan (Meta
acepta hasta 7 días de atraso; después la base los marca vencidos).
"""
import hashlib
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from core.db import como_sistema

logger = logging.getLogger("rumbo.whatsapp")

GRAPH = "https://graph.facebook.com"


def configurado():
    return bool(settings.META_DATASET_ID and settings.META_CAPI_TOKEN and settings.META_WABA_ID)


def hash_telefono(telefono):
    """Meta pide el teléfono solo con dígitos (con código de país) y en SHA-256."""
    digitos = "".join(c for c in (telefono or "") if c.isdigit())
    return hashlib.sha256(digitos.encode()).hexdigest()


def armar_evento(fila):
    """Evento de la Conversions API a partir de una fila de rumbo.tomar_eventos_conversion()."""
    evento = {
        "event_name": fila["evento"],
        "event_time": int(fila["ocurrido_en"].timestamp()),
        "event_id": f"rumbo-{fila['id']}",                  # Meta descarta duplicados con el mismo id
        "action_source": "business_messaging",
        "messaging_channel": "whatsapp",
        "user_data": {
            "whatsapp_business_account_id": settings.META_WABA_ID,
            "ctwa_clid": fila["ctwa_clid"],
            "ph": [hash_telefono(fila["telefono"])],
        },
    }
    if fila["evento"] == "Purchase" and fila.get("valor") is not None:
        evento["custom_data"] = {"currency": fila.get("moneda") or "USD", "value": float(fila["valor"])}
    return evento


def _publicar(eventos, timeout=20):
    cuerpo = {"data": eventos}
    if settings.META_CAPI_TEST_CODE:                          # para probar en "Eventos de prueba" de Meta
        cuerpo["test_event_code"] = settings.META_CAPI_TEST_CODE
    peticion = urllib.request.Request(
        f"{GRAPH}/{settings.WHATSAPP_API_VERSION}/{settings.META_DATASET_ID}/events",
        data=json.dumps(cuerpo).encode(),
        headers={"Authorization": f"Bearer {settings.META_CAPI_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {"error": {"message": e.reason}}


def enviar_pendientes(lote=20):
    """Toma y envía un lote. Devuelve {"tomados", "enviados", "fallidos"} (o el motivo si no se envía)."""
    if not configurado():
        return {"omitido": "faltan META_DATASET_ID, META_CAPI_TOKEN o META_WABA_ID"}
    with como_sistema() as cursor:
        cursor.execute("SELECT id, lead_id, evento, ctwa_clid, ocurrido_en, telefono, valor, moneda "
                       "FROM rumbo.tomar_eventos_conversion(%s)", [lote])
        columnas = [c.name for c in cursor.description]
        filas = [dict(zip(columnas, f)) for f in cursor.fetchall()]
    if not filas:
        return {"tomados": 0, "enviados": 0, "fallidos": 0}

    try:
        status, respuesta = _publicar([armar_evento(f) for f in filas])
        error, definitivo = None, False
        if status != 200:
            detalle = respuesta.get("error", {})
            error = f"Meta respondió {status}: {detalle.get('message')} (código {detalle.get('code')})"
            definitivo = 400 <= status < 500 and status != 429     # datos/permisos: reintentar no sirve
    except OSError as e:
        error, definitivo = f"Error de red: {e}", False

    with como_sistema() as cursor:
        for f in filas:
            cursor.execute("SELECT rumbo.marcar_evento_conversion(%s, %s, %s)", [f["id"], error, definitivo])
    if error:
        logger.error("Conversiones para Meta no enviadas (%s eventos): %s", len(filas), error)
        return {"tomados": len(filas), "enviados": 0, "fallidos": len(filas)}
    logger.info("Conversiones enviadas a Meta: %s", [f"{f['evento']}#{f['lead_id']}" for f in filas])
    return {"tomados": len(filas), "enviados": len(filas), "fallidos": 0}
