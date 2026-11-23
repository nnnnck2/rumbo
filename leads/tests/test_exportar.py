"""SCRUM-51 · Exportación a Excel sin base."""
import datetime as dt
from io import BytesIO

from django.test import RequestFactory, SimpleTestCase
from openpyxl import load_workbook

from leads import views
from leads.excel import HojaExcel


class HojaExcelTests(SimpleTestCase):
    def _leer(self, filas, **kw):
        h = HojaExcel("Prueba", **kw)
        for f in filas:
            h.writerow(f)
        r = h.respuesta("x.xlsx")
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="x.xlsx"')
        return load_workbook(BytesIO(r.content)).active

    def test_formulas_quedan_como_texto(self):
        hoja = self._leer([["Nombre"], ["=HYPERLINK(\"http://malo\")"], ["'=1+1"]])
        self.assertEqual(hoja["A2"].data_type, "s")
        self.assertEqual(hoja["A3"].value, "=1+1")
        self.assertEqual(hoja["A3"].data_type, "s")

    def test_fechas_en_hora_de_ecuador(self):
        utc = dt.datetime(2026, 11, 23, 17, 30, tzinfo=dt.timezone.utc)
        hoja = self._leer([["Llegó"], [utc]])
        self.assertEqual(hoja["A2"].value, dt.datetime(2026, 11, 23, 12, 30))       # UTC-5
        self.assertTrue(hoja["A1"].font.bold)

    def test_numeros_siguen_siendo_numeros(self):
        self.assertEqual(self._leer([["N"], [3]])["A2"].value, 3)


class FormatoTests(SimpleTestCase):
    def test_xlsx_solo_si_se_pide(self):
        rf = RequestFactory()
        self.assertTrue(views._es_excel(rf.get("/x/?formato=xlsx")))
        self.assertFalse(views._es_excel(rf.get("/x/")))

    def test_filtros_de_fecha_y_campana_se_conservan_entre_pestanas(self):
        for f in ("desde", "hasta", "campana"):
            self.assertIn(f, views.FILTROS_LISTA)
        self.assertEqual(views._fecha_filtro("2026-11-23"), dt.date(2026, 11, 23))
        self.assertIsNone(views._fecha_filtro("23/11/2026"))
