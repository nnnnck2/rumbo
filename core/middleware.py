from django.db import transaction

from .db import fijar_usuario


class ContextoRumboMiddleware:
    """Envuelve cada request en una transacción y fija `rumbo.usuario_id` con el usuario
    autenticado, para que las políticas RLS de la base sepan quién consulta.

    No se usa ATOMIC_REQUESTS porque esa transacción empieza después de los middlewares:
    un set_config(..., true) hecho aquí se perdería. Usuarios anónimos no fijan contexto
    y la base no les devuelve nada.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with transaction.atomic():
            usuario = getattr(request, "user", None)
            if usuario is not None and usuario.is_authenticated:
                fijar_usuario(usuario.pk)
            return self.get_response(request)
