import logging

from celery import shared_task

from . import respuesta_automatica
from .servicios import procesar_pendientes

logger = logging.getLogger("rumbo.whatsapp")

LOTE = 10
MAX_LOTES = 20


@shared_task(name="whatsapp.procesar_eventos_webhook")
def procesar_eventos_webhook():
    """Vacía la bandeja del webhook por lotes. Lo encola el endpoint al recibir un evento y
    Celery beat lo ejecuta cada 30 s como red de seguridad."""
    total = {"tomados": 0, "procesados": 0, "fallidos": 0}
    for _ in range(MAX_LOTES):
        lote = procesar_pendientes(LOTE)
        for clave in total:
            total[clave] += lote[clave]
        # Lote incompleto = no quedan más; lote con fallos = no insistir en el mismo ciclo.
        if lote["tomados"] < LOTE or lote["fallidos"]:
            break
    if total["tomados"]:
        logger.info("Bandeja del webhook: %s", total)
    return total


@shared_task(name="whatsapp.enviar_respuesta_automatica", bind=True, max_retries=5)
def enviar_respuesta_automatica(self, lead_id, phone_number_id=None):
    """RF-04 · Respuesta al primer mensaje. Reintenta con espera creciente si Meta o la red fallan
    temporalmente (30 s, 1, 2, 4, 8 min); los errores definitivos (4xx) solo se registran."""
    try:
        return respuesta_automatica.enviar(lead_id, phone_number_id)
    except respuesta_automatica.EnvioFallido as e:
        if e.reintentar and self.request.retries < self.max_retries:
            logger.warning("Respuesta automática al lead %s: %s · reintento %s", lead_id, e, self.request.retries + 1)
            raise self.retry(countdown=30 * 2 ** self.request.retries) from e
        logger.error("Respuesta automática al lead %s NO enviada: %s", lead_id, e)
        return f"fallido: {e}"
