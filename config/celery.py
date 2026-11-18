"""Celery de Rumbo (SCRUM-17).

Worker:  celery -A config worker -l info
Beat:    celery -A config beat -l info
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("rumbo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
