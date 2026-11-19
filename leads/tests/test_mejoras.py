"""Pruebas sin base de las mejoras SCRUM-88 a SCRUM-100 (la parte de base de datos está en
db/pruebas/10_mejoras_operacion.sql)."""
import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from leads import servicios, zonas
from leads.forms import ConfiguracionForm
from leads.views import _celda, enlace_whatsapp, entradas_por_anuncio

UTC = dt.timezone.utc


class ZonasTests(SimpleTestCase):
    """SCRUM-95 · Hora del cliente por el prefijo de su teléfono."""

    def test_prefijos(self):
        self.assertEqual(zonas.zona_del_telefono("+593991234567"), ("Ecuador", "America/Guayaquil"))
        self.assertEqual(zonas.zona_del_telefono("+573001234567")[0], "Colombia")
        self.assertEqual(zonas.zona_del_telefono("+34612345678")[0], "España")

    def test_el_prefijo_mas_largo_gana(self):
        self.assertEqual(zonas.zona_del_telefono("+18095551234")[0], "Rep. Dominicana")
        self.assertEqual(zonas.zona_del_telefono("+12125551234")[1], "America/New_York")

    def test_desconocido(self):
        self.assertIsNone(zonas.zona_del_telefono("+999123456789"))
        self.assertIsNone(zonas.hora_cliente("sin número"))

    def test_hora_inoportuna(self):
        # 03:00 UTC = 22:00 en Ecuador (UTC-5) → muy tarde; 15:00 UTC = 10:00 → bien
        tarde = zonas.hora_cliente("+593991234567", dt.datetime(2026, 11, 19, 3, 0, tzinfo=UTC))
        self.assertEqual((tarde["hora"].hour, tarde["inoportuna"]), (22, True))
        bien = zonas.hora_cliente("+593991234567", dt.datetime(2026, 11, 19, 15, 0, tzinfo=UTC))
        self.assertFalse(bien["inoportuna"])

    def test_espana_va_por_otra_hora(self):
        h = zonas.hora_cliente("+34612345678", dt.datetime(2026, 11, 19, 15, 0, tzinfo=UTC))
        self.assertEqual(h["hora"].hour, 16)          # Madrid en invierno = UTC+1


class WhatsappEnFichaTests(SimpleTestCase):
    """SCRUM-94 · Enlace wa.me con saludo."""

    def test_enlace_con_saludo(self):
        url = enlace_whatsapp(SimpleNamespace(telefono="+593991234567", nombre_perfil="Ana María Pérez"), "Carlos")
        self.assertTrue(url.startswith("https://wa.me/593991234567?text="))
        self.assertIn("Hola+Ana%2C+le+saluda+Carlos+de+Multivisa.", url)

    def test_sin_nombre(self):
        url = enlace_whatsapp(SimpleNamespace(telefono="+593991234567", nombre_perfil=None), "Carlos")
        self.assertIn("text=Hola%2C+le+saluda+Carlos", url)


class EntradasPorAnuncioTests(SimpleTestCase):
    """SCRUM-100 · Anuncios distintos por los que llegó el cliente."""

    def test_agrupa_por_anuncio_en_orden_de_llegada(self):
        a1, a2 = SimpleNamespace(pk=1), SimpleNamespace(pk=2)
        t = lambda h: dt.datetime(2026, 11, 19, h, tzinfo=UTC)  # noqa: E731
        origenes = [SimpleNamespace(anuncio_id=2, anuncio=a2, llegado_en=t(9)),
                    SimpleNamespace(anuncio_id=1, anuncio=a1, llegado_en=t(10)),
                    SimpleNamespace(anuncio_id=2, anuncio=a2, llegado_en=t(11))]
        entradas = entradas_por_anuncio(origenes)
        self.assertEqual([(e["anuncio"].pk, e["veces"]) for e in entradas], [(2, 2), (1, 1)])


class GuionTests(SimpleTestCase):
    """SCRUM-96 · Guion según el tipo de visa."""
    guiones = {"General": "Saludar\n\nConfirmar nombre", "Turismo": "- Fechas del viaje\n• ¿Viajó antes?"}

    def test_por_tipo_sin_importar_mayusculas_y_sin_vinetas(self):
        self.assertEqual(servicios.guion_para("turismo", self.guiones), ("Turismo", ["Fechas del viaje", "¿Viajó antes?"]))

    def test_sin_tipo_o_sin_guion_propio_usa_el_general(self):
        self.assertEqual(servicios.guion_para(None, self.guiones)[0], "General")
        self.assertEqual(servicios.guion_para("Estudiante", self.guiones), ("General", ["Saludar", "Confirmar nombre"]))

    def test_sin_guiones(self):
        self.assertIsNone(servicios.guion_para("Turismo", {}))


class MetasTests(SimpleTestCase):
    """SCRUM-97 · Meta del día."""

    def test_progreso(self):
        filas = servicios.medir_metas({"llamadas": 12, "citas": 3, "ventas": 0},
                                      {"llamadas": 20, "citas": 3, "ventas": 1})
        self.assertEqual([(f["clave"], f["pct"], f["cumplida"]) for f in filas],
                         [("llamadas", 60, False), ("citas", 100, True), ("ventas", 0, False)])
        self.assertEqual(filas[2]["nombre"], "venta")          # meta 1 → singular

    def test_meta_cero_no_se_muestra_y_el_exceso_no_pasa_de_100(self):
        filas = servicios.medir_metas({"llamadas": 30}, {"llamadas": 20, "citas": 0, "ventas": 0})
        self.assertEqual([(f["clave"], f["pct"]) for f in filas], [("llamadas", 100)])


class EmbudoTests(SimpleTestCase):
    """SCRUM-99 · Embudo por campaña y costos."""

    def fila(self, **kw):
        base = {"id": 1, "pais": "España", "nombre_campana": None, "titulo": "Visa España", "clave": "AD1",
                "inversion": None, "inversion_moneda": "USD", "leads": 10, "contactados": 6, "citas": 3, "ventas": 1,
                "leads_total": 20, "ventas_total": 2}
        return base | kw

    def test_porcentajes_y_costos_con_la_inversion_total(self):
        c = servicios.armar_embudo([self.fila(inversion=Decimal("100"))])[0]
        a = c["anuncios"][0]
        self.assertEqual((a["pct_contacto"], a["pct_cita"], a["pct_venta"]), (60, 30, 10))
        self.assertEqual((a["costo_lead"], a["costo_venta"]), (Decimal("5"), Decimal("50")))

    def test_sin_inversion_no_hay_costos(self):
        a = servicios.armar_embudo([self.fila()])[0]["anuncios"][0]
        self.assertIsNone(a["costo_lead"])

    def test_agrupa_por_pais_y_sin_pais_al_final(self):
        campanas = servicios.armar_embudo([self.fila(id=1, pais=None, leads=50), self.fila(id=2), self.fila(id=3)])
        self.assertEqual([(c["pais"], c["leads"]) for c in campanas], [("España", 20), ("Sin país", 50)])


class CsvTests(SimpleTestCase):
    """SCRUM-93 · Un texto del cliente no se ejecuta como fórmula en Excel."""

    def test_celdas_peligrosas(self):
        self.assertEqual(_celda("=HYPERLINK(\"x\")"), "'=HYPERLINK(\"x\")")
        self.assertEqual(_celda("+593991234567"), "'+593991234567")
        self.assertEqual(_celda("Ana"), "Ana")
        self.assertEqual(_celda(None), "")
        self.assertEqual(_celda(5), 5)


class ConfiguracionNuevaTests(SimpleTestCase):
    datos = {"hora_inicio": "09:00", "hora_fin": "18:00", "dias": ["1", "2", "3", "4", "5"],
             "max_intentos_por_asesor": 3, "minutos_primera_llamada": 30, "minutos_entre_reintentos": 30,
             "minutos_alerta_supervisor": 30, "texto_bienvenida": "¡Hola!", "texto_fuera_horario": "Fuera",
             "texto_privacidad": "", "max_intentos_por_lead": 9, "aviso_texto": "Hola {nombre}",
             "aviso_plantilla": "recordatorio_llamada", "aviso_idioma": "es_EC", "aviso_horas": 12,
             "meta_llamadas": 25, "meta_citas": 4, "meta_ventas": 0, "guion_0": "Saludar", "guion_1": "  "}

    def test_cambios_nuevos(self):
        f = ConfiguracionForm(self.datos)
        self.assertTrue(f.is_valid(), f.errors)
        c = f.cambios()
        self.assertEqual(c["max_intentos_por_lead"], 9)
        self.assertEqual(c["aviso_no_contesta"], {"activo": False, "texto": "Hola {nombre}", "plantilla": "recordatorio_llamada",
                                                  "idioma": "es_EC", "horas_entre": 12})
        self.assertEqual(c["metas_diarias"], {"llamadas": 25, "citas": 4, "ventas": 0})
        self.assertEqual(c["guiones_llamada"], {"General": "Saludar"})       # vacíos no se guardan

    def test_plantilla_e_idioma_invalidos(self):
        f = ConfiguracionForm(self.datos | {"aviso_plantilla": "Mi Plantilla", "aviso_idioma": "español",
                                            "max_intentos_por_lead": 50})
        self.assertFalse(f.is_valid())
        self.assertEqual(set(f.errors), {"aviso_plantilla", "aviso_idioma", "max_intentos_por_lead"})

    def test_carga_desde_la_base(self):
        inicial = ConfiguracionForm.desde_configuracion({
            "aviso_no_contesta": {"activo": False, "texto": "x", "plantilla": "", "idioma": "es", "horas_entre": 6},
            "metas_diarias": {"llamadas": 30, "citas": 5, "ventas": 2},
            "guiones_llamada": {"turismo": "Fechas"}})
        self.assertEqual((inicial["aviso_activo"], inicial["aviso_horas"], inicial["meta_llamadas"]), (False, 6, 30))
        self.assertEqual(inicial["max_intentos_por_lead"], 9)                  # por defecto
        indice_turismo = ConfiguracionForm.TIPOS_GUION.index("Turismo")
        self.assertEqual(inicial[f"guion_{indice_turismo}"], "Fechas")


class SemaforoHoraTests(SimpleTestCase):
    """SCRUM-102 · verde 9-19, ámbar 8-9 y 19-21, rojo el resto."""

    def test_tonos(self):
        casos = {dt.time(8, 59): "ambar", dt.time(9, 0): "verde", dt.time(18, 59): "verde", dt.time(19, 0): "ambar",
                 dt.time(20, 59): "ambar", dt.time(21, 0): "rojo", dt.time(7, 59): "rojo", dt.time(0, 30): "rojo"}
        for hora, tono in casos.items():
            self.assertEqual(zonas.tono_hora(hora), tono, hora)


class EnVivoOrdenTests(SimpleTestCase):
    """SCRUM-107 · Primero lo que necesita atención."""

    def test_orden_por_urgencia(self):
        from leads.views import orden_urgencia
        a = lambda nombre, **kw: {"nombre": nombre, "estado": "disponible", "sin_gestionar": 0, "por_llamar": 0,  # noqa: E731
                                  "inactivo": False} | kw
        asesores = [a("Ana", estado="pausa"), a("Beto", por_llamar=2), a("Caro", sin_gestionar=1),
                    a("Dani", inactivo=True), a("Eva")]
        self.assertEqual([x["nombre"] for x in sorted(asesores, key=orden_urgencia)],
                         ["Caro", "Beto", "Dani", "Eva", "Ana"])


class EmbudoDestacadosTests(SimpleTestCase):
    """SCRUM-108 · Escala del gráfico y mejor / peor costo por venta."""

    def fila(self, id, pais, leads, inversion, ventas_total):
        return {"id": id, "pais": pais, "nombre_campana": None, "titulo": f"A{id}", "clave": f"A{id}", "inversion": inversion,
                "inversion_moneda": "USD", "leads": leads, "contactados": 0, "citas": 0, "ventas": 0,
                "leads_total": leads, "ventas_total": ventas_total}

    def test_escala_y_destacados(self):
        campanas = servicios.armar_embudo([self.fila(1, "España", 40, Decimal("100"), 4),
                                           self.fila(2, "Canadá", 20, Decimal("90"), 1),
                                           self.fila(3, "Canadá", 10, None, 0)])
        espana = next(c for c in campanas if c["pais"] == "España")
        canada = next(c for c in campanas if c["pais"] == "Canadá")
        self.assertEqual((espana["ancho"]["leads"], canada["ancho"]["leads"]), (100, 75))
        destacados = {a["id"]: a.get("destacado") for c in campanas for a in c["anuncios"]}
        self.assertEqual(destacados, {1: "mejor", 2: "peor", 3: None})

    def test_un_solo_anuncio_con_costo_no_se_destaca(self):
        campanas = servicios.armar_embudo([self.fila(1, "España", 40, Decimal("100"), 4)])
        self.assertNotIn("destacado", campanas[0]["anuncios"][0])


class AvanceTotalTests(SimpleTestCase):
    """SCRUM-106 · Mini barra del menú."""

    def test_promedio_y_cumplidas(self):
        metas = servicios.medir_metas({"llamadas": 10, "citas": 3}, {"llamadas": 20, "citas": 3, "ventas": 0})
        self.assertEqual(servicios.avance_total(metas)["pct"], 75)
        self.assertFalse(servicios.avance_total(metas)["cumplidas"])
        todas = servicios.medir_metas({"llamadas": 20}, {"llamadas": 20, "citas": 0, "ventas": 0})
        self.assertTrue(servicios.avance_total(todas)["cumplidas"])
        self.assertIsNone(servicios.avance_total([]))


class PestanasConfiguracionTests(SimpleTestCase):
    """SCRUM-111 · Todos los campos del formulario están en alguna pestaña."""

    def test_cada_campo_tiene_pestana(self):
        en_pestanas = {c for campos in ConfiguracionForm.PESTANAS.values() for c in campos}
        self.assertEqual(set(ConfiguracionForm().fields), en_pestanas)
