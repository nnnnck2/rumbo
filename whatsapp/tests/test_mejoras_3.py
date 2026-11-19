"""SCRUM-114 (responder), 115 (bot), 116 (recordatorios), 122 (push): lógica sin base."""
import datetime as dt
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from core import push
from whatsapp import bot, cliente, envio_asesor, recordatorios
from whatsapp.parser import extraer_mensajes

UTC = dt.timezone.utc


class BotTests(SimpleTestCase):
    def test_interpretar(self):
        self.assertEqual(bot.interpretar("bot:visa:Turismo"), ("visa", "Turismo"))
        self.assertEqual(bot.interpretar("bot:pais:Estados Unidos"), ("pais", "Estados Unidos"))
        for otro in (None, "", "bot:otra:x", "bot:visa:", "menu:1"):
            self.assertIsNone(bot.interpretar(otro), otro)

    def test_opciones_entran_en_una_lista_de_whatsapp(self):
        for paso in ("visa", "pais"):
            filas = bot.opciones(paso)
            self.assertLessEqual(len(filas), 10)
            self.assertEqual(filas[-1][1], "Otro")
            self.assertTrue(all(i.startswith(f"bot:{paso}:") for i, _t in filas))

    def test_respuesta_otro_no_guarda_y_sigue(self):
        with mock.patch.object(bot, "preguntar", return_value="enviado (pais)") as preguntar, \
             mock.patch.object(bot, "como_sistema") as sistema:
            self.assertEqual(bot.procesar_respuesta(5, "bot:visa:Otro"), "enviado (pais)")
        sistema.assert_not_called()
        preguntar.assert_called_once_with(5, "pais")

    def test_respuesta_guarda_y_agradece_al_final(self):
        with mock.patch.object(bot, "preguntar", return_value="enviado (fin)") as preguntar, \
             mock.patch.object(bot, "como_sistema") as sistema:
            bot.procesar_respuesta(5, "bot:pais:España")
        sql, params = sistema.return_value.__enter__.return_value.execute.call_args.args
        self.assertIn("guardar_dato_bot", sql)
        self.assertEqual(params, [5, "pais_interes", "España"])
        preguntar.assert_called_once_with(5, "fin")

    def test_parser_lee_el_id_de_la_opcion(self):
        payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": "1", "display_phone_number": "593961319535"},
            "contacts": [{"wa_id": "593991234567", "profile": {"name": "Ana"}}],
            "messages": [{"id": "wamid.X", "from": "593991234567", "timestamp": "1763560000", "type": "interactive",
                          "interactive": {"type": "list_reply", "list_reply": {"id": "bot:visa:Turismo", "title": "Turismo"}}}]}}]}]}
        m = extraer_mensajes(payload)[0]
        self.assertEqual((m.respuesta_id, m.cuerpo), ("bot:visa:Turismo", "Turismo"))


class RecordatorioTests(SimpleTestCase):
    ahora = dt.datetime(2026, 11, 19, 10, 0, tzinfo=UTC)

    def test_cual_toca(self):
        h = lambda horas: self.ahora + dt.timedelta(hours=horas)  # noqa: E731
        self.assertEqual(recordatorios.cual_toca(h(23.5), set(), self.ahora), "24")
        self.assertIsNone(recordatorios.cual_toca(h(23.5), {"24"}, self.ahora))
        self.assertEqual(recordatorios.cual_toca(h(1.5), {"24"}, self.ahora), "2")
        self.assertIsNone(recordatorios.cual_toca(h(1.5), {"2"}, self.ahora))
        self.assertIsNone(recordatorios.cual_toca(h(30), set(), self.ahora))
        self.assertIsNone(recordatorios.cual_toca(h(-1), set(), self.ahora))

    def test_cita_agendada_hace_poco_no_manda_el_de_24_si_ya_toca_el_de_2(self):
        self.assertEqual(recordatorios.cual_toca(self.ahora + dt.timedelta(hours=1), set(), self.ahora), "2")


class EnvioAsesorTests(SimpleTestCase):
    def test_completar_respuesta_rapida(self):
        lead = SimpleNamespace(nombre_perfil="Ana Pérez")
        texto = envio_asesor.completar("Hola {nombre}, necesitamos: {documentos}. Cita: {cita}", lead, "Carlos",
                                       ["Pasaporte", "Foto"], "20/11 a las 10:00")
        self.assertEqual(texto, "Hola Ana, necesitamos: Pasaporte, Foto. Cita: 20/11 a las 10:00")
        self.assertEqual(envio_asesor.completar("Hola {nombre}, soy {asesor}.", SimpleNamespace(nombre_perfil=None), None),
                         "Hola, soy su asesor.")

    def _lead(self, ultimo_entrante):
        mensajes = mock.MagicMock()
        mensajes.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = ultimo_entrante
        numero = SimpleNamespace(meta_phone_number_id="111")
        return SimpleNamespace(pk=5, telefono="+593991234567", mensajes=mensajes,
                               asesor=SimpleNamespace(numero_whatsapp=numero))

    def test_fuera_de_la_ventana_no_envia(self):
        lead = self._lead(dt.datetime.now(UTC) - dt.timedelta(hours=30))
        with mock.patch.object(envio_asesor.cliente, "llamar_api") as llamar:
            with self.assertRaises(envio_asesor.NoEnviado) as e:
                envio_asesor.enviar(lead, "Hola")
        self.assertIn("24 h", e.exception.mensaje)
        llamar.assert_not_called()

    @override_settings(WHATSAPP_ACCESS_TOKEN="token")
    def test_envia_y_registra(self):
        lead = self._lead(dt.datetime.now(UTC) - dt.timedelta(hours=1))
        with mock.patch.object(envio_asesor.cliente, "llamar_api", return_value=(200, {"messages": [{"id": "wamid.A"}]})) as llamar, \
             mock.patch.object(envio_asesor, "connection") as conexion:
            self.assertEqual(envio_asesor.enviar(lead, "Hola"), "wamid.A")
        self.assertEqual(llamar.call_args.args[0], "111")
        sql, params = conexion.cursor.return_value.__enter__.return_value.execute.call_args.args
        self.assertIn("registrar_mensaje_saliente", sql)
        self.assertEqual(params, [5, "wamid.A", "Hola"])

    @override_settings(WHATSAPP_ACCESS_TOKEN="token")
    def test_error_de_meta_en_palabras_simples(self):
        lead = self._lead(dt.datetime.now(UTC) - dt.timedelta(hours=1))
        with mock.patch.object(envio_asesor.cliente, "llamar_api", return_value=(400, {"error": {"code": 131047}})):
            with self.assertRaises(envio_asesor.NoEnviado) as e:
                envio_asesor.enviar(lead, "Hola")
        self.assertIn("plantillas aprobadas", e.exception.mensaje)

    def test_texto_vacio(self):
        with self.assertRaises(envio_asesor.NoEnviado):
            envio_asesor.enviar(self._lead(None), "   ")


class ClienteTests(SimpleTestCase):
    def test_lista_interactiva_respeta_limites(self):
        filas = [(f"bot:visa:{i}", "Un título demasiado largo para WhatsApp") for i in range(12)]
        cuerpo = cliente.cuerpo_lista("+593991234567", "¿Qué visa?", "Elegir una opción", filas)
        accion = cuerpo["interactive"]["action"]
        self.assertEqual(len(accion["sections"][0]["rows"]), 10)
        self.assertLessEqual(len(accion["button"]), 20)
        self.assertTrue(all(len(r["title"]) <= 24 for r in accion["sections"][0]["rows"]))

    def test_plantilla_con_variables(self):
        cuerpo = cliente.cuerpo_plantilla_con_textos("+593991234567", "recordatorio", "es", ["Ana", "lunes 24/11"])
        self.assertEqual([p["text"] for p in cuerpo["template"]["components"][0]["parameters"]], ["Ana", "lunes 24/11"])


class PushTests(SimpleTestCase):
    def test_aviso(self):
        self.assertIn('"url": "/leads/5/"', push.armar_aviso("Cliente nuevo", None, "/leads/5/"))

    @override_settings(WEBPUSH_VAPID_PUBLIC_KEY="", WEBPUSH_VAPID_PRIVATE_KEY="")
    def test_sin_claves_no_toca_la_base(self):
        with mock.patch.object(push, "como_sistema") as sistema:
            self.assertIn("omitido", push.enviar_pendientes())
        sistema.assert_not_called()
