"""Formularios de las acciones sobre el lead y de la configuración (SCRUM-30 a 33).

Validan lo que conviene avisar antes de ir a la base (campos obligatorios según el resultado,
fechas en el pasado…). La base vuelve a validar todo: estas reglas son comodidad, no seguridad.
"""
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
    minutos_primera_llamada = forms.IntegerField(min_value=1, max_value=240, label="Minutos para la primera llamada",
                                                 help_text="Si el asesor no llama en este tiempo, se reasigna.")
    minutos_entre_reintentos = forms.IntegerField(min_value=1, max_value=1440, label="Minutos entre reintentos")
    minutos_alerta_supervisor = forms.IntegerField(min_value=1, max_value=480, label="Alertar al supervisor tras",
                                                   help_text="Minutos de atraso de una llamada pendiente.")
    # Textos automáticos de WhatsApp
    texto_bienvenida = forms.CharField(max_length=1024, label="Respuesta al primer mensaje",
                                       widget=forms.Textarea(attrs={"rows": 2}))
    texto_fuera_horario = forms.CharField(max_length=1024, label="Respuesta fuera de horario",
                                          widget=forms.Textarea(attrs={"rows": 3}))
    texto_privacidad = forms.CharField(max_length=1024, required=False, label="Aviso de privacidad (LOPDP)",
                                       widget=forms.Textarea(attrs={"rows": 3}),
                                       help_text="Pendiente de validar con el área (SCRUM-23).")

    ZONA = "America/Guayaquil"

    @classmethod
    def desde_configuracion(cls, config):
        horario = config.get("horario") or {}
        inicial = {
            "hora_inicio": horario.get("inicio", "09:00")[:5],
            "hora_fin": horario.get("fin", "18:00")[:5],
            "dias": horario.get("dias", [1, 2, 3, 4, 5]),
        }
        for clave in ("max_intentos_por_asesor", "minutos_primera_llamada", "minutos_entre_reintentos",
                      "minutos_alerta_supervisor", "texto_bienvenida", "texto_fuera_horario", "texto_privacidad"):
            if clave in config:
                inicial[clave] = config[clave]
        return inicial

    def clean(self):
        datos = super().clean()
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
        return cambios
