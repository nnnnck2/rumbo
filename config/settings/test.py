"""Pruebas unitarias:  python manage.py test --settings=config.settings.test
No necesitan base ni Redis (son SimpleTestCase). La integración contra la base real se
prueba con `manage.py simular_mensaje_whatsapp`."""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "solo-para-pruebas-no-usar-en-produccion")
os.environ.setdefault("DB_PASSWORD", "sin-uso-en-pruebas")

from .base import *  # noqa: E402,F401,F403

DEBUG = False
WHATSAPP_APP_SECRET = "secreto-de-prueba"
WHATSAPP_VERIFY_TOKEN = "token-de-prueba"
CELERY_TASK_ALWAYS_EAGER = True
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
