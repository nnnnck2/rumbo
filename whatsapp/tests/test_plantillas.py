"""SCRUM-55 (plantillas de seguimiento) y SCRUM-59 (sale por el número del asesor), sin base."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from leads.forms import ConfiguracionForm
from whatsapp import envio_asesor

CONFIG = {"activo": True, "plantillas": [
    {"nombre": "lista_documentos", "titulo": "Lista de documentos", "idioma": "es", "variables": ["nombre", "documentos"]},
    {"nombre": "hola_simple", "titulo": "Hola", "idioma": "es_EC", "variables": []}]}


def lead(numero="123456789012345"):
    asesor = SimpleNamespace(numero_whatsapp=SimpleNamespace(meta_phone_number_id=numero) if numero else None)
    return SimpleNamespace(pk=8, telefono="+593995551234", nombre_perfil="Pedro Pérez", asesor=asesor)


class PlantillasTests(SimpleTestCase):
    def test_desactivadas_no_se_ofrecen(self):
        self.assertEqual(envio_asesor.plantillas_disponibles({**CONFIG, "activo": False}), [])
        self.assertEqual(len(envio_asesor.plantillas_disponibles(CONFIG)), 2)

    def test_variables_en_orden(self):
        self.assertEqual(envio_asesor.variables_plantilla(CONFIG["plantillas"][0], lead(), "Beto", ["Pasaporte", "Foto"]),
                         ["Pedro", "Pasaporte, Foto"])

    def _enviar(self, nombre="lista_documentos", config=CONFIG, respuesta=(200, {"messages": [{"id": "wamid.X"}]}), l=None):
        with mock.patch.object(envio_asesor.cliente, "llamar_api", return_value=respuesta) as api, \
             mock.patch.object(envio_asesor, "connection") as conexion:
            wamid = envio_asesor.enviar_plantilla(l or lead(), nombre, config, "Beto", ["Pasaporte"])
        return wamid, api, conexion.cursor.return_value.__enter__.return_value.execute.call_args

    def test_envia_por_el_numero_del_asesor_y_registra(self):
        wamid, api, registro = self._enviar()
        self.assertEqual(wamid, "wamid.X")
        pnid, cuerpo = api.call_args[0]
        self.assertEqual(pnid, "123456789012345")                         # SCRUM-59: número del asesor
        self.assertEqual(cuerpo["template"]["name"], "lista_documentos")
        self.assertEqual([p["text"] for p in cuerpo["template"]["components"][0]["parameters"]], ["Pedro", "Pasaporte"])
        sql, params = registro[0]
        self.assertIn("registrar_mensaje_saliente", sql)
        self.assertEqual(params[3], "template")
        self.assertIn('"seguimiento": true', params[4])

    def test_plantilla_sin_variables(self):
        _wamid, api, _r = self._enviar("hola_simple")
        self.assertNotIn("components", api.call_args[0][1]["template"])

    def test_no_envia_si_esta_desactivada_o_no_existe(self):
        for nombre, config in (("lista_documentos", {**CONFIG, "activo": False}), ("otra", CONFIG)):
            with self.subTest(nombre=nombre), self.assertRaises(envio_asesor.NoEnviado):
                self._enviar(nombre, config)

    def test_sin_numero_del_asesor(self):
        with self.assertRaises(envio_asesor.NoEnviado) as e:
            self._enviar(l=lead(numero=None))
        self.assertIn("número de WhatsApp", e.exception.mensaje)

    def test_error_de_meta(self):
        with self.assertRaises(envio_asesor.NoEnviado):
            self._enviar(respuesta=(400, {"error": {"code": 132001, "message": "Template name does not exist"}}))


class ConfigPlantillasTests(SimpleTestCase):
    def test_ida_y_vuelta(self):
        inicial = ConfiguracionForm.desde_configuracion({"plantillas_seguimiento": CONFIG})
        self.assertTrue(inicial["pl_activo"])
        self.assertEqual((inicial["pl_nombre_0"], inicial["pl_variables_0"]), ("lista_documentos", ["nombre", "documentos"]))
        self.assertIn("pl_activo", ConfiguracionForm.PESTANAS["whatsapp"])

    def test_desactivadas_por_defecto(self):
        self.assertFalse(ConfiguracionForm.desde_configuracion({})["pl_activo"])
