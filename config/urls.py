from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("", core_views.inicio, name="inicio"),
    path("ayuda/", core_views.ayuda, name="ayuda"),
    path("salud/", core_views.salud, name="salud"),
    path("whatsapp/", include("whatsapp.urls")),
    path("leads/", include("leads.urls")),
    path("cuentas/", include("cuentas.urls")),
    path("admin/", admin.site.urls),
]
