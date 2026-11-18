import logging

from celery import shared_task

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
