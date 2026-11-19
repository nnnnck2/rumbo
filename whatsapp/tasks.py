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
        resultado = respuesta_automatica.enviar(lead_id, phone_number_id)
    except respuesta_automatica.EnvioFallido as e:
        if e.reintentar and self.request.retries < self.max_retries:
            logger.warning("Respuesta automática al lead %s: %s · reintento %s", lead_id, e, self.request.retries + 1)
            raise self.retry(countdown=30 * 2 ** self.request.retries) from e
        logger.error("Respuesta automática al lead %s NO enviada: %s", lead_id, e)
        return f"fallido: {e}"
    if resultado.startswith("enviado"):
        try:                                          # SCRUM-115: si el bot está activo, empieza a preguntar
            preguntar_bot.delay(lead_id, "visa")
        except Exception:  # noqa: BLE001 — sin Redis: la respuesta ya salió, el bot no es crítico
            logger.exception("No se pudo encolar el bot del lead %s", lead_id)
    return resultado


@shared_task(name="whatsapp.avisar_no_contesta", bind=True, max_retries=5)
def avisar_no_contesta(self, lead_id, usuario_id=None):
    """SCRUM-88 · WhatsApp al cliente que no contestó la llamada. Reintenta si Meta o la red fallan."""
    from . import aviso_no_contesta

    try:
        return aviso_no_contesta.enviar(lead_id, usuario_id)
    except respuesta_automatica.EnvioFallido as e:
        if e.reintentar and self.request.retries < self.max_retries:
            logger.warning("Aviso de no contesta al lead %s: %s · reintento %s", lead_id, e, self.request.retries + 1)
            raise self.retry(countdown=30 * 2 ** self.request.retries) from e
        logger.error("Aviso de no contesta al lead %s NO enviado: %s", lead_id, e)
        return f"fallido: {e}"


@shared_task(name="whatsapp.enviar_conversiones")
def enviar_conversiones():
    """SCRUM-92 · Envía a la Conversions API de Meta las citas y ventas pendientes (cada minuto)."""
    from . import conversiones

    return conversiones.enviar_pendientes()


@shared_task(name="whatsapp.preguntar_bot", bind=True, max_retries=3)
def preguntar_bot(self, lead_id, paso="visa"):
    """SCRUM-115: pregunta del bot (tipo de visa / destino) o agradecimiento."""
    from . import bot

    try:
        return bot.preguntar(lead_id, paso)
    except respuesta_automatica.EnvioFallido as e:
        if e.reintentar and self.request.retries < self.max_retries:
            raise self.retry(countdown=30 * 2 ** self.request.retries) from e
        logger.error("Bot · pregunta %s al lead %s NO enviada: %s", paso, lead_id, e)
        return f"fallido: {e}"


@shared_task(name="whatsapp.respuesta_bot", bind=True, max_retries=3)
def respuesta_bot(self, lead_id, respuesta_id):
    """SCRUM-115: el cliente eligió una opción de la lista del bot."""
    from . import bot

    try:
        return bot.procesar_respuesta(lead_id, respuesta_id)
    except respuesta_automatica.EnvioFallido as e:
        if e.reintentar and self.request.retries < self.max_retries:
            raise self.retry(countdown=30 * 2 ** self.request.retries) from e
        logger.error("Bot · respuesta del lead %s NO procesada: %s", lead_id, e)
        return f"fallido: {e}"


@shared_task(name="whatsapp.recordatorios_cita")
def recordatorios_cita():
    """SCRUM-116: recordatorios de cita 24 h y 2 h antes (cada 5 minutos)."""
    from . import recordatorios

    return recordatorios.enviar_pendientes()
