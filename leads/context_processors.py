"""Rol de Rumbo disponible en todas las plantillas (barra de navegación: enlaces y alertas)."""
from django.db import DatabaseError

from . import servicios


def rumbo(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    contexto = getattr(request, "rumbo", None)
    if contexto is None:
        try:
            contexto = servicios.contexto_actual()
        except DatabaseError:
            return {}
    return {"rumbo": contexto}
