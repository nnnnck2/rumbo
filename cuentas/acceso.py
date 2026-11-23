"""SCRUM-35 · Seguridad de acceso: bloqueo temporal tras varios fallos, registro de ingresos y contraseñas robustas.

El registro y la cuenta de fallos viven en la base (auditoria.acceso, migración 020): así el bloqueo vale para
todos los procesos de gunicorn y nadie puede borrar el rastro desde la aplicación.
"""
import ipaddress
import logging
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection
from django.utils import timezone

seguridad = logging.getLogger("rumbo.seguridad")


def ip_cliente(request):
    """IP real del cliente. Detrás de nginx se usa X-Real-IP (nginx lo sobrescribe con $remote_addr, el cliente
    no puede falsificarlo); en desarrollo, REMOTE_ADDR."""
    meta = request.META
    candidata = meta.get("HTTP_X_REAL_IP") if getattr(settings, "RUMBO_CONFIAR_X_REAL_IP", False) else None
    for valor in (candidata, meta.get("REMOTE_ADDR")):
        try:
            return str(ipaddress.ip_address((valor or "").strip()))
        except ValueError:
            continue
    return None


def registrar(request, usuario, evento, usuario_id=None):
    """Deja el evento en auditoria.acceso (ingreso, fallido, bloqueado, salida). Nunca rompe el login."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT auditoria.registrar_acceso(%s, %s, %s::inet, %s, %s)",
                           [(usuario or "")[:150], evento, ip_cliente(request),
                            request.META.get("HTTP_USER_AGENT", "")[:300], usuario_id])
    except DatabaseError:
        seguridad.exception("No se pudo registrar el acceso (%s · %r)", evento, usuario)


def bloqueado_hasta(request, usuario):
    """Hasta cuándo está bloqueado el ingreso para ese usuario o esa IP; None si puede intentar."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT auditoria.bloqueo_acceso(%s, %s::inet)", [(usuario or "")[:150], ip_cliente(request)])
            return cursor.fetchone()[0]
    except DatabaseError:
        seguridad.exception("No se pudo consultar el bloqueo de %r", usuario)
        return None


def texto_espera(hasta, ahora=None):
    minutos = max(1, -(-int((hasta - (ahora or timezone.now())).total_seconds()) // 60))   # hacia arriba
    return f"{minutos} minuto{'s' if minutos != 1 else ''}"


def accesos_recientes(limite=200, evento=None):
    """Para la pantalla de Auditoría (la base exige rol admin)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM auditoria.accesos_recientes(%s, %s)", [limite, evento or None])
        columnas = [c.name for c in cursor.description]
        return [dict(zip(columnas, f)) for f in cursor.fetchall()]


class ComplejidadValidator:
    """Contraseña robusta: además del largo (MinimumLengthValidator), letras, números y un símbolo o mayúscula."""

    def validate(self, password, user=None):
        faltan = []
        if not re.search(r"[^\W\d_]", password):
            faltan.append("letras")
        if not re.search(r"\d", password):
            faltan.append("números")
        if not (re.search(r"[^\w\s]|_", password) or re.search(r"[A-ZÁÉÍÓÚÑ]", password)):
            faltan.append("al menos una mayúscula o un símbolo (por ejemplo ! - . #)")
        if faltan:
            raise ValidationError("La contraseña debe tener " + ", ".join(faltan) + ".", code="password_too_simple")

    def get_help_text(self):
        return "Debe combinar letras, números y al menos una mayúscula o un símbolo."
