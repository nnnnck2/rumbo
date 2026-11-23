"""SCRUM-57 · Genera un token para la API de CALLFLOW. Muestra el token (para CALLFLOW) y su SHA-256 (para .env)."""
import secrets

from django.core.management.base import BaseCommand

from core.api_callflow import hash_token


class Command(BaseCommand):
    help = "Genera un token para que CALLFLOW consulte la API de Rumbo."

    def handle(self, *args, **opciones):
        token = "rbcf_" + secrets.token_urlsafe(32)
        self.stdout.write("Token para CALLFLOW (guárdelo en su .env, NO en Rumbo; no se vuelve a mostrar):")
        self.stdout.write(f"  RUMBO_API_TOKEN={token}")
        self.stdout.write("En el .env de Rumbo (si ya hay otro, sepárelos con coma para rotar sin cortar):")
        self.stdout.write(f"  CALLFLOW_API_TOKENS_SHA256={hash_token(token)}")
