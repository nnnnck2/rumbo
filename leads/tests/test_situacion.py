"""015 · Semáforo de gestión: qué color y texto ve el usuario según el estado del lead."""
import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from leads.servicios import situacion

AHORA = timezone.now()


def lead(pk=1, estado="asignado", proxima=None):
    return SimpleNamespace(pk=pk, estado_asignacion=estado, proxima_accion_en=proxima)


def plazo(minutos):
    return {1: (AHORA + dt.timedelta(minutes=minutos, seconds=30), 1)}


class SemaforoTest(SimpleTestCase):
    def test_sin_gestionar_cambia_de_color_con_el_tiempo(self):
        self.assertEqual(situacion(lead(), plazo(25), AHORA)["tono"], "verde")
        self.assertEqual(situacion(lead(), plazo(10), AHORA)["tono"], "amarillo")
        rojo = situacion(lead(), plazo(3), AHORA)
        self.assertEqual((rojo["tono"], rojo["texto"]), ("rojo", "Quedan 3 min"))
        self.assertEqual(situacion(lead(), plazo(25), AHORA, minutos_plazo=30)["pct"], 83)

    def test_plazo_vencido_avisa_que_pasa_a_otro(self):
        s = situacion(lead(), {1: (AHORA - dt.timedelta(minutes=2), 1)}, AHORA)
        self.assertEqual((s["tono"], s["texto"]), ("rojo", "Pasa ya a otro asesor"))

    def test_fuera_de_turno_el_reloj_se_detiene(self):
        self.assertEqual(situacion(lead(), plazo(10), AHORA, abierto=False)["tono"], "pausa")

    def test_llamada_atrasada_y_programada(self):
        self.assertEqual(situacion(lead(proxima=AHORA - dt.timedelta(minutes=10)), {}, AHORA)["tono"], "amarillo")
        atrasada = situacion(lead(proxima=AHORA - dt.timedelta(hours=3)), {}, AHORA)
        self.assertEqual((atrasada["tono"], atrasada["texto"]), ("rojo", "Atrasada 3 h"))
        self.assertEqual(situacion(lead(proxima=AHORA + dt.timedelta(days=2)), {}, AHORA)["tono"], "azul")

    def test_cola_y_cerrado(self):
        self.assertEqual(situacion(lead(estado="en_cola"), {}, AHORA)["tono"], "cola")
        self.assertEqual(situacion(lead(estado="cerrado"), {}, AHORA)["tono"], "cerrado")
