"""Formularios de las acciones sobre el lead y de la configuración (SCRUM-30 a 33).

Validan lo que conviene avisar antes de ir a la base (campos obligatorios según el resultado,
fechas en el pasado…). La base vuelve a validar todo: estas reglas son comodidad, no seguridad.
"""
import re
from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import Asesor, MotivoDescarte, ResultadoLlamada

DIAS = [(1, "Lun"), (2, "Mar"), (3, "Mié"), (4, "Jue"), (5, "Vie"), (6, "Sáb"), (7, "Dom")]


class Bootstrap:
    """Agrega las clases de Bootstrap a cada widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            w = campo.widget
            if isinstance(w, (forms.RadioSelect, forms.CheckboxSelectMultiple, forms.HiddenInput)):
                continue
            clase = "form-select" if isinstance(w, forms.Select) else "form-control"
            w.attrs["class"] = (w.attrs.get("class", "") + " " + clase).strip()


class FechaHoraLocal(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M", **kwargs)


# ─────────────────────────────── RF-22 · Resultado de la llamada ───────────────────────────────

class IntentoForm(Bootstrap, forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    resultado = forms.ChoiceField(widget=forms.RadioSelect)
    nota = forms.CharField(required=False, max_length=2000,
                           widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Nota (opcional)"}))
    agendar_para = forms.DateTimeField(required=False, label="Llamar el",
                                       input_formats=["%Y-%m-%dT%H:%M"], widget=FechaHoraLocal())
    # Venta cerrada (base de comisiones en CALLFLOW)
    tipo_visa = forms.CharField(required=False, max_length=80, label="Tipo de visa")
    pais = forms.CharField(required=False, max_length=80, label="País")
    valor = forms.DecimalField(required=False, min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    moneda = forms.CharField(required=False, max_length=3, initial="USD")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resultados = {r.codigo: r for r in ResultadoLlamada.objects.filter(activo=True).order_by("nombre")}
        self.fields["resultado"].choices = [(c, r.nombre) for c, r in self.resultados.items()]

    # SCRUM-77 · Botones de un toque: orden, color e icono de cada resultado.
    ESTILO = {
        "interesado": (1, "contacto", "hand-thumbs-up"),
        "llamar_despues": (2, "agenda", "clock-history"),
        "no_contesta": (3, "sin-contacto", "telephone-x"),
        "venta_cerrada": (4, "venta", "trophy"),
        "no_interesado": (5, "descarte", "hand-thumbs-down"),
        "numero_invalido": (6, "descarte", "slash-circle"),
    }

    @property
    def opciones(self):
        filas = []
        for codigo, r in self.resultados.items():
            orden, tono, icono = self.ESTILO.get(codigo, (9, "sin-contacto", "telephone"))
            tipo = "agenda" if r.requiere_agenda else "venta" if r.requiere_venta else "directo"
            confirmar = (f"«{r.nombre}» descarta al cliente. ¿Confirmar?"
                         if tipo == "directo" and r.etapa_destino_id == "descartado" else "")
            filas.append({"codigo": codigo, "nombre": r.nombre, "tono": tono, "icono": icono,
                          "tipo": tipo, "confirmar": confirmar, "orden": orden})
        return sorted(filas, key=lambda f: f["orden"])

    @property
    def elegido(self):
        """Resultado con datos extra (agenda o venta) ya elegido al volver con errores."""
        if not self.is_bound:
            return ""
        codigo = self.data.get("resultado", "")
        r = self.resultados.get(codigo)
        return codigo if r and (r.requiere_agenda or r.requiere_venta) else ""

    @property
    def codigos_agenda(self):
        return ",".join(c for c, r in self.resultados.items() if r.requiere_agenda)

    @property
    def codigos_venta(self):
        return ",".join(c for c, r in self.resultados.items() if r.requiere_venta)

    def clean(self):
        datos = super().clean()
        res = self.resultados.get(datos.get("resultado"))
        if res is None:
            return datos
        if res.requiere_agenda:
            cuando = datos.get("agendar_para")
            if not cuando:
                self.add_error("agendar_para", "Indique cuándo volver a llamar.")
            elif cuando <= timezone.now():
                self.add_error("agendar_para", "La fecha debe ser futura.")
        else:
            datos["agendar_para"] = None
        if res.requiere_venta:
            for campo in ("tipo_visa", "valor"):
                if not datos.get(campo):
                    self.add_error(campo, "Obligatorio para registrar la venta.")
            moneda = (datos.get("moneda") or "USD").upper()
            if len(moneda) != 3 or not moneda.isalpha():
                self.add_error("moneda", "Código de 3 letras (USD).")
            datos["moneda"] = moneda
        return datos

    def venta(self):
        d = self.cleaned_data
        if not self.resultados[d["resultado"]].requiere_venta:
            return None
        return {"tipo_visa": d["tipo_visa"].strip(), "valor": str(d["valor"]),
                "moneda": d["moneda"], "pais": (d.get("pais") or "").strip()}


# ─────────────────────────────── RF-25 · Cambio de etapa ───────────────────────────────

class EtapaForm(Bootstrap, forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    etapa = forms.ChoiceField(label="Pasar a")
    motivo_descarte = forms.ModelChoiceField(MotivoDescarte.objects.filter(activo=True), required=False,
                                             label="Motivo", empty_label="—")

    def __init__(self, *args, etapas=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["etapa"].choices = list(etapas)

    def clean(self):
        datos = super().clean()
        if datos.get("etapa") == "descartado" and not datos.get("motivo_descarte"):
            self.add_error("motivo_descarte", "Para descartar hay que indicar el motivo.")
        return datos


# ─────────────────────────────── RF-24 · Agendar llamada ───────────────────────────────

class AgendarForm(Bootstrap, forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    cuando = forms.DateTimeField(label="Llamar el", input_formats=["%Y-%m-%dT%H:%M"], widget=FechaHoraLocal())

    def clean_cuando(self):
        cuando = self.cleaned_data["cuando"]
        if cuando <= timezone.now():
            raise forms.ValidationError("La fecha debe ser futura.")
        return cuando


# ─────────────────────────────── RF-26 · Datos del caso y notas ───────────────────────────────

# Sugerencias para escribir rápido. Se puede poner cualquier otro valor (pendiente: lista del área).
TIPOS_VISA = ["Turismo", "Estudiante", "Trabajo", "Negocios", "Residencia", "Reunificación familiar", "Tránsito"]
PAISES = ["Estados Unidos", "Canadá", "España", "Reino Unido", "México", "Schengen (Europa)", "Australia"]


class DatosLeadForm(Bootstrap, forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    tipo_visa = forms.CharField(required=False, max_length=80, label="Tipo de visa",
                                widget=forms.TextInput(attrs={"list": "tipos-visa", "autocomplete": "off"}))
    pais_interes = forms.CharField(required=False, max_length=80, label="País de interés",
                                   widget=forms.TextInput(attrs={"list": "paises", "autocomplete": "off"}))
    cita_en = forms.DateTimeField(required=False, label="Fecha de la cita", input_formats=["%Y-%m-%dT%H:%M"],
                                  widget=FechaHoraLocal(),
                                  help_text="Al guardarla, el cliente recibe un recordatorio 24 h y 2 h antes.")

    def clean(self):
        datos = super().clean()
        for campo in ("tipo_visa", "pais_interes"):
            datos[campo] = " ".join((datos.get(campo) or "").split())   # sin espacios de más
        return datos


class NotaForm(Bootstrap, forms.Form):
    texto = forms.CharField(max_length=4000, label="Nueva nota",
                            widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Solo la ve el equipo (no el cliente)"}))

    def clean_texto(self):
        texto = self.cleaned_data["texto"].strip()
        if not texto:
            raise forms.ValidationError("Escriba la nota.")
        return texto


# ─────────────────────────────── RF-16 · Reasignación ───────────────────────────────

def asesores_activos():
    return Asesor.objects.filter(usuario__activo=True).select_related("usuario").order_by("usuario__nombre")


class ReasignarForm(Bootstrap, forms.Form):
    asesor = forms.ModelChoiceField(asesores_activos(), label="Reasignar a", empty_label="Elegir asesor…")

    def __init__(self, *args, excluir=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = asesores_activos()
        if excluir:
            qs = qs.exclude(pk=excluir)
        self.fields["asesor"].queryset = qs
        self.fields["asesor"].label_from_instance = lambda a: f"{a.usuario.nombre} · {a.get_estado_display()}"


class ReasignarLoteForm(ReasignarForm):
    leads = forms.TypedMultipleChoiceField(coerce=int, error_messages={"required": "Seleccione al menos un lead."})

    def __init__(self, *args, lead_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["leads"].choices = [(i, i) for i in lead_ids]


# ─────────────────────────────── RF-31 · Configuración ───────────────────────────────

class ConfiguracionForm(Bootstrap, forms.Form):
    # Horario de atención (turno): fuera de él los leads quedan en cola
    hora_inicio = forms.TimeField(label="Abre", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    hora_fin = forms.TimeField(label="Cierra", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    dias = forms.TypedMultipleChoiceField(choices=DIAS, coerce=int, label="Días de atención",
                                          widget=forms.CheckboxSelectMultiple)
    # Reparto y reintentos
    max_intentos_por_asesor = forms.IntegerField(min_value=1, max_value=10, label="Intentos por asesor",
                                                 help_text="Sin contacto tras estos intentos, el lead pasa al siguiente asesor.")
    minutos_primera_llamada = forms.IntegerField(min_value=1, max_value=240, label="Minutos para gestionar un lead nuevo",
                                                 help_text="Si el asesor no registra ninguna llamada en este tiempo (de turno), "
                                                           "el lead pasa al siguiente asesor. Recorre a todos y vuelve al primero.")
    minutos_entre_reintentos = forms.IntegerField(min_value=1, max_value=1440, label="Minutos entre reintentos")
    minutos_alerta_supervisor = forms.IntegerField(min_value=1, max_value=480, label="Alertar al supervisor tras",
                                                   help_text="Minutos de atraso de una llamada pendiente.")
    max_intentos_por_lead = forms.IntegerField(min_value=1, max_value=30, label="Tope de intentos por cliente",
                                               help_text="Intentos sin contacto sumando todos los asesores. Al llegar, "
                                                         "el cliente se descarta solo (se reabre si vuelve a escribir).")
    # SCRUM-53 · Leads registrados a mano
    lead_manual_asignar = forms.BooleanField(
        required=False, label="El cliente que registra un asesor queda asignado a ese asesor",
        help_text="Desmarcado: entra al reparto como un lead de WhatsApp. Lo que registra un supervisor siempre entra al reparto.")
    # SCRUM-88 · WhatsApp cuando el cliente no contesta
    aviso_activo = forms.BooleanField(required=False, label="Enviar WhatsApp cuando el cliente no contesta")
    aviso_texto = forms.CharField(max_length=1024, label="Texto del aviso",
                                  widget=forms.Textarea(attrs={"rows": 3}),
                                  help_text="{nombre} = primer nombre del cliente · {asesor} = quien llamó. "
                                            "Se envía si el cliente escribió en las últimas 24 h.")
    aviso_plantilla = forms.CharField(max_length=512, required=False, label="Plantilla de Meta (más de 24 h)",
                                      help_text="Nombre exacto de una plantilla aprobada en Meta. Vacío: pasadas las "
                                                "24 h no se envía nada (Meta no permite texto libre).")
    aviso_idioma = forms.CharField(max_length=5, initial="es", label="Idioma de la plantilla")
    aviso_horas = forms.IntegerField(min_value=1, max_value=168, label="Como máximo un aviso cada (horas)")
    # SCRUM-115 · Preguntas automáticas
    bot_activo = forms.BooleanField(required=False, label="Hacer preguntas automáticas antes de la llamada",
                                    help_text="Tras la respuesta automática: tipo de visa y país (listas de WhatsApp).")
    bot_texto_visa = forms.CharField(max_length=1024, required=False, label="Pregunta del tipo de visa")
    bot_texto_pais = forms.CharField(max_length=1024, required=False, label="Pregunta del país")
    bot_texto_gracias = forms.CharField(max_length=1024, required=False, label="Mensaje final")
    # SCRUM-116 · Recordatorio de cita
    rec_activo = forms.BooleanField(required=False, label="Recordar la cita al cliente (24 h y 2 h antes)")
    rec_texto = forms.CharField(max_length=1024, required=False, label="Texto del recordatorio",
                                widget=forms.Textarea(attrs={"rows": 2}),
                                help_text="{nombre} = cliente · {cita} = día y hora. Se usa si el cliente escribió en las últimas 24 h.")
    rec_plantilla = forms.CharField(max_length=512, required=False, label="Plantilla de Meta (más de 24 h)",
                                    help_text="Con dos variables: {{1}} nombre y {{2}} fecha de la cita.")
    rec_idioma = forms.CharField(max_length=5, required=False, initial="es", label="Idioma de la plantilla")
    # SCRUM-55 · Plantillas de seguimiento (aprobadas por Meta; cada envío fuera de 24 h tiene costo)
    pl_activo = forms.BooleanField(required=False, label="Permitir a los asesores enviar plantillas de seguimiento",
                                   help_text="Actívelo solo después de confirmar las tarifas de Meta: cada plantilla enviada "
                                             "fuera de la ventana de 24 h se cobra.")
    # SCRUM-121 · Reporte semanal · SCRUM-130 · Comisión estimada
    reporte_destinatarios = forms.CharField(max_length=2000, required=False, label="Enviar el reporte de los lunes a",
                                            widget=forms.Textarea(attrs={"rows": 2, "placeholder": "gerencia@multivisa.ec, …"}),
                                            help_text="Correos separados por coma. Vacío = no se envía.")
    comision_tipo = forms.ChoiceField(choices=[("porcentaje", "Porcentaje de lo vendido"), ("fijo", "Monto fijo por venta")],
                                      required=False, label="Regla de la comisión estimada")
    comision_valor = forms.DecimalField(min_value=0, max_value=100000, decimal_places=2, required=False,
                                        label="Valor", help_text="Solo para mostrar una estimación: la oficial la calcula CALLFLOW.")
    # SCRUM-97 · Meta del día de cada asesor (0 = no se mide)
    meta_llamadas = forms.IntegerField(min_value=0, max_value=1000, label="Llamadas")
    meta_citas = forms.IntegerField(min_value=0, max_value=1000, label="Citas")
    meta_ventas = forms.IntegerField(min_value=0, max_value=1000, label="Ventas")
    # Textos automáticos de WhatsApp
    texto_bienvenida = forms.CharField(max_length=1024, label="Respuesta al primer mensaje",
                                       widget=forms.Textarea(attrs={"rows": 2}))
    texto_fuera_horario = forms.CharField(max_length=1024, label="Respuesta fuera de horario",
                                          widget=forms.Textarea(attrs={"rows": 3}))
    texto_privacidad = forms.CharField(max_length=1024, required=False, label="Aviso de privacidad (LOPDP)",
                                       widget=forms.Textarea(attrs={"rows": 3}),
                                       help_text="Pendiente de validar con el área (SCRUM-23).")

    ZONA = "America/Guayaquil"
    # SCRUM-96 · Un guion de llamada por tipo de visa (más el general). SCRUM-117 · Lo mismo para documentos.
    TIPOS_GUION = ["General", *TIPOS_VISA]
    RESPUESTAS = 4             # SCRUM-114 · espacios para respuestas rápidas
    PLANTILLAS = 3             # SCRUM-55 · espacios para plantillas de seguimiento
    VARIABLES_PLANTILLA = [("nombre", "Nombre"), ("asesor", "Asesor"), ("documentos", "Documentos que faltan"),
                           ("cita", "Fecha de la cita")]
    # SCRUM-111 · Campos de cada pestaña (para abrir la que tiene errores).
    PESTANAS = {
        "horario": ["hora_inicio", "hora_fin", "dias"],
        "reparto": ["max_intentos_por_asesor", "minutos_primera_llamada", "minutos_entre_reintentos",
                    "minutos_alerta_supervisor", "max_intentos_por_lead", "lead_manual_asignar"],
        "whatsapp": ["texto_bienvenida", "texto_fuera_horario", "texto_privacidad", "aviso_activo", "aviso_texto",
                     "aviso_plantilla", "aviso_idioma", "aviso_horas", "bot_activo", "bot_texto_visa", "bot_texto_pais",
                     "bot_texto_gracias", "rec_activo", "rec_texto", "rec_plantilla", "rec_idioma",
                     *[f"rr_{c}_{i}" for i in range(4) for c in ("titulo", "texto")],
                     "pl_activo", *[f"pl_{c}_{i}" for i in range(3) for c in ("nombre", "titulo", "idioma", "variables")]],
        "metas": ["meta_llamadas", "meta_citas", "meta_ventas", "comision_tipo", "comision_valor"],
        "guiones": [f"guion_{i}" for i in range(len(TIPOS_GUION))] + [f"doc_{i}" for i in range(len(TIPOS_GUION))],
        "reportes": ["reporte_destinatarios"],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["aviso_activo"].widget.attrs["class"] = "form-check-input"
        for i, tipo in enumerate(self.TIPOS_GUION):
            self.fields[f"guion_{i}"] = forms.CharField(
                max_length=4000, required=False, label=tipo,
                widget=forms.Textarea(attrs={"rows": 4, "class": "form-control",
                                             "placeholder": "Un paso por línea" if i else "Se usa si el cliente no tiene "
                                                            "tipo de visa o su tipo no tiene guion propio."}))

        for i, tipo in enumerate(self.TIPOS_GUION):
            self.fields[f"doc_{i}"] = forms.CharField(
                max_length=4000, required=False, label=tipo,
                widget=forms.Textarea(attrs={"rows": 4, "class": "form-control", "placeholder": "Un documento por línea"}))
        for i in range(self.RESPUESTAS):
            self.fields[f"rr_titulo_{i}"] = forms.CharField(max_length=80, required=False, label="Título",
                                                            widget=forms.TextInput(attrs={"class": "form-control"}))
            self.fields[f"rr_texto_{i}"] = forms.CharField(
                max_length=1000, required=False, label="Mensaje",
                widget=forms.Textarea(attrs={"rows": 2, "class": "form-control",
                                             "placeholder": "{nombre}, {asesor}, {documentos} y {cita} se completan solos"}))
        for i in range(self.PLANTILLAS):                                                  # SCRUM-55
            self.fields[f"pl_nombre_{i}"] = forms.RegexField(
                regex=r"^[a-z0-9_]*$", max_length=512, required=False, label="Nombre en Meta",
                error_messages={"invalid": "Solo minúsculas, números y _ (como en el Administrador de WhatsApp)."},
                widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "lista_documentos"}))
            self.fields[f"pl_titulo_{i}"] = forms.CharField(max_length=80, required=False, label="Botón en la ficha",
                                                            widget=forms.TextInput(attrs={"class": "form-control"}))
            self.fields[f"pl_idioma_{i}"] = forms.RegexField(regex=r"^[a-z]{2}(_[A-Z]{2})?$", max_length=5, required=False,
                                                             initial="es", label="Idioma",
                                                             widget=forms.TextInput(attrs={"class": "form-control"}))
            self.fields[f"pl_variables_{i}"] = forms.MultipleChoiceField(
                choices=self.VARIABLES_PLANTILLA, required=False, label="Variables {{1}}, {{2}}… en este orden",
                widget=forms.CheckboxSelectMultiple)
        for campo in ("bot_activo", "rec_activo", "lead_manual_asignar", "pl_activo"):
            self.fields[campo].widget.attrs["class"] = "form-check-input"

    @property
    def campos_guion(self):
        return [self[f"guion_{i}"] for i in range(len(self.TIPOS_GUION))]

    @property
    def campos_documentos(self):
        return [self[f"doc_{i}"] for i in range(len(self.TIPOS_GUION))]

    @property
    def plantillas_seguimiento(self):
        return [(self[f"pl_nombre_{i}"], self[f"pl_titulo_{i}"], self[f"pl_idioma_{i}"], self[f"pl_variables_{i}"])
                for i in range(self.PLANTILLAS)]

    @property
    def respuestas_rapidas(self):
        return [(self[f"rr_titulo_{i}"], self[f"rr_texto_{i}"]) for i in range(self.RESPUESTAS)]

    @classmethod
    def desde_configuracion(cls, config):
        horario = config.get("horario") or {}
        inicial = {
            "hora_inicio": horario.get("inicio", "09:00")[:5],
            "hora_fin": horario.get("fin", "18:00")[:5],
            "dias": horario.get("dias", [1, 2, 3, 4, 5]),
        }
        for clave in ("max_intentos_por_asesor", "minutos_primera_llamada", "minutos_entre_reintentos",
                      "minutos_alerta_supervisor", "texto_bienvenida", "texto_fuera_horario", "texto_privacidad",
                      "max_intentos_por_lead"):
            if clave in config:
                inicial[clave] = config[clave]
        inicial.setdefault("max_intentos_por_lead", 9)
        inicial["lead_manual_asignar"] = (config.get("lead_manual") or {}).get("asignar_a_quien_registra", True)
        aviso = config.get("aviso_no_contesta") or {}
        inicial.update({"aviso_activo": aviso.get("activo", True), "aviso_texto": aviso.get("texto", ""),
                        "aviso_plantilla": aviso.get("plantilla", ""), "aviso_idioma": aviso.get("idioma", "es"),
                        "aviso_horas": aviso.get("horas_entre", 24)})
        metas = config.get("metas_diarias") or {}
        inicial.update({"meta_llamadas": metas.get("llamadas", 20), "meta_citas": metas.get("citas", 3),
                        "meta_ventas": metas.get("ventas", 1)})
        guiones = {k.lower(): v for k, v in (config.get("guiones_llamada") or {}).items()}
        documentos = {k.lower(): v for k, v in (config.get("documentos_por_visa") or {}).items()}
        for i, tipo in enumerate(cls.TIPOS_GUION):
            inicial[f"guion_{i}"] = guiones.get(tipo.lower(), "")
            inicial[f"doc_{i}"] = documentos.get(tipo.lower(), "")
        for i, (titulo, texto) in enumerate(list((config.get("respuestas_rapidas") or {}).items())[:cls.RESPUESTAS]):
            inicial[f"rr_titulo_{i}"], inicial[f"rr_texto_{i}"] = titulo, texto
        bot = config.get("bot_preguntas") or {}
        inicial.update({"bot_activo": bot.get("activo", False), "bot_texto_visa": bot.get("texto_visa", ""),
                        "bot_texto_pais": bot.get("texto_pais", ""), "bot_texto_gracias": bot.get("texto_gracias", "")})
        rec = config.get("recordatorio_cita") or {}
        inicial.update({"rec_activo": rec.get("activo", True), "rec_texto": rec.get("texto", ""),
                        "rec_plantilla": rec.get("plantilla", ""), "rec_idioma": rec.get("idioma", "es")})
        pl = config.get("plantillas_seguimiento") or {}
        inicial["pl_activo"] = bool(pl.get("activo"))
        for i, p in enumerate((pl.get("plantillas") or [])[:cls.PLANTILLAS]):
            inicial.update({f"pl_nombre_{i}": p.get("nombre", ""), f"pl_titulo_{i}": p.get("titulo", ""),
                            f"pl_idioma_{i}": p.get("idioma", "es"), f"pl_variables_{i}": p.get("variables", [])})
        inicial["reporte_destinatarios"] = ", ".join((config.get("reporte_semanal") or {}).get("destinatarios", []))
        comision = config.get("comision") or {}
        inicial.update({"comision_tipo": comision.get("tipo", "porcentaje"), "comision_valor": comision.get("valor", 5)})
        return inicial

    def clean_rec_plantilla(self):
        valor = (self.cleaned_data.get("rec_plantilla") or "").strip()
        if valor and not re.fullmatch(r"[a-z0-9_]+", valor):
            raise forms.ValidationError("El nombre de la plantilla en Meta solo tiene minúsculas, números y _.")
        return valor

    def clean_reporte_destinatarios(self):
        from django.core.validators import validate_email

        correos = [c.strip() for c in re.split(r"[,;\s]+", self.cleaned_data.get("reporte_destinatarios") or "") if c.strip()]
        for c in correos:
            try:
                validate_email(c)
            except forms.ValidationError as e:
                raise forms.ValidationError(f"Correo inválido: {c}") from e
        if len(correos) > 20:
            raise forms.ValidationError("Como máximo 20 correos.")
        return correos

    def clean_aviso_plantilla(self):
        valor = (self.cleaned_data.get("aviso_plantilla") or "").strip()
        if valor and not re.fullmatch(r"[a-z0-9_]+", valor):
            raise forms.ValidationError("El nombre de la plantilla en Meta solo tiene minúsculas, números y _.")
        return valor

    def clean_aviso_idioma(self):
        valor = (self.cleaned_data.get("aviso_idioma") or "es").strip()
        if not re.fullmatch(r"[a-z]{2}(_[A-Z]{2})?", valor):
            raise forms.ValidationError("Código de idioma como es o es_EC.")
        return valor

    def clean(self):
        datos = super().clean()
        for i in range(self.PLANTILLAS):                                    # SCRUM-55: nombre y botón van juntos
            if bool((datos.get(f"pl_nombre_{i}") or "").strip()) != bool((datos.get(f"pl_titulo_{i}") or "").strip()):
                self.add_error(f"pl_titulo_{i}", "Complete el nombre en Meta y el texto del botón (o deje los dos vacíos).")
        inicio, fin = datos.get("hora_inicio"), datos.get("hora_fin")
        if inicio and fin and inicio >= fin:
            self.add_error("hora_fin", "Debe ser después de la hora de apertura.")
        return datos

    def cambios(self, zona_actual=None):
        d = self.cleaned_data
        cambios = {
            "horario": {"inicio": d["hora_inicio"].strftime("%H:%M"), "fin": d["hora_fin"].strftime("%H:%M"),
                        "dias": sorted(d["dias"]), "zona": zona_actual or self.ZONA},
            "max_intentos_por_asesor": d["max_intentos_por_asesor"],
            "minutos_primera_llamada": d["minutos_primera_llamada"],
            "minutos_entre_reintentos": d["minutos_entre_reintentos"],
            "minutos_alerta_supervisor": d["minutos_alerta_supervisor"],
            "texto_bienvenida": d["texto_bienvenida"].strip(),
            "texto_fuera_horario": d["texto_fuera_horario"].strip(),
        }
        if d.get("texto_privacidad", "").strip():
            cambios["texto_privacidad"] = d["texto_privacidad"].strip()
        cambios["max_intentos_por_lead"] = d["max_intentos_por_lead"]
        cambios["lead_manual"] = {"asignar_a_quien_registra": bool(d.get("lead_manual_asignar"))}
        cambios["aviso_no_contesta"] = {"activo": bool(d.get("aviso_activo")), "texto": d["aviso_texto"].strip(),
                                        "plantilla": d.get("aviso_plantilla", ""), "idioma": d["aviso_idioma"],
                                        "horas_entre": d["aviso_horas"]}
        cambios["metas_diarias"] = {"llamadas": d["meta_llamadas"], "citas": d["meta_citas"], "ventas": d["meta_ventas"]}
        cambios["guiones_llamada"] = {tipo: d[f"guion_{i}"].strip() for i, tipo in enumerate(self.TIPOS_GUION)
                                      if (d.get(f"guion_{i}") or "").strip()}
        cambios["documentos_por_visa"] = {tipo: d[f"doc_{i}"].strip() for i, tipo in enumerate(self.TIPOS_GUION)
                                          if (d.get(f"doc_{i}") or "").strip()}
        cambios["respuestas_rapidas"] = {d[f"rr_titulo_{i}"].strip(): d[f"rr_texto_{i}"].strip()
                                         for i in range(self.RESPUESTAS)
                                         if (d.get(f"rr_titulo_{i}") or "").strip() and (d.get(f"rr_texto_{i}") or "").strip()}
        cambios["bot_preguntas"] = {
            "activo": bool(d.get("bot_activo")),
            "texto_visa": (d.get("bot_texto_visa") or "").strip() or "¿Qué tipo de visa necesitas?",
            "texto_pais": (d.get("bot_texto_pais") or "").strip() or "¿A qué país quieres viajar?",
            "texto_gracias": (d.get("bot_texto_gracias") or "").strip() or "¡Gracias! Un asesor te llamará pronto."}
        cambios["recordatorio_cita"] = {
            "activo": bool(d.get("rec_activo")),
            "texto": (d.get("rec_texto") or "").strip() or "Hola {nombre}, te recordamos tu cita con Multivisa el {cita}.",
            "plantilla": d.get("rec_plantilla") or "", "idioma": (d.get("rec_idioma") or "es").strip() or "es"}
        cambios["reporte_semanal"] = {"destinatarios": d.get("reporte_destinatarios") or []}
        orden = [v for v, _ in self.VARIABLES_PLANTILLA]
        cambios["plantillas_seguimiento"] = {"activo": bool(d.get("pl_activo")), "plantillas": [
            {"nombre": d[f"pl_nombre_{i}"].strip(), "titulo": d[f"pl_titulo_{i}"].strip(),
             "idioma": (d.get(f"pl_idioma_{i}") or "es").strip() or "es",
             "variables": sorted(d.get(f"pl_variables_{i}") or [], key=orden.index)}
            for i in range(self.PLANTILLAS) if (d.get(f"pl_nombre_{i}") or "").strip()]}
        if d.get("comision_tipo"):
            cambios["comision"] = {"tipo": d["comision_tipo"], "valor": float(d.get("comision_valor") or 0)}
        return cambios


# ─────────────────────────────── SCRUM-53 · Registro manual de leads (RF-07) ───────────────────────────────

CANALES_MANUALES = [("llamada", "Llamada entrante"), ("referido", "Referido"), ("visita", "Visita a la oficina"),
                    ("otro", "Otro canal")]
ORIGENES = {"whatsapp": "WhatsApp", "manual": "Registro manual", **dict(CANALES_MANUALES)}


def normalizar_telefono(texto):
    """Número escrito como lo dicta el cliente → E.164. Ecuador por defecto:
    0991234567 → +593991234567 · 593991234567 → +593991234567 · +1 305 555 0100 → +13055550100."""
    texto = (texto or "").strip()
    digitos = re.sub(r"\D", "", texto)
    if texto.startswith("+"):
        numero = "+" + digitos
    elif texto.startswith("00"):
        numero = "+" + digitos[2:]
    elif digitos.startswith("593"):
        numero = "+" + digitos
    elif digitos.startswith("0") and len(digitos) in (9, 10):          # celular (10) o fijo con código de área (9)
        numero = "+593" + digitos[1:]
    elif len(digitos) == 9 and digitos.startswith("9"):                # celular sin el 0
        numero = "+593" + digitos
    else:
        numero = "+" + digitos
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", numero):
        raise forms.ValidationError("Número inválido. Escríbalo como 0991234567 o con el código del país (+1 305…).")
    return numero


class LeadManualForm(Bootstrap, forms.Form):
    telefono = forms.CharField(max_length=30, label="Teléfono",
                               help_text="Celular de Ecuador (0991234567) o con código de país (+1 305 555 0100).",
                               widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "off"}))
    nombre = forms.CharField(max_length=200, required=False, label="Nombre del cliente")
    origen = forms.ChoiceField(choices=CANALES_MANUALES, label="¿Por dónde llegó?")
    tipo_visa = forms.ChoiceField(choices=[("", "—")] + [(v, v) for v in TIPOS_VISA], required=False, label="Tipo de visa")
    pais_interes = forms.ChoiceField(choices=[("", "—")] + [(p, p) for p in PAISES], required=False, label="País de interés")
    nota = forms.CharField(max_length=4000, required=False, label="Nota",
                           widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Qué necesita, quién lo refirió…"}))

    def clean_telefono(self):
        return normalizar_telefono(self.cleaned_data["telefono"])
