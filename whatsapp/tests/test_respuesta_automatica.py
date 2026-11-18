"""RF-04 · Respuesta automática al primer mensaje (SCRUM-23). Sin base: lectura y API simuladas."""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from whatsapp import cliente, respuesta_automatica as ra, servicios, tasks
from whatsapp.management.commands.simular_mensaje_whatsapp import construir_payload

CONFIG = {"texto_bienvenida": "¡Hola, te saluda Multivisa! ¿Cómo podemos ayudarlo?",
          "texto_fuera_horario": "Estamos fuera de horario; un asesor te contactará en horario de atención.",
          "texto_privacidad": "Aviso LOPDP."}


class ComponerTests(SimpleTestCase):
    def test_en_horario_bienvenida_mas_privacidad(self):
        self.assertEqual(ra.componer(CONFIG, True),
                         "¡Hola, te saluda Multivisa! ¿Cómo podemos ayudarlo?\n\nAviso LOPDP.")

    def test_fuera_de_horario(self):
        self.assertTrue(ra.componer(CONFIG, False).startswith("Estamos fuera de horario"))

    def test_sin_privacidad_ni_textos_usa_los_de_defecto(self):
        self.assertEqual(ra.componer({}, True), ra.POR_DEFECTO["texto_bienvenida"])

    def test_limite_de_whatsapp(self):
        self.assertEqual(len(ra.componer({"texto_bienvenida": "x" * 5000}, True)), ra.LIMITE)


@override_settings(WHATSAPP_ACCESS_TOKEN="token")
class EnviarTests(SimpleTestCase):
    estado = ("+593991234567", "111", False, CONFIG, True)

    def _enviar(self, estado=None, api=(200, {"messages": [{"id": "wamid.OK"}]})):
        with mock.patch.object(ra, "_leer_estado", return_value=estado or self.estado), \
             mock.patch.object(ra.cliente, "llamar_api", return_value=api) as llamar, \
             mock.patch.object(ra, "como_sistema") as sistema:
            resultado = ra.enviar(5, "999")
        return resultado, llamar, sistema

    def test_envia_por_el_numero_de_entrada_y_registra(self):
        resultado, llamar, sistema = self._enviar()
        self.assertEqual(resultado, "enviado (bienvenida)")
        pnid, cuerpo = llamar.call_args.args
        self.assertEqual(pnid, "999")
        self.assertEqual(cuerpo["to"], "593991234567")
        self.assertIn("Aviso LOPDP.", cuerpo["text"]["body"])
        sql, params = sistema.return_value.__enter__.return_value.execute.call_args.args
        self.assertIn("registrar_respuesta_automatica", sql)
        self.assertEqual(params[:2], [5, "wamid.OK"])

    def test_no_repite_si_ya_se_respondio(self):
        resultado, llamar, _ = self._enviar(estado=("+593991234567", "111", True, CONFIG, True))
        self.assertEqual(resultado, "ya respondido")
        llamar.assert_not_called()

    def test_error_5xx_se_reintenta(self):
        with self.assertRaises(ra.EnvioFallido) as e:
            self._enviar(api=(503, {"error": {"message": "caído", "code": 2}}))
        self.assertTrue(e.exception.reintentar)

    def test_error_4xx_no_se_reintenta(self):
        with self.assertRaises(ra.EnvioFallido) as e:
            self._enviar(api=(400, {"error": {"message": "fuera de ventana", "code": 131047}}))
        self.assertFalse(e.exception.reintentar)

    @override_settings(WHATSAPP_ACCESS_TOKEN="")
    def test_sin_token_no_falla(self):
        with mock.patch.object(ra, "_leer_estado", return_value=self.estado), self.assertLogs("rumbo.whatsapp", "WARNING"):
            self.assertEqual(ra.enviar(5), "sin token")

    def test_red_caida_se_reintenta(self):
        with mock.patch.object(ra, "_leer_estado", return_value=self.estado), \
             mock.patch.object(ra.cliente, "llamar_api", side_effect=TimeoutError("timeout")), \
             self.assertRaises(ra.EnvioFallido) as e:
            ra.enviar(5)
        self.assertTrue(e.exception.reintentar)


class TareaTests(SimpleTestCase):
    def test_error_definitivo_no_reintenta(self):
        with mock.patch.object(ra, "enviar", side_effect=ra.EnvioFallido("400", reintentar=False)), \
             self.assertLogs("rumbo.whatsapp", "ERROR"):
            self.assertTrue(tasks.enviar_respuesta_automatica.apply(args=[5]).get().startswith("fallido"))


class EncolarTests(SimpleTestCase):
    """procesar_payload encola la respuesta solo para leads nuevos."""

    def _procesar(self, lead_nuevo, mensaje_nuevo):
        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(1,), (42, lead_nuevo, mensaje_nuevo, None)]
        payload = construir_payload("+593991234567", "Hola", "Ana", "+593961319535", "777")
        with mock.patch.object(servicios.transaction, "on_commit") as on_commit:
            servicios.procesar_payload(cursor, payload)
        return on_commit

    def test_lead_nuevo_encola(self):
        on_commit = self._procesar(True, True)
        on_commit.assert_called_once()
        self.assertEqual(on_commit.call_args.args[0].args, (42, "777"))

    def test_lead_existente_no_encola(self):
        self._procesar(False, True).assert_not_called()

    def test_reenvio_de_meta_no_encola(self):
        self._procesar(True, False).assert_not_called()


class ClienteTests(SimpleTestCase):
    def test_wamid(self):
        self.assertEqual(cliente.wamid({"messages": [{"id": "wamid.X"}]}), "wamid.X")
        self.assertIsNone(cliente.wamid({"error": {}}))
