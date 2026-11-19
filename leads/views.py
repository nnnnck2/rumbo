"""Pantallas y acciones del lead (SCRUM-30, 31, 32) y panel de configuración (SCRUM-33).

La ficha del lead (SCRUM-29) y la lista de llamadas (SCRUM-28) son de Gabo; las acciones
están en plantillas parciales (leads/_accion_*.html) para incluirlas en esas pantallas.
Las acciones responden con el bloque #ficha actualizado (HTMX) o redirigen (sin JS).

Permisos: los decide la base. Un asesor solo ve (RLS) y solo puede tocar (funciones SQL) sus
leads. Aquí además se ocultan los botones que su rol no puede usar.
"""
import datetime as dt
import json
from urllib.parse import quote, urlsplit

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from cuentas.permisos import SUPERVISION, TODOS, con_rol

from . import servicios
from .forms import (PAISES, TIPOS_VISA, AgendarForm, ConfiguracionForm, DatosLeadForm, EtapaForm, IntentoForm,
                    NotaForm, ReasignarForm, ReasignarLoteForm, asesores_activos)
from .models import Etapa, EstadoAsignacion, Lead


# ─────────────────────────────── Ficha ───────────────────────────────

def _lead(pk):
    return (Lead.objects.select_related("etapa", "motivo_descarte", "asesor__usuario", "numero_whatsapp")
            .filter(pk=pk).first())


def _contexto_ficha(request, lead, intento_form=None, etapa_form=None, reasignar_form=None, agendar_form=None,
                    datos_form=None, nota_form=None):
    puede_actuar = lead.estado_asignacion == EstadoAsignacion.ASIGNADO
    puede_editar = request.rumbo.es_supervisor or (lead.asesor_id and lead.asesor_id == request.rumbo.asesor_id)
    return {
        "lead": lead,
        **_modo_siguiente(request),
        "datos_form": (datos_form or DatosLeadForm(initial={"version": lead.version, "tipo_visa": lead.tipo_visa,
                                                            "pais_interes": lead.pais_interes}))
                      if puede_editar else None,
        "tipos_visa": TIPOS_VISA,
        "paises": PAISES,
        "notas": lead.notas.select_related("autor_usuario").order_by("-creado_en"),
        "nota_form": nota_form or NotaForm(),
        "vencida": bool(puede_actuar and lead.proxima_accion_en and lead.proxima_accion_en <= timezone.now()),
        "agendar_form": (agendar_form or AgendarForm(initial={"version": lead.version})) if puede_actuar else None,
        "rumbo": request.rumbo,
        "intentos": lead.intentos.select_related("resultado", "asesor__usuario").order_by("-numero"),
        "historial_etapas": lead.historial_etapas.select_related("desde", "hacia", "usuario").order_by("-creado_en"),
        "asignaciones": lead.asignaciones.select_related("asesor__usuario", "asesor_anterior__usuario",
                                                          "asignado_por_usuario").order_by("-creado_en"),
        "mensajes": lead.mensajes.order_by("-ocurrido_en")[:20],
        "puede_registrar": puede_actuar,
        "intento_form": intento_form or (IntentoForm(initial={"version": lead.version}) if puede_actuar else None),
        "etapa_form": etapa_form or EtapaForm(initial={"version": lead.version},
                                              etapas=servicios.etapas_permitidas(lead.etapa_id)),
        "reasignar_form": (reasignar_form or ReasignarForm(excluir=lead.asesor_id))
                          if request.rumbo.es_supervisor and lead.estado_asignacion != EstadoAsignacion.CERRADO
                          else None,
    }


def _responder_ficha(request, lead, **forms):
    plantilla = "leads/_ficha.html" if request.htmx else "leads/ficha.html"
    return render(request, plantilla, _contexto_ficha(request, lead, **forms))


def _lead_ya_no_visible(request, texto):
    """Tras la acción el lead pasó a otro asesor (p. ej. 3er intento): el asesor ya no lo ve."""
    messages.success(request, texto)
    destino = reverse("leads:lista")
    if request.htmx:
        respuesta = render(request, "leads/_mensajes.html")
        respuesta["HX-Redirect"] = destino
        return respuesta
    return redirect(destino)


@con_rol(*TODOS)
def ficha(request, pk):
    lead = _lead(pk)
    if lead is None:                      # no existe o RLS no se lo muestra a este usuario
        raise PermissionDenied
    return render(request, "leads/ficha.html", {**_contexto_ficha(request, lead), **_volver_de_ficha(request)})


def _volver_de_ficha(request):
    """El botón "Volver" regresa a la pantalla de donde vino (inicio, alertas o la lista con sus filtros)."""
    previo = urlsplit(request.META.get("HTTP_REFERER", ""))
    if previo.netloc == request.get_host():
        if previo.path == reverse("inicio"):
            return {"volver_url": reverse("inicio"), "volver_texto": "Volver al inicio"}
        if previo.path == reverse("leads:alertas"):
            return {"volver_url": previo.path, "volver_texto": "Volver a llamadas atrasadas"}
        if previo.path == reverse("leads:lista"):
            return {"volver_url": previo.path + (f"?{previo.query}" if previo.query else ""), "volver_texto": "Volver a la lista"}
    return {"volver_url": reverse("leads:lista"), "volver_texto": "Volver a la lista"}


# ─────────────────────────────── RF-22 · Registrar intento ───────────────────────────────

@require_POST
@con_rol(*TODOS)
def registrar_intento(request, pk):
    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    form = IntentoForm(request.POST)
    if not form.is_valid():
        return _responder_ficha(request, lead, intento_form=form)
    d = form.cleaned_data
    try:
        servicios.registrar_intento(lead.pk, d["version"], d["resultado"], d["nota"], d["agendar_para"], form.venta())
    except servicios.ErrorNegocio as e:
        messages.error(request, e.mensaje)
        lead = _lead(pk)
        if lead is None:
            return _lead_ya_no_visible(request, e.mensaje)
        return _responder_ficha(request, lead, intento_form=None if e.tipo == "conflicto" else form)

    resultado = form.resultados[d["resultado"]].nombre
    nombre = nombre_cliente(lead)
    lead = _lead(pk)
    if request.POST.get("siguiente"):          # SCRUM-76: pasa solo al siguiente cliente pendiente
        messages.success(request, f"Guardado: {nombre} · {resultado}.")
        return _ir_a(request, reverse("leads:siguiente"))
    if lead is None:
        return _lead_ya_no_visible(request, f"Intento registrado ({resultado}). Se agotaron los intentos: "
                                            "el lead pasó al siguiente asesor.")
    messages.success(request, f"Intento registrado: {resultado}.")
    return _responder_ficha(request, lead)


# ─────────────────────────────── SCRUM-76 · Llamar al siguiente ───────────────────────────────

CLAVE_SALTADOS = "rumbo_saltados"


def nombre_cliente(lead):
    return (lead.nombre_perfil or lead.telefono) if lead else "el cliente"


def _ir_a(request, url):
    """Redirección que también funciona con HTMX (recarga la página completa)."""
    if request.htmx:
        respuesta = render(request, "leads/_mensajes.html")
        respuesta["HX-Redirect"] = url
        return respuesta
    return redirect(url)


def _pendientes(request):
    """Leads a los que ya toca llamar, del más atrasado al más reciente. El asesor ve los suyos (RLS)."""
    qs = Lead.objects.filter(estado_asignacion=EstadoAsignacion.ASIGNADO, proxima_accion_en__lte=timezone.now())
    if request.rumbo.asesor_id:
        qs = qs.filter(asesor_id=request.rumbo.asesor_id)
    return qs.order_by("proxima_accion_en", "id")


def _en_modo_siguiente(request):
    if request.GET.get("siguiente") or request.POST.get("siguiente"):
        return True
    # Las acciones HTMX de la ficha (notas, datos…) no llevan el parámetro: se mira la URL de la página.
    return "siguiente=1" in request.headers.get("HX-Current-URL", "")


def _modo_siguiente(request):
    if not _en_modo_siguiente(request):
        return {"modo_siguiente": False}
    saltados = request.session.get(CLAVE_SALTADOS, [])
    return {"modo_siguiente": True, "quedan": _pendientes(request).exclude(pk__in=saltados).count()}


@require_http_methods(["GET"])
@con_rol(*TODOS)
def siguiente(request):
    """Abre la ficha del cliente más urgente. ?desde_inicio=1 empieza de cero; ?saltar=<id> lo deja para el final."""
    saltados = [] if request.GET.get("desde_inicio") else request.session.get(CLAVE_SALTADOS, [])
    if request.GET.get("saltar", "").isdigit():
        saltados.append(int(request.GET["saltar"]))
    request.session[CLAVE_SALTADOS] = saltados
    lead = _pendientes(request).exclude(pk__in=saltados).first()
    if lead is None:
        request.session.pop(CLAVE_SALTADOS, None)
        omitidos = _pendientes(request).filter(pk__in=saltados).count() if saltados else 0
        messages.success(request, "No quedan llamadas pendientes." if not omitidos else
                         f"Terminó la ronda. Quedan {omitidos} cliente{'s' if omitidos != 1 else ''} que saltó.")
        return redirect("inicio")
    return redirect(f"{reverse('leads:ficha', args=[lead.pk])}?siguiente=1")


# ─────────────────────────────── RF-24 · Agendar llamada ───────────────────────────────

@require_POST
@con_rol(*TODOS)
def agendar(request, pk):
    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    form = AgendarForm(request.POST)
    if not form.is_valid():
        return _responder_ficha(request, lead, agendar_form=form)
    try:
        servicios.agendar_llamada(lead.pk, form.cleaned_data["version"], form.cleaned_data["cuando"])
    except servicios.ErrorNegocio as e:
        messages.error(request, e.mensaje)
        return _responder_ficha(request, _lead(pk), agendar_form=None if e.tipo == "conflicto" else form)
    cuando = timezone.localtime(form.cleaned_data["cuando"])
    messages.success(request, f"Llamada agendada para el {cuando:%d/%m a las %H:%M}.")
    return _responder_ficha(request, _lead(pk))


# ─────────────────────────────── RF-26 · Datos del caso y notas ───────────────────────────────

@require_POST
@con_rol(*TODOS)
def guardar_datos(request, pk):
    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    form = DatosLeadForm(request.POST)
    if not form.is_valid():
        return _responder_ficha(request, lead, datos_form=form)
    d = form.cleaned_data
    try:
        servicios.actualizar_datos_lead(lead.pk, d["version"], d["tipo_visa"], d["pais_interes"])
    except servicios.ErrorNegocio as e:
        messages.error(request, e.mensaje)
        return _responder_ficha(request, _lead(pk), datos_form=None if e.tipo == "conflicto" else form)
    messages.success(request, "Datos del caso guardados.")
    return _responder_ficha(request, _lead(pk))


@require_POST
@con_rol(*TODOS)
def agregar_nota(request, pk):
    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    form = NotaForm(request.POST)
    if not form.is_valid():
        return _responder_ficha(request, lead, nota_form=form)
    try:
        servicios.agregar_nota(lead.pk, form.cleaned_data["texto"], request.rumbo.usuario_id)
    except servicios.ErrorNegocio as e:
        messages.error(request, e.mensaje)
        return _responder_ficha(request, lead, nota_form=form)
    messages.success(request, "Nota agregada.")
    return _responder_ficha(request, _lead(pk))


# ─────────────────────────────── RF-25 · Cambiar etapa ───────────────────────────────

@require_POST
@con_rol(*TODOS)
def cambiar_etapa(request, pk):
    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    form = EtapaForm(request.POST, etapas=servicios.etapas_permitidas(lead.etapa_id))
    if not form.is_valid():
        return _responder_ficha(request, lead, etapa_form=form)
    d = form.cleaned_data
    motivo = d["motivo_descarte"].pk if d.get("motivo_descarte") else None
    try:
        servicios.cambiar_etapa(lead.pk, d["version"], d["etapa"], motivo)
    except servicios.ErrorNegocio as e:
        messages.error(request, e.mensaje)
        lead = _lead(pk)
        return _responder_ficha(request, lead, etapa_form=None if e.tipo == "conflicto" else form)
    lead = _lead(pk)
    if lead is None:
        return _lead_ya_no_visible(request, "Etapa actualizada.")
    messages.success(request, f"Etapa: {lead.etapa.nombre}.")
    return _responder_ficha(request, lead)


# ─────────────────────────────── RF-16 · Reasignar ───────────────────────────────

@require_POST
@con_rol(*SUPERVISION)
def reasignar(request, pk):
    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    form = ReasignarForm(request.POST, excluir=lead.asesor_id)
    if not form.is_valid():
        return _responder_ficha(request, lead, reasignar_form=form)
    asesor = form.cleaned_data["asesor"]
    try:
        servicios.reasignar(lead.pk, asesor.pk)
    except servicios.ErrorNegocio as e:
        messages.error(request, e.mensaje)
        return _responder_ficha(request, _lead(pk), reasignar_form=form)
    messages.success(request, f"Lead reasignado a {asesor.usuario.nombre}.")
    return _responder_ficha(request, _lead(pk))


@require_POST
@con_rol(*SUPERVISION)
def reasignar_lote(request):
    ids = [int(x) for x in request.POST.getlist("leads") if x.isdigit()]
    form = ReasignarLoteForm(request.POST, lead_ids=ids)
    if form.is_valid():
        asesor = form.cleaned_data["asesor"]
        hechos, errores = servicios.reasignar_lote(form.cleaned_data["leads"], asesor.pk)
        if hechos:
            messages.success(request, f"{len(hechos)} lead(s) reasignado(s) a {asesor.usuario.nombre}.")
        for lead_id, error in errores:
            messages.error(request, f"Lead {lead_id}: {error}")
    else:
        for errores in form.errors.values():
            for error in errores:
                messages.error(request, error)
    return redirect(request.POST.get("volver") or reverse("leads:lista"))


# ─────────────────────────────── Lista con filtros (RF-25: filtro por etapa) ───────────────────────────────

@require_http_methods(["GET"])
@con_rol(*TODOS)
def lista(request):
    f = request.GET
    qs = Lead.objects.select_related("etapa", "asesor__usuario").order_by("-primer_contacto_en")
    # Filtros que se combinan con cualquier pestaña: búsqueda, etapa y asesor.
    if f.get("etapa"):
        qs = qs.filter(etapa_id=f["etapa"])
    if f.get("asesor") and request.rumbo.es_supervisor:
        qs = qs.filter(asesor_id=f["asesor"]) if f["asesor"] != "ninguno" else qs.filter(asesor__isnull=True)
    if f.get("q"):
        qs = qs.filter(Q(telefono__icontains=f["q"]) | Q(nombre_perfil__icontains=f["q"]))

    # Pestañas (RF-24: "Por llamar ahora" = llamadas que ya toca hacer, vencidas incluidas).
    ahora = timezone.now()
    pendientes = qs.filter(estado_asignacion=EstadoAsignacion.ASIGNADO, proxima_accion_en__lte=ahora)
    conteo = dict(qs.order_by().values_list("estado_asignacion").annotate(n=Count("id")))
    pestanas = [
        {"clave": "pendientes", "nombre": "Por llamar ahora", "n": pendientes.count(), "url": "pendientes=1"},
        {"clave": "asignado", "nombre": "Abiertos", "n": conteo.get(EstadoAsignacion.ASIGNADO, 0), "url": "estado=asignado"},
    ]
    if request.rumbo.es_supervisor:
        pestanas.append({"clave": "en_cola", "nombre": "En cola", "n": conteo.get(EstadoAsignacion.EN_COLA, 0),
                         "url": "estado=en_cola"})
    pestanas += [
        {"clave": "cerrado", "nombre": "Cerrados", "n": conteo.get(EstadoAsignacion.CERRADO, 0), "url": "estado=cerrado"},
        {"clave": "", "nombre": "Todos", "n": sum(conteo.values()), "url": ""},
    ]
    if f.get("pendientes"):
        activa = "pendientes"
        qs = pendientes.order_by("proxima_accion_en")
    elif f.get("estado") in EstadoAsignacion.values:
        activa = f["estado"]
        qs = qs.filter(estado_asignacion=activa)
    else:
        activa = ""

    pagina = Paginator(qs, 50).get_page(f.get("pagina"))
    # Para mantener la búsqueda y los filtros al cambiar de pestaña o de página.
    extra = "&".join(f"{k}={quote(v)}" for k, v in f.items() if k in ("q", "etapa", "asesor") and v)
    return render(request, "leads/lista.html", {
        "pagina": pagina,
        "rumbo": request.rumbo,
        "etapas": Etapa.objects.filter(activo=True),
        "asesores": asesores_activos() if request.rumbo.es_supervisor else [],
        "filtros": f,
        "pestanas": pestanas,
        "activa": activa,
        "extra": extra,
        "mas_filtros": bool(f.get("etapa") or f.get("asesor")),
        "lote_form": ReasignarForm() if request.rumbo.es_supervisor else None,
        "volver": request.get_full_path(),
        "ahora": ahora,
    })


# ─────────────────────────────── RF-33 · Alertas de leads sin llamar ───────────────────────────────

@require_http_methods(["GET"])
@con_rol(*SUPERVISION)
def alertas(request):
    """Panel del supervisor. Se refresca solo (HTMX) cada 30 s."""
    contexto = {"alertas": servicios.leads_sin_llamar(), "rumbo": request.rumbo,
                "umbral": servicios.leer_configuracion().get("minutos_alerta_supervisor", 30)}
    plantilla = "leads/_alertas_tabla.html" if request.htmx else "leads/alertas.html"
    return render(request, plantilla, contexto)


@require_http_methods(["GET"])
@con_rol(*SUPERVISION)
def alertas_contador(request):
    """Insignia de la barra de navegación (HTMX, cada 30 s). Dispara la notificación del navegador."""
    filas = servicios.leads_sin_llamar()
    # Texto para la notificación. El nombre viene del perfil de WhatsApp (lo escribe el cliente):
    # se escapa "<", ">" y "&" para que no pueda cerrar el <script> ni inyectar HTML.
    detalle = [f"{f['nombre_perfil'] or f['telefono']} · {f['asesor'] or 'sin asesor'} · {f['minutos']} min"
               for f in filas[:3]]
    alertas_json = (json.dumps(detalle, ensure_ascii=True)
                    .replace("<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026"))
    return render(request, "leads/_alertas_contador.html", {"total": len(filas), "alertas_json": alertas_json})


# ─────────────────────────────── SCRUM-44 · Métricas del piloto ───────────────────────────────

MOTIVOS_REASIGNACION = {
    "reintentos_agotados": "Intentos agotados", "sin_primera_llamada": "No llamó a tiempo",
    "asesor_inactivo": "Asesor inactivo", "cola_horario": "Desde la cola de fuera de horario", "manual": "Manual (supervisor)",
}


@require_http_methods(["GET"])
@con_rol(*SUPERVISION)
def metricas(request):
    hoy = timezone.localdate()
    try:
        desde = dt.date.fromisoformat(request.GET.get("desde", ""))
    except ValueError:
        desde = hoy - dt.timedelta(days=6)
    try:
        hasta = dt.date.fromisoformat(request.GET.get("hasta", ""))
    except ValueError:
        hasta = hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    zona = timezone.get_current_timezone()
    inicio = dt.datetime.combine(desde, dt.time.min, zona)
    fin = dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time.min, zona)
    datos = servicios.metricas_piloto(inicio, fin)
    datos["reasignaciones"] = [(MOTIVOS_REASIGNACION.get(m, m), n) for m, n in sorted(datos["reasignaciones"].items())]
    return render(request, "leads/metricas.html", {
        **datos, "desde": desde, "hasta": hasta, "rumbo": request.rumbo,
        "webhook": servicios.errores_webhook(inicio, fin) if request.rumbo.es_admin else None,
    })


# ─────────────────────────────── RF-31 · Configuración ───────────────────────────────

@require_http_methods(["GET", "POST"])
@con_rol("admin")
def configuracion(request):
    actual = servicios.leer_configuracion()
    if request.method == "POST":
        form = ConfiguracionForm(request.POST)
        if form.is_valid():
            try:
                zona = (actual.get("horario") or {}).get("zona")
                servicios.guardar_configuracion(form.cambios(zona), request.rumbo.usuario_id)
            except servicios.ErrorNegocio as e:
                messages.error(request, e.mensaje)
            else:
                messages.success(request, "Configuración guardada. Rige desde ya, sin reiniciar el sistema.")
                return redirect("leads:configuracion")
    else:
        form = ConfiguracionForm(initial=ConfiguracionForm.desde_configuracion(actual))
    return render(request, "leads/configuracion.html", {"form": form, "rumbo": request.rumbo})
