"""Pone en todas las plantillas `rumbo` (rol del usuario según la base), `mi_asesor`
(estado del asesor para el selector de la barra) y `por_llamar` (llamadas que ya toca hacer,
para el contador del menú). Se calculan solo si la plantilla los usa."""
from django.db import DatabaseError
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from leads.models import Asesor, EstadoAsignacion, Lead
from leads.servicios import Contexto, contexto_actual

SIN_CONTEXTO = Contexto(None, None, None)


def rumbo(request):
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return {"rumbo": SIN_CONTEXTO}

    def _ctx():
        ctx = getattr(request, "rumbo", None)
        if ctx is not None:
            return ctx
        try:
            return contexto_actual()
        except DatabaseError:            # p. ej. página de error tras un fallo de la base
            return SIN_CONTEXTO

    def _asesor():
        ctx = _ctx()
        return Asesor.objects.filter(pk=ctx.asesor_id).first() if ctx.asesor_id else None

    def _por_llamar():
        # RLS: el asesor cuenta solo los suyos; el supervisor, los de todo el equipo.
        if not _ctx().rol:
            return 0
        try:
            return Lead.objects.filter(estado_asignacion=EstadoAsignacion.ASIGNADO,
                                       proxima_accion_en__lte=timezone.now()).count()
        except DatabaseError:
            return 0

    def _sin_leer():
        from leads.models import Notificacion
        try:
            return Notificacion.objects.filter(leida_en__isnull=True).count()   # RLS: solo las propias
        except DatabaseError:
            return 0

    def _anuncios_sin_pais():
        from leads.models import Anuncio
        if not _ctx().es_admin:
            return 0
        try:
            return Anuncio.objects.filter(pais__isnull=True).count()
        except DatabaseError:
            return 0

    def _meta_dia():
        # SCRUM-106: mini barra de la meta del día en el menú del asesor.
        ctx = _ctx()
        if not ctx.asesor_id:
            return None
        try:
            import datetime as dt

            from leads.servicios import avance_total, leer_configuracion, progreso_del_dia
            inicio = dt.datetime.combine(timezone.localdate(), dt.time.min, timezone.get_current_timezone())
            return avance_total(progreso_del_dia(ctx.asesor_id, ctx.usuario_id,
                                                 leer_configuracion().get("metas_diarias"), inicio))
        except DatabaseError:
            return None

    from django.conf import settings

    return {"push_clave_publica": settings.WEBPUSH_VAPID_PUBLIC_KEY,                    # SCRUM-122
            "rumbo": SimpleLazyObject(_ctx), "mi_asesor": SimpleLazyObject(_asesor),
            "meta_dia": SimpleLazyObject(_meta_dia),
            "por_llamar": SimpleLazyObject(_por_llamar),
            "notificaciones_sin_leer": SimpleLazyObject(_sin_leer),
            "anuncios_sin_pais": SimpleLazyObject(_anuncios_sin_pais)}
