"""SCRUM-115 · Preguntas automáticas antes de la llamada.

Flujo (solo si bot_preguntas.activo):
  1. Tras la respuesta automática al primer mensaje → lista "¿Qué tipo de visa necesitas?".
  2. El cliente elige (id "bot:visa:<tipo>") → se guarda el tipo de visa y se pregunta el destino.
  3. Elige destino (id "bot:pais:<país>") → se guarda y se agradece.
Los datos se guardan con rumbo.guardar_dato_bot(), que no pisa lo que ya escribió el asesor o la campaña.
"Otro" no guarda nada: el asesor lo pregunta en la llamada.
"""
import json
import logging

from psycopg.types.json import Jsonb

from core.db import como_sistema

from . import cliente
from .respuesta_automatica import EnvioFallido

logger = logging.getLogger("rumbo.whatsapp")

OTRO = "Otro"


def opciones(paso):
    from leads.forms import PAISES, TIPOS_VISA

    lista = TIPOS_VISA if paso == "visa" else PAISES
    return [(f"bot:{paso}:{v}", v) for v in lista[:9]] + [(f"bot:{paso}:{OTRO}", OTRO)]


def interpretar(respuesta_id):
    """'bot:visa:Turismo' → ('visa', 'Turismo'); cualquier otra cosa → None."""
    partes = (respuesta_id or "").split(":", 2)
    if len(partes) != 3 or partes[0] != "bot" or partes[1] not in ("visa", "pais") or not partes[2].strip():
        return None
    return partes[1], partes[2].strip()[:80]


def _estado(lead_id):
    with como_sistema() as cursor:
        cursor.execute("""SELECT l.telefono, n.meta_phone_number_id, l.datos ->> 'bot_paso',
                                 (SELECT c.valor FROM rumbo.configuracion c WHERE c.clave = 'bot_preguntas')
                          FROM rumbo.lead l LEFT JOIN rumbo.numero_whatsapp n ON n.id = l.numero_whatsapp_id
                          WHERE l.id = %s""", [lead_id])
        fila = cursor.fetchone()
    if fila is None:
        return None
    telefono, pnid, paso, config = fila
    config = json.loads(config) if isinstance(config, str) else (config or {})
    return {"telefono": telefono, "pnid": pnid, "paso": paso, "config": config}


def _enviar(lead_id, estado, cuerpo, registro, marca):
    try:
        status, respuesta = cliente.llamar_api(estado["pnid"], cuerpo)
    except cliente.SinToken:
        return "sin token"
    except OSError as e:
        raise EnvioFallido(f"Error de red: {e}", reintentar=True) from e
    wamid = cliente.wamid(respuesta)
    if status != 200 or not wamid:
        raise EnvioFallido(cliente.explicar_error(respuesta, status), reintentar=status == 429 or status >= 500)
    with como_sistema() as cursor:
        cursor.execute("SELECT rumbo.registrar_mensaje_automatico(%s, %s, %s, %s, %s)",
                       [lead_id, wamid, registro, cuerpo.get("type", "text"), Jsonb({"bot": marca})])
        if marca in ("visa", "pais", "fin"):
            cursor.execute("SELECT rumbo.guardar_dato_bot(%s, 'bot_paso', %s)", [lead_id, marca])
    return f"enviado ({marca})"


def preguntar(lead_id, paso):
    """Envía la pregunta `paso` ('visa' o 'pais') o el agradecimiento ('fin')."""
    estado = _estado(lead_id)
    if estado is None:
        return "lead inexistente"
    config = estado["config"]
    if not config.get("activo"):
        return "bot desactivado"
    if not estado["pnid"]:
        return "sin phone_number_id"
    if paso == "fin":
        texto = config.get("texto_gracias") or "¡Gracias!"
        return _enviar(lead_id, estado, cliente.cuerpo_texto(estado["telefono"], texto), texto, "fin")
    texto = config.get("texto_visa" if paso == "visa" else "texto_pais") or ""
    cuerpo = cliente.cuerpo_lista(estado["telefono"], texto, "Elegir", opciones(paso))
    return _enviar(lead_id, estado, cuerpo, texto, paso)


def procesar_respuesta(lead_id, respuesta_id):
    """El cliente tocó una opción de la lista: guarda el dato y sigue con la próxima pregunta."""
    elegido = interpretar(respuesta_id)
    if elegido is None:
        return "no es del bot"
    paso, valor = elegido
    if valor != OTRO:
        with como_sistema() as cursor:
            cursor.execute("SELECT rumbo.guardar_dato_bot(%s, %s, %s)",
                           [lead_id, "tipo_visa" if paso == "visa" else "pais_interes", valor])
    return preguntar(lead_id, "pais" if paso == "visa" else "fin")
