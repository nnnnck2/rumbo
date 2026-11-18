from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm

from leads.forms import Bootstrap
from leads.models import Asesor, NumeroWhatsapp

ROLES = [("asesor", "Asesor"), ("supervisor", "Supervisor"), ("admin", "Administrador")]


class LoginForm(Bootstrap, AuthenticationForm):
    error_messages = {
        "invalid_login": "Usuario o contraseña incorrectos.",
        "inactive": "Este usuario está desactivado.",
    }


class UsuarioForm(Bootstrap, forms.Form):
    username = forms.RegexField(regex=r"^[\w.@+-]{3,150}$", label="Usuario",
                                help_text="Con el que ingresa. Letras, números y . @ + - _",
                                error_messages={"invalid": "Use de 3 a 150 letras, números o . @ + - _"})
    nombre = forms.CharField(max_length=120, label="Nombre completo")
    rol = forms.ChoiceField(choices=ROLES)
    activo = forms.BooleanField(required=False, initial=True)
    numero_whatsapp = forms.ModelChoiceField(NumeroWhatsapp.objects.filter(activo=True), required=False,
                                             label="Número de WhatsApp", empty_label="—",
                                             help_text="Solo asesores: número desde el que escribe a sus clientes.")
    codigo_callflow = forms.CharField(max_length=40, required=False, label="Código CALLFLOW",
                                      help_text="Solo asesores: código de empleado para comisiones.")
    password1 = forms.CharField(label="Contraseña", strip=False, required=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repetir contraseña", strip=False, required=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, usuario=None, **kwargs):
        """usuario=None → alta (contraseña obligatoria). Con usuario → edición (contraseña opcional)."""
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.fields["activo"].widget.attrs["class"] = "form-check-input"
        if usuario is not None:
            self.fields["username"].disabled = True
            self.fields["password1"].help_text = "Déjela vacía para no cambiarla."
        else:
            del self.fields["activo"]
            self.fields["password1"].required = self.fields["password2"].required = True
            self.fields["password1"].help_text = password_validation.password_validators_help_text_html()

    def clean_username(self):
        username = self.cleaned_data["username"]
        if self.usuario is None and get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return username

    def clean_codigo_callflow(self):
        codigo = self.cleaned_data["codigo_callflow"].strip()
        if codigo:
            otros = Asesor.objects.filter(codigo_callflow=codigo)
            if self.usuario is not None:
                otros = otros.exclude(usuario_id=self.usuario.pk)
            if otros.exists():
                raise forms.ValidationError("Ya lo tiene otro asesor.")
        return codigo

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get("password1"), datos.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            else:
                usuario = self.usuario or get_user_model()(username=datos.get("username", ""))
                try:
                    password_validation.validate_password(p1, usuario)
                except forms.ValidationError as e:
                    self.add_error("password1", e)
        return datos

    def datos_servicio(self):
        d = self.cleaned_data
        es_asesor = d["rol"] == "asesor"
        return {
            "nombre": d["nombre"].strip(),
            "rol": d["rol"],
            "password": d.get("password1") or None,
            "numero_whatsapp_id": d["numero_whatsapp"].pk if es_asesor and d.get("numero_whatsapp") else None,
            "codigo_callflow": d["codigo_callflow"] if es_asesor else None,
        }
