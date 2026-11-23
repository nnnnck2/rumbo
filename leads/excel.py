"""SCRUM-51 · Exportar a Excel (.xlsx) con la misma interfaz que csv.writer (writerow), para reutilizar
las exportaciones de leads y de métricas en los dos formatos."""
import datetime as dt
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class HojaExcel:
    """writerow() como csv.writer. Fechas con zona → hora local de Ecuador (Excel no guarda zonas).
    Los textos que empiezan con = + - @ se guardan como texto, nunca como fórmula."""

    def __init__(self, titulo="Rumbo", encabezado_en=1):
        self.libro = Workbook()
        self.hoja = self.libro.active
        self.hoja.title = titulo[:31]
        self.encabezado_en = encabezado_en
        self.anchos = {}

    def writerow(self, fila):
        valores = [self._valor(v) for v in fila]
        self.hoja.append(valores)
        n = self.hoja.max_row
        for i, v in enumerate(valores, start=1):
            celda = self.hoja.cell(row=n, column=i)
            if isinstance(v, str):
                celda.data_type = "s"                   # nunca fórmula (inyección en Excel)
            elif isinstance(v, dt.datetime):
                celda.number_format = "dd/mm/yyyy hh:mm"
            self.anchos[i] = min(max(self.anchos.get(i, 8), len(str(v if v is not None else "")) + 2), 60)
        if n == self.encabezado_en:
            for celda in self.hoja[n]:
                celda.font = Font(bold=True)

    @staticmethod
    def _valor(v):
        if isinstance(v, dt.datetime) and v.tzinfo is not None:
            return timezone.localtime(v).replace(tzinfo=None)
        if isinstance(v, str) and v.startswith("'") and v[1:2] in ("=", "+", "-", "@"):
            return v[1:]                                 # la marca anti-fórmula del CSV no hace falta aquí
        return v

    def respuesta(self, nombre):
        for i, ancho in self.anchos.items():
            self.hoja.column_dimensions[get_column_letter(i)].width = ancho
        if self.encabezado_en:
            self.hoja.freeze_panes = self.hoja.cell(row=self.encabezado_en + 1, column=1)
        salida = BytesIO()
        self.libro.save(salida)
        respuesta = HttpResponse(salida.getvalue(), content_type=TIPO_XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        return respuesta
