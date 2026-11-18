"""Comprueba que los modelos de Django (managed=False) coinciden con las tablas reales del
esquema rumbo: misma tabla, mismas columnas y nulabilidad compatible (SCRUM-21).

    python manage.py verificar_modelos

Correrlo después de cada migración SQL nueva (db/migraciones): si alguien agrega, quita o
renombra una columna y no actualiza leads/models.py, aquí falla en vez de fallar en producción.
"""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

ESQUEMA = "rumbo"


class Command(BaseCommand):
    help = "Verifica que leads/models.py coincide con las tablas del esquema rumbo."

    def handle(self, *args, **opciones):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name, is_nullable = 'YES' FROM information_schema.columns "
                "WHERE table_schema = %s",
                [ESQUEMA],
            )
            columnas = {}
            for tabla, columna, nula in cursor.fetchall():
                columnas.setdefault(tabla, {})[columna] = nula

        problemas = []
        modelos = [m for m in apps.get_app_config("leads").get_models()]
        for modelo in modelos:
            tabla = modelo._meta.db_table
            if modelo._meta.managed:
                problemas.append(f"{modelo.__name__}: debe ser managed = False")
            if tabla not in columnas:
                problemas.append(f"{modelo.__name__}: no existe la tabla {ESQUEMA}.{tabla}")
                continue
            reales = columnas[tabla]
            del_modelo = set()
            for campo in modelo._meta.concrete_fields:
                del_modelo.add(campo.column)
                if campo.column not in reales:
                    problemas.append(f"{modelo.__name__}.{campo.name}: no existe la columna {tabla}.{campo.column}")
                elif reales[campo.column] and not campo.null and not campo.primary_key:
                    problemas.append(f"{modelo.__name__}.{campo.name}: la columna admite NULL; poner null=True")
            for faltante in sorted(set(reales) - del_modelo):
                problemas.append(f"{modelo.__name__}: falta el campo para la columna {tabla}.{faltante}")

        if problemas:
            raise CommandError("Modelos desalineados con la base:\n  · " + "\n  · ".join(problemas))
        self.stdout.write(self.style.SUCCESS(
            f"✔ {len(modelos)} modelos coinciden con {ESQUEMA} (tablas, columnas y nulabilidad)."))
