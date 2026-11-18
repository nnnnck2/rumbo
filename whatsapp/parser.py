"""Convierte el payload del webhook de WhatsApp Cloud API en mensajes entrantes.

Formato (resumido):
{"object": "whatsapp_business_account",
 "entry": [{"changes": [{"field": "messages", "value": {
     "metadata": {"display_phone_number": "593961319535", "phone_number_id": "1234567890"},
     "contacts": [{"profile": {"name": "Ana"}, "wa_id": "593991234567"}],
     "messages": [{"from": "593991234567", "id": "wamid.X", "timestamp": "1700000000",
                   "type": "text", "text": {"body": "Hola"}}],
     "statuses": [...]}}]}]}
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
TIPO = re.compile(r"^[a-z_]{1,30}$")
MAX_CUERPO = 4096


class PayloadInvalido(ValueError):
    pass


@dataclass
class MensajeEntrante:
    wa_message_id: str
    telefono: str
    nombre_perfil: str | None
    phone_number_id: str | None
    numero_destino: str | None
    tipo: str
    cuerpo: str | None
    ocurrido_en: datetime
    payload: dict = field(default_factory=dict)


def a_e164(numero: str | None) -> str | None:
    if not numero:
        return None
    digitos = re.sub(r"\D", "", str(numero))
    telefono = f"+{digitos}"
    return telefono if E164.match(telefono) else None


def _cuerpo(mensaje: dict) -> str | None:
    tipo = mensaje.get("type")
    contenido = mensaje.get(tipo) if isinstance(mensaje.get(tipo), dict) else {}
    if tipo == "text":
        texto = contenido.get("body")
    elif tipo == "button":
        texto = contenido.get("text")
    elif tipo == "interactive":
        respuesta = contenido.get("button_reply") or contenido.get("list_reply") or {}
        texto = respuesta.get("title")
    elif tipo in ("image", "video", "document"):
        texto = contenido.get("caption")
    elif tipo == "location":
        texto = " ".join(str(contenido.get(k, "")) for k in ("name", "address")).strip() or None
    else:
        texto = None
    return texto[:MAX_CUERPO] if isinstance(texto, str) else None


def _fecha(timestamp) -> datetime:
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return datetime.now(tz=timezone.utc)


def extraer_mensajes(payload: dict) -> list[MensajeEntrante]:
    """Devuelve los mensajes entrantes del payload. Ignora estados de entrega (statuses)."""
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        raise PayloadInvalido("El payload no es de whatsapp_business_account")

    mensajes = []
    for entrada in payload.get("entry") or []:
        for cambio in entrada.get("changes") or []:
            if cambio.get("field") != "messages":
                continue
            valor = cambio.get("value") or {}
            metadata = valor.get("metadata") or {}
            nombres = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in valor.get("contacts") or []
            }
            for m in valor.get("messages") or []:
                wa_id = m.get("id")
                telefono = a_e164(m.get("from"))
                if not wa_id or not telefono:
                    raise PayloadInvalido(f"Mensaje sin id o con teléfono inválido: {m.get('from')!r}")
                tipo = m.get("type") or "text"
                mensajes.append(MensajeEntrante(
                    wa_message_id=str(wa_id)[:255],
                    telefono=telefono,
                    nombre_perfil=(nombres.get(m.get("from")) or None),
                    phone_number_id=metadata.get("phone_number_id"),
                    numero_destino=a_e164(metadata.get("display_phone_number")),
                    tipo=tipo if TIPO.match(tipo) else "desconocido",
                    cuerpo=_cuerpo(m),
                    ocurrido_en=_fecha(m.get("timestamp")),
                    payload={"mensaje": m, "metadata": metadata},
                ))
    return mensajes
