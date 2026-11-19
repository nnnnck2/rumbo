"""Envía el reporte semanal por correo (SCRUM-121). Por defecto, la semana pasada (lunes a domingo)."""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from core import reporte


class Command(BaseCommand):
    help = "Envía el resumen semanal de Métricas a los destinatarios configurados."

    def add_arguments(self, parser):
        parser.add_argument("--desde", help="Primer día (AAAA-MM-DD); se envían 7 días.")
        parser.add_argument("--para", nargs="*", help="Correos (si no, los de Configuración).")

    def handle(self, *args, desde=None, para=None, **options):
        inicio = None
        if desde:
            try:
                inicio = dt.date.fromisoformat(desde)
            except ValueError as e:
                raise CommandError("Use --desde AAAA-MM-DD") from e
        self.stdout.write(reporte.enviar(inicio, None, para or None))
