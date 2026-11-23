"""SCRUM-117, 119, 123, 125, 126, 128, 129, 130 · Prioridad, documentos, línea de tiempo, agenda, mapa de
calor, alertas de calidad, comisiones y búsqueda. Todo con la conexión del request (RLS decide qué ve cada uno).
"""
import datetime as dt
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import Case, Count, Exists, ExpressionWrapper, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, Least
from django.utils import timezone

from .models import EstadoAsignacion, Lead, LeadOrigen, MensajeWhatsapp

# ─────────────────────────────── SCRUM-119 · Prioridad del lead ───────────────────────────────

PESOS = {"anuncio": 20, "bot": 15, "escribio": 15, "cita": 25, "reciente": 10, "por_intento": 5}
PRIORIDAD_ALTA = 35
MAX_INTENTOS_RESTA = 6


def _si(condicion, peso):
    return Case(When(condicion, then=Value(peso)), default=Value(0), output_field=IntegerField())


def con_prioridad(qs, ahora=None):
    """Agrega `prioridad` (número), `p_anuncio` y `n_entrantes` a cada lead del queryset."""
    ahora = ahora or timezone.now()
    entrantes = (MensajeWhatsapp.objects.filter(lead=OuterRef("pk"), direccion="entrante").order_by()
                 .values("lead").annotate(n=Count("id")).values("n"))
    qs = qs.annotate(n_entrantes=Coalesce(Subquery(entrantes), 0),
                     p_anuncio=Exists(LeadOrigen.objects.filter(lead=OuterRef("pk"))))
    puntaje = (_si(Q(p_anuncio=True), PESOS["anuncio"])
               + _si(Q(datos__respondio_bot=True), PESOS["bot"])
               + _si(Q(n_entrantes__gt=1), PESOS["escribio"])
               + _si(Q(etapa_id="cita_agendada"), PESOS["cita"])
               + _si(Q(primer_contacto_en__gte=ahora - dt.timedelta(hours=2)), PESOS["reciente"])
               - Least(F("intentos_totales"), Value(MAX_INTENTOS_RESTA)) * Value(PESOS["por_intento"]))
    return qs.annotate(prioridad=ExpressionWrapper(puntaje, output_field=IntegerField()))


# ─────────────────────────────── SCRUM-28 · Lista de llamadas (RF-20) ───────────────────────────────

TIPO_NUEVO, TIPO_AGENDADA, TIPO_REINTENTO = 0, 1, 2
TIPOS_LLAMADA = {TIPO_NUEVO: "Nuevo", TIPO_AGENDADA: "Agendada", TIPO_REINTENTO: "Reintento"}


def con_tipo_llamada(qs):
    """Agrega `tipo_llamada` y `espera_desde` a leads asignados:
      · Nuevo: el asesor aún no lo llamó ni lo agendó (el reparto deja proxima_accion_en = asignado_en).
      · Agendada: tiene una hora acordada (agendar sin intento, o último intento con "volver a llamar").
      · Reintento: le toca de nuevo tras un intento sin contacto.
    `espera_desde` es desde cuándo está esperando la llamada (al recibirlo o a la hora que tocaba)."""
    from .models import IntentoLlamada

    ultimo_agendado = (IntentoLlamada.objects.filter(lead=OuterRef("pk"), asesor=OuterRef("asesor_id"))
                       .order_by("-numero").values("agendado_para")[:1])
    qs = qs.annotate(ultimo_agendado=Subquery(ultimo_agendado))
    es_nuevo = Q(intentos_asesor_actual=0) & Q(proxima_accion_en__lte=F("asignado_en"))
    tipo = Case(
        When(es_nuevo, then=Value(TIPO_NUEVO)),
        When(Q(intentos_asesor_actual=0) | Q(ultimo_agendado__isnull=False), then=Value(TIPO_AGENDADA)),
        default=Value(TIPO_REINTENTO), output_field=IntegerField())
    espera = Case(When(es_nuevo, then=F("asignado_en")),
                  default=F("proxima_accion_en"))
    return qs.annotate(tipo_llamada=tipo, espera_desde=espera)


def orden_lista_llamadas(qs):
    """RF-20: primero los nuevos; después agendadas y reintentos vencidos. Dentro de cada grupo, los más
    calientes (SCRUM-119) y, a igual prioridad, el que más espera."""
    return con_tipo_llamada(con_prioridad(qs)).order_by("tipo_llamada", "-prioridad", "espera_desde", "id")


def texto_espera(desde, ahora=None):
    """"3 min", "1 h 05 min", "2 d": cuánto lleva esperando el cliente."""
    if not desde:
        return ""
    minutos = max(0, int(((ahora or timezone.now()) - desde).total_seconds() // 60))
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 24 * 60:
        return f"{minutos // 60} h {minutos % 60:02d} min"
    return f"{minutos // (24 * 60)} d"


def razones_prioridad(lead, ahora=None):
    """Texto corto de por qué el lead tiene esa prioridad (para el chip)."""
    ahora = ahora or timezone.now()
    razones = []
    if getattr(lead, "p_anuncio", False):
        razones.append("llegó por un anuncio")
    if (lead.datos or {}).get("respondio_bot"):
        razones.append("respondió las preguntas")
    if getattr(lead, "n_entrantes", 0) > 1:
        razones.append("volvió a escribir")
    if lead.etapa_id == "cita_agendada":
        razones.append("tiene cita")
    if lead.primer_contacto_en and lead.primer_contacto_en >= ahora - dt.timedelta(hours=2):
        razones.append("llegó hace poco")
    if lead.intentos_totales:
        razones.append(f"{lead.intentos_totales} intento{'s' if lead.intentos_totales != 1 else ''} sin cerrar")
    return ", ".join(razones)


# ─────────────────────────────── SCRUM-117 · Documentos ───────────────────────────────

ESTADOS_DOC = ["falta", "pedido", "recibido"]


def documentos_de(lead, config):
    """[{"nombre", "estado"}] según el tipo de visa del lead (o el general) y lo marcado en lead.datos."""
    por_visa = {k.strip().lower(): v for k, v in (config or {}).items()}
    texto = por_visa.get((lead.tipo_visa or "").strip().lower()) or por_visa.get("general") or ""
    nombres = [l.strip().lstrip("-•*·").strip() for l in texto.splitlines()]
    marcados = (lead.datos or {}).get("documentos") or {}
    return [{"nombre": n, "estado": marcados.get(n, "falta")} for n in nombres if n]


def siguiente_estado(estado):
    return ESTADOS_DOC[(ESTADOS_DOC.index(estado) + 1) % len(ESTADOS_DOC)] if estado in ESTADOS_DOC else "pedido"


def marcar_documento(lead_id, nombre, estado):
    """Guarda el estado de un documento en lead.datos.documentos. RLS: solo el dueño o supervisión."""
    if estado not in ESTADOS_DOC or not (1 <= len(nombre) <= 120):
        return False
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """UPDATE rumbo.lead
               SET datos = datos || jsonb_build_object('documentos',
                                coalesce(datos -> 'documentos', '{}'::jsonb) || jsonb_build_object(%s::text, %s::text))
               WHERE id = %s""", [nombre, estado, lead_id])
        return cursor.rowcount == 1


# ─────────────────────────────── SCRUM-126 · Línea de tiempo ───────────────────────────────

def linea_de_tiempo(lead, intentos, historial, asignaciones, notas, mensajes):
    """Todo lo que pasó con el cliente, del más reciente al más antiguo."""
    eventos = []
    for i in intentos:
        eventos.append({"en": i.creado_en, "tipo": "llamada", "icono": "telephone",
                        "titulo": f"Llamada #{i.numero} · {i.resultado.nombre}",
                        "detalle": " · ".join(filter(None, [i.asesor.usuario.nombre, i.nota]))})
    for h in historial:
        eventos.append({"en": h.creado_en, "tipo": "etapa", "icono": "signpost-split",
                        "titulo": f"{h.desde.nombre + ' → ' if h.desde else ''}{h.hacia.nombre}",
                        "detalle": h.usuario.nombre if h.usuario else ""})
    for a in asignaciones:
        eventos.append({"en": a.creado_en, "tipo": "asignacion", "icono": "person-arrow-right",
                        "titulo": f"Asignado a {a.asesor.usuario.nombre}", "detalle": a.get_motivo_display()})
    for n in notas:
        eventos.append({"en": n.creado_en, "tipo": "nota", "icono": "sticky",
                        "titulo": "Nota", "detalle": f"{n.autor_usuario.nombre}: {n.texto}"})
    for m in mensajes:
        quien = "Cliente" if m.direccion == "entrante" else ("Automático" if (m.payload or {}).get("automatica") else "Multivisa")
        eventos.append({"en": m.ocurrido_en, "tipo": "mensaje", "icono": "whatsapp",
                        "titulo": f"WhatsApp · {quien}", "detalle": (m.cuerpo or f"[{m.tipo}]")[:280]})
    return sorted(eventos, key=lambda e: e["en"], reverse=True)


# ─────────────────────────────── SCRUM-125 · Agenda ───────────────────────────────

def cita_de(lead):
    """datetime de la cita guardada en lead.datos.cita_en (o None)."""
    valor = (lead.datos or {}).get("cita_en")
    if not valor:
        return None
    try:
        return dt.datetime.fromisoformat(valor)
    except ValueError:
        return None


def agenda(lunes, asesor_id=None):
    """{fecha: [eventos]} de lunes a domingo: llamadas programadas y citas."""
    zona = timezone.get_current_timezone()
    inicio = dt.datetime.combine(lunes, dt.time.min, zona)
    fin = inicio + dt.timedelta(days=7)
    base = Lead.objects.select_related("asesor__usuario", "etapa")
    if asesor_id:
        base = base.filter(asesor_id=asesor_id)
    dias = {lunes + dt.timedelta(days=i): [] for i in range(7)}
    for l in base.filter(estado_asignacion=EstadoAsignacion.ASIGNADO, proxima_accion_en__gte=inicio,
                         proxima_accion_en__lt=fin):
        cuando = timezone.localtime(l.proxima_accion_en)
        dias[cuando.date()].append({"en": cuando, "tipo": "llamada", "lead": l})
    for l in base.filter(etapa_id="cita_agendada", datos__has_key="cita_en"):
        cuando = cita_de(l)
        if cuando and inicio <= cuando < fin:
            cuando = timezone.localtime(cuando)
            dias[cuando.date()].append({"en": cuando, "tipo": "cita", "lead": l})
    for eventos in dias.values():
        eventos.sort(key=lambda e: e["en"])
    return dias


# ─────────────────────────────── SCRUM-128 · Mapa de calor ───────────────────────────────

MIN_LLAMADAS_HORA = 5   # con menos, el porcentaje de esa hora no es confiable


def resumen_mapa(filas):
    """La mejor y la peor hora (solo las que tienen al menos MIN_LLAMADAS_HORA llamadas), para decirlo en palabras."""
    confiables = [c for f in filas for c in f["celdas"] if c["llamadas"] >= MIN_LLAMADAS_HORA]
    if not confiables:
        return None
    mejor = max(confiables, key=lambda c: (c["pct"], c["llamadas"]))
    peor = min(confiables, key=lambda c: (c["pct"], -c["llamadas"]))
    return {"mejor": mejor, "peor": peor if peor is not mejor and peor["pct"] < mejor["pct"] else None}


def mapa_de_calor(desde, hasta, contacto):
    """Tasa de contacto por día de la semana (1–7) y hora local. Devuelve (horas, filas)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT extract(isodow FROM i.creado_en AT TIME ZONE %(zona)s)::int AS dia,
                      extract(hour FROM i.creado_en AT TIME ZONE %(zona)s)::int AS hora,
                      count(*) AS llamadas,
                      count(*) FILTER (WHERE i.resultado_codigo = ANY(%(contacto)s)) AS contactos
               FROM rumbo.intento_llamada i
               WHERE i.creado_en >= %(desde)s AND i.creado_en < %(hasta)s
               GROUP BY 1, 2""",
            {"zona": timezone.get_current_timezone_name(), "desde": desde, "hasta": hasta, "contacto": list(contacto)})
        celdas = {(d, h): (n, c) for d, h, n, c in cursor.fetchall()}
    horas = sorted({h for _d, h in celdas}) or list(range(9, 18))
    horas = list(range(min(horas), max(horas) + 1))
    nombres = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    filas = []
    for d in range(1, 8):
        fila = []
        for h in horas:
            n, c = celdas.get((d, h), (0, 0))
            pct = round(100 * c / n) if n else None
            # Un solo color, más intenso cuanto más se logra hablar (4 tonos de 25 en 25).
            fila.append({"hora": h, "llamadas": n, "contactos": c, "pct": pct, "poco": 0 < n < MIN_LLAMADAS_HORA,
                         "nivel": None if pct is None else min(3, pct // 25), "dia": nombres[d - 1]})
        filas.append({"dia": nombres[d - 1][:3].capitalize(), "celdas": fila, "llamadas": sum(c["llamadas"] for c in fila)})
    return horas, filas


# ─────────────────────────────── SCRUM-129 · Alertas de calidad ───────────────────────────────

MIN_LLAMADAS = 10
UMBRAL = 0.6


def alertas_calidad(contacto, dias=7, ahora=None):
    """Asesores con tasa de contacto o de citas < 60 % de la del equipo (últimos `dias`, con 10+ llamadas)."""
    desde = (ahora or timezone.now()) - dt.timedelta(days=dias)
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT a.id, u.nombre,
                      (SELECT count(*) FROM rumbo.intento_llamada i WHERE i.asesor_id = a.id AND i.creado_en >= %(desde)s),
                      (SELECT count(*) FROM rumbo.intento_llamada i WHERE i.asesor_id = a.id AND i.creado_en >= %(desde)s
                                                                    AND i.resultado_codigo = ANY(%(contacto)s)),
                      (SELECT count(*) FROM rumbo.lead_etapa_historial h WHERE h.usuario_id = u.id
                                                                         AND h.hacia = 'cita_agendada' AND h.creado_en >= %(desde)s)
               FROM rumbo.asesor a JOIN rumbo.usuario u ON u.id = a.usuario_id WHERE u.activo""",
            {"desde": desde, "contacto": list(contacto)})
        filas = cursor.fetchall()
    return evaluar_calidad([{"id": i, "nombre": n, "llamadas": ll, "contactos": c, "citas": ci} for i, n, ll, c, ci in filas])


def evaluar_calidad(asesores):
    """Compara cada asesor con el equipo. Puro (se prueba sin base)."""
    total_llamadas = sum(a["llamadas"] for a in asesores)
    total_contactos = sum(a["contactos"] for a in asesores)
    total_citas = sum(a["citas"] for a in asesores)
    if not total_llamadas:
        return []
    equipo_contacto = total_contactos / total_llamadas
    equipo_cita = total_citas / total_contactos if total_contactos else 0
    alertas = []
    for a in asesores:
        if a["llamadas"] < MIN_LLAMADAS:
            continue
        contacto = a["contactos"] / a["llamadas"]
        cita = a["citas"] / a["contactos"] if a["contactos"] else 0
        motivos = []
        if equipo_contacto and contacto < UMBRAL * equipo_contacto:
            motivos.append(f"contacto {round(100 * contacto)} % (equipo {round(100 * equipo_contacto)} %)")
        if equipo_cita and cita < UMBRAL * equipo_cita:
            motivos.append(f"citas {round(100 * cita)} % de los contactados (equipo {round(100 * equipo_cita)} %)")
        if motivos:
            alertas.append({**a, "motivos": motivos})
    return alertas


# ─────────────────────────────── SCRUM-130 · Comisiones (estimado) ───────────────────────────────

def comision_del_mes(asesor_id, regla, desde):
    """{"ventas", "total", "moneda", "estimada", "regla"} del asesor desde `desde`. Solo ventas no anuladas."""
    from .models import Venta

    ventas = list(Venta.objects.filter(asesor_id=asesor_id, anulada_en__isnull=True, cerrada_en__gte=desde)
                  .values_list("valor", "moneda"))
    return calcular_comision(ventas, regla)


def calcular_comision(ventas, regla):
    regla = regla or {"tipo": "porcentaje", "valor": 0}
    total = sum((v for v, _m in ventas), Decimal("0"))
    monedas = {m for _v, m in ventas} or {"USD"}
    valor = Decimal(str(regla.get("valor") or 0))
    estimada = (total * valor / 100) if regla.get("tipo") == "porcentaje" else valor * len(ventas)
    texto_regla = f"{valor.normalize()} % de lo vendido" if regla.get("tipo") == "porcentaje" else f"{valor.normalize()} por venta"
    return {"ventas": len(ventas), "total": total, "moneda": "/".join(sorted(monedas)), "estimada": estimada.quantize(Decimal("0.01")),
            "regla": texto_regla, "varias_monedas": len(monedas) > 1}


# ─────────────────────────────── SCRUM-123 · Búsqueda global ───────────────────────────────

def buscar(q, limite=8):
    q = (q or "").strip()
    if len(q) < 2:
        return []
    digitos = "".join(c for c in q if c.isdigit())
    filtro = Q(nombre_perfil__icontains=q)
    if len(digitos) >= 3:
        filtro |= Q(telefono__contains=digitos)
    return list(Lead.objects.filter(filtro, anonimizado_en__isnull=True).select_related("etapa", "asesor__usuario")
                .order_by("-ultimo_mensaje_en", "-primer_contacto_en")[:limite])

