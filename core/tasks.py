"""Tareas generales de Celery (SCRUM-17)."""
import logging
import socket

from celery import shared_task
from django.utils import timezone

from .db import ejecutar_funcion_sistema

logger = logging.getLogger("rumbo.tareas")


@shared_task(name="core.ping")
def ping(mensaje="ping"):
    """Tarea de prueba: confirma que el worker recibe y ejecuta tareas.
    El resultado queda guardado en Redis (CELERY_RESULT_BACKEND) y en el log del worker."""
    respuesta = {
        "mensaje": mensaje,
        "respuesta": "pong",
        "worker": socket.gethostname(),
        "ejecutada_en": timezone.now().isoformat(),
    }
    logger.info("Tarea de prueba ejecutada: %s", respuesta)
    return respuesta


@shared_task(name="core.reasignar_sin_primera_llamada")
def reasignar_sin_primera_llamada():
    """RF-14: reasigna leads sin primera llamada dentro del tiempo máximo."""
    total = ejecutar_funcion_sistema("SELECT rumbo.reasignar_sin_primera_llamada()")
    if total:
        logger.info("Leads reasignados por no recibir la primera llamada: %s", total)
    return total


@shared_task(name="core.generar_avisos")
def generar_avisos():
    """017: notificaciones por tiempo (plazo por vencer, hora de llamar, llamadas atrasadas)."""
    total = ejecutar_funcion_sistema("SELECT rumbo.generar_avisos()")
    if total:
        logger.info("Notificaciones generadas: %s", total)
    return total


@shared_task(name="core.liberar_cola")
def liberar_cola():
    """RF-13: reparte la cola de fuera de horario cuando abre la atención."""
    total = ejecutar_funcion_sistema("SELECT rumbo.liberar_cola()")
    if total:
        logger.info("Leads repartidos desde la cola: %s", total)
    return total


@shared_task(name="core.enviar_push")
def enviar_push():
    """SCRUM-122: notificaciones nuevas → push a los dispositivos suscritos."""
    from . import push

    return push.enviar_pendientes()


@shared_task(name="core.enviar_reporte_semanal")
def enviar_reporte_semanal():
    """SCRUM-121: lunes 08:00, resumen de la semana pasada por correo."""
    from . import reporte

    return reporte.enviar()
