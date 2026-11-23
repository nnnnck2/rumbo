"""Pruebas sin base de SCRUM-28 (lista de llamadas) y SCRUM-29 (ficha)."""
import datetime as dt

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from leads import operacion

UTC = dt.timezone.utc
AHORA = dt.datetime(2026, 11, 23, 15, 0, tzinfo=UTC)


class TextoEsperaTests(SimpleTestCase):
    def test_minutos_horas_y_dias(self):
        self.assertEqual(operacion.texto_espera(AHORA - dt.timedelta(minutes=7), AHORA), "7 min")
        self.assertEqual(operacion.texto_espera(AHORA - dt.timedelta(minutes=65), AHORA), "1 h 05 min")
        self.assertEqual(operacion.texto_espera(AHORA - dt.timedelta(days=2, hours=3), AHORA), "2 d")

    def test_sin_fecha_o_futura(self):
        self.assertEqual(operacion.texto_espera(None, AHORA), "")
        self.assertEqual(operacion.texto_espera(AHORA + dt.timedelta(minutes=5), AHORA), "0 min")


class OrdenListaTests(SimpleTestCase):
    def test_nuevos_primero_luego_prioridad_y_espera(self):
        qs = operacion.orden_lista_llamadas(operacion.Lead.objects.all())
        self.assertEqual(qs.query.order_by, ("tipo_llamada", "-prioridad", "espera_desde", "id"))

    def test_nombres_de_los_tipos(self):
        self.assertEqual(list(operacion.TIPOS_LLAMADA.values()), ["Nuevo", "Agendada", "Reintento"])


class ListaSeActualizaSolaTests(SimpleTestCase):
    """La pestaña "Por llamar ahora" se refresca por HTMX; las demás no (no se pierde lo que se está leyendo)."""

    def test_plantilla_tiene_el_polling_solo_en_pendientes(self):
        with open("leads/templates/leads/lista.html", encoding="utf-8") as f:
            plantilla = f.read()
        self.assertIn('{% if activa == "pendientes" %}hx-get=', plantilla)
        self.assertIn("every 10s", plantilla)
        self.assertIn("marca-lead:checked", plantilla)      # no se refresca con leads marcados


class FichaClicParaLlamarTests(SimpleTestCase):
    def test_enlace_tel(self):
        with open("leads/templates/leads/_ficha.html", encoding="utf-8") as f:
            ficha = f.read()
        self.assertIn('href="tel:{{ lead.telefono }}"', ficha)
        self.assertIn("Etapa · próxima acción", ficha)


class TelefonoManualTests(SimpleTestCase):
    """SCRUM-53 · Número dictado por el cliente → E.164."""

    def test_formatos_de_ecuador(self):
        from leads.forms import normalizar_telefono

        for texto in ("0991234567", "099 123 4567", "991234567", "593991234567", "+593 99 123 4567", "00593991234567"):
            with self.subTest(texto=texto):
                self.assertEqual(normalizar_telefono(texto), "+593991234567")

    def test_fijo_y_extranjero(self):
        from leads.forms import normalizar_telefono

        self.assertEqual(normalizar_telefono("02 245 6789"), "+59322456789")
        self.assertEqual(normalizar_telefono("+1 (305) 555-0100"), "+13055550100")

    def test_invalidos(self):
        from django.forms import ValidationError

        from leads.forms import normalizar_telefono

        for texto in ("", "12", "abc", "+0123456789"):
            with self.subTest(texto=texto), self.assertRaises(ValidationError):
                normalizar_telefono(texto)


class LeadManualConfigTests(SimpleTestCase):
    def test_desde_y_hacia_la_configuracion(self):
        from leads.forms import ConfiguracionForm

        self.assertTrue(ConfiguracionForm.desde_configuracion({})["lead_manual_asignar"])
        self.assertFalse(ConfiguracionForm.desde_configuracion(
            {"lead_manual": {"asignar_a_quien_registra": False}})["lead_manual_asignar"])
        self.assertIn("lead_manual_asignar", ConfiguracionForm.PESTANAS["reparto"])
