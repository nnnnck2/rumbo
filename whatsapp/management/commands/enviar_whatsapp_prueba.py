"""Envía un mensaje de prueba por la WhatsApp Cloud API (SCRUM-9).

    # Plantilla hello_world: la única permitida para iniciar la conversación con el número de prueba
    python manage.py enviar_whatsapp_prueba --a +593991234567

    # Texto libre: solo dentro de las 24 h siguientes a un mensaje del cliente
    python manage.py enviar_whatsapp_prueba --a +593991234567 --texto "Hola desde Rumbo"

Sale por el número conectado de rumbo.numero_whatsapp (o --phone-number-id). El token es
WHATSAPP_ACCESS_TOKEN (.env); con el número de prueba sirve el temporal de 24 h de la pantalla
"Configuración de la API". El destino debe estar en los destinatarios permitidos (máx. 5).
Dar de alta el número es tarea de admin (RLS): ver "Número de prueba de Meta" en el README.
"""
import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.db import como_sistema

GRAPH = "https://graph.facebook.com"


def enviar_mensaje(phone_number_id, destino, texto=None, plantilla="hello_world", idioma="en_US"):
    """Llama a la Cloud API y devuelve (http_status, respuesta_json)."""
    if not settings.WHATSAPP_ACCESS_TOKEN:
        raise CommandError("Falta WHATSAPP_ACCESS_TOKEN en .env.")
    cuerpo = {"messaging_product": "whatsapp", "to": destino.lstrip("+")}
    if texto:
        cuerpo |= {"type": "text", "text": {"body": texto}}
    else:
        cuerpo |= {"type": "template", "template": {"name": plantilla, "language": {"code": idioma}}}
    peticion = urllib.request.Request(
        f"{GRAPH}/{settings.WHATSAPP_API_VERSION}/{phone_number_id}/messages",
        data=json.dumps(cuerpo).encode(),
        headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {"error": {"message": e.reason}}


class Command(BaseCommand):
    help = "Envía un mensaje de prueba por la WhatsApp Cloud API (SCRUM-9)."

    def add_arguments(self, parser):
        parser.add_argument("--a", dest="destino", required=True, help="Teléfono de destino, +E164.")
        parser.add_argument("--texto", help="Texto libre (solo dentro de la ventana de 24 h).")
        parser.add_argument("--plantilla", default="hello_world")
        parser.add_argument("--idioma", default="en_US")
        parser.add_argument("--phone-number-id",
                            help="Por defecto, el del único número conectado en rumbo.numero_whatsapp.")

    def handle(self, *args, **o):
        pnid = o["phone_number_id"]
        if not pnid:
            with como_sistema() as cursor:
                cursor.execute("SELECT meta_phone_number_id FROM rumbo.numero_whatsapp "
                               "WHERE activo AND conectado_api")
                filas = cursor.fetchall()
            if len(filas) != 1:
                raise CommandError(f"Hay {len(filas)} números conectados; indique --phone-number-id.")
            pnid = filas[0][0]

        estado, respuesta = enviar_mensaje(pnid, o["destino"], o["texto"], o["plantilla"], o["idioma"])
        if estado == 200 and respuesta.get("messages"):
            self.stdout.write(self.style.SUCCESS(
                f"✔ Enviado a {o['destino']} · id {respuesta['messages'][0]['id']}"))
            return
        error = respuesta.get("error", {})
        pista = {
            131030: "El destino no está en la lista de destinatarios permitidos del número de prueba.",
            131047: "Pasaron más de 24 h desde el último mensaje del cliente: use una plantilla.",
            190: "Token vencido o inválido (el temporal dura 24 h).",
        }.get(error.get("code"), "")
        raise CommandError(f"Meta respondió {estado}: {error.get('message', respuesta)} "
                           f"(código {error.get('code')}). {pista}".strip())
