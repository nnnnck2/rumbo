"""Usuarios (RF-30, SCRUM-27) y estado de los asesores (RF-11, SCRUM-25).

Un usuario son dos filas con el mismo id:
  · django.auth_user  → usuario y contraseña (login).
  · rumbo.usuario     → nombre, rol y activo (lo que usa la base para RLS).
  · rumbo.asesor      → además, si el rol es asesor (número de WhatsApp, código CALLFLOW, estado).
Se crean y modifican juntas en una transacción. La base solo deja escribir rumbo.usuario y
rumbo.asesor al rol admin (RLS); aquí no se repite esa regla, se traduce su error.
"""
import json
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction

from leads.models import Asesor, EstadoAsesor, Usuario
from leads.servicios import ErrorNegocio, traducir

# Estados que el asesor elige con un clic. "ocupado" lo usa el sistema (SCRUM-39), no se elige.
ESTADOS_ELEGIBLES = (EstadoAsesor.DISPONIBLE, EstadoAsesor.PAUSA, EstadoAsesor.FUERA_TURNO)


def _sql(sql, params):
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, params)
    except IntegrityError as exc:
        if getattr(exc.__cause__, "sqlstate", None) == "23505":
            raise ErrorNegocio("Ya existe otro asesor con ese código CALLFLOW.") from exc
        raise traducir(exc) from exc
    except DatabaseError as exc:
        raise traducir(exc) from exc


# ─────────────────────────────── RF-11 · Estado del asesor ───────────────────────────────

def cambiar_estado(estado, asesor_id=None):
    """Sin asesor_id: el propio (asesor). Con asesor_id: supervisor/admin cambia el de otro.
    La base valida que un asesor solo cambie el suyo."""
    if estado not in ESTADOS_ELEGIBLES:
        raise ErrorNegocio("Estado no válido.")
    _sql("SELECT rumbo.cambiar_estado_asesor(%s::rumbo.estado_asesor, %s)", [estado, asesor_id])


def asesores_con_carga():
    """Todos los asesores activos con su estado y cuántos leads abiertos tienen (supervisor)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT a.id, u.nombre, a.estado::text, a.estado_desde, n.telefono,
                      count(l.id) FILTER (WHERE l.estado_asignacion = 'asignado') AS abiertos
               FROM rumbo.asesor a
               JOIN rumbo.usuario u ON u.id = a.usuario_id
               LEFT JOIN rumbo.numero_whatsapp n ON n.id = a.numero_whatsapp_id
               LEFT JOIN rumbo.lead l ON l.asesor_id = a.id
               WHERE u.activo
               GROUP BY a.id, u.nombre, a.estado, a.estado_desde, n.telefono
               ORDER BY (a.estado <> 'disponible'), u.nombre""")
        columnas = [c.name for c in cursor.description]
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


# ─────────────────────────────── RF-30 · Usuarios ───────────────────────────────

@dataclass
class FilaUsuario:
    id: int
    username: str
    nombre: str | None
    rol: str | None
    activo: bool
    ultimo_ingreso: object
    asesor: Asesor | None

    @property
    def rol_display(self):
        return dict(Usuario._meta.get_field("rol").choices).get(self.rol, "Sin rol")


def listar_usuarios():
    usuarios = Usuario.objects.in_bulk()
    asesores = {a.usuario_id: a for a in Asesor.objects.select_related("numero_whatsapp")}
    filas = []
    for u in get_user_model().objects.order_by("username"):
        r = usuarios.get(u.pk)
        filas.append(FilaUsuario(u.pk, u.username, r.nombre if r else None, r.rol if r else None,
                                 bool(r and r.activo and u.is_active), u.last_login, asesores.get(u.pk)))
    return filas


def crear_usuario(*, username, nombre, rol, password, numero_whatsapp_id=None, codigo_callflow=None):
    with transaction.atomic():
        user = get_user_model().objects.create_user(username=username, password=password)
        _sql("INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (%s, %s, %s::rumbo.rol_usuario)",
             [user.pk, nombre, rol])
        if rol == "asesor":
            _sql("INSERT INTO rumbo.asesor (usuario_id, numero_whatsapp_id, codigo_callflow) VALUES (%s, %s, %s)",
                 [user.pk, numero_whatsapp_id, codigo_callflow or None])
    return user


def actualizar_usuario(user, *, nombre, rol, activo, password=None, numero_whatsapp_id=None,
                       codigo_callflow=None, editor_id=None):
    actual = Usuario.objects.filter(pk=user.pk).first()
    if editor_id == user.pk and (not activo or rol != "admin"):
        raise ErrorNegocio("No puede quitarse a sí mismo el rol de administrador ni desactivarse.")
    if actual and actual.rol == "asesor" and rol != "asesor":
        raise ErrorNegocio("Un asesor no puede cambiar de rol (tiene leads e historial a su nombre). "
                           "Desactívelo y cree un usuario nuevo con el otro rol.")
    with transaction.atomic():
        if actual is None:
            _sql("INSERT INTO rumbo.usuario (id, nombre, rol, activo) VALUES (%s, %s, %s::rumbo.rol_usuario, %s)",
                 [user.pk, nombre, rol, activo])
        else:
            _sql("UPDATE rumbo.usuario SET nombre = %s, rol = %s::rumbo.rol_usuario, activo = %s WHERE id = %s",
                 [nombre, rol, activo, user.pk])
        if rol == "asesor":
            if Asesor.objects.filter(usuario_id=user.pk).exists():
                _sql("UPDATE rumbo.asesor SET numero_whatsapp_id = %s, codigo_callflow = %s WHERE usuario_id = %s",
                     [numero_whatsapp_id, codigo_callflow or None, user.pk])
            else:
                _sql("INSERT INTO rumbo.asesor (usuario_id, numero_whatsapp_id, codigo_callflow) VALUES (%s, %s, %s)",
                     [user.pk, numero_whatsapp_id, codigo_callflow or None])
        user.is_active = activo
        if password:
            user.set_password(password)
        user.save()


def guardar_especialidades(asesor_id, paises, visas):
    """SCRUM-118 · Países y tipos de visa que domina el asesor (los usa el reparto). Solo admin (lo valida la base)."""
    _sql("SELECT rumbo.guardar_especialidades(%s, %s, %s)", [asesor_id, list(paises), list(visas)])


# ─────────────────────────────── SCRUM-35 · Auditoría ───────────────────────────────

def _filas(sql, params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columnas = [c.name for c in cursor.description]
        return [dict(zip(columnas, f)) for f in cursor.fetchall()]


def reasignaciones_recientes(limite=300):
    """Cada cambio de asesor de un lead (automático o manual), con quién lo hizo."""
    return _filas(
        """SELECT s.creado_en, s.lead_id, s.motivo::text AS motivo, s.vuelta,
                  ua.nombre AS desde, un.nombre AS hacia, up.nombre AS por
           FROM rumbo.asignacion s
           JOIN rumbo.asesor an ON an.id = s.asesor_id JOIN rumbo.usuario un ON un.id = an.usuario_id
           LEFT JOIN rumbo.asesor aa ON aa.id = s.asesor_anterior_id LEFT JOIN rumbo.usuario ua ON ua.id = aa.usuario_id
           LEFT JOIN rumbo.usuario up ON up.id = s.asignado_por_usuario_id
           WHERE s.asesor_anterior_id IS NOT NULL OR s.motivo <> 'reparto'
           ORDER BY s.id DESC LIMIT %s""", [limite])


def cambios_auditados(tabla, limite=300):
    """Cambios de auditoria.registro de una tabla (configuración o usuarios), con el nombre de quien los hizo."""
    filas = _filas(
        """SELECT r.ocurrido_en, r.operacion, r.registro_id, r.cambios, r.despues, r.cliente_ip, u.nombre AS por
           FROM auditoria.registro r LEFT JOIN rumbo.usuario u ON u.id = r.usuario_id
           WHERE r.tabla = %s ORDER BY r.id DESC LIMIT %s""", [tabla, limite])
    for f in filas:
        for k in ("cambios", "despues"):                 # Django entrega jsonb como texto en cursores crudos
            if isinstance(f[k], str):
                f[k] = json.loads(f[k])
        texto = lambda v: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)  # noqa: E731
        f["etiqueta"] = f["registro_id"] or (f["despues"] or {}).get("clave") or ""
        if f["operacion"] == "UPDATE":
            f["detalle"] = [(k, texto(v.get("antes")), texto(v.get("despues"))) for k, v in (f["cambios"] or {}).items()]
        else:
            f["detalle"] = [(k, None, texto(v)) for k, v in (f["despues"] or {}).items()
                            if k in ("valor", "nombre", "rol", "activo")]
    return filas
