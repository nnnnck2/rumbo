from django.urls import path

from . import views

app_name = "leads"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("reasignar/", views.reasignar_lote, name="reasignar_lote"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("<int:pk>/", views.ficha, name="ficha"),
    path("<int:pk>/intento/", views.registrar_intento, name="registrar_intento"),
    path("<int:pk>/etapa/", views.cambiar_etapa, name="cambiar_etapa"),
    path("<int:pk>/reasignar/", views.reasignar, name="reasignar"),
]
