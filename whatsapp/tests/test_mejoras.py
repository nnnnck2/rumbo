"""SCRUM-88 (aviso de no contesta), SCRUM-91 (próxima apertura) y SCRUM-92 (conversiones para Meta)."""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from whatsapp import aviso_no_contesta as anc
from whatsapp import conversiones
from whatsapp import respuesta_automatica as ra

UTC = dt.timezone.utc
AHORA = dt.datetime(2026, 11, 19, 15, 0, tzinfo=UTC)
CONFIG = {"activo": True, "texto": "Hola {nombre}, le saluda {asesor} de Multivisa.", "plantilla": "",
          "idioma": "es", "horas_entre": 24}


def estado(**kw):
    base = {"telefono": "+593991234567", "nombre": "Ana Pérez", "pnid": "111", "estado": "asignado",
            "ultimo_entrante": AHORA - dt.timedelta(hours=2), "ultimo_aviso": None, "asesor": "Carlos",
            "config": dict(CONFIG)}
    return base | kw


class ComponerAvisoTests(SimpleTestCase):
    def test_reemplaza_nombre_y_asesor(self):
        self.assertEqual(anc.componer(CONFIG["texto"], "Ana Pérez", "Carlos"), "Hola Ana, le saluda Carlos de Multivisa.")

    def test_sin_nombre_no_deja_espacios_raros(self):
        self.assertEqual(anc.componer(CONFIG["texto"], None, None), "Hola, le saluda su asesor de Multivisa.")


class DecidirAvisoTests(SimpleTestCase):
    def test_ventana_abierta_envia_texto(self):
        tipo, texto = anc.decidir(estado(), AHORA)
        self.assertEqual((tipo, texto), ("texto", "Hola Ana, le saluda Carlos de Multivisa."))

    def test_desactivado(self):
        self.assertEqual(anc.decidir(estado(config=CONFIG | {"activo": False}), AHORA), ("nada", "desactivado"))

    def test_lead_cerrado(self):
        self.assertEqual(anc.decidir(estado(estado="cerrado"), AHORA)[0], "nada")

    def test_no_repite_dentro_de_las_horas_configuradas(self):
        self.assertEqual(anc.decidir(estado(ultimo_aviso=AHORA - dt.timedelta(hours=3)), AHORA)[0], "nada")
        self.assertEqual(anc.decidir(estado(ultimo_aviso=AHORA - dt.timedelta(hours=30)), AHORA)[0], "texto")

    def test_ventana_cerrada_usa_plantilla_o_no_envia(self):
        viejo = AHORA - dt.timedelta(hours=30)
        self.assertEqual(anc.decidir(estado(ultimo_entrante=viejo), AHORA)[0], "nada")
        con_plantilla = estado(ultimo_entrante=viejo, config=CONFIG | {"plantilla": "recordatorio"})
        self.assertEqual(anc.decidir(con_plantilla, AHORA), ("plantilla", None))


@override_settings(WHATSAPP_ACCESS_TOKEN="token")
class EnviarAvisoTests(SimpleTestCase):
    def _enviar(self, est, api=(200, {"messages": [{"id": "wamid.AV"}]})):
        with mock.patch.object(anc, "_leer_estado", return_value=est), \
             mock.patch.object(anc.timezone, "now", return_value=AHORA), \
             mock.patch.object(anc.cliente, "llamar_api", return_value=api) as llamar, \
             mock.patch.object(anc, "como_sistema") as sistema:
            resultado = anc.enviar(5, 9)
        return resultado, llamar, sistema

    def test_envia_texto_y_registra_como_automatico(self):
        resultado, llamar, sistema = self._enviar(estado())
        self.assertEqual(resultado, "enviado (texto)")
        pnid, cuerpo = llamar.call_args.args
        self.assertEqual((pnid, cuerpo["type"], cuerpo["to"]), ("111", "text", "593991234567"))
        sql, params = sistema.return_value.__enter__.return_value.execute.call_args.args
        self.assertIn("registrar_mensaje_automatico", sql)
        self.assertEqual(params[:2], [5, "wamid.AV"])

    def test_plantilla_fuera_de_la_ventana(self):
        est = estado(ultimo_entrante=AHORA - dt.timedelta(days=2), config=CONFIG | {"plantilla": "recordatorio"})
        resultado, llamar, _ = self._enviar(est)
        self.assertEqual(resultado, "enviado (plantilla)")
        self.assertEqual(llamar.call_args.args[1]["template"]["name"], "recordatorio")

    def test_error_5xx_se_reintenta(self):
        with self.assertRaises(ra.EnvioFallido) as e:
            self._enviar(estado(), api=(500, {"error": {"message": "caído", "code": 1}}))
        self.assertTrue(e.exception.reintentar)

    def test_nada_que_enviar_no_llama_a_meta(self):
        resultado, llamar, _ = self._enviar(estado(config=CONFIG | {"activo": False}))
        self.assertTrue(resultado.startswith("no enviado"))
        llamar.assert_not_called()


class ProximaAperturaTests(SimpleTestCase):
    """SCRUM-91 · {proxima_apertura} en el texto de fuera de horario (zona America/Guayaquil, UTC-5)."""
    jueves_noche = dt.datetime(2026, 11, 20, 2, 0, tzinfo=UTC)          # jueves 19/11 21:00 en Ecuador

    def test_textos(self):
        self.assertEqual(ra.texto_apertura(dt.datetime(2026, 11, 20, 14, 0, tzinfo=UTC), self.jueves_noche),
                         "mañana viernes desde las 09:00")
        self.assertEqual(ra.texto_apertura(dt.datetime(2026, 11, 23, 14, 0, tzinfo=UTC), self.jueves_noche),
                         "el lunes 23/11 desde las 09:00")
        self.assertEqual(ra.texto_apertura(dt.datetime(2026, 11, 20, 1, 0, tzinfo=UTC), self.jueves_noche),
                         "hoy desde las 20:00")
        self.assertEqual(ra.texto_apertura(None), "en cuanto abramos")

    def test_componer_reemplaza_la_marca(self):
        with mock.patch.object(ra.timezone, "now", return_value=self.jueves_noche):
            texto = ra.componer({"texto_fuera_horario": "Le llamaremos {proxima_apertura}."}, False,
                                dt.datetime(2026, 11, 20, 14, 0, tzinfo=UTC))
        self.assertEqual(texto, "Le llamaremos mañana viernes desde las 09:00.")


@override_settings(META_DATASET_ID="123", META_CAPI_TOKEN="tok", META_WABA_ID="999", META_CAPI_TEST_CODE="")
class ConversionesTests(SimpleTestCase):
    fila = {"id": 15, "lead_id": 7, "evento": "Purchase", "ctwa_clid": "CLID", "telefono": "+593991234567",
            "ocurrido_en": dt.datetime(2026, 11, 19, 15, 0, tzinfo=UTC), "valor": Decimal("350.00"), "moneda": "USD"}

    def test_evento_sin_datos_personales_en_claro(self):
        e = conversiones.armar_evento(self.fila)
        self.assertEqual((e["event_name"], e["action_source"], e["messaging_channel"], e["event_id"]),
                         ("Purchase", "business_messaging", "whatsapp", "rumbo-15"))
        self.assertEqual(e["user_data"]["ctwa_clid"], "CLID")
        self.assertEqual(e["user_data"]["whatsapp_business_account_id"], "999")
        self.assertEqual(e["user_data"]["ph"], [conversiones.hash_telefono("+593991234567")])
        self.assertNotIn("593991234567", str(e))
        self.assertEqual(e["custom_data"], {"currency": "USD", "value": 350.0})

    def test_cita_sin_valor(self):
        e = conversiones.armar_evento(self.fila | {"evento": "Schedule", "valor": None})
        self.assertNotIn("custom_data", e)

    def test_hash_solo_digitos(self):
        self.assertEqual(conversiones.hash_telefono("+593 99-123-4567"), conversiones.hash_telefono("593991234567"))

    @override_settings(META_DATASET_ID="")
    def test_sin_configurar_no_toca_la_base(self):
        with mock.patch.object(conversiones, "como_sistema") as sistema:
            resultado = conversiones.enviar_pendientes()
        self.assertIn("omitido", resultado)
        sistema.assert_not_called()

    def _enviar(self, respuesta):
        cursor = mock.MagicMock()
        columnas = ["id", "lead_id", "evento", "ctwa_clid", "ocurrido_en", "telefono", "valor", "moneda"]
        cursor.description = [type("C", (), {"name": c}) for c in columnas]
        cursor.fetchall.return_value = [tuple(self.fila[c] for c in columnas)]
        sistema = mock.MagicMock()
        sistema.return_value.__enter__.return_value = cursor
        with mock.patch.object(conversiones, "como_sistema", sistema), \
             mock.patch.object(conversiones, "_publicar", return_value=respuesta) as publicar:
            resultado = conversiones.enviar_pendientes()
        marcas = [c.args for c in cursor.execute.call_args_list if "marcar_evento_conversion" in c.args[0]]
        return resultado, publicar, marcas

    def test_envio_correcto_marca_enviado(self):
        resultado, publicar, marcas = self._enviar((200, {"events_received": 1}))
        self.assertEqual(resultado["enviados"], 1)
        self.assertEqual(publicar.call_args.args[0][0]["event_id"], "rumbo-15")
        self.assertEqual(marcas[0][1], [15, None, False])

    def test_error_400_es_definitivo(self):
        resultado, _, marcas = self._enviar((400, {"error": {"message": "Invalid parameter", "code": 100}}))
        self.assertEqual(resultado["fallidos"], 1)
        self.assertTrue(marcas[0][1][2])

    def test_error_500_se_reintenta(self):
        _, _, marcas = self._enviar((500, {"error": {"message": "caído"}}))
        self.assertFalse(marcas[0][1][2])


class PreverAvisoTests(SimpleTestCase):
    """SCRUM-104 · Lo que se le dice al asesor al registrar "No contesta"."""

    def _prever(self, est):
        with mock.patch.object(anc, "_estado_del_request", return_value=est), \
             mock.patch.object(anc.timezone, "now", return_value=AHORA):
            return anc.prever(5, 9)

    def test_se_envia(self):
        self.assertEqual(self._prever(estado()), (True, "Rumbo le envía un WhatsApp a Ana avisando que lo llamó."))

    def test_motivos_para_no_enviar(self):
        self.assertIn("ya se le avisó", self._prever(estado(ultimo_aviso=AHORA - dt.timedelta(hours=1)))[1])
        self.assertIn("más de 24 h", self._prever(estado(ultimo_entrante=AHORA - dt.timedelta(days=2)))[1])
        self.assertEqual(self._prever(estado(config=CONFIG | {"activo": False})),
                         (False, "No se envió WhatsApp: el aviso automático está desactivado."))
