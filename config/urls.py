from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("", core_views.inicio, name="inicio"),
    path("ayuda/", core_views.ayuda, name="ayuda"),
    path("notificaciones/", core_views.notificaciones, name="notificaciones"),
    path("notificaciones/contadores/", core_views.notificaciones_contadores, name="notificaciones_contadores"),
    path("notificaciones/panel/", core_views.notificaciones_panel, name="notificaciones_panel"),
    path("notificaciones/leidas/", core_views.notificaciones_leidas, name="notificaciones_leidas"),
    path("notificaciones/<int:pk>/abrir/", core_views.notificacion_abrir, name="notificacion_abrir"),
    path("salud/", core_views.salud, name="salud"),
    path("whatsapp/", include("whatsapp.urls")),
    path("leads/", include("leads.urls")),
    path("cuentas/", include("cuentas.urls")),
    path("admin/", admin.site.urls),
]
