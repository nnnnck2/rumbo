from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET


@require_GET
def inicio(request):
    """Sin sesión → login. Con rol en la base → sus leads. Sin rol → aviso (403)."""
    if not request.user.is_authenticated:
        return redirect("cuentas:login")
    from leads.servicios import contexto_actual

    if contexto_actual().rol in ("asesor", "supervisor", "admin"):
        return redirect("leads:lista")
    return render(request, "core/inicio.html", status=403)


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
