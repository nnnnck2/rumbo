"""Acceso a la base de Rumbo.

La base decide qué ve cada quien con RLS a partir de `rumbo.usuario_id`, fijado por
transacción. Sin contexto no se ve nada (falla cerrada). Las escrituras de negocio se
hacen con las funciones SQL de db/migraciones/006, nunca con el ORM.
"""
from contextlib import contextmanager

from django.db import connection, transaction

USUARIO_SISTEMA = 0  # rumbo.usuario id 0, rol 'sistema' (workers y webhook)


def fijar_usuario(usuario_id):
    """Fija el usuario de la transacción actual. Debe llamarse dentro de un atomic()."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('rumbo.usuario_id', %s, true)", [str(int(usuario_id))])


@contextmanager
def como_sistema():
    """Transacción con el usuario 'sistema'. Devuelve un cursor listo para usar."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT set_config('rumbo.usuario_id', %s, true)", [str(USUARIO_SISTEMA)])
        yield cursor


def ejecutar_funcion_sistema(sql, params=None):
    """Ejecuta una función de negocio como 'sistema' y devuelve el primer valor."""
    with como_sistema() as cursor:
        cursor.execute(sql, params or [])
        fila = cursor.fetchone()
        return fila[0] if fila else None
