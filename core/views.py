import datetime as dt

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.db.models import F
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST


def _inicio_del_dia():
    return dt.datetime.combine(timezone.localdate(), dt.time.min, timezone.get_current_timezone())


def _panel_asesor(ctx):
    """Lo que el asesor necesita al empezar: su estado, a quién llamar ahora y lo que viene."""
    from leads.models import EstadoAsignacion, IntentoLlamada, Lead, Venta

    ahora = timezone.now()
    abiertos = Lead.objects.filter(estado_asignacion=EstadoAsignacion.ASIGNADO, asesor_id=ctx.asesor_id)
    ya = abiertos.filter(proxima_accion_en__lte=ahora).select_related("etapa").order_by("proxima_accion_en")
    inicio_mes = _inicio_del_dia().replace(day=1)
    from leads.servicios import con_situacion

    return {
        "por_llamar_lista": con_situacion(ya[:6]),
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


# ─────────────────────────────── 017 · Notificaciones (como CALLFLOW) ───────────────────────────────
# La campana pide /notificaciones/contadores/ cada 10 s: devuelve el número sin leer y, como avisos
# flotantes, las notificaciones nuevas que todavía no se mostraron en esta sesión.

CLAVE_ULTIMA = "rumbo_notif_ultima"
VENTANA_INICIAL_MIN = 10
MAX_AVISOS = 4


def _mis_notificaciones():
    from leads.models import Notificacion

    return Notificacion.objects.all()     # RLS: la base devuelve solo las del usuario


def _nuevas_para_mostrar(request):
    ultima = request.session.get(CLAVE_ULTIMA)
    pendientes = _mis_notificaciones().filter(leida_en__isnull=True)
    if ultima is None:      # recién ingresó: solo las de los últimos minutos (no una avalancha)
        pendientes = pendientes.filter(creado_en__gte=timezone.now() - dt.timedelta(minutes=VENTANA_INICIAL_MIN))
    else:
        pendientes = pendientes.filter(pk__gt=ultima)
    nuevas = list(pendientes.order_by("-pk")[:MAX_AVISOS])[::-1]
    maxima = _mis_notificaciones().order_by("-pk").values_list("pk", flat=True).first()
    request.session[CLAVE_ULTIMA] = max(ultima or 0, maxima or 0)
    return nuevas


def _con_rol_activo(vista):
    """Notificaciones: cualquier usuario con rol en Rumbo."""
    from cuentas.permisos import TODOS, con_rol

    return con_rol(*TODOS)(vista)


@require_GET
@never_cache
@_con_rol_activo
def notificaciones_contadores(request):
    sin_leer = _mis_notificaciones().filter(leida_en__isnull=True).count()
    return render(request, "core/_contadores.html", {"sin_leer": sin_leer, "avisos_nuevos": _nuevas_para_mostrar(request)})


@require_GET
@never_cache
@_con_rol_activo
def notificaciones_panel(request):
    return _panel(request)


def _panel(request):
    return render(request, "core/_campana.html", {
        "notificaciones": _mis_notificaciones().order_by(F("leida_en").asc(nulls_first=True), "-pk")[:8],
        "sin_leer": _mis_notificaciones().filter(leida_en__isnull=True).count(),
    })


@require_POST
@_con_rol_activo
def notificaciones_leidas(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT rumbo.marcar_notificaciones_leidas()")
    if request.htmx:
        return _panel(request)
    return redirect("notificaciones")


@require_GET
@_con_rol_activo
def notificacion_abrir(request, pk):
    """Marca como leída y lleva a su pantalla (solo rutas internas)."""
    n = _mis_notificaciones().filter(pk=pk).first()
    if n is None:
        return redirect("notificaciones")
    if n.leida_en is None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rumbo.marcar_notificaciones_leidas(%s::bigint[])", [[n.pk]])
    destino = n.url if n.url and url_has_allowed_host_and_scheme(n.url, allowed_hosts={request.get_host()}) else None
    return redirect(destino or "notificaciones")


@require_GET
@_con_rol_activo
def notificaciones(request):
    from django.core.paginator import Paginator

    qs = _mis_notificaciones().order_by("-pk")
    sin_leer = request.GET.get("ver") == "sin_leer"
    if sin_leer:
        qs = qs.filter(leida_en__isnull=True)
    return render(request, "core/notificaciones.html", {
        "pagina": Paginator(qs, 25).get_page(request.GET.get("pagina")), "solo_sin_leer": sin_leer,
        "sin_leer": _mis_notificaciones().filter(leida_en__isnull=True).count(),
        "hoy": timezone.localdate(),
    })
