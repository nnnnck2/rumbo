"""SCRUM-116 · Recordatorio de cita al cliente, 24 h y 2 h antes.

La fecha de la cita está en lead.datos.cita_en (ISO, la guarda el asesor en Datos del caso). Celery revisa
cada 5 minutos. Cada recordatorio se manda una sola vez (queda marcado en el mensaje: recordatorio_cita = 24 | 2).
Ventana de 24 h abierta → texto; cerrada → plantilla aprobada con {{1}} = nombre y {{2}} = fecha de la cita.
"""
import datetime as dt
import json
import logging

from django.utils import timezone
from psycopg.types.json import Jsonb

from core.db import como_sistema

from . import cliente
from .aviso_no_contesta import componer as completar_nombre

logger = logging.getLogger("rumbo.whatsapp")

MARGEN = dt.timedelta(minutes=5)
VENTANA = dt.timedelta(hours=24)
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def texto_cita(cuando):
    local = timezone.localtime(cuando)
    return f"{DIAS[local.weekday()]} {local:%d/%m} a las {local:%H:%M}"


def cual_toca(cita_en, enviados, ahora):
    """'2', '24' o None según cuánto falta y lo ya enviado."""
    falta = cita_en - ahora
    if falta <= dt.timedelta(0):
        return None
    if falta <= dt.timedelta(hours=2) + MARGEN:
        return None if "2" in enviados else "2"
    if falta <= dt.timedelta(hours=24) + MARGEN:
        return None if ("24" in enviados or "2" in enviados) else "24"
    return None


_SQL = """
SELECT l.id, l.telefono, l.nombre_perfil, (l.datos ->> 'cita_en')::timestamptz AS cita_en, l.datos ->> 'cita_en',
       n.meta_phone_number_id,
       (SELECT max(m.ocurrido_en) FROM rumbo.mensaje_whatsapp m WHERE m.lead_id = l.id AND m.direccion = 'entrante'),
       coalesce((SELECT array_agg(m.payload ->> 'recordatorio_cita') FROM rumbo.mensaje_whatsapp m
                 WHERE m.lead_id = l.id AND m.payload ? 'recordatorio_cita'
                   AND m.payload ->> 'cita_en' = l.datos ->> 'cita_en'), '{}')
FROM rumbo.lead l LEFT JOIN rumbo.numero_whatsapp n ON n.id = l.numero_whatsapp_id
WHERE l.etapa_codigo = 'cita_agendada' AND l.anonimizado_en IS NULL
  AND l.datos ->> 'cita_en' ~ '^\\d{4}-\\d{2}-\\d{2}T'
  AND (l.datos ->> 'cita_en')::timestamptz BETWEEN now() AND now() + interval '24 hours 5 minutes'
"""


def enviar_pendientes():
    with como_sistema() as cursor:
        cursor.execute("SELECT valor FROM rumbo.configuracion WHERE clave = 'recordatorio_cita'")
        fila = cursor.fetchone()
        config = (json.loads(fila[0]) if isinstance(fila[0], str) else fila[0]) if fila else {}
        if not config.get("activo"):
            return {"omitido": "recordatorio desactivado"}
        cursor.execute(_SQL)
        citas = cursor.fetchall()
    ahora, enviados, omitidos = timezone.now(), 0, 0
    for lead_id, telefono, nombre, cita_en, cita_texto, pnid, ultimo_entrante, ya in citas:
        cual = cual_toca(cita_en, set(filter(None, ya)), ahora)
        if cual is None or not pnid:
            continue
        cita = texto_cita(cita_en)
        if ultimo_entrante and ahora - ultimo_entrante < VENTANA:
            registro = completar_nombre(config["texto"].replace("{cita}", cita), nombre, None)
            cuerpo, tipo = cliente.cuerpo_texto(telefono, registro), "text"
        elif config.get("plantilla"):
            cuerpo = cliente.cuerpo_plantilla_con_textos(telefono, config["plantilla"], config.get("idioma") or "es",
                                                          [(nombre or "").split()[0] if nombre else "", cita])
            registro, tipo = f"[plantilla {config['plantilla']}] {cita}", "template"
        else:
            omitidos += 1
            continue
        try:
            status, respuesta = cliente.llamar_api(pnid, cuerpo)
        except (cliente.SinToken, OSError) as e:
            logger.warning("Recordatorio de cita del lead %s no enviado: %s", lead_id, e)
            continue
        wamid = cliente.wamid(respuesta)
        if status != 200 or not wamid:
            logger.error("Recordatorio de cita del lead %s rechazado: %s", lead_id, cliente.explicar_error(respuesta, status))
            continue
        with como_sistema() as cursor:
            cursor.execute("SELECT rumbo.registrar_mensaje_automatico(%s, %s, %s, %s, %s)",
                           [lead_id, wamid, registro, tipo,
                            # el mismo texto guardado en el lead: si la cita se mueve, los recordatorios se repiten
                            Jsonb({"recordatorio_cita": cual, "cita_en": cita_texto})])
        enviados += 1
    return {"citas": len(citas), "enviados": enviados, "sin_ventana_ni_plantilla": omitidos}
