"""Pruebas sin base: los modelos no deben generar DDL y el admin es de solo lectura."""
from django.apps import apps
from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase


class ModelosTests(SimpleTestCase):
    def test_todos_los_modelos_son_unmanaged(self):
        for modelo in apps.get_app_config("leads").get_models():
            with self.subTest(modelo=modelo.__name__):
                self.assertFalse(modelo._meta.managed, "las tablas las crean las migraciones SQL de db/")

    def test_admin_de_solo_lectura(self):
        peticion = RequestFactory().get("/")
        for modelo in apps.get_app_config("leads").get_models():
            modelo_admin = admin.site._registry.get(modelo)
            if modelo_admin is None:
                continue
            with self.subTest(modelo=modelo.__name__):
                self.assertFalse(modelo_admin.has_add_permission(peticion))
                self.assertFalse(modelo_admin.has_change_permission(peticion))
                self.assertFalse(modelo_admin.has_delete_permission(peticion))
