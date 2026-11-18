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
