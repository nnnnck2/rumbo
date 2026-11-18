from django.test import SimpleTestCase

from whatsapp.management.commands.simular_mensaje_whatsapp import construir_payload
from whatsapp.parser import PayloadInvalido, a_e164, extraer_mensajes


class ParserTests(SimpleTestCase):
    def test_mensaje_de_texto(self):
        payload = construir_payload("+593991234567", "Hola", "Ana", "+593961319535", "123456")
        [m] = extraer_mensajes(payload)
        self.assertEqual(m.telefono, "+593991234567")
        self.assertEqual(m.nombre_perfil, "Ana")
        self.assertEqual(m.cuerpo, "Hola")
        self.assertEqual(m.tipo, "text")
        self.assertEqual(m.numero_destino, "+593961319535")
        self.assertEqual(m.phone_number_id, "123456")
        self.assertTrue(m.wa_message_id.startswith("wamid."))

    def test_estados_de_entrega_se_ignoran(self):
        payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{
            "field": "messages", "value": {"statuses": [{"id": "wamid.x", "status": "read"}]}}]}]}
        self.assertEqual(extraer_mensajes(payload), [])

    def test_objeto_incorrecto(self):
        with self.assertRaises(PayloadInvalido):
            extraer_mensajes({"object": "page"})

    def test_telefono_invalido(self):
        payload = construir_payload("+593991234567", "Hola", "Ana", "+593961319535", "1")
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "12"
        with self.assertRaises(PayloadInvalido):
            extraer_mensajes(payload)

    def test_interactivo_y_cuerpo_largo(self):
        payload = construir_payload("+593991234567", "x" * 5000, "Ana", "+593961319535", "1")
        mensaje = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        self.assertEqual(len(extraer_mensajes(payload)[0].cuerpo), 4096)
        mensaje.update(type="interactive", interactive={"button_reply": {"title": "Sí"}})
        self.assertEqual(extraer_mensajes(payload)[0].cuerpo, "Sí")

    def test_a_e164(self):
        self.assertEqual(a_e164("593 99-123-4567"), "+593991234567")
        self.assertIsNone(a_e164("abc"))
        self.assertIsNone(a_e164(None))
