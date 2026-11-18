"""Login (RF-30), gestión de usuarios (admin) y estado de los asesores (RF-11)."""
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from leads.models import Asesor, EstadoAsesor, Usuario
from leads.servicios import ErrorNegocio

from . import servicios
from .forms import LoginForm, UsuarioForm
from .permisos import ADMIN, SUPERVISION, con_rol

seguridad = logging.getLogger("rumbo.seguridad")


# ─────────────────────────────── Login ───────────────────────────────

class Ingresar(auth_views.LoginView):
    template_name = "cuentas/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_invalid(self, form):
        seguridad.warning("Ingreso fallido · usuario=%r · ip=%s", form.data.get("username", "")[:150],
                          self.request.META.get("REMOTE_ADDR", ""))
        return super().form_invalid(form)


class Salir(auth_views.LogoutView):
    pass


# ─────────────────────────────── RF-11 · Estado del asesor ───────────────────────────────

@require_POST
@con_rol("asesor")
def mi_estado(request):
    """El asesor cambia su estado con un clic (barra superior). HTMX: devuelve el selector."""
    try:
        servicios.cambiar_estado(request.POST.get("estado"))
    except ErrorNegocio as e:
        messages.error(request, e.mensaje)
    if request.htmx:
        return render(request, "cuentas/_estado_asesor.html", {"rumbo": request.rumbo})
    return redirect(request.POST.get("volver") or reverse("inicio"))


@require_http_methods(["GET", "POST"])
@con_rol(*SUPERVISION)
def asesores(request):
    """El supervisor ve el estado de todos los asesores y puede cambiarlo (p. ej. uno que se
    fue sin pasar a 'fuera de turno'). La tabla se refresca sola cada 30 s."""
    if request.method == "POST":
        asesor = get_object_or_404(Asesor.objects.select_related("usuario"), pk=request.POST.get("asesor"))
        try:
            servicios.cambiar_estado(request.POST.get("estado"), asesor.pk)
        except ErrorNegocio as e:
            messages.error(request, e.mensaje)
        else:
            messages.success(request, f"{asesor.usuario.nombre}: {EstadoAsesor(request.POST['estado']).label}.")
        if not request.htmx:
            return redirect("cuentas:asesores")
    filas = servicios.asesores_con_carga()
    contexto = {
        "rumbo": request.rumbo,
        "filas": filas,
        "estados": servicios.ESTADOS_ELEGIBLES,
        "disponibles": sum(f["estado"] == EstadoAsesor.DISPONIBLE for f in filas),
    }
    plantilla = "cuentas/_tabla_asesores.html" if request.htmx else "cuentas/asesores.html"
    return render(request, plantilla, contexto)


# ─────────────────────────────── RF-30 · Usuarios (admin) ───────────────────────────────

@require_http_methods(["GET"])
@con_rol(*ADMIN)
def usuarios(request):
    return render(request, "cuentas/usuarios.html", {"rumbo": request.rumbo, "filas": servicios.listar_usuarios()})


@require_http_methods(["GET", "POST"])
@con_rol(*ADMIN)
def usuario_nuevo(request):
    form = UsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            servicios.crear_usuario(username=form.cleaned_data["username"], **form.datos_servicio())
        except ErrorNegocio as e:
            messages.error(request, e.mensaje)
        else:
            seguridad.info("Usuario creado · %s (%s) por usuario_id=%s", form.cleaned_data["username"],
                           form.cleaned_data["rol"], request.rumbo.usuario_id)
            messages.success(request, f"Usuario {form.cleaned_data['username']} creado.")
            return redirect("cuentas:usuarios")
    return render(request, "cuentas/usuario_form.html", {"rumbo": request.rumbo, "form": form, "nuevo": True})


@require_http_methods(["GET", "POST"])
@con_rol(*ADMIN)
def usuario_editar(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk)
    perfil = Usuario.objects.filter(pk=pk).first()
    asesor = Asesor.objects.filter(usuario_id=pk).first()
    inicial = {
        "username": user.username,
        "nombre": perfil.nombre if perfil else user.get_full_name() or user.username,
        "rol": perfil.rol if perfil else "asesor",
        "activo": bool(perfil and perfil.activo and user.is_active),
        "numero_whatsapp": asesor.numero_whatsapp_id if asesor else None,
        "codigo_callflow": asesor.codigo_callflow if asesor else "",
    }
    form = UsuarioForm(request.POST or None, usuario=user, initial=inicial)
    if perfil and perfil.rol == "asesor":
        form.fields["rol"].disabled = True          # la base no deja cambiar el rol de un asesor
        form.fields["rol"].help_text = "Un asesor no cambia de rol: desactívelo y cree otro usuario."
    if request.method == "POST" and form.is_valid():
        datos = form.datos_servicio()
        try:
            servicios.actualizar_usuario(user, activo=form.cleaned_data["activo"], editor_id=request.rumbo.usuario_id,
                                         **datos)
        except ErrorNegocio as e:
            messages.error(request, e.mensaje)
        else:
            if datos["password"] and user.pk == request.user.pk:
                update_session_auth_hash(request, user)
            seguridad.info("Usuario modificado · %s por usuario_id=%s (rol=%s activo=%s clave_cambiada=%s)",
                           user.username, request.rumbo.usuario_id, datos["rol"], form.cleaned_data["activo"],
                           bool(datos["password"]))
            messages.success(request, f"Usuario {user.username} actualizado.")
            return redirect("cuentas:usuarios")
    return render(request, "cuentas/usuario_form.html", {
        "rumbo": request.rumbo, "form": form, "nuevo": False, "editado": user,
        "es_asesor": bool(perfil and perfil.rol == "asesor"),
    })
