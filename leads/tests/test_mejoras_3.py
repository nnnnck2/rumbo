"""Pruebas sin base de SCRUM-114 a SCRUM-130 (la parte de base está en db/pruebas/11_bot_lopdp_push.sql)."""
import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from leads import operacion, servicios
from leads.forms import ConfiguracionForm

UTC = dt.timezone.utc


class DocumentosTests(SimpleTestCase):
    """SCRUM-117."""
    config = {"General": "Pasaporte\nFoto", "Turismo": "- Pasaporte\n• Extractos bancarios\n\n"}

    def lead(self, tipo=None, marcados=None):
        return SimpleNamespace(tipo_visa=tipo, datos={"documentos": marcados or {}})

    def test_lista_por_tipo_de_visa_con_estado(self):
        docs = operacion.documentos_de(self.lead("turismo", {"Pasaporte": "recibido"}), self.config)
        self.assertEqual(docs, [{"nombre": "Pasaporte", "estado": "recibido"},
                                {"nombre": "Extractos bancarios", "estado": "falta"}])

    def test_sin_tipo_usa_el_general(self):
        self.assertEqual([d["nombre"] for d in operacion.documentos_de(self.lead(), self.config)], ["Pasaporte", "Foto"])

    def test_ciclo_de_estados(self):
        self.assertEqual([operacion.siguiente_estado(e) for e in ("falta", "pedido", "recibido")],
                         ["pedido", "recibido", "falta"])


class CalidadTests(SimpleTestCase):
    """SCRUM-129 · 60 % de la tasa del equipo, con al menos 10 llamadas."""

    def test_detecta_contacto_bajo(self):
        asesores = [{"id": 1, "nombre": "Ana", "llamadas": 40, "contactos": 20, "citas": 6},
                    {"id": 2, "nombre": "Beto", "llamadas": 40, "contactos": 20, "citas": 6},
                    {"id": 3, "nombre": "Caro", "llamadas": 40, "contactos": 4, "citas": 1}]
        alertas = operacion.evaluar_calidad(asesores)
        self.assertEqual([a["nombre"] for a in alertas], ["Caro"])
        self.assertIn("contacto 10 %", alertas[0]["motivos"][0])

    def test_pocas_llamadas_no_alerta(self):
        asesores = [{"id": 1, "nombre": "Ana", "llamadas": 40, "contactos": 20, "citas": 5},
                    {"id": 2, "nombre": "Nuevo", "llamadas": 5, "contactos": 0, "citas": 0}]
        self.assertEqual(operacion.evaluar_calidad(asesores), [])

    def test_sin_llamadas(self):
        self.assertEqual(operacion.evaluar_calidad([]), [])


class ComisionTests(SimpleTestCase):
    """SCRUM-130."""

    def test_porcentaje(self):
        c = operacion.calcular_comision([(Decimal("300"), "USD"), (Decimal("200"), "USD")], {"tipo": "porcentaje", "valor": 5})
        self.assertEqual((c["ventas"], c["total"], c["estimada"], c["moneda"]), (2, Decimal("500"), Decimal("25.00"), "USD"))

    def test_fijo_por_venta(self):
        c = operacion.calcular_comision([(Decimal("300"), "USD")] * 3, {"tipo": "fijo", "valor": 20})
        self.assertEqual(c["estimada"], Decimal("60.00"))

    def test_sin_ventas(self):
        self.assertEqual(operacion.calcular_comision([], {"tipo": "porcentaje", "valor": 5})["estimada"], Decimal("0.00"))


class LineaDeTiempoTests(SimpleTestCase):
    """SCRUM-126 · Todo mezclado y del más reciente al más antiguo."""

    def test_orden(self):
        t = lambda h: dt.datetime(2026, 11, 19, h, tzinfo=UTC)  # noqa: E731
        nota = SimpleNamespace(creado_en=t(9), autor_usuario=SimpleNamespace(nombre="Ana"), texto="Llamar tarde")
        mensaje = SimpleNamespace(ocurrido_en=t(11), direccion="entrante", payload={}, cuerpo="Hola", tipo="text")
        eventos = operacion.linea_de_tiempo(None, [], [], [], [nota], [mensaje])
        self.assertEqual([e["tipo"] for e in eventos], ["mensaje", "nota"])
        self.assertEqual(eventos[0]["titulo"], "WhatsApp · Cliente")


class HaceCortoTests(SimpleTestCase):
    def test_formatos(self):
        ahora = dt.datetime(2026, 11, 19, 15, 0, tzinfo=UTC)
        casos = {dt.timedelta(seconds=20): "ahora", dt.timedelta(minutes=12): "12 min",
                 dt.timedelta(hours=4, minutes=18): "4 h 18", dt.timedelta(hours=5): "5 h",
                 dt.timedelta(hours=12, minutes=40): "12 h", dt.timedelta(days=2, hours=3): "2 días"}
        for delta, texto in casos.items():
            self.assertEqual(servicios.hace_corto(ahora - delta, ahora), texto, delta)
        self.assertIsNone(servicios.hace_corto(None, ahora))


class CitaTests(SimpleTestCase):
    def test_lee_la_fecha_guardada(self):
        lead = SimpleNamespace(datos={"cita_en": "2026-11-20T10:30:00-05:00"})
        self.assertEqual(operacion.cita_de(lead).hour, 10)
        self.assertIsNone(operacion.cita_de(SimpleNamespace(datos={"cita_en": "mañana"})))
        self.assertIsNone(operacion.cita_de(SimpleNamespace(datos={})))


class ConfiguracionNuevaTests(SimpleTestCase):
    base = {"hora_inicio": "09:00", "hora_fin": "18:00", "dias": ["1"], "max_intentos_por_asesor": 3,
            "minutos_primera_llamada": 30, "minutos_entre_reintentos": 30, "minutos_alerta_supervisor": 30,
            "texto_bienvenida": "Hola", "texto_fuera_horario": "Fuera", "max_intentos_por_lead": 9,
            "aviso_texto": "Hola", "aviso_idioma": "es", "aviso_horas": 24,
            "meta_llamadas": 20, "meta_citas": 3, "meta_ventas": 1}

    def test_secciones_nuevas(self):
        f = ConfiguracionForm(self.base | {"bot_activo": "on", "rec_plantilla": "recordatorio_cita",
                                           "reporte_destinatarios": "a@multivisa.ec, b@multivisa.ec",
                                           "comision_tipo": "fijo", "comision_valor": "25",
                                           "rr_titulo_0": "Saludo", "rr_texto_0": "Hola {nombre}", "doc_0": "Pasaporte"})
        self.assertTrue(f.is_valid(), f.errors)
        c = f.cambios()
        self.assertTrue(c["bot_preguntas"]["activo"])
        self.assertEqual(c["recordatorio_cita"]["plantilla"], "recordatorio_cita")
        self.assertEqual(c["reporte_semanal"], {"destinatarios": ["a@multivisa.ec", "b@multivisa.ec"]})
        self.assertEqual(c["comision"], {"tipo": "fijo", "valor": 25.0})
        self.assertEqual(c["respuestas_rapidas"], {"Saludo": "Hola {nombre}"})
        self.assertEqual(c["documentos_por_visa"], {"General": "Pasaporte"})

    def test_correo_invalido(self):
        f = ConfiguracionForm(self.base | {"reporte_destinatarios": "gerencia, otro@x.ec"})
        self.assertFalse(f.is_valid())
        self.assertIn("reporte_destinatarios", f.errors)

    def test_todos_los_campos_estan_en_una_pestana(self):
        en_pestanas = {c for campos in ConfiguracionForm.PESTANAS.values() for c in campos}
        self.assertEqual(set(ConfiguracionForm().fields), en_pestanas)


class MejoresHorasTests(SimpleTestCase):
    """SCRUM-128 · el resumen en palabras solo usa horas con al menos 5 llamadas."""

    def celda(self, dia, hora, llamadas, contactos):
        return {"dia": dia, "hora": hora, "llamadas": llamadas, "contactos": contactos,
                "pct": round(100 * contactos / llamadas) if llamadas else None}

    def test_mejor_y_peor_momento(self):
        filas = [{"celdas": [self.celda("jueves", 9, 10, 8), self.celda("jueves", 10, 2, 2),
                             self.celda("miércoles", 14, 7, 2), self.celda("lunes", 11, 0, 0)]}]
        resumen = operacion.resumen_mapa(filas)
        self.assertEqual((resumen["mejor"]["dia"], resumen["mejor"]["hora"]), ("jueves", 9))   # 100 % con 2 llamadas no cuenta
        self.assertEqual((resumen["peor"]["dia"], resumen["peor"]["hora"]), ("miércoles", 14))

    def test_pocas_llamadas_no_recomienda(self):
        self.assertIsNone(operacion.resumen_mapa([{"celdas": [self.celda("jueves", 9, 4, 4)]}]))

    def test_una_sola_hora_confiable_no_tiene_peor(self):
        self.assertIsNone(operacion.resumen_mapa([{"celdas": [self.celda("jueves", 9, 6, 3)]}])["peor"])
