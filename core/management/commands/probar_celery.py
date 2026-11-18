from celery.exceptions import TimeoutError as CeleryTimeout
from django.core.management.base import BaseCommand, CommandError

from core.tasks import ping


class Command(BaseCommand):
    help = "Envía la tarea de prueba al worker de Celery y espera su resultado."

    def add_arguments(self, parser):
        parser.add_argument("--espera", type=int, default=20, help="Segundos máximos de espera.")

    def handle(self, *args, **opciones):
        resultado = ping.delay("prueba desde manage.py")
        self.stdout.write(f"Tarea enviada: {resultado.id}")
        try:
            valor = resultado.get(timeout=opciones["espera"])
        except CeleryTimeout as exc:
            raise CommandError("El worker no respondió a tiempo. ¿Está corriendo?") from exc
        self.stdout.write(self.style.SUCCESS(f"Resultado ({resultado.status}): {valor}"))
