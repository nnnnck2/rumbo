"""SCRUM-57 · API para CALLFLOW sin base: token, métodos, parámetros y paginado."""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, override_settings

from core import api_callflow

TOKEN = "rbcf_prueba"
HASH = api_callflow.hash_token(TOKEN)


@override_settings(CALLFLOW_API_TOKENS_SHA256=["otro", HASH])
class ApiCallflowTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def _get(self, vista, url="/x/", token=TOKEN, filas=None):
        request = self.rf.get(url, HTTP_AUTHORIZATION=f"Bearer {token}" if token else "")
        with mock.patch.object(api_callflow, "_filas", return_value=filas or []) as consulta:
            return vista(request), consulta

    def test_sin_token_o_token_malo(self):
        for token in (None, "malo"):
            with self.subTest(token=token):
                r, consulta = self._get(api_callflow.ventas, token=token)
                self.assertEqual(r.status_code, 401)
                self.assertIn("Bearer", r["WWW-Authenticate"])
                consulta.assert_not_called()

    @override_settings(CALLFLOW_API_TOKENS_SHA256=[])
    def test_sin_tokens_configurados_la_api_esta_cerrada(self):
        self.assertEqual(self._get(api_callflow.asesores)[0].status_code, 401)

    def test_solo_get(self):
        r = api_callflow.ventas(self.rf.post("/x/", HTTP_AUTHORIZATION=f"Bearer {TOKEN}"))
        self.assertEqual(r.status_code, 405)

    def test_paginado_y_siguiente(self):
        filas = [{"venta_id": 7, "actualizado_en": "2026-11-23T12:00:00-05:00"},
                 {"venta_id": 9, "actualizado_en": "2026-11-23T12:05:00-05:00"}]
        r, consulta = self._get(api_callflow.ventas, "/x/?limite=2&desde=2026-11-01T00:00:00-05:00&despues_id=3", filas=filas)
        self.assertEqual(r.status_code, 200)
        import json

        cuerpo = json.loads(r.content)
        self.assertTrue(cuerpo["hay_mas"])
        self.assertEqual(cuerpo["siguiente"], {"desde": "2026-11-23T12:05:00-05:00", "despues_id": 9})
        _sql, params = consulta.call_args[0]
        self.assertEqual(params[1:], [3, 2])
        self.assertEqual(params[0].utcoffset(), dt.timedelta(hours=-5))

    def test_parametros_invalidos(self):
        for url in ("/x/?desde=ayer", "/x/?desde=2026-11-01T00:00:00", "/x/?despues_id=x", "/x/?limite=muchos"):
            with self.subTest(url=url):
                self.assertEqual(self._get(api_callflow.ventas, url)[0].status_code, 400)

    def test_dinero_y_fechas_como_texto(self):
        self.assertEqual(api_callflow._json(Decimal("450.00")), "450.00")
        self.assertEqual(api_callflow._json(dt.datetime(2026, 11, 23, tzinfo=dt.timezone.utc)), "2026-11-23T00:00:00+00:00")
