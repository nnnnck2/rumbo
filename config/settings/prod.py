"""Producción (VPS detrás de un proxy con HTTPS)."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
# 127.0.0.1/localhost: el healthcheck de Docker consulta /salud/ dentro del contenedor.
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS") + ["127.0.0.1", "localhost"]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# SCRUM-35: IP real del cliente para el bloqueo de ingresos (nginx pone X-Real-IP = $remote_addr).
RUMBO_CONFIAR_X_REAL_IP = env.bool("RUMBO_CONFIAR_X_REAL_IP", default=True)
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_REDIRECT_EXEMPT = [r"^salud/$"]
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
