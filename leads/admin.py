"""Admin de Django para revisar los datos (SCRUM-21). Solo lectura.

Las escrituras de negocio pasan por las funciones SQL (reparto, etapas, intentos, ventas);
el admin no las reemplaza. Lo que cada usuario ve lo decide RLS en la base: un usuario de
Django sin fila en rumbo.usuario no ve nada (ver "Usuarios" en el README).
"""
from django.contrib import admin

from . import models


class SoloLectura(admin.ModelAdmin):
    list_per_page = 50

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SoloLecturaInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class MensajeInline(SoloLecturaInline):
    model = models.MensajeWhatsapp
    fields = ["ocurrido_en", "direccion", "tipo", "cuerpo", "numero_whatsapp", "estado_entrega"]
    ordering = ["-ocurrido_en"]


class IntentoInline(SoloLecturaInline):
    model = models.IntentoLlamada
    fields = ["numero", "creado_en", "asesor", "resultado", "nota", "agendado_para"]


class AsignacionInline(SoloLecturaInline):
    model = models.Asignacion
    fk_name = "lead"
    fields = ["creado_en", "motivo", "asesor_anterior", "asesor", "asignado_por_usuario"]


class EtapaHistorialInline(SoloLecturaInline):
    model = models.LeadEtapaHistorial
    fields = ["creado_en", "desde", "hacia", "usuario"]


class NotaInline(SoloLecturaInline):
    model = models.NotaLead
    fields = ["creado_en", "autor_usuario", "texto"]


@admin.register(models.Lead)
class LeadAdmin(SoloLectura):
    list_display = ["telefono", "nombre_perfil", "etapa", "estado_asignacion", "asesor",
                    "intentos_asesor_actual", "primer_contacto_en", "ultimo_mensaje_en"]
    list_filter = ["estado_asignacion", "etapa", "asesor", "numero_whatsapp", "origen"]
    search_fields = ["telefono", "nombre_perfil"]
    date_hierarchy = "primer_contacto_en"
    list_select_related = ["etapa", "asesor__usuario"]
    inlines = [MensajeInline, AsignacionInline, IntentoInline, EtapaHistorialInline, NotaInline]


@admin.register(models.Asesor)
class AsesorAdmin(SoloLectura):
    list_display = ["usuario", "estado", "estado_desde", "numero_whatsapp", "codigo_callflow", "ultimo_lead_en"]
    list_filter = ["estado", "numero_whatsapp"]
    list_select_related = ["usuario", "numero_whatsapp"]


@admin.register(models.Usuario)
class UsuarioAdmin(SoloLectura):
    list_display = ["id", "nombre", "rol", "activo", "creado_en"]
    list_filter = ["rol", "activo"]


@admin.register(models.NumeroWhatsapp)
class NumeroWhatsappAdmin(SoloLectura):
    list_display = ["telefono", "meta_phone_number_id", "conectado_api", "activo"]


@admin.register(models.Asignacion)
class AsignacionAdmin(SoloLectura):
    list_display = ["creado_en", "lead", "motivo", "asesor_anterior", "asesor", "asignado_por_usuario"]
    list_filter = ["motivo", "asesor"]
    date_hierarchy = "creado_en"
    list_select_related = ["lead", "asesor__usuario", "asesor_anterior__usuario", "asignado_por_usuario"]


@admin.register(models.IntentoLlamada)
class IntentoLlamadaAdmin(SoloLectura):
    list_display = ["creado_en", "lead", "numero", "asesor", "resultado", "agendado_para"]
    list_filter = ["resultado", "asesor"]
    date_hierarchy = "creado_en"
    list_select_related = ["lead", "asesor__usuario", "resultado"]


@admin.register(models.MensajeWhatsapp)
class MensajeWhatsappAdmin(SoloLectura):
    list_display = ["ocurrido_en", "lead", "direccion", "tipo", "cuerpo", "numero_whatsapp"]
    list_filter = ["direccion", "tipo", "numero_whatsapp"]
    search_fields = ["wa_message_id", "lead__telefono"]
    date_hierarchy = "ocurrido_en"
    list_select_related = ["lead", "numero_whatsapp"]


@admin.register(models.Venta)
class VentaAdmin(SoloLectura):
    list_display = ["cerrada_en", "lead", "asesor", "tipo_visa", "pais", "valor", "moneda", "anulada_en"]
    list_filter = ["asesor", "tipo_visa", "moneda"]
    date_hierarchy = "cerrada_en"
    list_select_related = ["lead", "asesor__usuario"]


@admin.register(models.Etapa)
class EtapaAdmin(SoloLectura):
    list_display = ["orden", "codigo", "nombre", "es_final", "activo"]


@admin.register(models.ResultadoLlamada)
class ResultadoLlamadaAdmin(SoloLectura):
    list_display = ["codigo", "nombre", "cuenta_como_intento", "requiere_agenda", "requiere_venta",
                    "etapa_destino", "motivo_descarte", "activo"]


@admin.register(models.MotivoDescarte)
class MotivoDescarteAdmin(SoloLectura):
    list_display = ["codigo", "nombre", "activo"]


@admin.register(models.Configuracion)
class ConfiguracionAdmin(SoloLectura):
    list_display = ["clave", "valor", "descripcion", "actualizado_en"]
