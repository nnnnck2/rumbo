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


def cuerpo_plantilla_con_textos(destino, plantilla, idioma, textos):
    """Plantilla con variables {{1}}, {{2}}… en el cuerpo (en el orden de `textos`)."""
    return {"to": destino.lstrip("+"), "type": "template",
            "template": {"name": plantilla, "language": {"code": idioma},
                         "components": [{"type": "body",
                                         "parameters": [{"type": "text", "text": str(t)[:1000]} for t in textos]}]}}


def cuerpo_lista(destino, texto, boton, filas):
    """Mensaje interactivo de lista (SCRUM-115). filas = [(id, titulo)], máx. 10; títulos de hasta 24 caracteres."""
    return {"to": destino.lstrip("+"), "type": "interactive",
            "interactive": {"type": "list", "body": {"text": texto[:1024]},
                            "action": {"button": boton[:20],
                                       "sections": [{"title": "Opciones",
                                                     "rows": [{"id": i[:200], "title": t[:24]} for i, t in filas[:10]]}]}}}


MENSAJES_ERROR = {
    131047: "Pasaron más de 24 h desde el último mensaje del cliente: WhatsApp solo permite plantillas aprobadas.",
    131026: "El número del cliente no puede recibir mensajes de WhatsApp.",
    131051: "Tipo de mensaje no admitido.",
    190: "El token de WhatsApp venció o no es válido.",
    100: "Meta rechazó el mensaje (parámetro inválido).",
    131056: "Demasiados mensajes seguidos a este cliente: espere un momento.",
}


def explicar_error(respuesta, status):
    """Error de Meta en palabras simples, para mostrarlo al asesor."""
    error = (respuesta or {}).get("error", {})
    return MENSAJES_ERROR.get(error.get("code")) or f"Meta no aceptó el mensaje ({status}): {error.get('message') or 'sin detalle'}."
