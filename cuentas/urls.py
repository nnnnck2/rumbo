from django.urls import path

from . import views

app_name = "cuentas"

urlpatterns = [
    path("ingresar/", views.Ingresar.as_view(), name="login"),
    path("salir/", views.Salir.as_view(), name="logout"),
    path("mi-estado/", views.mi_estado, name="mi_estado"),
    path("asesores/", views.asesores, name="asesores"),
    path("usuarios/", views.usuarios, name="usuarios"),
    path("usuarios/nuevo/", views.usuario_nuevo, name="usuario_nuevo"),
    path("usuarios/<int:pk>/", views.usuario_editar, name="usuario_editar"),
    path("auditoria/", views.auditoria, name="auditoria"),
]
