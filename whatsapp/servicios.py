"""Bandeja de entrada del webhook (patrón inbox):

1. El endpoint guarda el evento crudo con rumbo.recibir_evento_webhook y responde 200.
2. Un worker de Celery toma los eventos pendientes (SKIP LOCKED), registra cada mensaje
   con rumbo.registrar_mensaje_entrante (crea el lead y reparte) y marca el evento.
Si el worker falla, el evento sigue pendiente y se reintenta (máx. 10 veces, ver 006).
"""
import hashlib
import json
import logging
from functools import partial

from django.db import transaction
from psycopg.types.json import Jsonb

from core.db import como_sistema

from .parser import extraer_mensajes

logger = logging.getLogger("rumbo.whatsapp")


class NumeroDesconocido(LookupError):
    pass


def clave_idempotencia(cuerpo: bytes) -> str:
    # Meta reenvía exactamente el mismo cuerpo cuando reintenta: mismo hash, mismo evento.
    return hashlib.sha256(cuerpo).hexdigest()


def guardar_evento(cuerpo: bytes, payload: dict) -> int | None:
    """Guarda el evento firmado. Devuelve su id, o None si ya se había recibido."""
    with como_sistema() as cursor:
        cursor.execute(
            "SELECT rumbo.recibir_evento_webhook(%s, true, %s)",
            [clave_idempotencia(cuerpo), Jsonb(payload)],
        )
        return cursor.fetchone()[0]


def _numero_whatsapp_id(cursor, mensaje) -> int:
    cursor.execute(
        """SELECT id FROM rumbo.numero_whatsapp
           WHERE activo AND (meta_phone_number_id = %s OR telefono = %s)
           ORDER BY (meta_phone_number_id IS NOT DISTINCT FROM %s) DESC, id
           LIMIT 1""",
        [mensaje.phone_number_id, mensaje.numero_destino, mensaje.phone_number_id],
    )
    fila = cursor.fetchone()
    if not fila:
        raise NumeroDesconocido(
            f"Número de WhatsApp no registrado: phone_number_id={mensaje.phone_number_id} "
            f"display={mensaje.numero_destino}. Cárguelo en rumbo.numero_whatsapp."
        )
    return fila[0]


def procesar_payload(cursor, payload: dict) -> list[tuple]:
    resultados = []
    for mensaje in extraer_mensajes(payload):
        numero_id = _numero_whatsapp_id(cursor, mensaje)
        cursor.execute(
            "SELECT * FROM rumbo.registrar_mensaje_entrante(%s, %s, %s, %s::smallint, %s, %s, %s, %s)",
            [mensaje.wa_message_id, mensaje.telefono, mensaje.nombre_perfil, numero_id,
             mensaje.tipo, mensaje.cuerpo, Jsonb(mensaje.payload), mensaje.ocurrido_en],
        )
        resultado = cursor.fetchone()
        resultados.append(resultado)
        logger.info("Mensaje %s → lead %s (nuevo=%s, mensaje_nuevo=%s, asesor=%s)",
                    mensaje.wa_message_id, *resultado)
        lead_id, lead_nuevo, mensaje_nuevo, _ = resultado
        if lead_nuevo and mensaje_nuevo:
            # RF-04: se encola al confirmar; si este evento se deshace (savepoint), no se envía nada.
            transaction.on_commit(partial(_encolar_respuesta, lead_id, mensaje.phone_number_id))
    return resultados


def _encolar_respuesta(lead_id, phone_number_id):
    from .tasks import enviar_respuesta_automatica

    try:
        enviar_respuesta_automatica.delay(lead_id, phone_number_id)
    except Exception:  # noqa: BLE001 — sin Redis no hay worker; queda en el log para reenviar a mano
        logger.exception("No se pudo encolar la respuesta automática del lead %s", lead_id)


def procesar_pendientes(lote: int = 10) -> dict:
    """Procesa un lote de eventos. Cada evento en su propio savepoint: uno que falla no
    deshace los demás y queda con su error para reintentarse."""
    procesados = fallidos = 0
    with como_sistema() as cursor:
        cursor.execute("SELECT id, payload FROM rumbo.tomar_eventos_webhook(%s)", [lote])
        eventos = cursor.fetchall()
        for evento_id, payload in eventos:
            try:
                if isinstance(payload, str):  # el backend de Django entrega jsonb como texto
                    payload = json.loads(payload)
                with transaction.atomic():
                    procesar_payload(cursor, payload)
            except Exception as exc:  # noqa: BLE001 — se guarda el error y se reintenta luego
                fallidos += 1
                logger.exception("Error procesando el evento de webhook %s", evento_id)
                cursor.execute("SELECT rumbo.marcar_evento_webhook(%s, %s)",
                               [evento_id, f"{type(exc).__name__}: {exc}"])
            else:
                procesados += 1
                cursor.execute("SELECT rumbo.marcar_evento_webhook(%s, NULL)", [evento_id])
    return {"tomados": len(eventos), "procesados": procesados, "fallidos": fallidos}
