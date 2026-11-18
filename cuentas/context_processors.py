"""Pone en todas las plantillas `rumbo` (rol del usuario según la base) y `mi_asesor`
(estado del asesor para el selector de la barra). Se calculan solo si la plantilla los usa."""
from django.utils.functional import SimpleLazyObject

from leads.models import Asesor
from leads.servicios import Contexto, contexto_actual

SIN_CONTEXTO = Contexto(None, None, None)


def rumbo(request):
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return {"rumbo": SIN_CONTEXTO}

    def _ctx():
        return getattr(request, "rumbo", None) or contexto_actual()

    def _asesor():
        ctx = _ctx()
        return Asesor.objects.filter(pk=ctx.asesor_id).first() if ctx.asesor_id else None

    return {"rumbo": SimpleLazyObject(_ctx), "mi_asesor": SimpleLazyObject(_asesor)}
