"""Simula un mensaje entrante de WhatsApp contra la base real, pasando por el mismo
camino que uno de Meta: payload firmado → webhook → bandeja → registrar_mensaje_entrante.

    python manage.py simular_mensaje_whatsapp --telefono +593991234567 --texto "Hola"

Sirve para probar RF-01/RF-02 de punta a punta mientras el número de prueba de Meta
(SCRUM-9) y el HTTPS público (SCRUM-12) no están listos.
"""
import json
import time
import uuid
from unittest import mock

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from core.db import como_sistema
from whatsapp import views
from whatsapp.firma import calcular_firma
from whatsapp.servicios import procesar_pendientes


def construir_payload(telefono, texto, nombre, numero_destino, phone_number_id):
    digitos = telefono.lstrip("+")
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "0",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": numero_destino.lstrip("+"),
                                 "phone_number_id": phone_number_id},
                    "contacts": [{"profile": {"name": nombre}, "wa_id": digitos}],
                    "messages": [{
                        "from": digitos,
                        "id": f"wamid.SIMULADO.{uuid.uuid4().hex}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": texto},
                    }],
                },
            }],
        }],
    }


class Command(BaseCommand):
    help = "Envía un mensaje simulado y firmado al webhook y lo procesa contra la base."

    def add_arguments(self, parser):
        parser.add_argument("--telefono", default="+593990000001")
        parser.add_argument("--texto", default="Hola, quiero información de visas")
        parser.add_argument("--nombre", default="Cliente de prueba")
        parser.add_argument("--numero-destino", default="+593961319535",
                            help="Número de la empresa que recibe (rumbo.numero_whatsapp).")
        parser.add_argument("--phone-number-id", default="0000000000")
        parser.add_argument("--firma-invalida", action="store_true",
                            help="Envía una firma incorrecta: debe responder 403.")

    def handle(self, *args, **o):
        if not settings.WHATSAPP_APP_SECRET:
            raise CommandError("Configure WHATSAPP_APP_SECRET en .env")

        payload = construir_payload(o["telefono"], o["texto"], o["nombre"],
                                    o["numero_destino"], o["phone_number_id"])
        cuerpo = json.dumps(payload).encode()
        firma = "sha256=" + "0" * 64 if o["firma_invalida"] else calcular_firma(cuerpo, settings.WHATSAPP_APP_SECRET)

        peticion = RequestFactory().post("/whatsapp/webhook/", data=cuerpo,
                                         content_type="application/json",
                                         HTTP_X_HUB_SIGNATURE_256=firma)
        # El procesamiento se hace aquí mismo, sin depender de que el worker esté corriendo.
        with mock.patch.object(views, "_encolar"):
            respuesta = views.webhook(peticion)
        self.stdout.write(f"Webhook respondió {respuesta.status_code}")
        if respuesta.status_code != 200:
            return

        self.stdout.write(f"Procesamiento: {procesar_pendientes()}")
        wamid = payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
        with como_sistema() as cursor:
            cursor.execute(
                """SELECT l.id, l.telefono, l.nombre_perfil, l.estado_asignacion, l.asesor_id,
                          m.wa_message_id, m.cuerpo
                   FROM rumbo.mensaje_whatsapp m JOIN rumbo.lead l ON l.id = m.lead_id
                   WHERE m.wa_message_id = %s""",
                [wamid],
            )
            fila = cursor.fetchone()
        if not fila:
            raise CommandError("El mensaje no quedó guardado en la base")
        self.stdout.write(self.style.SUCCESS(
            f"Guardado → lead {fila[0]} {fila[1]} ({fila[2]}) · {fila[3]} · asesor {fila[4]} · "
            f"mensaje {fila[5]}: {fila[6]!r}"
        ))
