"""Acciones de negocio sobre los leads (SCRUM-30, 31, 32, 33).

Toda escritura pasa por las funciones SQL de db/migraciones/006 (o por la tabla de
configuración, que valida un trigger). La base decide permisos (rol del contexto RLS),
reglas (transiciones de etapa, venta obligatoria…) y concurrencia (bloqueo optimista).
Aquí solo se traducen sus errores a mensajes para el usuario.

Cada llamada corre en su propio savepoint: el request ya está dentro de una transacción
(core.middleware), y un error de la base la dejaría inutilizable para el resto de la página.
"""
import json
import logging
from dataclasses import dataclass

from django.db import DatabaseError, connection, transaction
from django.utils import timezone

logger = logging.getLogger("rumbo.leads")


class ErrorNegocio(Exception):
    """Error que se muestra al usuario. `tipo`: conflicto | validacion | permiso | no_existe."""

    def __init__(self, mensaje, tipo="validacion"):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.tipo = tipo


_TIPOS = {
    "RB409": "conflicto",          # bloqueo optimista: otro usuario cambió el lead
    "RB422": "validacion",         # regla de negocio
    "23514": "validacion",         # CHECK (p. ej. descartar sin motivo)
    "23503": "validacion",         # FK (etapa o resultado inexistente)
    "RB403": "permiso",
    "42501": "permiso",            # insufficient_privilege / RLS
    "P0002": "no_existe",          # no_data_found
}

_MENSAJES = {
    "conflicto": "Otro usuario modificó este lead mientras lo tenía abierto. Se recargaron los datos: revise y repita la acción.",
    "permiso": "No tiene permiso para esta acción.",
}


def _sqlstate(exc):
    causa = exc.__cause__ or exc
    return getattr(causa, "sqlstate", None)


def _mensaje_base(exc):
    causa = exc.__cause__ or exc
    diag = getattr(causa, "diag", None)
    texto = getattr(diag, "message_primary", None) or str(causa).splitlines()[0]
    return texto.removeprefix("Configuración inválida ")


def traducir(exc):
    estado = _sqlstate(exc)
    tipo = _TIPOS.get(estado)
    if tipo is None:
        raise exc                  # error inesperado: que lo vea el log, no el usuario
    if tipo == "validacion" and estado == "23514" and "descarte" in str(exc):
        return ErrorNegocio("Para descartar un lead hay que indicar el motivo.", tipo)
    return ErrorNegocio(_MENSAJES.get(tipo) or _mensaje_base(exc), tipo)


def _ejecutar(sql, params, uno=True):
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, params)
            if uno:
                fila = cursor.fetchone()
                return fila[0] if fila else None
            return None
    except DatabaseError as exc:
        raise traducir(exc) from exc


# ─────────────────────────────── Contexto ───────────────────────────────

@dataclass(frozen=True)
class Contexto:
    usuario_id: int | None
    rol: str | None
    asesor_id: int | None

    @property
    def es_supervisor(self):
        return self.rol in ("supervisor", "admin")

    @property
    def es_admin(self):
        return self.rol == "admin"


def contexto_actual():
    """Rol y asesor del usuario del request, tal como los ve la base (rumbo.usuario)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT rumbo.ctx_usuario_id(), rumbo.ctx_rol()::text, rumbo.ctx_asesor_id()")
        return Contexto(*cursor.fetchone())


# ─────────────────────────────── RF-22 · Intentos de llamada ───────────────────────────────

def registrar_intento(lead_id, version, resultado, nota=None, agendar_para=None, venta=None):
    """Registra el intento y ejecuta la acción del resultado (agenda, etapa, venta, reparto).
    Devuelve la nueva versión del lead."""
    return _ejecutar(
        "SELECT rumbo.registrar_intento(%s, %s, %s, %s, %s, %s::jsonb)",
        [lead_id, version, resultado, nota or None, agendar_para,
         json.dumps(venta, default=str) if venta else None],
    )


# ─────────────────────────────── RF-25 · Etapas ───────────────────────────────

def cambiar_etapa(lead_id, version, etapa, motivo_descarte=None):
    return _ejecutar("SELECT rumbo.cambiar_etapa(%s, %s, %s, %s)",
                     [lead_id, version, etapa, motivo_descarte or None])


def etapas_permitidas(etapa_actual):
    """Etapas a las que se puede pasar desde la actual (tabla rumbo.etapa_transicion)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT e.codigo, e.nombre FROM rumbo.etapa_transicion t
               JOIN rumbo.etapa e ON e.codigo = t.hacia
               WHERE t.desde = %s AND e.activo ORDER BY e.orden""",
            [etapa_actual],
        )
        return cursor.fetchall()


# ─────────────────────────────── RF-24 · Agendar llamada ───────────────────────────────

def agendar_llamada(lead_id, version, cuando):
    """Reprograma la próxima llamada sin registrar un intento. Devuelve la nueva versión."""
    return _ejecutar("SELECT rumbo.agendar_llamada(%s, %s, %s)", [lead_id, version, cuando])


# ─────────────────────────────── RF-33 · Leads sin llamar ───────────────────────────────

MOTIVOS_ALERTA = {
    "sin_primera_llamada": "Sin primera llamada",
    "reintento_vencido": "Reintento vencido",
    "agenda_vencida": "Llamada agendada vencida",
    "en_cola": "En cola, sin asesor en turno",
}


def leads_sin_llamar():
    """Leads con la llamada atrasada más del umbral configurado (solo dentro del turno).
    RLS: el supervisor ve todos; el asesor, los suyos."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT lead_id, telefono, nombre_perfil, asesor, motivo, desde, minutos "
                       "FROM rumbo.leads_sin_llamar()")
        columnas = [c.name for c in cursor.description]
        filas = [dict(zip(columnas, f)) for f in cursor.fetchall()]
    for f in filas:
        f["motivo_texto"] = MOTIVOS_ALERTA.get(f["motivo"], f["motivo"])
    return filas


# ─────────────────────────────── RF-26 · Datos del caso y notas ───────────────────────────────

# ─────────────── 015 · Plazo de gestión y "situación" de cada lead (semáforo) ───────────────

def plazos_gestion():
    """{lead_id: (vence_en, vuelta)} de los leads que su asesor aún no gestionó. RLS: el asesor ve los suyos."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT lead_id, vence_en, vuelta FROM rumbo.plazos_gestion()")
        return {lead_id: (vence, vuelta) for lead_id, vence, vuelta in cursor.fetchall()}


def en_horario():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rumbo.en_horario()")
        return cursor.fetchone()[0]


def _duracion(minutos):
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 24 * 60:
        return f"{minutos // 60} h {minutos % 60:02d} min" if minutos % 60 else f"{minutos // 60} h"
    dias = minutos // (24 * 60)
    return f"{dias} día{'s' if dias != 1 else ''}"


def situacion(lead, plazos, ahora, abierto=True, minutos_plazo=30):
    """Qué pasa con el lead ahora, para mostrarlo con color (verde, amarillo, rojo, azul, gris).

    Devuelve {"tono", "icono", "texto", "detalle", "pct"}; pct = parte del plazo que queda (barra).
    """
    if lead.estado_asignacion == "cerrado":
        return {"tono": "cerrado", "icono": "check2-circle", "texto": "Cerrado", "detalle": "", "pct": None}
    if lead.estado_asignacion == "en_cola":
        return {"tono": "cola", "icono": "hourglass-split", "texto": "En cola",
                "detalle": "Esperando a un asesor en turno", "pct": None}
    plazo = plazos.get(lead.pk)
    if plazo:                                   # todavía sin gestionar: corre el reloj de 30 min
        vence, _vuelta = plazo
        if not abierto:
            return {"tono": "pausa", "icono": "pause-circle", "texto": "Sin gestionar",
                    "detalle": "El reloj sigue al abrir el turno", "pct": None}
        quedan = max(0, int((vence - ahora).total_seconds() // 60))
        pct = max(0, min(100, round(100 * quedan / max(minutos_plazo, 1))))
        tono = "rojo" if quedan <= 5 else "amarillo" if quedan <= 15 else "verde"
        return {"tono": tono, "icono": "stopwatch", "texto": f"Quedan {quedan} min" if quedan else "Pasa ya a otro asesor",
                "detalle": "Si no se registra una llamada, pasa a otro asesor", "pct": pct, "minutos": quedan}
    if lead.proxima_accion_en and lead.proxima_accion_en <= ahora:
        atraso = int((ahora - lead.proxima_accion_en).total_seconds() // 60)
        return {"tono": "rojo" if atraso >= 30 else "amarillo", "icono": "telephone-forward",
                "texto": "Toca llamar" if atraso < 1 else f"Atrasada {_duracion(atraso)}",
                "detalle": "Reintento o llamada agendada", "pct": None}
    if lead.proxima_accion_en:
        cuando = timezone.localtime(lead.proxima_accion_en)
        hoy = cuando.date() == timezone.localtime(ahora).date()
        return {"tono": "azul", "icono": "calendar-event",
                "texto": f"Llamar {'hoy' if hoy else cuando.strftime('%d/%m')} {cuando.strftime('%H:%M')}",
                "detalle": "Llamada programada", "pct": None}
    return {"tono": "gris", "icono": "dash-circle", "texto": "Sin llamada pendiente", "detalle": "", "pct": None}


ORDEN_TONO = {"rojo": 0, "amarillo": 1, "verde": 2, "pausa": 3, "cola": 4, "azul": 5, "gris": 6, "cerrado": 7}


def con_situacion(leads):
    """Pone `lead.situacion` a cada lead (una sola consulta de plazos para todos)."""
    leads = list(leads)
    if not leads:
        return leads
    plazos, abierto, ahora = plazos_gestion(), en_horario(), timezone.now()
    minutos = leer_configuracion().get("minutos_primera_llamada", 30)
    for lead in leads:
        lead.situacion = situacion(lead, plazos, ahora, abierto, minutos)
    return leads


# ─────────────── 017 · Campañas por país ───────────────

def categorizar_anuncio(anuncio_id, pais, nombre_campana=None):
    """El admin asigna el país de la campaña. Devuelve cuántos leads tomaron ese país."""
    return _ejecutar("SELECT rumbo.categorizar_anuncio(%s, %s, %s)", [anuncio_id, pais, nombre_campana or None])


def actualizar_datos_lead(lead_id, version, tipo_visa, pais_interes):
    """Guarda tipo de visa y país en lead.datos (jsonb; la base genera las columnas tipo_visa y
    pais_interes para filtrar). Conserva el resto de datos. Bloqueo optimista por versión.
    Devuelve la nueva versión."""
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """UPDATE rumbo.lead
                   SET datos = (datos - 'tipo_visa' - 'pais_interes')
                               || jsonb_strip_nulls(jsonb_build_object('tipo_visa', %s::text, 'pais_interes', %s::text))
                   WHERE id = %s AND version = %s
                   RETURNING version""",
                [tipo_visa or None, pais_interes or None, lead_id, version],
            )
            fila = cursor.fetchone()
            if fila:
                return fila[0]
            # 0 filas: o cambió la versión, o RLS no le deja editar este lead
            cursor.execute("SELECT version FROM rumbo.lead WHERE id = %s", [lead_id])
            visible = cursor.fetchone()
    except DatabaseError as exc:
        raise traducir(exc) from exc
    if visible and visible[0] != version:
        raise ErrorNegocio(_MENSAJES["conflicto"], "conflicto")
    raise ErrorNegocio(_MENSAJES["permiso"], "permiso")


def agregar_nota(lead_id, texto, usuario_id):
    """Nota interna (solo inserción: la base no deja editarlas ni borrarlas)."""
    _ejecutar("INSERT INTO rumbo.nota_lead (lead_id, autor_usuario_id, texto) VALUES (%s, %s, %s) RETURNING id",
              [lead_id, usuario_id, texto.strip()])


# ─────────────────────────────── RF-16 · Reasignación manual ───────────────────────────────

def reasignar(lead_id, asesor_id):
    _ejecutar("SELECT rumbo.reasignar_manual(%s, %s)", [lead_id, asesor_id])


def reasignar_lote(lead_ids, asesor_id):
    """Reasigna varios leads. Cada uno es independiente: si uno falla (p. ej. está cerrado),
    los demás se reasignan igual. Devuelve (reasignados, [(lead_id, mensaje_error)])."""
    hechos, errores = [], []
    for lead_id in lead_ids:
        try:
            reasignar(lead_id, asesor_id)
            hechos.append(lead_id)
        except ErrorNegocio as e:
            errores.append((lead_id, e.mensaje))
    return hechos, errores


# ─────────────────────────────── RF-31 · Configuración ───────────────────────────────

def guardar_configuracion(cambios, usuario_id):
    """Guarda {clave: valor}. Todo o nada: si una clave es inválida no se guarda ninguna.
    La base valida cada valor (trigger) y solo admite al rol admin (RLS). Los cambios rigen
    desde la siguiente operación: las funciones leen la configuración en cada llamada."""
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            for clave, valor in cambios.items():
                cursor.execute(
                    """INSERT INTO rumbo.configuracion AS c (clave, valor, actualizado_por_usuario_id)
                       VALUES (%s, %s::jsonb, %s)
                       ON CONFLICT (clave) DO UPDATE
                          SET valor = EXCLUDED.valor,
                              actualizado_por_usuario_id = EXCLUDED.actualizado_por_usuario_id
                          WHERE c.valor IS DISTINCT FROM EXCLUDED.valor""",
                    [clave, json.dumps(valor, ensure_ascii=False), usuario_id],
                )
                if cursor.rowcount == 0 and not _existe_config(cursor, clave):
                    raise ErrorNegocio("No tiene permiso para cambiar la configuración.", "permiso")
    except DatabaseError as exc:
        raise traducir(exc) from exc


def _existe_config(cursor, clave):
    cursor.execute("SELECT 1 FROM rumbo.configuracion WHERE clave = %s", [clave])
    return cursor.fetchone() is not None


def leer_configuracion():
    with connection.cursor() as cursor:
        cursor.execute("SELECT clave, valor FROM rumbo.configuracion")
        return {clave: (json.loads(v) if isinstance(v, str) else v) for clave, v in cursor.fetchall()}


# ─────────────────────────────── SCRUM-44 · Métricas del piloto ───────────────────────────────

# Resultados que significan que se habló con el cliente (el resto: no contesta, número inválido).
RESULTADOS_CONTACTO = ("interesado", "no_interesado", "venta_cerrada", "llamar_despues")

_SQL_METRICAS = """
WITH leads AS (
    SELECT l.id, l.primer_contacto_en, l.asesor_id, l.estado_asignacion,
           (SELECT min(s.creado_en) FROM rumbo.asignacion s WHERE s.lead_id = l.id) AS asignado_primero,
           (SELECT min(i.creado_en) FROM rumbo.intento_llamada i WHERE i.lead_id = l.id) AS primer_intento,
           EXISTS (SELECT 1 FROM rumbo.intento_llamada i
                   WHERE i.lead_id = l.id AND i.resultado_codigo = ANY(%(contacto)s)) AS contactado,
           EXISTS (SELECT 1 FROM rumbo.venta v WHERE v.lead_id = l.id AND v.anulada_en IS NULL) AS vendido,
           EXISTS (SELECT 1 FROM rumbo.mensaje_whatsapp m
                   WHERE m.lead_id = l.id AND m.direccion = 'saliente') AS respondido
    FROM rumbo.lead l
    WHERE l.primer_contacto_en >= %(desde)s AND l.primer_contacto_en < %(hasta)s AND l.anonimizado_en IS NULL
)
SELECT {grupo} AS grupo,
       count(*)                                                    AS leads,
       count(primer_intento)                                       AS llamados,
       count(*) FILTER (WHERE contactado)                          AS contactados,
       count(*) FILTER (WHERE vendido)                             AS ventas,
       count(*) FILTER (WHERE NOT respondido)                      AS sin_respuesta_automatica,
       count(*) FILTER (WHERE estado_asignacion = 'en_cola')       AS en_cola,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM primer_intento - asignado_primero) / 60)
                                                                   AS min_asignado_a_llamada_mediana,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM primer_intento - asignado_primero) / 60)
                                                                   AS min_asignado_a_llamada_p90,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM primer_intento - primer_contacto_en) / 60)
                                                                   AS min_llegada_a_llamada_mediana
FROM leads l
{union}
GROUP BY 1
ORDER BY 1 NULLS FIRST
"""


def metricas_piloto(desde, hasta):
    """Indicadores del piloto (SCRUM-44) para los leads que llegaron entre desde y hasta.
    Devuelve {"total": {...}, "por_asesor": [...], "reasignaciones": {...}}. RLS: el supervisor
    ve todo el equipo."""
    params = {"desde": desde, "hasta": hasta, "contacto": list(RESULTADOS_CONTACTO)}
    with connection.cursor() as cursor:
        cursor.execute(_SQL_METRICAS.format(grupo="NULL::text", union=""), params)
        cols = [c.name for c in cursor.description]
        total = dict(zip(cols, cursor.fetchone()))
        cursor.execute(_SQL_METRICAS.format(
            grupo="coalesce(u.nombre, 'Sin asesor')",
            union="LEFT JOIN rumbo.asesor a ON a.id = l.asesor_id LEFT JOIN rumbo.usuario u ON u.id = a.usuario_id"),
            params)
        por_asesor = [dict(zip(cols, f)) for f in cursor.fetchall()]
        cursor.execute(
            """SELECT s.motivo::text, count(*) FROM rumbo.asignacion s JOIN rumbo.lead l ON l.id = s.lead_id
               WHERE s.creado_en >= %(desde)s AND s.creado_en < %(hasta)s AND s.motivo <> 'reparto'
               GROUP BY 1""", params)
        reasignaciones = dict(cursor.fetchall())
    for fila in [total, *por_asesor]:
        fila["tasa_contacto"] = round(100 * fila["contactados"] / fila["llamados"]) if fila["llamados"] else None
        fila["tasa_llamados"] = round(100 * fila["llamados"] / fila["leads"]) if fila["leads"] else None
    return {"total": total, "por_asesor": por_asesor, "reasignaciones": reasignaciones}


def metricas_por_campana(desde, hasta):
    """017 · Mismos indicadores agrupados por país de la campaña de origen (o "WhatsApp directo")."""
    params = {"desde": desde, "hasta": hasta, "contacto": list(RESULTADOS_CONTACTO)}
    with connection.cursor() as cursor:
        cursor.execute(_SQL_METRICAS.format(
            grupo="coalesce(an.pais, CASE WHEN an.id IS NULL THEN 'WhatsApp directo' ELSE 'Anuncio sin país' END)",
            union="""LEFT JOIN LATERAL (SELECT o.anuncio_id FROM rumbo.lead_origen o WHERE o.lead_id = l.id
                                        ORDER BY o.llegado_en, o.id LIMIT 1) og ON true
                     LEFT JOIN rumbo.anuncio an ON an.id = og.anuncio_id"""), params)
        cols = [c.name for c in cursor.description]
        filas = [dict(zip(cols, f)) for f in cursor.fetchall()]
    for fila in filas:
        fila["tasa_contacto"] = round(100 * fila["contactados"] / fila["llamados"]) if fila["llamados"] else None
        fila["tasa_venta"] = round(100 * fila["ventas"] / fila["leads"]) if fila["leads"] else None
    return sorted(filas, key=lambda f: -f["leads"])


def errores_webhook(desde, hasta):
    """Eventos del webhook que fallaron al procesarse (solo admin los ve, RLS)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT count(*) FILTER (WHERE ultimo_error IS NOT NULL),
                      count(*) FILTER (WHERE ultimo_error IS NOT NULL AND procesado_en IS NULL),
                      count(*)
               FROM rumbo.webhook_evento WHERE recibido_en >= %s AND recibido_en < %s""", [desde, hasta])
        con_error, pendientes, total = cursor.fetchone()
    return {"con_error": con_error, "pendientes": pendientes, "total": total}


# ─────────────── SCRUM-88 · WhatsApp cuando el cliente no contesta ───────────────

def programar_aviso_no_contesta(lead_id, usuario_id):
    """Encola el WhatsApp de "le llamamos y no contestó" al confirmar la transacción. La tarea decide
    si corresponde (activo, ventana de 24 h, ya avisado hace poco…)."""

    def encolar():
        from whatsapp.tasks import avisar_no_contesta

        try:
            avisar_no_contesta.delay(lead_id, usuario_id)
        except Exception:  # noqa: BLE001 — sin Redis no hay worker: que no rompa el registro de la llamada
            logger.exception("No se pudo encolar el aviso de no contesta del lead %s", lead_id)

    transaction.on_commit(encolar)


# ─────────────── SCRUM-93 · Exportaciones ───────────────

def registrar_exportacion(que, filas, filtros):
    """Deja constancia de la exportación (quién, qué y cuántas filas). Solo supervisión (lo valida la base)."""
    return _ejecutar("SELECT rumbo.registrar_exportacion(%s, %s, %s::jsonb)",
                     [que, filas, json.dumps(filtros, ensure_ascii=False, default=str)])


# ─────────────── SCRUM-96 · Guion de llamada ───────────────

GUION_GENERAL = "General"


def guion_para(tipo_visa, guiones):
    """(título, [pasos]) del guion del tipo de visa del lead; si no hay, el general. None si no hay ninguno."""
    por_clave = {k.strip().lower(): (k, v) for k, v in (guiones or {}).items() if (v or "").strip()}
    elegido = por_clave.get((tipo_visa or "").strip().lower()) or por_clave.get(GUION_GENERAL.lower())
    if not elegido:
        return None
    titulo, texto = elegido
    pasos = [linea.strip().lstrip("-•*·").strip() for linea in texto.splitlines()]
    return titulo, [p for p in pasos if p]


# ─────────────── SCRUM-97 · Meta del día del asesor ───────────────

METAS_POR_DEFECTO = {"llamadas": 20, "citas": 3, "ventas": 1}
NOMBRES_META = {"llamadas": ("llamada", "llamadas"), "citas": ("cita", "citas"), "ventas": ("venta", "ventas")}


def medir_metas(hecho, metas):
    """[{"clave", "nombre", "hecho", "meta", "pct", "cumplida"}]. Una meta en 0 no se muestra."""
    metas = {**METAS_POR_DEFECTO, **(metas or {})}
    filas = []
    for clave in ("llamadas", "citas", "ventas"):
        meta = int(metas.get(clave) or 0)
        if meta <= 0:
            continue
        n = hecho.get(clave, 0)
        singular, plural = NOMBRES_META[clave]
        filas.append({"clave": clave, "nombre": singular if meta == 1 else plural, "hecho": n, "meta": meta,
                      "pct": min(100, round(100 * n / meta)), "cumplida": n >= meta})
    return filas


def progreso_del_dia(asesor_id, usuario_id, metas, desde):
    """Lo hecho hoy frente a la meta. Citas = leads que este usuario pasó a "Cita agendada" hoy."""
    from .models import IntentoLlamada, LeadEtapaHistorial, Venta

    hecho = {
        "llamadas": IntentoLlamada.objects.filter(asesor_id=asesor_id, creado_en__gte=desde).count(),
        "citas": LeadEtapaHistorial.objects.filter(usuario_id=usuario_id, hacia_id="cita_agendada",
                                                   creado_en__gte=desde).count(),
        "ventas": Venta.objects.filter(asesor_id=asesor_id, anulada_en__isnull=True, cerrada_en__gte=desde).count(),
    }
    return medir_metas(hecho, metas)


# ─────────────── SCRUM-98 · Panel en vivo del equipo ───────────────

def panel_en_vivo(desde):
    """Estado del equipo ahora mismo. RLS: solo supervisión ve a todos."""
    with connection.cursor() as cursor:
        cursor.execute(
            """WITH plazos AS (SELECT p.lead_id FROM rumbo.plazos_gestion() p)
               SELECT a.id, u.nombre, a.estado::text AS estado, a.estado_desde,
                      count(l.id) AS abiertos,
                      count(l.id) FILTER (WHERE l.proxima_accion_en <= now()) AS por_llamar,
                      count(l.id) FILTER (WHERE l.id IN (SELECT lead_id FROM plazos)) AS sin_gestionar,
                      (SELECT count(*) FROM rumbo.intento_llamada i
                       WHERE i.asesor_id = a.id AND i.creado_en >= %(desde)s) AS llamadas_hoy,
                      (SELECT max(i.creado_en) FROM rumbo.intento_llamada i WHERE i.asesor_id = a.id) AS ultima_llamada,
                      (SELECT count(*) FROM rumbo.venta v WHERE v.asesor_id = a.id AND v.anulada_en IS NULL
                                                            AND v.cerrada_en >= %(desde)s) AS ventas_hoy
               FROM rumbo.asesor a
               JOIN rumbo.usuario u ON u.id = a.usuario_id
               LEFT JOIN rumbo.lead l ON l.asesor_id = a.id AND l.estado_asignacion = 'asignado'
               WHERE u.activo
               GROUP BY a.id, u.nombre, a.estado, a.estado_desde
               ORDER BY array_position(ARRAY['disponible', 'ocupado', 'pausa', 'fuera_turno'], a.estado::text), u.nombre""",
            {"desde": desde})
        columnas = [c.name for c in cursor.description]
        asesores = [dict(zip(columnas, f)) for f in cursor.fetchall()]
        cursor.execute(
            """SELECT count(*) FILTER (WHERE estado_asignacion = 'en_cola'),
                      (SELECT count(*) FROM rumbo.plazos_gestion()),
                      count(*) FILTER (WHERE estado_asignacion = 'asignado' AND proxima_accion_en <= now())
               FROM rumbo.lead""")
        en_cola, sin_gestionar, por_llamar = cursor.fetchone()
        # Sin horario configurado la base devuelve -infinity, que Python no puede representar.
        cursor.execute("SELECT nullif(rumbo.inicio_turno(), '-infinity')")
        inicio_turno = cursor.fetchone()[0]
    return {"asesores": asesores, "en_cola": en_cola, "sin_gestionar": sin_gestionar, "por_llamar": por_llamar,
            "atrasadas": len(leads_sin_llamar()), "abierto": en_horario(), "inicio_turno": inicio_turno}


def hace_corto(desde, ahora):
    """'ahora', '12 min', '5 h', '5 h 20', '2 días': para tarjetas angostas."""
    if desde is None:
        return None
    minutos = max(0, int((ahora - desde).total_seconds() // 60))
    if minutos < 1:
        return "ahora"
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 24 * 60:
        h, m = divmod(minutos, 60)
        return f"{h} h {m:02d}" if m and h < 10 else f"{h} h"
    dias = minutos // (24 * 60)
    return f"{dias} día{'s' if dias != 1 else ''}"


# ─────────────── SCRUM-99 · Embudo por campaña y anuncio ───────────────

_SQL_EMBUDO = """
WITH origen AS (
    SELECT DISTINCT ON (o.lead_id) o.lead_id, o.anuncio_id
    FROM rumbo.lead_origen o ORDER BY o.lead_id, o.llegado_en, o.id
), leads AS (
    SELECT l.id, og.anuncio_id,
           (l.primer_contacto_en >= %(desde)s AND l.primer_contacto_en < %(hasta)s) AS en_periodo,
           EXISTS (SELECT 1 FROM rumbo.intento_llamada i
                   WHERE i.lead_id = l.id AND i.resultado_codigo = ANY(%(contacto)s)) AS contactado,
           EXISTS (SELECT 1 FROM rumbo.lead_etapa_historial h
                   WHERE h.lead_id = l.id AND h.hacia = 'cita_agendada') AS cita,
           EXISTS (SELECT 1 FROM rumbo.venta v WHERE v.lead_id = l.id AND v.anulada_en IS NULL) AS vendido
    FROM rumbo.lead l JOIN origen og ON og.lead_id = l.id
    WHERE l.anonimizado_en IS NULL
)
SELECT an.id, an.pais, an.nombre_campana, an.titulo, an.clave, an.inversion, an.inversion_moneda,
       count(*) FILTER (WHERE x.en_periodo)                             AS leads,
       count(*) FILTER (WHERE x.en_periodo AND x.contactado)            AS contactados,
       count(*) FILTER (WHERE x.en_periodo AND (x.cita OR x.vendido))   AS citas,
       count(*) FILTER (WHERE x.en_periodo AND x.vendido)               AS ventas,
       count(*)                                                         AS leads_total,
       count(*) FILTER (WHERE x.vendido)                                AS ventas_total
FROM leads x JOIN rumbo.anuncio an ON an.id = x.anuncio_id
GROUP BY an.id
HAVING count(*) FILTER (WHERE x.en_periodo) > 0
ORDER BY an.pais NULLS LAST, count(*) FILTER (WHERE x.en_periodo) DESC
"""


def _pct(parte, total):
    return round(100 * parte / total) if total else None


def armar_embudo(anuncios):
    """Agrupa las filas de anuncios por campaña (país) y calcula porcentajes y costos."""
    campanas = {}
    for a in anuncios:
        a["nombre"] = a["nombre_campana"] or a["titulo"] or f"Anuncio {a['clave'][:20]}"
        a["pct_contacto"], a["pct_cita"], a["pct_venta"] = (_pct(a["contactados"], a["leads"]),
                                                            _pct(a["citas"], a["leads"]), _pct(a["ventas"], a["leads"]))
        inv = a["inversion"]
        a["costo_lead"] = (inv / a["leads_total"]) if inv is not None and a["leads_total"] else None
        a["costo_venta"] = (inv / a["ventas_total"]) if inv is not None and a["ventas_total"] else None
        clave = a["pais"] or "Sin país"
        c = campanas.setdefault(clave, {"pais": clave, "anuncios": [], "leads": 0, "contactados": 0, "citas": 0,
                                        "ventas": 0})
        c["anuncios"].append(a)
        for k in ("leads", "contactados", "citas", "ventas"):
            c[k] += a[k]
    for c in campanas.values():
        c["pct_contacto"], c["pct_cita"], c["pct_venta"] = (_pct(c["contactados"], c["leads"]),
                                                            _pct(c["citas"], c["leads"]), _pct(c["ventas"], c["leads"]))
    resultado = sorted(campanas.values(), key=lambda c: (c["pais"] == "Sin país", -c["leads"]))
    # SCRUM-108 · Escala del gráfico (la campaña con más leads ocupa todo el ancho).
    maximo = max((c["leads"] for c in resultado), default=0)
    for c in resultado:
        c["ancho"] = {k: round(100 * c[k] / maximo) if maximo else 0
                      for k in ("leads", "contactados", "citas", "ventas")}
    # SCRUM-108 · Mejor y peor costo por venta (solo si hay al menos dos anuncios comparables).
    con_costo = [a for c in resultado for a in c["anuncios"] if a["costo_venta"] is not None]
    if len(con_costo) >= 2:
        min(con_costo, key=lambda a: a["costo_venta"])["destacado"] = "mejor"
        max(con_costo, key=lambda a: a["costo_venta"])["destacado"] = "peor"
    return resultado


def embudo_por_anuncio(desde, hasta):
    """Embudo leads → contactados → citas → ventas de cada anuncio (leads llegados en el período, contados
    en su primer anuncio), agrupado por campaña (país). Los costos usan la inversión TOTAL del anuncio
    sobre TODOS sus leads: la inversión no se registra por fecha."""
    params = {"desde": desde, "hasta": hasta, "contacto": list(RESULTADOS_CONTACTO)}
    with connection.cursor() as cursor:
        cursor.execute(_SQL_EMBUDO, params)
        columnas = [c.name for c in cursor.description]
        return armar_embudo([dict(zip(columnas, f)) for f in cursor.fetchall()])


def registrar_inversion(anuncio_id, monto):
    _ejecutar("SELECT rumbo.registrar_inversion_anuncio(%s, %s)", [anuncio_id, monto])


# ─────────────── SCRUM-113 · Estado de la conexión con Meta ───────────────

VARIABLES_META = ("META_DATASET_ID", "META_CAPI_TOKEN", "META_WABA_ID")


def estado_conversiones(dias=30):
    """Si la Conversions API está configurada y cómo van los eventos de los últimos `dias` (solo admin, RLS)."""
    from django.conf import settings

    faltan = [v for v in VARIABLES_META if not getattr(settings, v, "")]
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT count(*) FILTER (WHERE estado = 'enviado'), count(*) FILTER (WHERE estado = 'pendiente'),
                      count(*) FILTER (WHERE estado = 'error'), count(*) FILTER (WHERE estado = 'vencido'),
                      max(enviado_en)
               FROM rumbo.evento_conversion WHERE creado_en >= now() - make_interval(days => %s)""", [dias])
        enviados, pendientes, errores, vencidos, ultimo_envio = cursor.fetchone()
        cursor.execute("""SELECT ultimo_error, creado_en FROM rumbo.evento_conversion
                          WHERE ultimo_error IS NOT NULL AND estado IN ('error', 'pendiente')
                          ORDER BY id DESC LIMIT 1""")
        error = cursor.fetchone()
    return {"configurado": not faltan, "faltan": faltan, "dias": dias, "enviados": enviados, "pendientes": pendientes,
            "errores": errores, "vencidos": vencidos, "ultimo_envio": ultimo_envio,
            "ultimo_error": error[0] if error else None, "ultimo_error_en": error[1] if error else None,
            "prueba": bool(getattr(settings, "META_CAPI_TEST_CODE", ""))}


def avance_total(metas):
    """SCRUM-106 · Promedio del avance de las metas del día (0–100) y si se cumplieron todas."""
    if not metas:
        return None
    return {"pct": round(sum(m["pct"] for m in metas) / len(metas)), "cumplidas": all(m["cumplida"] for m in metas),
            "resumen": " · ".join(f"{m['hecho']}/{m['meta']} {m['nombre']}" for m in metas)}
