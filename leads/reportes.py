"""Tablas de Métricas en CSV (para descargar y para el reporte semanal por correo, SCRUM-93 y SCRUM-121)."""
import csv
import datetime as dt
import io

from django.utils import timezone

from . import servicios


def celda(valor):
    """Evita que Excel interprete un texto del cliente como fórmula (inyección CSV)."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return "" if valor is None else valor


def rango_dias(desde, hasta):
    zona = timezone.get_current_timezone()
    return (dt.datetime.combine(desde, dt.time.min, zona),
            dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time.min, zona))


def escribir_metricas(w, desde, hasta):
    """Escribe las tablas en el writer `w`. Devuelve (datos de métricas, cantidad de filas)."""
    inicio, fin = rango_dias(desde, hasta)
    datos = servicios.metricas_piloto(inicio, fin)
    por_campana = servicios.metricas_por_campana(inicio, fin)
    embudo = servicios.embudo_por_anuncio(inicio, fin)
    w.writerow([f"Métricas de Rumbo · leads llegados del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"])
    w.writerow([])
    w.writerow(["Por asesor", "Leads", "Llamados", "Contactados", "Contacto %", "Ventas",
                "Asignado → primera llamada (min, mediana)"])
    for f in [*datos["por_asesor"], {**datos["total"], "grupo": "TOTAL"}]:
        mediana = f["min_asignado_a_llamada_mediana"]
        w.writerow([celda(f["grupo"]), f["leads"], f["llamados"], f["contactados"], f["tasa_contacto"], f["ventas"],
                    round(mediana) if mediana is not None else ""])
    w.writerow([])
    w.writerow(["Por campaña (país)", "Leads", "Llamados", "Contacto %", "Ventas", "Conversión %"])
    for f in por_campana:
        w.writerow([celda(f["grupo"]), f["leads"], f["llamados"], f["tasa_contacto"], f["ventas"], f["tasa_venta"]])
    w.writerow([])
    w.writerow(["Campaña", "Anuncio", "Leads", "Contactados", "Citas", "Ventas", "Inversión total",
                "Costo por lead", "Costo por venta"])
    for c in embudo:
        for a in c["anuncios"]:
            w.writerow([celda(c["pais"]), celda(a["nombre"]), a["leads"], a["contactados"], a["citas"], a["ventas"],
                        a["inversion"] if a["inversion"] is not None else "",
                        round(a["costo_lead"], 2) if a["costo_lead"] is not None else "",
                        round(a["costo_venta"], 2) if a["costo_venta"] is not None else ""])
    return datos, len(datos["por_asesor"]) + len(por_campana) + sum(len(c["anuncios"]) for c in embudo)


def csv_metricas(desde, hasta):
    """(texto CSV con BOM y ';', datos) para adjuntar a un correo."""
    salida = io.StringIO()
    salida.write("﻿")
    datos, _ = escribir_metricas(csv.writer(salida, delimiter=";"), desde, hasta)
    return salida.getvalue(), datos
