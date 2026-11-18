"""Pruebas sin base de las acciones (SCRUM-30 a 33): formularios y traducción de errores."""
import datetime as dt
from types import SimpleNamespace

from django.db import DatabaseError
from django.test import SimpleTestCase

from leads import servicios
from leads.forms import ConfiguracionForm, EtapaForm


def error_bd(sqlstate, mensaje):
    causa = Exception(mensaje)
    causa.sqlstate = sqlstate
    causa.diag = SimpleNamespace(message_primary=mensaje)
    exc = DatabaseError(mensaje)
    exc.__cause__ = causa
    return exc


class TraducirErroresTests(SimpleTestCase):
    def test_conflicto_de_version(self):
        e = servicios.traducir(error_bd("RB409", "El lead 5 fue modificado por otro usuario"))
        self.assertEqual(e.tipo, "conflicto")
        self.assertIn("Otro usuario modificó", e.mensaje)

    def test_regla_de_negocio_muestra_el_mensaje_de_la_base(self):
        e = servicios.traducir(error_bd("RB422", "El resultado llamar_despues requiere una fecha futura"))
        self.assertEqual((e.tipo, e.mensaje), ("validacion", "El resultado llamar_despues requiere una fecha futura"))

    def test_permiso(self):
        e = servicios.traducir(error_bd("42501", "new row violates row-level security policy"))
        self.assertEqual(e.tipo, "permiso")
        self.assertNotIn("row-level", e.mensaje)

    def test_descartar_sin_motivo(self):
        e = servicios.traducir(error_bd("23514", 'violates check constraint "lead_descarte_ck"'))
        self.assertIn("motivo", e.mensaje)

    def test_error_inesperado_no_se_oculta(self):
        with self.assertRaises(DatabaseError):
            servicios.traducir(error_bd("XX000", "boom"))


class EtapaFormTests(SimpleTestCase):
    def test_descartar_exige_motivo(self):
        f = EtapaForm({"version": 1, "etapa": "descartado"}, etapas=[("descartado", "Descartado")])
        self.assertFalse(f.is_valid())
        self.assertIn("motivo_descarte", f.errors)

    def test_etapa_fuera_de_las_permitidas(self):
        f = EtapaForm({"version": 1, "etapa": "pago"}, etapas=[("en_contacto", "En contacto")])
        self.assertFalse(f.is_valid())
        self.assertIn("etapa", f.errors)


class ConfiguracionFormTests(SimpleTestCase):
    datos = {"hora_inicio": "09:00", "hora_fin": "18:00", "dias": ["1", "2", "3", "4", "5"],
             "max_intentos_por_asesor": 3, "minutos_primera_llamada": 15, "minutos_entre_reintentos": 30,
             "minutos_alerta_supervisor": 30,
             "texto_bienvenida": "¡Hola!", "texto_fuera_horario": "Fuera de horario", "texto_privacidad": ""}

    def test_cambios_en_el_formato_de_la_base(self):
        f = ConfiguracionForm(self.datos)
        self.assertTrue(f.is_valid(), f.errors)
        c = f.cambios("America/Guayaquil")
        self.assertEqual(c["horario"], {"inicio": "09:00", "fin": "18:00", "dias": [1, 2, 3, 4, 5],
                                        "zona": "America/Guayaquil"})
        self.assertEqual(c["max_intentos_por_asesor"], 3)
        self.assertNotIn("texto_privacidad", c)        # vacío: no se guarda

    def test_cierre_antes_de_apertura(self):
        f = ConfiguracionForm(self.datos | {"hora_fin": "08:00"})
        self.assertFalse(f.is_valid())
        self.assertIn("hora_fin", f.errors)

    def test_limites(self):
        f = ConfiguracionForm(self.datos | {"max_intentos_por_asesor": 0, "minutos_entre_reintentos": 5000})
        self.assertFalse(f.is_valid())
        self.assertEqual(set(f.errors), {"max_intentos_por_asesor", "minutos_entre_reintentos"})

    def test_carga_desde_la_base(self):
        inicial = ConfiguracionForm.desde_configuracion(
            {"horario": {"inicio": "08:30:00", "fin": "17:00", "dias": [1, 2], "zona": "UTC"},
             "max_intentos_por_asesor": 4})
        self.assertEqual((inicial["hora_inicio"], inicial["dias"], inicial["max_intentos_por_asesor"]),
                         ("08:30", [1, 2], 4))


class AgendarFormTests(SimpleTestCase):
    def test_no_se_agenda_en_el_pasado(self):
        from leads.forms import AgendarForm
        f = AgendarForm({"version": 1, "cuando": "2020-01-01T10:00"})
        self.assertFalse(f.is_valid())
        self.assertIn("cuando", f.errors)


class NotificacionTests(SimpleTestCase):
    def test_nombre_del_cliente_no_puede_cerrar_el_script(self):
        from unittest import mock

        from django.test import RequestFactory

        from leads import views
        fila = {"nombre_perfil": "</script><img src=x onerror=alert(1)>", "telefono": "+593991234567",
                "asesor": "Ana", "minutos": 40}
        peticion = RequestFactory().get("/leads/alertas/contador/")
        peticion.user = mock.Mock(is_authenticated=True)
        peticion.htmx = True
        with mock.patch("leads.views.servicios.leads_sin_llamar", return_value=[fila]), \
             mock.patch("leads.views.servicios.contexto_actual",
                        return_value=servicios.Contexto(3, "supervisor", None)), \
             mock.patch("cuentas.context_processors.contexto_actual",
                        return_value=servicios.Contexto(3, "supervisor", None)):
            html = views.alertas_contador(peticion).content.decode()
        self.assertNotIn("</script><img", html)
        self.assertIn(r"\u003c/script\u003e", html)
