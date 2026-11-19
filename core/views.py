import datetime as dt

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET


def _inicio_del_dia():
    return dt.datetime.combine(timezone.localdate(), dt.time.min, timezone.get_current_timezone())


def _panel_asesor(ctx):
    """Lo que el asesor necesita al empezar: su estado, a quién llamar ahora y lo que viene."""
    from leads.models import EstadoAsignacion, IntentoLlamada, Lead, Venta

    ahora = timezone.now()
    abiertos = Lead.objects.filter(estado_asignacion=EstadoAsignacion.ASIGNADO, asesor_id=ctx.asesor_id)
    ya = abiertos.filter(proxima_accion_en__lte=ahora).select_related("etapa").order_by("proxima_accion_en")
    inicio_mes = _inicio_del_dia().replace(day=1)
    return {
        "por_llamar_lista": ya[:6],
        "por_llamar_total": ya.count(),
        "proximas": abiertos.filter(proxima_accion_en__gt=ahora).select_related("etapa").order_by("proxima_accion_en")[:5],
        "abiertos": abiertos.count(),
        "llamadas_hoy": IntentoLlamada.objects.filter(asesor_id=ctx.asesor_id, creado_en__gte=_inicio_del_dia()).count(),
        "ventas_mes": Venta.objects.filter(asesor_id=ctx.asesor_id, anulada_en__isnull=True, cerrada_en__gte=inicio_mes).count(),
        "ahora": ahora,
    }


def _panel_supervision():
    """Resumen del día para supervisor y administrador."""
    from cuentas.servicios import asesores_con_carga
    from leads import servicios
    from leads.models import EstadoAsignacion, IntentoLlamada, Lead, Venta

    hoy = _inicio_del_dia()
    alertas = servicios.leads_sin_llamar()
    equipo = asesores_con_carga()
    return {
        "alertas": alertas[:5],
        "alertas_total": len(alertas),
        "umbral": servicios.leer_configuracion().get("minutos_alerta_supervisor", 30),
        "equipo": equipo,
        "disponibles": sum(a["estado"] == "disponible" for a in equipo),
        "leads_hoy": Lead.objects.filter(primer_contacto_en__gte=hoy).count(),
        "en_cola": Lead.objects.filter(estado_asignacion=EstadoAsignacion.EN_COLA).count(),
        "llamadas_hoy": IntentoLlamada.objects.filter(creado_en__gte=hoy).count(),
        "ventas_hoy": Venta.objects.filter(anulada_en__isnull=True, cerrada_en__gte=hoy).count(),
    }


@require_GET
def inicio(request):
    """Sin sesión → login. Con rol → su panel de inicio. Sin rol en la base → aviso (403)."""
    if not request.user.is_authenticated:
        return redirect("cuentas:login")
    from leads.servicios import contexto_actual

    ctx = contexto_actual()
    if ctx.rol not in ("asesor", "supervisor", "admin"):
        return render(request, "core/sin_rol.html", status=403)
    contexto = {"rumbo": ctx}
    if ctx.es_supervisor:
        contexto.update(_panel_supervision())
    if ctx.asesor_id:
        contexto.update(_panel_asesor(ctx))
    return render(request, "core/inicio.html", contexto)


@require_GET
@login_required
def ayuda(request):
    """Guía corta de uso dentro de la aplicación (SCRUM-46), según el rol."""
    return render(request, "core/ayuda.html")


@require_GET
def salud(request):
    """Healthcheck para Docker y el proxy: la app responde y llega a la base."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001
        return JsonResponse({"estado": "error", "base": False}, status=503)
    return JsonResponse({"estado": "ok", "base": True})
