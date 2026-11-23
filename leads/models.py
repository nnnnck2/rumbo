"""Modelo de datos de Rumbo en Django (SCRUM-21).

Las tablas NO las crea Django: viven en el esquema `rumbo` y se definen con las migraciones
SQL de db/migraciones (integridad, RLS, auditoría y funciones de negocio en la base). Por eso
todos los modelos son `managed = False`: Django las lee, pero nunca hace migraciones sobre ellas.

Reglas para el resto del código:
  · Leer con el ORM está bien: la base filtra por RLS según `rumbo.usuario_id` (middleware).
  · Escribir asignación, etapa, intentos o ventas: SIEMPRE con las funciones SQL de 006
    (rumbo.registrar_intento, rumbo.cambiar_etapa, rumbo.reasignar_manual…), nunca con .save().
    La base rechaza la mayoría de esas escrituras directas (permisos por columna de 009).
  · Los enums de Postgres (rol, estado del asesor…) se leen como texto; las opciones de abajo
    deben coincidir con los CREATE TYPE de 003.
"""
from django.db import models


class Rol(models.TextChoices):
    ASESOR = "asesor", "Asesor"
    SUPERVISOR = "supervisor", "Supervisor"
    ADMIN = "admin", "Administrador"
    SISTEMA = "sistema", "Sistema"


class EstadoAsesor(models.TextChoices):
    DISPONIBLE = "disponible", "Disponible"
    OCUPADO = "ocupado", "Ocupado"
    PAUSA = "pausa", "En pausa"
    FUERA_TURNO = "fuera_turno", "Fuera de turno"


class EstadoAsignacion(models.TextChoices):
    EN_COLA = "en_cola", "En cola"
    ASIGNADO = "asignado", "Asignado"
    CERRADO = "cerrado", "Cerrado"


class MotivoAsignacion(models.TextChoices):
    REPARTO = "reparto", "Reparto (round robin)"
    REINTENTOS_AGOTADOS = "reintentos_agotados", "Reintentos agotados"
    SIN_PRIMERA_LLAMADA = "sin_primera_llamada", "Sin primera llamada a tiempo"
    ASESOR_INACTIVO = "asesor_inactivo", "Asesor inactivo"
    COLA_HORARIO = "cola_horario", "Cola de fuera de horario"
    MANUAL = "manual", "Reasignación manual"


class ModeloRumbo(models.Model):
    class Meta:
        abstract = True
        managed = False


# ─────────────────────────────── Catálogos (002) ───────────────────────────────

class Etapa(ModeloRumbo):
    codigo = models.TextField(primary_key=True)
    nombre = models.TextField()
    orden = models.SmallIntegerField(unique=True)
    es_final = models.BooleanField()
    activo = models.BooleanField()

    class Meta(ModeloRumbo.Meta):
        db_table = "etapa"
        ordering = ["orden"]
        verbose_name = "etapa"

    def __str__(self):
        return self.nombre


class MotivoDescarte(ModeloRumbo):
    codigo = models.TextField(primary_key=True)
    nombre = models.TextField()
    activo = models.BooleanField()

    class Meta(ModeloRumbo.Meta):
        db_table = "motivo_descarte"
        ordering = ["nombre"]
        verbose_name = "motivo de descarte"
        verbose_name_plural = "motivos de descarte"

    def __str__(self):
        return self.nombre


class ResultadoLlamada(ModeloRumbo):
    codigo = models.TextField(primary_key=True)
    nombre = models.TextField()
    cuenta_como_intento = models.BooleanField()
    requiere_agenda = models.BooleanField()
    requiere_venta = models.BooleanField()
    etapa_destino = models.ForeignKey(Etapa, models.DO_NOTHING, db_column="etapa_destino",
                                      null=True, related_name="+")
    motivo_descarte = models.ForeignKey(MotivoDescarte, models.DO_NOTHING, db_column="motivo_descarte_codigo",
                                        null=True, related_name="+")
    activo = models.BooleanField()

    class Meta(ModeloRumbo.Meta):
        db_table = "resultado_llamada"
        ordering = ["nombre"]
        verbose_name = "resultado de llamada"
        verbose_name_plural = "resultados de llamada"

    def __str__(self):
        return self.nombre


# ─────────────────────────────── Usuarios y asesores (003) ───────────────────────────────

class Usuario(ModeloRumbo):
    """Un registro por usuario de Django: id = auth_user.id (0 = sistema)."""
    id = models.BigIntegerField(primary_key=True)
    nombre = models.TextField()
    rol = models.CharField(max_length=20, choices=Rol.choices)
    activo = models.BooleanField()
    version = models.IntegerField()
    creado_en = models.DateTimeField()
    actualizado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "usuario"
        ordering = ["nombre"]
        verbose_name = "usuario"

    def __str__(self):
        return f"{self.nombre} ({self.get_rol_display()})"


class NumeroWhatsapp(ModeloRumbo):
    id = models.SmallAutoField(primary_key=True)
    telefono = models.TextField(unique=True)
    meta_phone_number_id = models.TextField(unique=True, null=True)
    conectado_api = models.BooleanField()
    activo = models.BooleanField()
    creado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "numero_whatsapp"
        ordering = ["id"]
        verbose_name = "número de WhatsApp"
        verbose_name_plural = "números de WhatsApp"

    def __str__(self):
        return self.telefono


class Asesor(ModeloRumbo):
    id = models.BigAutoField(primary_key=True)
    usuario = models.OneToOneField(Usuario, models.DO_NOTHING, related_name="asesor")
    numero_whatsapp = models.ForeignKey(NumeroWhatsapp, models.DO_NOTHING, null=True, related_name="asesores")
    codigo_callflow = models.TextField(unique=True, null=True)
    estado = models.CharField(max_length=20, choices=EstadoAsesor.choices)
    estado_desde = models.DateTimeField()
    ultimo_lead_en = models.DateTimeField(null=True)
    preferencias = models.JSONField()
    max_pendientes = models.SmallIntegerField(null=True)                         # 022 · SCRUM-54
    peso_reparto = models.DecimalField(max_digits=3, decimal_places=2)            # 022 · SCRUM-54
    reparto_pase = models.DecimalField(max_digits=14, decimal_places=4)           # 022 · lo maneja _repartir
    version = models.IntegerField()
    creado_en = models.DateTimeField()
    actualizado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "asesor"
        ordering = ["usuario__nombre"]
        verbose_name = "asesor"
        verbose_name_plural = "asesores"

    def __str__(self):
        return self.usuario.nombre


# ─────────────────────────────── Leads ───────────────────────────────

class Lead(ModeloRumbo):
    id = models.BigAutoField(primary_key=True)
    telefono = models.TextField(unique=True)        # E.164 (+593…), lo valida la base
    nombre_perfil = models.TextField(null=True)
    numero_whatsapp = models.ForeignKey(NumeroWhatsapp, models.DO_NOTHING, null=True, related_name="leads")
    origen = models.TextField()
    etapa = models.ForeignKey(Etapa, models.DO_NOTHING, db_column="etapa_codigo", related_name="leads")
    motivo_descarte = models.ForeignKey(MotivoDescarte, models.DO_NOTHING, db_column="motivo_descarte_codigo",
                                        null=True, related_name="leads")
    estado_asignacion = models.CharField(max_length=20, choices=EstadoAsignacion.choices)
    asesor = models.ForeignKey(Asesor, models.DO_NOTHING, null=True, related_name="leads")
    asignado_en = models.DateTimeField(null=True)
    intentos_asesor_actual = models.SmallIntegerField()
    intentos_totales = models.IntegerField()
    proxima_accion_en = models.DateTimeField(null=True)
    datos = models.JSONField()
    tipo_visa = models.TextField(null=True, editable=False)      # columna generada desde datos
    pais_interes = models.TextField(null=True, editable=False)   # columna generada desde datos
    consentimiento_en = models.DateTimeField(null=True)
    anonimizado_en = models.DateTimeField(null=True)
    primer_contacto_en = models.DateTimeField()
    ultimo_mensaje_en = models.DateTimeField(null=True)
    cerrado_en = models.DateTimeField(null=True)
    version = models.IntegerField()
    creado_en = models.DateTimeField()
    actualizado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "lead"
        ordering = ["-primer_contacto_en"]
        verbose_name = "lead"

    def __str__(self):
        return f"{self.nombre_perfil or 'Sin nombre'} · {self.telefono}"


class NotaLead(ModeloRumbo):
    id = models.BigAutoField(primary_key=True)
    lead = models.ForeignKey(Lead, models.DO_NOTHING, related_name="notas")
    autor_usuario = models.ForeignKey(Usuario, models.DO_NOTHING, related_name="+")
    texto = models.TextField()
    creado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "nota_lead"
        ordering = ["-creado_en"]
        verbose_name = "nota"


class LeadEtapaHistorial(ModeloRumbo):
    id = models.BigAutoField(primary_key=True)
    lead = models.ForeignKey(Lead, models.DO_NOTHING, related_name="historial_etapas")
    desde = models.ForeignKey(Etapa, models.DO_NOTHING, db_column="desde", null=True, related_name="+")
    hacia = models.ForeignKey(Etapa, models.DO_NOTHING, db_column="hacia", related_name="+")
    usuario = models.ForeignKey(Usuario, models.DO_NOTHING, null=True, related_name="+")
    creado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "lead_etapa_historial"
        ordering = ["creado_en"]
        verbose_name = "cambio de etapa"
        verbose_name_plural = "historial de etapas"


class Asignacion(ModeloRumbo):
    id = models.BigAutoField(primary_key=True)
    lead = models.ForeignKey(Lead, models.DO_NOTHING, related_name="asignaciones")
    asesor_anterior = models.ForeignKey(Asesor, models.DO_NOTHING, null=True, related_name="+")
    asesor = models.ForeignKey(Asesor, models.DO_NOTHING, related_name="asignaciones")
    motivo = models.CharField(max_length=30, choices=MotivoAsignacion.choices)
    asignado_por_usuario = models.ForeignKey(Usuario, models.DO_NOTHING, null=True, related_name="+")
    vuelta = models.SmallIntegerField(default=1)   # 015: sube cuando el lead ya pasó por todos los asesores
    creado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "asignacion"
        ordering = ["creado_en"]
        verbose_name = "asignación"
        verbose_name_plural = "asignaciones"


class IntentoLlamada(ModeloRumbo):
    id = models.BigAutoField(primary_key=True)
    lead = models.ForeignKey(Lead, models.DO_NOTHING, related_name="intentos")
    asesor = models.ForeignKey(Asesor, models.DO_NOTHING, related_name="intentos")
    numero = models.IntegerField()
    resultado = models.ForeignKey(ResultadoLlamada, models.DO_NOTHING, db_column="resultado_codigo",
                                  related_name="+")
    nota = models.TextField(null=True)
    agendado_para = models.DateTimeField(null=True)
    registrado_por_usuario = models.ForeignKey(Usuario, models.DO_NOTHING, related_name="+")
    creado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "intento_llamada"
        ordering = ["lead_id", "numero"]
        verbose_name = "intento de llamada"
        verbose_name_plural = "intentos de llamada"


# ─────────────────────────────── WhatsApp ───────────────────────────────

class MensajeWhatsapp(ModeloRumbo):
    id = models.BigAutoField(primary_key=True)
    lead = models.ForeignKey(Lead, models.DO_NOTHING, related_name="mensajes")
    numero_whatsapp = models.ForeignKey(NumeroWhatsapp, models.DO_NOTHING, related_name="mensajes")
    wa_message_id = models.TextField(unique=True)
    direccion = models.TextField()                   # entrante | saliente
    tipo = models.TextField()
    cuerpo = models.TextField(null=True)
    enviado_por_asesor = models.ForeignKey(Asesor, models.DO_NOTHING, null=True, related_name="+")
    estado_entrega = models.TextField(null=True)
    payload = models.JSONField()
    ocurrido_en = models.DateTimeField()
    creado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "mensaje_whatsapp"
        ordering = ["ocurrido_en"]
        verbose_name = "mensaje de WhatsApp"
        verbose_name_plural = "mensajes de WhatsApp"


# ─────────────────────────────── Ventas y configuración ───────────────────────────────

class Anuncio(ModeloRumbo):
    """Anuncio de Meta (Click-to-WhatsApp) del que llegaron leads (016). Se crea solo."""
    id = models.BigAutoField(primary_key=True)
    clave = models.TextField(unique=True)
    meta_source_id = models.TextField(null=True)
    tipo_origen = models.TextField()
    enlace = models.TextField(null=True)
    titulo = models.TextField(null=True)
    texto = models.TextField(null=True)
    tipo_medio = models.TextField(null=True)
    pais = models.TextField(null=True)                      # 017: país de la campaña
    nombre_campana = models.TextField(null=True)
    categorizado_en = models.DateTimeField(null=True)
    categorizado_por_usuario = models.ForeignKey(Usuario, models.DO_NOTHING, null=True, related_name="+")
    inversion = models.DecimalField(max_digits=12, decimal_places=2, null=True)   # 018: costo por lead / venta
    inversion_moneda = models.CharField(max_length=3, default="USD")
    primer_visto_en = models.DateTimeField()
    ultimo_visto_en = models.DateTimeField()
    creado_en = models.DateTimeField()
    actualizado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "anuncio"
        ordering = ["-ultimo_visto_en"]
        verbose_name = "anuncio"

    def __str__(self):
        return self.titulo or self.meta_source_id or self.clave


class LeadOrigen(ModeloRumbo):
    """Cada llegada de un lead desde un anuncio (016). La primera es el origen del lead."""
    id = models.BigAutoField(primary_key=True)
    lead = models.ForeignKey(Lead, models.DO_NOTHING, related_name="origenes")
    anuncio = models.ForeignKey(Anuncio, models.DO_NOTHING, related_name="llegadas")
    mensaje = models.OneToOneField("MensajeWhatsapp", models.DO_NOTHING, related_name="+")
    ctwa_clid = models.TextField(null=True)
    llegado_en = models.DateTimeField()
    creado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "lead_origen"
        ordering = ["llegado_en"]
        verbose_name = "origen del lead"
        verbose_name_plural = "orígenes de leads"


class Notificacion(ModeloRumbo):
    """Aviso para un usuario (017). Los crea la base en cada evento; la app solo los marca como leídos."""
    ICONOS = {
        "lead_nuevo": ("person-plus", "verde"), "lead_reasignado": ("arrow-left-right", "azul"),
        "lead_quitado": ("box-arrow-right", "gris"), "cliente_escribio": ("whatsapp", "verde"),
        "plazo_por_vencer": ("stopwatch", "amarillo"), "hora_de_llamar": ("telephone-forward", "azul"),
        "llamada_atrasada": ("alarm", "rojo"), "sin_gestionar_vuelta": ("arrow-repeat", "rojo"),
        "anuncio_sin_pais": ("megaphone", "morado"), "alerta_sistema": ("exclamation-octagon", "rojo"),   # 021
    }
    TIPOS = {
        "lead_nuevo": "Cliente nuevo", "lead_reasignado": "Cliente reasignado", "lead_quitado": "Cliente que pasó a otro",
        "cliente_escribio": "Mensaje de WhatsApp", "plazo_por_vencer": "Plazo por vencer", "hora_de_llamar": "Hora de llamar",
        "llamada_atrasada": "Llamada atrasada", "sin_gestionar_vuelta": "Sin gestionar", "anuncio_sin_pais": "Campañas",
        "alerta_sistema": "Alerta del sistema",
    }

    id = models.BigAutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, models.DO_NOTHING, related_name="notificaciones")
    tipo = models.TextField()
    titulo = models.TextField()
    mensaje = models.TextField(null=True)
    lead = models.ForeignKey(Lead, models.DO_NOTHING, null=True, related_name="+")
    url = models.TextField(null=True)
    clave = models.TextField(null=True)
    leida_en = models.DateTimeField(null=True)
    push_en = models.DateTimeField(null=True)          # 019: ya se envió por push (SCRUM-122)
    creado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "notificacion"
        ordering = ["-id"]
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"

    @property
    def icono(self):
        return self.ICONOS.get(self.tipo, ("bell", "gris"))[0]

    @property
    def tono(self):
        return self.ICONOS.get(self.tipo, ("bell", "gris"))[1]

    @property
    def tipo_nombre(self):
        return self.TIPOS.get(self.tipo, "Aviso")

    @property
    def leida(self):
        return self.leida_en is not None


class Venta(ModeloRumbo):
    id = models.BigAutoField(primary_key=True)
    lead = models.ForeignKey(Lead, models.DO_NOTHING, related_name="ventas")
    asesor = models.ForeignKey(Asesor, models.DO_NOTHING, related_name="ventas")
    tipo_visa = models.TextField()
    pais = models.TextField(null=True)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    moneda = models.CharField(max_length=3)
    cerrada_en = models.DateTimeField()
    registrada_por_usuario = models.ForeignKey(Usuario, models.DO_NOTHING, related_name="+")
    anulada_en = models.DateTimeField(null=True)
    motivo_anulacion = models.TextField(null=True)
    version = models.IntegerField()
    creado_en = models.DateTimeField()
    actualizado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "venta"
        ordering = ["-cerrada_en"]
        verbose_name = "venta"


class Configuracion(ModeloRumbo):
    clave = models.TextField(primary_key=True)
    valor = models.JSONField()
    descripcion = models.TextField(null=True)
    actualizado_por_usuario = models.ForeignKey(Usuario, models.DO_NOTHING, null=True, related_name="+")
    version = models.IntegerField()
    creado_en = models.DateTimeField()
    actualizado_en = models.DateTimeField()

    class Meta(ModeloRumbo.Meta):
        db_table = "configuracion"
        ordering = ["clave"]
        verbose_name = "configuración"
        verbose_name_plural = "configuración"

    def __str__(self):
        return self.clave
