from django.urls import path

from . import views

app_name = "leads"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("siguiente/", views.siguiente, name="siguiente"),
    path("tablero/", views.tablero, name="tablero"),
    path("campanas/", views.campanas, name="campanas"),
    path("reasignar/", views.reasignar_lote, name="reasignar_lote"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("alertas/", views.alertas, name="alertas"),
    path("metricas/", views.metricas, name="metricas"),
    path("metricas/exportar/", views.exportar_metricas, name="exportar_metricas"),
    path("exportar/", views.exportar_leads, name="exportar_leads"),
    path("en-vivo/", views.en_vivo, name="en_vivo"),
    path("alertas/contador/", views.alertas_contador, name="alertas_contador"),
    path("<int:pk>/", views.ficha, name="ficha"),
    path("<int:pk>/intento/", views.registrar_intento, name="registrar_intento"),
    path("<int:pk>/etapa/", views.cambiar_etapa, name="cambiar_etapa"),
    path("<int:pk>/agendar/", views.agendar, name="agendar"),
    path("<int:pk>/datos/", views.guardar_datos, name="guardar_datos"),
    path("<int:pk>/nota/", views.agregar_nota, name="agregar_nota"),
    path("<int:pk>/reasignar/", views.reasignar, name="reasignar"),
]
