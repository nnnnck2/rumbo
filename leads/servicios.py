"""Acciones de negocio sobre los leads (SCRUM-30, 31, 32, 33).

Toda escritura pasa por las funciones SQL de db/migraciones/006 (o por la tabla de
configuración, que valida un trigger). La base decide permisos (rol del contexto RLS),
reglas (transiciones de etapa, venta obligatoria…) y concurrencia (bloqueo optimista).
Aquí solo se traducen sus errores a mensajes para el usuario.

Cada llamada corre en su propio savepoint: el request ya está dentro de una transacción
(core.middleware), y un error de la base la dejaría inutilizable para el resto de la página.
"""
import json
from dataclasses import dataclass

from django.db import DatabaseError, connection, transaction
from django.utils import timezone


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
