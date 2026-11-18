from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def inicio(request):
    return render(request, "core/inicio.html")


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
