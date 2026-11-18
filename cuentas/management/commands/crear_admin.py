"""Crea el PRIMER administrador de Rumbo (SCRUM-27).

    python manage.py crear_admin --usuario admin --nombre "Nombre Apellido"

Pide la contraseña dos veces (o la toma de RUMBO_ADMIN_PASSWORD, para scripts). Crea el usuario
de Django y su fila en rumbo.usuario con rol admin mediante rumbo.crear_primer_admin, que la
base solo acepta mientras no exista ningún admin activo. Los demás usuarios se crean desde la
pantalla Usuarios.
"""
import getpass
import os

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from core.db import como_sistema


class Command(BaseCommand):
    help = "Crea el primer administrador (solo si todavía no hay ninguno activo)."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True)
        parser.add_argument("--nombre", required=True)

    def handle(self, *args, usuario, nombre, **o):
        User = get_user_model()
        clave = os.environ.get("RUMBO_ADMIN_PASSWORD")
        if not clave:
            clave = getpass.getpass("Contraseña: ")
            if clave != getpass.getpass("Repetir contraseña: "):
                raise CommandError("Las contraseñas no coinciden.")
        try:
            password_validation.validate_password(clave, User(username=usuario))
        except ValidationError as e:
            raise CommandError(" ".join(e.messages)) from e

        try:
            with como_sistema() as cursor:
                user, creado = User.objects.get_or_create(username=usuario)
                user.set_password(clave)
                user.is_active = True
                user.save()
                cursor.execute("SELECT rumbo.crear_primer_admin(%s, %s)", [user.pk, nombre])
        except DatabaseError as e:
            causa = e.__cause__ or e
            raise CommandError(getattr(getattr(causa, "diag", None), "message_primary", None) or str(causa)) from e
        self.stdout.write(self.style.SUCCESS(
            f"✔ Administrador {usuario} (id {user.pk}) {'creado' if creado else 'actualizado'}. Ingrese en /cuentas/ingresar/"))
