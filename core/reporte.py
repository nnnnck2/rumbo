"""SCRUM-121 · Reporte semanal por correo a gerencia (lunes 08:00, semana anterior de lunes a domingo).

Destinatarios: configuración reporte_semanal.destinatarios. Correo: variables EMAIL_* del .env; sin
EMAIL_HOST no se envía (queda en el log). A mano: python manage.py enviar_reporte_semanal [--desde AAAA-MM-DD].
"""
import datetime as dt
import json
import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from .db import como_sistema

logger = logging.getLogger("rumbo.reporte")


def semana_anterior(hoy=None):
    hoy = hoy or timezone.localdate()
    lunes = hoy - dt.timedelta(days=hoy.weekday() + 7)
    return lunes, lunes + dt.timedelta(days=6)


def destinatarios():
    with como_sistema() as cursor:
        cursor.execute("SELECT valor FROM rumbo.configuracion WHERE clave = 'reporte_semanal'")
        fila = cursor.fetchone()
    valor = (json.loads(fila[0]) if isinstance(fila[0], str) else fila[0]) if fila else {}
    return [d for d in valor.get("destinatarios", []) if d]


def enviar(desde=None, hasta=None, para=None):
    from leads.reportes import csv_metricas

    if not settings.EMAIL_HOST:
        logger.warning("Reporte semanal no enviado: falta EMAIL_HOST en .env")
        return "sin correo configurado"
    para = para or destinatarios()
    if not para:
        return "sin destinatarios"
    if desde is None:
        desde, hasta = semana_anterior()
    hasta = hasta or desde + dt.timedelta(days=6)
    with como_sistema():                  # el sistema ve todo el equipo (RLS)
        texto_csv, datos = csv_metricas(desde, hasta)
    cuerpo = render_to_string("core/correo_reporte.txt", {"desde": desde, "hasta": hasta, **datos})
    correo = EmailMessage(f"Rumbo · resumen del {desde:%d/%m} al {hasta:%d/%m}", cuerpo,
                          settings.DEFAULT_FROM_EMAIL, para)
    correo.attach(f"rumbo-metricas-{desde:%Y%m%d}-{hasta:%Y%m%d}.csv", texto_csv.encode("utf-8"), "text/csv")
    correo.send(fail_silently=False)
    logger.info("Reporte semanal enviado a %s", ", ".join(para))
    return f"enviado a {len(para)}"
