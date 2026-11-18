"""RF-04 · Respuesta automática al primer mensaje (SCRUM-23).

Cuando un número escribe por primera vez (lead nuevo), el worker encola el envío al confirmar
la transacción. El envío:
  1. Lee los textos de rumbo.configuracion (editables en Configuración, rigen al instante).
  2. Elige bienvenida o fuera de horario según rumbo.en_horario() y agrega el aviso de privacidad.
  3. Lo envía por el mismo número al que escribió el cliente (ventana de 24 h abierta: texto libre).
  4. Lo registra como mensaje saliente automático del lead.
No se piden datos antes de asignar el lead (definido con el área).
"""
import json
import logging

from core.db import como_sistema

from . import cliente

logger = logging.getLogger("rumbo.whatsapp")

LIMITE = 4096                                   # máximo de un texto de WhatsApp (y de la columna cuerpo)
POR_DEFECTO = {
    "texto_bienvenida": "¡Hola, te saluda Multivisa! ¿Cómo podemos ayudarlo?",
    "texto_fuera_horario": "¡Hola, te saluda Multivisa! Estamos fuera del horario de atención. "
                           "Un asesor te contactará en cuanto abramos.",
}


class EnvioFallido(Exception):
    def __init__(self, mensaje, reintentar):
        super().__init__(mensaje)
        self.reintentar = reintentar


def componer(config: dict, en_horario: bool) -> str:
    """Texto final: bienvenida (o fuera de horario) + aviso de privacidad si está configurado."""
    clave = "texto_bienvenida" if en_horario else "texto_fuera_horario"
    partes = [(config.get(clave) or POR_DEFECTO[clave]).strip()]
    privacidad = (config.get("texto_privacidad") or "").strip()
    if privacidad:
        partes.append(privacidad)
    return "\n\n".join(partes)[:LIMITE]


def _leer_estado(lead_id):
    """(telefono, phone_number_id del número de entrada, ya_respondido, config, en_horario)."""
    with como_sistema() as cursor:
        cursor.execute(
            """SELECT l.telefono, n.meta_phone_number_id,
                      EXISTS (SELECT 1 FROM rumbo.mensaje_whatsapp m
                              WHERE m.lead_id = l.id AND m.direccion = 'saliente'
                                AND m.payload ? 'automatica'),
                      rumbo.en_horario()
               FROM rumbo.lead l LEFT JOIN rumbo.numero_whatsapp n ON n.id = l.numero_whatsapp_id
               WHERE l.id = %s""",
            [lead_id],
        )
        fila = cursor.fetchone()
        if fila is None:
            return None
        cursor.execute("SELECT clave, valor FROM rumbo.configuracion "
                       "WHERE clave IN ('texto_bienvenida', 'texto_fuera_horario', 'texto_privacidad')")
        config = {c: (json.loads(v) if isinstance(v, str) else v) for c, v in cursor.fetchall()}
    telefono, pnid, ya, en_horario = fila
    return telefono, pnid, ya, config, en_horario


def enviar(lead_id: int, phone_number_id: str | None = None) -> str:
    """Envía la respuesta automática del lead. Devuelve qué pasó (para el log/resultado de Celery).
    Idempotente: si ya se registró una respuesta automática para el lead, no envía otra."""
    estado = _leer_estado(lead_id)
    if estado is None:
        return "lead inexistente"
    telefono, pnid_base, ya, config, en_horario = estado
    if ya:
        return "ya respondido"
    pnid = phone_number_id or pnid_base
    if not pnid:
        logger.warning("Respuesta automática no enviada: el número de entrada del lead %s no tiene "
                       "meta_phone_number_id", lead_id)
        return "sin phone_number_id"

    texto = componer(config, en_horario)
    try:
        status, respuesta = cliente.llamar_api(pnid, cliente.cuerpo_texto(telefono, texto))
    except cliente.SinToken:
        logger.warning("Respuesta automática no enviada al lead %s: falta WHATSAPP_ACCESS_TOKEN", lead_id)
        return "sin token"
    except OSError as e:                                    # red: timeout, DNS, conexión
        raise EnvioFallido(f"Error de red al enviar: {e}", reintentar=True) from e

    wamid = cliente.wamid(respuesta)
    if status != 200 or not wamid:
        error = respuesta.get("error", {})
        # 429 (límite) y 5xx: reintentar. 4xx: el reintento daría lo mismo (token, destino, ventana 24 h).
        reintentar = status == 429 or status >= 500
        raise EnvioFallido(f"Meta respondió {status}: {error.get('message')} (código {error.get('code')})",
                           reintentar=reintentar)

    with como_sistema() as cursor:
        cursor.execute("SELECT rumbo.registrar_respuesta_automatica(%s, %s, %s)", [lead_id, wamid, texto])
    tipo = "bienvenida" if en_horario else "fuera de horario"
    logger.info("Respuesta automática (%s) enviada al lead %s · %s", tipo, lead_id, wamid)
    return f"enviado ({tipo})"
