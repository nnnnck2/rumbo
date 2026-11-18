"""RF-01 · Webhook de WhatsApp Cloud API.

GET  → verificación de Meta (hub.mode / hub.verify_token / hub.challenge).
POST → valida la firma (RF-02), guarda el evento crudo y responde 200 de inmediato;
       el procesamiento lo hace Celery.
"""
import hmac
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .firma import verificar_firma
from .servicios import guardar_evento

logger = logging.getLogger("rumbo.whatsapp")
seguridad = logging.getLogger("rumbo.seguridad")


def _ip(request):
    reenviada = request.headers.get("X-Forwarded-For", "")
    return reenviada.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


def _encolar():
    from .tasks import procesar_eventos_webhook

    try:
        procesar_eventos_webhook.delay()
    except Exception:  # noqa: BLE001 — si Redis no responde, beat lo procesa en ≤30 s
        logger.exception("No se pudo encolar el procesamiento del webhook")


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request):
    if request.method == "GET":
        return _verificar_suscripcion(request)

    cuerpo = request.body
    valida, motivo = verificar_firma(
        cuerpo, request.headers.get("X-Hub-Signature-256"), settings.WHATSAPP_APP_SECRET
    )
    if not valida:
        seguridad.warning("Webhook rechazado (403): %s · ip=%s · bytes=%s", motivo, _ip(request), len(cuerpo))
        return HttpResponseForbidden("firma inválida")

    try:
        payload = json.loads(cuerpo)
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Webhook con firma válida pero JSON inválido · ip=%s", _ip(request))
        return HttpResponseBadRequest("json inválido")
    if not isinstance(payload, dict):
        return HttpResponseBadRequest("json inválido")

    evento_id = guardar_evento(cuerpo, payload)
    if evento_id is None:
        logger.info("Webhook repetido (Meta reintentó un evento ya guardado)")
    else:
        transaction.on_commit(_encolar)
    return HttpResponse("ok")


def _verificar_suscripcion(request):
    modo = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token", "")
    reto = request.GET.get("hub.challenge", "")
    esperado = settings.WHATSAPP_VERIFY_TOKEN
    if modo == "subscribe" and esperado and hmac.compare_digest(token.encode(), esperado.encode()):
        logger.info("Webhook verificado por Meta")
        return HttpResponse(reto, content_type="text/plain")
    seguridad.warning("Verificación de webhook rechazada · ip=%s · modo=%s", _ip(request), modo)
    return HttpResponseForbidden("token inválido")
