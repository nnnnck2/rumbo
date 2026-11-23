"""SCRUM-57 (RF-35) · API de solo lectura para que CALLFLOW calcule comisiones con las ventas de visas.

CALLFLOW → Rumbo (HTTPS). CALLFLOW nunca recibe conexiones.

    GET /api/callflow/v1/ventas/?desde=<ISO 8601>&despues_id=<id>&limite=<1..1000>
    GET /api/callflow/v1/asesores/
    Authorization: Bearer <token>

Ventas: sincronización incremental. La primera vez sin `desde`; después, con el `siguiente` que devolvió la
respuesta anterior, hasta que `hay_mas` sea false. Una venta anulada vuelve a salir con `anulada_en`:
CALLFLOW revierte esa comisión. No sale ningún dato del cliente (teléfono, nombre, mensajes, notas).

Token: se genera con `python manage.py generar_token_callflow`. En el servidor solo se guarda su SHA-256
(CALLFLOW_API_TOKENS_SHA256 en .env; admite varios para rotarlo sin cortar el servicio).
"""
import datetime as dt
import hashlib
import hmac
import logging
from decimal import Decimal

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .db import como_sistema

seguridad = logging.getLogger("rumbo.seguridad")
VERSION = "v1"


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def token_valido(encabezado):
    """Compara el SHA-256 del token Bearer contra los configurados, en tiempo constante."""
    if not encabezado or not encabezado.startswith("Bearer "):
        return False
    recibido = hash_token(encabezado[7:].strip())
    validos = [h.strip().lower() for h in getattr(settings, "CALLFLOW_API_TOKENS_SHA256", []) if h.strip()]
    return any(hmac.compare_digest(recibido, h) for h in validos)


def _ip(request):
    from cuentas.acceso import ip_cliente

    return ip_cliente(request)


def _protegida(vista):
    @csrf_exempt
    @never_cache
    @require_GET
    def envoltura(request, *args, **kwargs):
        if not token_valido(request.META.get("HTTP_AUTHORIZATION", "")):
            seguridad.warning("API CALLFLOW · token inválido · ip=%s · %s", _ip(request), request.path)
            respuesta = JsonResponse({"error": "no_autorizado", "detalle": "Token inválido o ausente."}, status=401)
            respuesta["WWW-Authenticate"] = 'Bearer realm="rumbo-callflow"'
            return respuesta
        return vista(request, *args, **kwargs)
    envoltura.__name__ = vista.__name__
    return envoltura


def _json(valor):
    if isinstance(valor, Decimal):
        return str(valor)                      # dinero exacto: CALLFLOW lo convierte a Decimal
    if isinstance(valor, dt.datetime):
        return valor.isoformat()
    return valor


def _filas(sql, params):
    with como_sistema() as cursor:
        cursor.execute(sql, params)
        columnas = [c.name for c in cursor.description]
        return [{k: _json(v) for k, v in zip(columnas, f)} for f in cursor.fetchall()]


def _error(detalle):
    return JsonResponse({"error": "parametro_invalido", "detalle": detalle}, status=400)


@_protegida
def ventas(request):
    desde, despues_id = request.GET.get("desde"), request.GET.get("despues_id")
    try:
        desde = dt.datetime.fromisoformat(desde) if desde else None
    except ValueError:
        return _error("desde debe ser una fecha ISO 8601 con zona, p. ej. 2026-11-23T10:00:00-05:00.")
    if desde is not None and desde.tzinfo is None:
        return _error("desde debe incluir la zona horaria.")
    if despues_id and not despues_id.isdigit():
        return _error("despues_id debe ser un número.")
    try:
        limite = min(max(int(request.GET.get("limite") or 500), 1), 1000)
    except ValueError:
        return _error("limite debe ser un número entre 1 y 1000.")
    filas = _filas("SELECT * FROM api.callflow_ventas(%s, %s, %s)", [desde, int(despues_id) if despues_id else None, limite])
    ultimo = filas[-1] if filas else None
    seguridad.info("API CALLFLOW · ventas · %s filas · ip=%s", len(filas), _ip(request))
    return JsonResponse({
        "version": VERSION,
        "ventas": filas,
        "hay_mas": len(filas) == limite,
        # Para la próxima llamada (si no hubo filas, repetir la misma consulta más tarde).
        "siguiente": {"desde": ultimo["actualizado_en"], "despues_id": ultimo["venta_id"]} if ultimo else
                     {"desde": desde.isoformat() if desde else None, "despues_id": int(despues_id) if despues_id else None},
    }, json_dumps_params={"ensure_ascii": False})


@_protegida
def asesores(request):
    filas = _filas("SELECT * FROM api.callflow_asesores()", [])
    seguridad.info("API CALLFLOW · asesores · %s filas · ip=%s", len(filas), _ip(request))
    return JsonResponse({"version": VERSION, "asesores": filas}, json_dumps_params={"ensure_ascii": False})
