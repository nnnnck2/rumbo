"""RF-01 / RF-02 · comportamiento del endpoint (sin base: guardar_evento simulado)."""
import json
from unittest import mock

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase

from whatsapp import views
from whatsapp.firma import calcular_firma
from whatsapp.management.commands.simular_mensaje_whatsapp import construir_payload

URL = "/whatsapp/webhook/"


class WebhookTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.cuerpo = json.dumps(construir_payload("+593991234567", "Hola", "Ana", "+593961319535", "1")).encode()

    def _post(self, firma):
        extra = {"HTTP_X_HUB_SIGNATURE_256": firma} if firma else {}
        return views.webhook(self.rf.post(URL, data=self.cuerpo, content_type="application/json", **extra))

    # ── Verificación GET ──
    def test_verificacion_correcta_devuelve_challenge(self):
        r = views.webhook(self.rf.get(URL, {"hub.mode": "subscribe", "hub.verify_token": "token-de-prueba",
                                            "hub.challenge": "12345"}))
        self.assertEqual((r.status_code, r.content), (200, b"12345"))

    def test_verificacion_con_token_incorrecto(self):
        with self.assertLogs("rumbo.seguridad", "WARNING"):
            r = views.webhook(self.rf.get(URL, {"hub.mode": "subscribe", "hub.verify_token": "otro",
                                                "hub.challenge": "12345"}))
        self.assertEqual(r.status_code, 403)

    # ── POST firmado ──
    @mock.patch("whatsapp.views.transaction.on_commit")
    @mock.patch("whatsapp.views.guardar_evento", return_value=7)
    def test_firma_valida_guarda_y_encola(self, guardar, on_commit):
        r = self._post(calcular_firma(self.cuerpo, settings.WHATSAPP_APP_SECRET))
        self.assertEqual(r.status_code, 200)
        guardar.assert_called_once()
        self.assertEqual(guardar.call_args.args[0], self.cuerpo)
        on_commit.assert_called_once_with(views._encolar)

    @mock.patch("whatsapp.views.transaction.on_commit")
    @mock.patch("whatsapp.views.guardar_evento", return_value=None)
    def test_evento_repetido_no_se_encola(self, guardar, on_commit):
        r = self._post(calcular_firma(self.cuerpo, settings.WHATSAPP_APP_SECRET))
        self.assertEqual(r.status_code, 200)
        on_commit.assert_not_called()

    @mock.patch("whatsapp.views.guardar_evento")
    def test_firma_invalida_se_rechaza_y_registra(self, guardar):
        with self.assertLogs("rumbo.seguridad", "WARNING") as logs:
            r = self._post(calcular_firma(self.cuerpo, "otro-secreto"))
        self.assertEqual(r.status_code, 403)
        self.assertIn("firma inválida", logs.output[0])
        guardar.assert_not_called()

    @mock.patch("whatsapp.views.guardar_evento")
    def test_sin_firma_se_rechaza(self, guardar):
        with self.assertLogs("rumbo.seguridad", "WARNING"):
            r = self._post(None)
        self.assertEqual(r.status_code, 403)
        guardar.assert_not_called()

    @mock.patch("whatsapp.views.guardar_evento")
    def test_json_invalido_con_firma_valida(self, guardar):
        self.cuerpo = b"no es json"
        with self.assertLogs("rumbo.whatsapp", "WARNING"):
            r = self._post(calcular_firma(self.cuerpo, settings.WHATSAPP_APP_SECRET))
        self.assertEqual(r.status_code, 400)
        guardar.assert_not_called()

    def test_metodo_no_permitido(self):
        self.assertEqual(views.webhook(self.rf.put(URL)).status_code, 405)
