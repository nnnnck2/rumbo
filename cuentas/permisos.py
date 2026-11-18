"""RF-30 · Roles (SCRUM-27).

El rol NO vive en Django: es la columna rumbo.usuario.rol, y la base lo usa para RLS y para
validar cada función de negocio. Aquí solo se lee para decidir qué pantallas mostrar:
  · asesor      → sus leads (la base no le devuelve otros) y su estado.
  · supervisor  → todos los leads y asesores; reasigna y cambia el estado de los asesores.
  · admin       → además gestiona usuarios y configuración.
Un usuario de Django sin fila activa en rumbo.usuario no tiene rol: 403 en todo.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from leads import servicios

TODOS = ("asesor", "supervisor", "admin")
SUPERVISION = ("supervisor", "admin")
ADMIN = ("admin",)


def con_rol(*roles):
    """login_required + rol de la base (rumbo.usuario). Sin fila en rumbo.usuario → 403."""
    def decorador(vista):
        @login_required
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            request.rumbo = servicios.contexto_actual()
            if request.rumbo.rol not in roles:
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador
