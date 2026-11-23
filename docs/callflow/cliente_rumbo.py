"""Cliente de referencia para CALLFLOW (SCRUM-57): trae de Rumbo las ventas de visas y calcula comisiones.

Solo usa la biblioteca estándar, así se puede copiar tal cual en CALLFLOW (p. ej. en un comando de gestión
que corra cada hora). CALLFLOW es quien llama a Rumbo; CALLFLOW nunca recibe conexiones.

    RUMBO_API_URL=https://visas.empresa.com  RUMBO_API_TOKEN=rbcf_…  python cliente_rumbo.py 2026-11
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from decimal import Decimal


class ClienteRumbo:
    def __init__(self, url=None, token=None, timeout=20):
        self.url = (url or os.environ["RUMBO_API_URL"]).rstrip("/")
        self.token = token or os.environ["RUMBO_API_TOKEN"]
        self.timeout = timeout

    def _get(self, ruta, **params):
        consulta = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        peticion = urllib.request.Request(f"{self.url}/api/callflow/v1/{ruta}/" + (f"?{consulta}" if consulta else ""),
                                          headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        with urllib.request.urlopen(peticion, timeout=self.timeout) as r:
            return json.load(r)

    def asesores(self):
        return self._get("asesores")["asesores"]

    def ventas(self, desde=None, despues_id=None, limite=500):
        """Todas las ventas cambiadas desde el punto dado. Devuelve (ventas, siguiente) — guarde `siguiente`
        para la próxima sincronización incremental."""
        todas, siguiente = [], {"desde": desde, "despues_id": despues_id}
        while True:
            pagina = self._get("ventas", limite=limite, **siguiente)
            todas.extend(pagina["ventas"])
            siguiente = pagina["siguiente"]
            if not pagina["hay_mas"]:
                return todas, siguiente


def comisiones_del_mes(ventas, mes, porcentaje=Decimal("5")):
    """{codigo_callflow: (n_ventas, total, comision)} de las ventas cerradas en `mes` (AAAA-MM), sin las anuladas.
    La regla real es la de CALLFLOW; aquí un porcentaje fijo para la prueba."""
    por_asesor = defaultdict(lambda: [0, Decimal("0")])
    for v in ventas:
        if v["anulada_en"] or not v["cerrada_en"].startswith(mes):
            continue
        fila = por_asesor[v["asesor_codigo_callflow"] or f"sin-codigo-{v['asesor_id']}"]
        fila[0] += 1
        fila[1] += Decimal(v["valor"])
    return {k: (n, total, (total * porcentaje / 100).quantize(Decimal("0.01"))) for k, (n, total) in por_asesor.items()}


if __name__ == "__main__":
    mes = sys.argv[1] if len(sys.argv) > 1 else None
    cliente = ClienteRumbo()
    ventas, siguiente = cliente.ventas()
    print(f"{len(cliente.asesores())} asesores · {len(ventas)} ventas · próxima sincronización desde {siguiente}")
    if mes:
        for codigo, (n, total, comision) in sorted(comisiones_del_mes(ventas, mes).items()):
            print(f"  {codigo}: {n} venta(s) · total {total} · comisión {comision}")
