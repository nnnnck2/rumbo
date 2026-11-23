"""SCRUM-41 sin base: reglas de alerta del webhook y /salud/?completo=1."""
import datetime as dt
from unittest import mock

from django.test import SimpleTestCase, override_settings

from core import monitoreo

UTC = dt.timezone.utc
AHORA = dt.datetime(2026, 11, 23, 17, 0, tzinfo=UTC)        # 12:00 en Ecuador
APERTURA = dt.datetime(2026, 11, 23, 14, 0, tzinfo=UTC)     # 09:00 en Ecuador


def estado(**cambios):
    base = {"ultimo_valido_en": AHORA - dt.timedelta(minutes=10), "recibidos_1h": 3, "atascados": 0,
            "agotados_24h": 0, "con_error_1h": 0, "firmas_invalidas_1h": 0, "ultimo_error": None,
            "en_horario": True, "abierto_desde": APERTURA}
    return base | cambios


def claves(e, **kw):
    return [a[0] for a in monitoreo.evaluar(e, AHORA, **kw)]


class ReglasTests(SimpleTestCase):
    def test_todo_bien_no_alerta(self):
        self.assertEqual(claves(estado()), [])

    def test_mensajes_atascados_y_agotados(self):
        alertas = monitoreo.evaluar(estado(atascados=2, agotados_24h=1, ultimo_error="lead sin teléfono"), AHORA)
        self.assertEqual([a[0] for a in alertas], ["webhook_atascados", "webhook_agotados"])
        self.assertIn("lead sin teléfono", alertas[0][2])

    def test_silencio_en_horario(self):
        self.assertEqual(claves(estado(ultimo_valido_en=AHORA - dt.timedelta(hours=4), abierto_desde=AHORA - dt.timedelta(hours=6)),
                                minutos_silencio=180),
                         ["webhook_silencio"])

    def test_silencio_cuenta_desde_la_apertura(self):
        # Lo último llegó ayer, pero el turno abrió hace 2 h 50 min: todavía no es silencio anormal.
        e = estado(ultimo_valido_en=AHORA - dt.timedelta(hours=20), abierto_desde=AHORA - dt.timedelta(minutes=170))
        self.assertEqual(claves(e, minutos_silencio=180), [])

    def test_fuera_de_horario_no_avisa_silencio(self):
        self.assertEqual(claves(estado(ultimo_valido_en=AHORA - dt.timedelta(hours=10), en_horario=False)), [])

    def test_firmas_invalidas(self):
        self.assertEqual(claves(estado(firmas_invalidas_1h=25)), ["webhook_firmas"])
        self.assertEqual(claves(estado(firmas_invalidas_1h=3)), [])


class VigilarTests(SimpleTestCase):
    @override_settings(WEBHOOK_MINUTOS_SILENCIO=180, RUMBO_ALERTAS_CORREO=["ti@multivisa.ec"], EMAIL_HOST="smtp")
    def test_avisa_registra_correo_y_late(self):
        with mock.patch.object(monitoreo, "leer_estado", return_value=estado(atascados=1)), \
             mock.patch.object(monitoreo, "como_sistema") as sistema, \
             mock.patch.object(monitoreo, "send_mail") as correo, \
             mock.patch.object(monitoreo, "latir") as latir, \
             self.assertLogs("rumbo.monitoreo", "ERROR"):
            sistema.return_value.__enter__.return_value.fetchone.return_value = (1,)
            resultado = monitoreo.vigilar(AHORA)
        self.assertEqual(resultado, {"alertas": ["webhook_atascados"], "avisadas": ["webhook_atascados"]})
        clave = sistema.return_value.__enter__.return_value.execute.call_args[0][1][0]
        self.assertEqual(clave, "webhook_atascados:2026-11-23T12")          # una por hora (hora de Ecuador)
        correo.assert_called_once()
        latir.assert_called_once()

    def test_ya_avisada_no_manda_correo(self):
        with mock.patch.object(monitoreo, "leer_estado", return_value=estado(atascados=1)), \
             mock.patch.object(monitoreo, "como_sistema") as sistema, \
             mock.patch.object(monitoreo, "send_mail") as correo, \
             mock.patch.object(monitoreo, "latir"), self.assertLogs("rumbo.monitoreo", "ERROR"):
            sistema.return_value.__enter__.return_value.fetchone.return_value = (0,)
            self.assertEqual(monitoreo.vigilar(AHORA)["avisadas"], [])
        correo.assert_not_called()


class SaludCompletaTests(SimpleTestCase):
    """/salud/?completo=1: 503 si la vigilancia no late o hay mensajes atascados."""

    def _pedir(self, latido, atascados=0):
        from django.test import RequestFactory

        from core import views

        request = RequestFactory().get("/salud/?completo=1")
        with mock.patch("core.views.connection") as conexion, \
             mock.patch.object(monitoreo, "ultimo_latido", return_value=latido), \
             mock.patch("core.db.como_sistema"), \
             mock.patch.object(monitoreo, "leer_estado", return_value=estado(atascados=atascados)), \
             mock.patch("core.views.timezone.now", return_value=AHORA):
            conexion.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
            return views.salud(request)

    def test_sano(self):
        self.assertEqual(self._pedir(AHORA - dt.timedelta(minutes=4)).status_code, 200)

    def test_vigilancia_caida(self):
        r = self._pedir(AHORA - dt.timedelta(minutes=40))
        self.assertEqual(r.status_code, 503)
        self.assertIn("vigilancia", r.content.decode())

    def test_mensajes_atascados(self):
        self.assertEqual(self._pedir(AHORA - dt.timedelta(minutes=1), atascados=3).status_code, 503)
