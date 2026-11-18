"""Cliente mínimo de la WhatsApp Cloud API (envío de mensajes)."""
import json
import urllib.error
import urllib.request

from django.conf import settings

GRAPH = "https://graph.facebook.com"


class SinToken(RuntimeError):
    """No hay WHATSAPP_ACCESS_TOKEN: no se puede enviar (típico en desarrollo)."""


def llamar_api(phone_number_id, cuerpo, timeout=15):
    """POST /{phone_number_id}/messages. Devuelve (http_status, respuesta_json).
    Los errores HTTP se devuelven, no se lanzan; los de red (timeout, DNS) sí se lanzan."""
    if not settings.WHATSAPP_ACCESS_TOKEN:
        raise SinToken("Falta WHATSAPP_ACCESS_TOKEN en .env.")
    peticion = urllib.request.Request(
        f"{GRAPH}/{settings.WHATSAPP_API_VERSION}/{phone_number_id}/messages",
        data=json.dumps({"messaging_product": "whatsapp", **cuerpo}).encode(),
        headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {"error": {"message": e.reason}}


def cuerpo_texto(destino, texto):
    return {"to": destino.lstrip("+"), "type": "text", "text": {"body": texto, "preview_url": False}}


def cuerpo_plantilla(destino, plantilla, idioma):
    return {"to": destino.lstrip("+"), "type": "template",
            "template": {"name": plantilla, "language": {"code": idioma}}}


def wamid(respuesta):
    """Id del mensaje enviado, o None si Meta no lo aceptó."""
    mensajes = respuesta.get("messages") or []
    return mensajes[0].get("id") if mensajes else None
