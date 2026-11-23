"""Pantallas y acciones del lead (SCRUM-30, 31, 32) y panel de configuración (SCRUM-33).

La ficha del lead (SCRUM-29) y la lista de llamadas (SCRUM-28) son de Gabo; las acciones
están en plantillas parciales (leads/_accion_*.html) para incluirlas en esas pantallas.
Las acciones responden con el bloque #ficha actualizado (HTMX) o redirigen (sin JS).

Permisos: los decide la base. Un asesor solo ve (RLS) y solo puede tocar (funciones SQL) sus
leads. Aquí además se ocultan los botones que su rol no puede usar.
"""
import csv
import datetime as dt
import re
from urllib.parse import quote, urlencode, urlsplit

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from cuentas.permisos import SUPERVISION, TODOS, con_rol

from . import operacion, servicios, zonas
from .forms import (ORIGENES, PAISES, TIPOS_VISA, AgendarForm, ConfiguracionForm, DatosLeadForm, EtapaForm,
                    IntentoForm, LeadManualForm, NotaForm, ReasignarForm, ReasignarLoteForm, asesores_activos)
from .models import (Anuncio, Asesor, Asignacion, Etapa, EstadoAsignacion, Lead, LeadEtapaHistorial, LeadOrigen,
                     Usuario)


# ─────────────────────────────── Ficha ───────────────────────────────

def _lead(pk):
    return (Lead.objects.select_related("etapa", "motivo_descarte", "asesor__usuario", "numero_whatsapp")
            .filter(pk=pk).first())


def _contexto_ficha(request, lead, intento_form=None, etapa_form=None, reasignar_form=None, agendar_form=None,
                    datos_form=None, nota_form=None):
    puede_actuar = lead.estado_asignacion == EstadoAsignacion.ASIGNADO
    puede_editar = request.rumbo.es_supervisor or (lead.asesor_id and lead.asesor_id == request.rumbo.asesor_id)
    servicios.con_situacion([lead])
    origenes = list(lead.origenes.select_related("anuncio").order_by("llegado_en"))
    config = servicios.leer_configuracion()
    return {
        "lead": lead,
        **_recorrido(request, lead),
        "origen": origenes[0] if origenes else None,        # 016: anuncio del que llegó
        "otras_llegadas": len(origenes) - 1 if origenes else 0,
        "entradas_anuncios": entradas_por_anuncio(origenes),  # SCRUM-100
        "whatsapp_url": enlace_whatsapp(lead, _nombre_usuario(request)),   # SCRUM-94
        "hora_cliente": zonas.hora_cliente(lead.telefono),  # SCRUM-95
        "guion": servicios.guion_para(lead.tipo_visa, config.get("guiones_llamada")),   # SCRUM-96
        "ultimo_aviso": lead.mensajes.filter(direccion="saliente", payload__has_key="aviso_no_contesta")
                        .order_by("-ocurrido_en").first(),                                # SCRUM-104
        "reapertura": reapertura(lead),                                                   # SCRUM-110
        **_extras_ficha(request, lead, config),                                          # SCRUM-114 a 126
        "hoy": timezone.localdate(),
        "ahora": timezone.now(),                                                          # SCRUM-29
        "origen_texto": ORIGENES.get(lead.origen, lead.origen),                           # SCRUM-53
        # SCRUM-43 · LOPDP: aviso de privacidad y consentimiento
        "aviso_privacidad_en": servicios.aviso_privacidad_enviado(lead.pk),
        "consentimiento": (lead.datos or {}).get("consentimiento") or {},
        "medios_consentimiento": servicios.MEDIOS_CONSENTIMIENTO,
        **_modo_siguiente(request),
        "datos_form": (datos_form or DatosLeadForm(initial={"version": lead.version, "tipo_visa": lead.tipo_visa,
                                                            "pais_interes": lead.pais_interes,
                                                            "cita_en": operacion.cita_de(lead)}))
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


def _nombre_usuario(request):
    nombre = Usuario.objects.filter(pk=request.rumbo.usuario_id).values_list("nombre", flat=True).first()
    return nombre or request.user.get_full_name() or request.user.get_username()


def enlace_whatsapp(lead, asesor):
    """SCRUM-94 · Abre el chat del cliente en WhatsApp (wa.me) con un saludo listo para enviar."""
    nombre = (lead.nombre_perfil or "").split()
    saludo = f"Hola {nombre[0]}, " if nombre else "Hola, "
    saludo += f"le saluda {asesor} de Multivisa."
    return f"https://wa.me/{lead.telefono.lstrip('+')}?{urlencode({'text': saludo})}"


def _extras_ficha(request, lead, config):
    """SCRUM-114 (WhatsApp desde la ficha), 117 (documentos), 119 (prioridad), 126 (línea de tiempo)."""
    from whatsapp import envio_asesor

    documentos = operacion.documentos_de(lead, config.get("documentos_por_visa"))
    faltan = [d["nombre"] for d in documentos if d["estado"] != "recibido"]
    cita = operacion.cita_de(lead)
    cita_texto = cita and timezone.localtime(cita).strftime("%d/%m a las %H:%M")
    asesor = _nombre_usuario(request)
    rapidas = [{"titulo": t, "texto": envio_asesor.completar(x, lead, asesor, faltan, cita_texto)}
               for t, x in (config.get("respuestas_rapidas") or {}).items()]
    abierta, cierra = envio_asesor.ventana_abierta(lead)
    con_p = operacion.con_prioridad(Lead.objects.filter(pk=lead.pk)).values("prioridad", "n_entrantes", "p_anuncio").first() or {}
    lead.p_anuncio, lead.n_entrantes = con_p.get("p_anuncio"), con_p.get("n_entrantes", 0)
    prioridad = con_p.get("prioridad", 0)
    puede = request.rumbo.es_supervisor or (lead.asesor_id and lead.asesor_id == request.rumbo.asesor_id)
    return {
        "documentos": documentos, "docs_recibidos": sum(d["estado"] == "recibido" for d in documentos),
        "pedir_documentos": envio_asesor.completar("Hola {nombre}, para avanzar con su trámite necesitamos: {documentos}.",
                                                   lead, asesor, faltan) if faltan else "",
        "respuestas_rapidas": rapidas, "ventana_abierta": abierta, "ventana_cierra": cierra,
        # SCRUM-55: plantillas de seguimiento · SCRUM-59: número por el que sale el mensaje
        "plantillas": envio_asesor.plantillas_disponibles(config.get("plantillas_seguimiento")),
        "numero_envio": lead.asesor.numero_whatsapp.telefono if lead.asesor and lead.asesor.numero_whatsapp else None,
        "puede_escribir": bool(puede and lead.estado_asignacion != EstadoAsignacion.CERRADO or puede and abierta),
        "cita": cita,
        "prioridad": prioridad, "prioridad_alta": prioridad >= operacion.PRIORIDAD_ALTA,
        "razones_prioridad": operacion.razones_prioridad(lead),
        "linea_tiempo": operacion.linea_de_tiempo(
            lead, lead.intentos.select_related("resultado", "asesor__usuario"),
            lead.historial_etapas.select_related("desde", "hacia", "usuario"),
            lead.asignaciones.select_related("asesor__usuario"),
            lead.notas.select_related("autor_usuario"), lead.mensajes.all()[:200]),
    }


DIAS_REABIERTO = 30


def reapertura(lead):
    """SCRUM-110 · {"en", "motivo"} si el lead se reabrió (descartado → nuevo) en los últimos 30 días."""
    h = (LeadEtapaHistorial.objects.filter(lead=lead, desde_id="descartado", hacia_id="nuevo",
                                           creado_en__gte=timezone.now() - dt.timedelta(days=DIAS_REABIERTO))
         .order_by("-creado_en").first())
    if h is None:
        return None
    # El motivo del descarte anterior queda en la nota automática de la reapertura (018).
    nota = (lead.notas.filter(autor_usuario_id=0, texto__startswith="Reabierto automáticamente")
            .order_by("-creado_en").values_list("texto", flat=True).first() or "")
    motivo = re.search(r"«(.+?)»", nota)
    return {"en": h.creado_en, "motivo": motivo.group(1) if motivo else None}


def entradas_por_anuncio(origenes):
    """SCRUM-100 · Anuncios distintos por los que llegó el cliente: [{"anuncio", "primera", "veces"}]."""
    por_anuncio = {}
    for o in origenes:
        e = por_anuncio.setdefault(o.anuncio_id, {"anuncio": o.anuncio, "primera": o.llegado_en, "veces": 0})
        e["veces"] += 1
    return sorted(por_anuncio.values(), key=lambda e: e["primera"])


def _recorrido(request, lead):
    """015 · Por qué asesores pasó el lead en la vuelta actual y quiénes faltan (para dibujarlo)."""
    filas = list(Asignacion.objects.filter(lead=lead).order_by("creado_en").values_list("asesor_id", "vuelta"))
    if not filas:
        return {"recorrido": [], "vuelta": None}
    vuelta = max(v for _a, v in filas)
    visitados = []                      # en orden de paso; si volvió a alguien, cuenta su último paso
    for a, v in filas:
        if v == vuelta:
            if a in visitados:
                visitados.remove(a)
            visitados.append(a)
    # RLS: el asesor solo ve su propia fila de asesor; los demás se muestran como "Otro asesor".
    nombres = {a.pk: a.usuario.nombre for a in Asesor.objects.select_related("usuario")}
    recorrido = [{"nombre": nombres.get(a, "Otro asesor"), "actual": a == lead.asesor_id and lead.estado_asignacion == "asignado",
                  "yo": a == request.rumbo.asesor_id} for a in visitados]
    faltan = []
    if request.rumbo.es_supervisor:
        faltan = [a.usuario.nombre for a in Asesor.objects.select_related("usuario")
                  .filter(usuario__activo=True, estado__in=["disponible", "ocupado"])
                  .exclude(pk__in=visitados).order_by("ultimo_lead_en", "id")]
    return {"recorrido": recorrido, "vuelta": vuelta, "faltan": faltan}


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

    res = form.resultados[d["resultado"]]
    resultado = res.nombre
    nombre = nombre_cliente(lead)
    if res.cuenta_como_intento:              # SCRUM-88: "no contesta" → WhatsApp al cliente (si corresponde)
        from whatsapp.aviso_no_contesta import prever

        servicios.programar_aviso_no_contesta(lead.pk, request.rumbo.usuario_id)
        envia, texto_aviso = prever(lead.pk, request.rumbo.usuario_id)          # SCRUM-104
        if texto_aviso:
            (messages.info if envia else messages.warning)(request, texto_aviso)
    lead = _lead(pk)
    if lead is not None and lead.motivo_descarte_id == "sin_contacto" and res.cuenta_como_intento:
        # SCRUM-89: se llegó al tope de intentos del cliente
        messages.warning(request, f"{nombre} se descartó solo: llegó al tope de intentos sin contacto. "
                                  "Si vuelve a escribir, se reabre.")
        if request.POST.get("siguiente"):
            return _ir_a(request, reverse("leads:siguiente"))
        return _responder_ficha(request, lead)
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
    # SCRUM-28: primero los nuevos, luego agendadas y reintentos; dentro, los más calientes (SCRUM-119).
    return operacion.orden_lista_llamadas(qs)


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


# ─────────────────────────────── SCRUM-53 · Registro manual de leads (RF-07) ───────────────────────────────

@require_http_methods(["GET", "POST"])
@con_rol(*TODOS)
def lead_nuevo(request):
    """Cliente que llegó por llamada, referido o visita: se gestiona igual que uno de WhatsApp."""
    form = LeadManualForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            lead_id, nuevo, asesor_id = servicios.registrar_lead_manual(
                d["telefono"], d["nombre"].strip(), d["origen"], d["tipo_visa"], d["pais_interes"], d["nota"].strip(),
                d.get("consentimiento"))
        except servicios.ErrorNegocio as e:
            messages.error(request, e.mensaje)
        else:
            lead = _lead(lead_id)                  # RLS: None si lo atiende otro asesor
            if not nuevo:
                if lead is None:
                    form.add_error("telefono", "Ese número ya está registrado y lo atiende otro asesor. "
                                               "Si necesita gestionarlo, pídaselo al supervisor.")
                else:
                    messages.warning(request, f"Ese número ya estaba registrado: {nombre_cliente(lead)}. "
                                              "No se creó otro; esta es su ficha.")
                    return redirect("leads:ficha", lead.pk)
            elif lead is not None and asesor_id and asesor_id == request.rumbo.asesor_id:
                messages.success(request, f"Cliente registrado y asignado a usted: {nombre_cliente(lead)}.")
                return redirect("leads:ficha", lead.pk)
            elif lead is not None:
                asesor = lead.asesor.usuario.nombre if lead.asesor else None
                messages.success(request, f"Cliente registrado. {'Lo recibió ' + asesor if asesor else 'Quedó en cola hasta que haya un asesor en turno'}.")
                return redirect("leads:ficha", lead.pk)
            else:
                messages.success(request, "Cliente registrado. Entró al reparto y lo recibió otro asesor.")
                return redirect("leads:lista")
    return render(request, "leads/nuevo.html", {"form": form, "rumbo": request.rumbo})


# ─────────────────────────────── SCRUM-114 · Responder por WhatsApp ───────────────────────────────

@require_POST
@con_rol(*TODOS)
def responder_whatsapp(request, pk):
    from whatsapp import envio_asesor

    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    try:
        envio_asesor.enviar(lead, request.POST.get("texto", ""))
    except envio_asesor.NoEnviado as e:
        messages.error(request, e.mensaje)
    else:
        messages.success(request, "Mensaje enviado por WhatsApp.")
    return _responder_ficha(request, _lead(pk) or lead)


@require_POST
@con_rol(*TODOS)
def enviar_plantilla(request, pk):
    """SCRUM-55 · Plantilla aprobada por Meta (lista de documentos, recordatorio…), también fuera de las 24 h."""
    from whatsapp import envio_asesor

    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    if not (request.rumbo.es_supervisor or lead.asesor_id == request.rumbo.asesor_id):
        raise PermissionDenied
    config = servicios.leer_configuracion()
    faltan = [d["nombre"] for d in operacion.documentos_de(lead, config.get("documentos_por_visa")) if d["estado"] != "recibido"]
    cita = operacion.cita_de(lead)
    try:
        envio_asesor.enviar_plantilla(lead, request.POST.get("plantilla", ""), config.get("plantillas_seguimiento"),
                                      _nombre_usuario(request), faltan,
                                      cita and timezone.localtime(cita).strftime("%d/%m a las %H:%M"))
    except envio_asesor.NoEnviado as e:
        messages.error(request, e.mensaje)
    else:
        messages.success(request, "Plantilla enviada por WhatsApp.")
    return _responder_ficha(request, _lead(pk) or lead)


# ─────────────────────────────── SCRUM-43 · LOPDP: consentimiento ───────────────────────────────

@require_POST
@con_rol(*TODOS)
def registrar_consentimiento(request, pk):
    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    medio = request.POST.get("medio", "")
    if medio not in dict(servicios.MEDIOS_CONSENTIMIENTO):
        messages.error(request, "Elija cómo dio su consentimiento el cliente.")
        return _responder_ficha(request, lead)
    try:
        nuevo = servicios.registrar_consentimiento(lead.pk, medio)
    except servicios.ErrorNegocio as e:
        messages.error(request, e.mensaje)
    else:
        (messages.success if nuevo else messages.info)(
            request, "Consentimiento registrado." if nuevo else "El consentimiento ya estaba registrado.")
    return _responder_ficha(request, _lead(pk) or lead)


# ─────────────────────────────── SCRUM-117 · Documentos ───────────────────────────────

@require_POST
@con_rol(*TODOS)
def marcar_documento(request, pk):
    lead = _lead(pk)
    if lead is None:
        raise PermissionDenied
    nombre = request.POST.get("documento", "").strip()
    estado = request.POST.get("estado") or operacion.siguiente_estado(request.POST.get("actual", "falta"))
    if not operacion.marcar_documento(lead.pk, nombre, estado):
        messages.error(request, "No se pudo actualizar el documento.")
    return _responder_ficha(request, _lead(pk))


# ─────────────────────────────── SCRUM-123 · Búsqueda global ───────────────────────────────

@require_http_methods(["GET"])
@con_rol(*TODOS)
def buscar(request):
    q = request.GET.get("q", "")
    resultados = operacion.buscar(q)
    if not request.htmx and len(resultados) == 1:
        return redirect("leads:ficha", resultados[0].pk)
    return render(request, "leads/_buscar.html", {"resultados": resultados, "q": q, "rumbo": request.rumbo})


# ─────────────────────────────── SCRUM-125 · Agenda ───────────────────────────────

@require_http_methods(["GET"])
@con_rol(*TODOS)
def agenda(request):
    hoy = timezone.localdate()
    try:
        base = dt.date.fromisoformat(request.GET.get("semana", ""))
    except ValueError:
        base = hoy
    lunes = base - dt.timedelta(days=base.weekday())
    asesor_id = request.rumbo.asesor_id
    if request.rumbo.es_supervisor:
        asesor_id = int(request.GET["asesor"]) if request.GET.get("asesor", "").isdigit() else None
    dias = operacion.agenda(lunes, asesor_id)
    return render(request, "leads/agenda.html", {
        "dias": dias, "lunes": lunes, "domingo": lunes + dt.timedelta(days=6), "hoy": hoy,
        "anterior": lunes - dt.timedelta(days=7), "siguiente": lunes + dt.timedelta(days=7),
        "asesores": asesores_activos() if request.rumbo.es_supervisor else [], "asesor_id": asesor_id,
        "total": sum(len(e) for e in dias.values()), "rumbo": request.rumbo,
    })


# ─────────────────────────────── SCRUM-120 · Solicitudes LOPDP ───────────────────────────────

TIPOS_LOPDP = [("acceso", "Acceso"), ("rectificacion", "Rectificación"), ("eliminacion", "Eliminación"),
               ("oposicion", "Oposición")]


@require_http_methods(["GET", "POST"])
@con_rol("admin")
def lopdp(request):
    from django.db import connection

    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "registrar":
                telefono = "".join(c for c in request.POST.get("telefono", "") if c.isdigit())
                lead = Lead.objects.filter(telefono="+" + telefono).first() if telefono else None
                if lead is None:
                    raise servicios.ErrorNegocio("No hay ningún cliente con ese teléfono.")
                servicios._ejecutar("SELECT rumbo.registrar_solicitud_lopdp(%s, %s, %s, %s)",
                                    [lead.pk, request.POST.get("tipo"), request.POST.get("recibida_en") or None,
                                     request.POST.get("detalle", "")])
                messages.success(request, "Solicitud registrada. Plazo: 15 días.")
            elif accion in ("atendida", "rechazada"):
                servicios._ejecutar("SELECT rumbo.atender_solicitud_lopdp(%s, %s, %s)",
                                    [int(request.POST.get("solicitud")), accion, request.POST.get("respuesta", "")],
                                    uno=False)
                messages.success(request, "Solicitud cerrada.")
            elif accion == "anonimizar":
                if request.POST.get("confirmar") != "ANONIMIZAR":
                    raise servicios.ErrorNegocio("Escriba ANONIMIZAR para confirmar (no se puede deshacer).")
                servicios._ejecutar("SELECT rumbo.anonimizar_lead(%s)", [int(request.POST.get("lead"))], uno=False)
                messages.success(request, "Datos personales del cliente anonimizados.")
        except servicios.ErrorNegocio as e:
            messages.error(request, e.mensaje)
        except (TypeError, ValueError):
            messages.error(request, "Datos inválidos.")
        return redirect("leads:lopdp")
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT s.id, s.lead_id, l.telefono, l.nombre_perfil, l.anonimizado_en, s.tipo, s.detalle, s.recibida_en,
                      s.vence_en, s.estado, s.respuesta, s.atendida_en, (s.vence_en - current_date) AS dias
               FROM rumbo.solicitud_lopdp s JOIN rumbo.lead l ON l.id = s.lead_id
               ORDER BY (s.estado <> 'pendiente'), s.vence_en, s.id DESC LIMIT 200""")
        columnas = [c.name for c in cursor.description]
        solicitudes = [dict(zip(columnas, f)) for f in cursor.fetchall()]
    nombres = dict(TIPOS_LOPDP)
    for x in solicitudes:
        x["tipo_texto"] = nombres.get(x["tipo"], x["tipo"])
        x["tono"] = ("cerrada" if x["estado"] != "pendiente" else "rojo" if x["dias"] <= 2
                     else "amarillo" if x["dias"] <= 5 else "verde")
    return render(request, "leads/lopdp.html", {"solicitudes": solicitudes, "tipos": TIPOS_LOPDP,
                                                "hoy": timezone.localdate(), "rumbo": request.rumbo,
                                                "pendientes": sum(x["estado"] == "pendiente" for x in solicitudes)})


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
        servicios.actualizar_datos_lead(lead.pk, d["version"], d["tipo_visa"], d["pais_interes"], d.get("cita_en"))
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

FILTROS_LISTA = ("q", "etapa", "asesor", "pais", "varias", "desde", "hasta", "campana")     # SCRUM-51: fechas y campaña


def _fecha_filtro(valor):
    try:
        return dt.date.fromisoformat(valor or "")
    except ValueError:
        return None


def _leads_filtrados(request):
    """Leads con los filtros que se combinan con cualquier pestaña (búsqueda, etapa, asesor, país y
    "llegó por varios anuncios"). Los usan la lista y la exportación."""
    f = request.GET
    primer_anuncio = LeadOrigen.objects.filter(lead=OuterRef("pk")).order_by("llegado_en")
    # Subconsulta (no JOIN + GROUP BY) para no alterar los conteos de las pestañas.
    anuncios_distintos = (LeadOrigen.objects.filter(lead=OuterRef("pk")).order_by().values("lead")
                          .annotate(n=Count("anuncio", distinct=True)).values("n"))
    qs = (Lead.objects.select_related("etapa", "asesor__usuario").order_by("-primer_contacto_en")
          .annotate(anuncio_titulo=Subquery(primer_anuncio.values("anuncio__titulo")[:1]),     # 016
                    anuncio_clave=Subquery(primer_anuncio.values("anuncio__clave")[:1]),
                    anuncio_pais=Subquery(primer_anuncio.values("anuncio__pais")[:1]),
                    n_anuncios=Coalesce(Subquery(anuncios_distintos), 0),                # SCRUM-100
                    reabierto=Exists(LeadEtapaHistorial.objects.filter(                   # SCRUM-110
                        lead=OuterRef("pk"), desde_id="descartado", hacia_id="nuevo",
                        creado_en__gte=timezone.now() - dt.timedelta(days=DIAS_REABIERTO)))))
    if f.get("etapa"):
        qs = qs.filter(etapa_id=f["etapa"])
    if f.get("asesor") and request.rumbo.es_supervisor:
        qs = qs.filter(asesor_id=f["asesor"]) if f["asesor"] != "ninguno" else qs.filter(asesor__isnull=True)
    if f.get("q"):
        qs = qs.filter(Q(telefono__icontains=f["q"]) | Q(nombre_perfil__icontains=f["q"]))
    if f.get("pais"):                       # 017: las campañas se organizan por país
        qs = qs.filter(pais_interes=f["pais"]) if f["pais"] != "sin_pais" else qs.filter(pais_interes__isnull=True)
    if f.get("varias"):                     # SCRUM-100: llegó por más de un anuncio
        qs = qs.filter(n_anuncios__gte=2)
    # SCRUM-51: fecha de llegada (primer contacto, días de Ecuador) y campaña (anuncio del que llegó)
    zona = timezone.get_current_timezone()
    if desde := _fecha_filtro(f.get("desde")):
        qs = qs.filter(primer_contacto_en__gte=dt.datetime.combine(desde, dt.time.min, zona))
    if hasta := _fecha_filtro(f.get("hasta")):
        qs = qs.filter(primer_contacto_en__lt=dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time.min, zona))
    if f.get("campana", "").isdigit():
        qs = qs.filter(Exists(LeadOrigen.objects.filter(lead=OuterRef("pk"), anuncio_id=int(f["campana"]))))
    return qs


def _pestana(request, qs):
    """Aplica la pestaña elegida: Por llamar ahora, Abiertos, En cola, Cerrados o Todos."""
    f = request.GET
    if f.get("pendientes"):
        pendientes = qs.filter(estado_asignacion=EstadoAsignacion.ASIGNADO, proxima_accion_en__lte=timezone.now())
        return "pendientes", operacion.orden_lista_llamadas(pendientes)          # SCRUM-28 (RF-20)
    if f.get("estado") in EstadoAsignacion.values:
        return f["estado"], qs.filter(estado_asignacion=f["estado"])
    return "", qs


@require_http_methods(["GET"])
@con_rol(*TODOS)
def lista(request):
    f = request.GET
    qs = _leads_filtrados(request)

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
    activa, qs = _pestana(request, qs)

    if activa != "pendientes":
        qs = operacion.con_prioridad(qs)
    pagina = Paginator(qs, 50).get_page(f.get("pagina"))
    pagina.object_list = servicios.con_situacion(pagina.object_list)
    for l in pagina.object_list:                                      # SCRUM-119
        l.prioridad_alta = (getattr(l, "prioridad", 0) or 0) >= operacion.PRIORIDAD_ALTA
        l.razones = operacion.razones_prioridad(l) if l.prioridad_alta else ""
        if activa == "pendientes":                                    # SCRUM-28: tipo y tiempo de espera
            l.tipo_texto = operacion.TIPOS_LLAMADA.get(l.tipo_llamada, "")
            l.espera = operacion.texto_espera(l.espera_desde, ahora)
    # Para mantener la búsqueda y los filtros al cambiar de pestaña o de página.
    extra = "&".join(f"{k}={quote(v)}" for k, v in f.items() if k in FILTROS_LISTA and v)
    return render(request, "leads/lista.html", {
        "pagina": pagina,
        "rumbo": request.rumbo,
        "etapas": Etapa.objects.filter(activo=True),
        "asesores": asesores_activos() if request.rumbo.es_supervisor else [],
        "filtros": f,
        "pestanas": pestanas,
        "activa": activa,
        "extra": extra,
        "mas_filtros": bool(f.get("etapa") or f.get("asesor") or f.get("pais") or f.get("varias") or f.get("desde")
                            or f.get("hasta") or f.get("campana")),
        "campanas": Anuncio.objects.order_by("pais", "nombre_campana", "titulo") if request.rumbo.es_supervisor else [],
        "consulta": request.GET.urlencode(),
        "total_leads": Lead.objects.count() if request.rumbo.es_supervisor else None,     # SCRUM-109
        "paises_leads": sorted(p for p in Lead.objects.exclude(pais_interes__isnull=True)
                               .values_list("pais_interes", flat=True).distinct() if p),
        "lote_form": ReasignarForm() if request.rumbo.es_supervisor else None,
        "volver": request.get_full_path(),
        "ahora": ahora,
    })


# ─────────────────────────────── 017 · Campañas por país (admin) ───────────────────────────────

@require_http_methods(["GET", "POST"])
@con_rol("admin")
def campanas(request):
    """Cada anuncio de Meta del que llegaron leads, con su país. Al asignar el país, los leads de esa
    campaña (los que llegaron y los que lleguen) quedan con ese país de interés."""
    if request.method == "POST" and request.POST.get("accion") == "inversion":     # SCRUM-99
        return _guardar_inversion(request)
    if request.method == "POST":
        anuncio_id = request.POST.get("anuncio")
        try:
            total = servicios.categorizar_anuncio(int(anuncio_id), request.POST.get("pais", ""),
                                                  request.POST.get("nombre_campana", ""))
        except (TypeError, ValueError):
            messages.error(request, "Anuncio no válido.")
        except servicios.ErrorNegocio as e:
            messages.error(request, e.mensaje)
        else:
            messages.success(request, f"Campaña guardada. {total} lead{'s' if total != 1 else ''} "
                                      f"tomaron el país {request.POST.get('pais', '').strip()}.")
        return redirect(f"{reverse('leads:campanas')}#anuncio-{anuncio_id}")

    primeros = (LeadOrigen.objects.order_by("lead_id", "llegado_en", "id").distinct("lead_id")
                .values_list("lead_id", "anuncio_id"))
    origen_de = dict(primeros)
    leads_por_anuncio, ventas_por_anuncio = {}, {}
    vendidos = set(Lead.objects.filter(pk__in=origen_de, ventas__anulada_en__isnull=True, ventas__isnull=False)
                   .values_list("pk", flat=True))
    for lead_id, anuncio_id in origen_de.items():
        leads_por_anuncio[anuncio_id] = leads_por_anuncio.get(anuncio_id, 0) + 1
        if lead_id in vendidos:
            ventas_por_anuncio[anuncio_id] = ventas_por_anuncio.get(anuncio_id, 0) + 1
    anuncios = list(Anuncio.objects.order_by(F("pais").asc(nulls_first=True), "-ultimo_visto_en"))
    for a in anuncios:
        a.leads = leads_por_anuncio.get(a.pk, 0)
        a.ventas = ventas_por_anuncio.get(a.pk, 0)
    paises = sorted({a.pais for a in anuncios if a.pais} | set(PAISES))
    return render(request, "leads/campanas.html", {
        "anuncios": anuncios, "paises": paises, "rumbo": request.rumbo,
        "meta": servicios.estado_conversiones(),                                          # SCRUM-113
        "sin_pais": sum(1 for a in anuncios if not a.pais),
    })


def _guardar_inversion(request):
    from decimal import Decimal, InvalidOperation

    anuncio_id = request.POST.get("anuncio", "")
    texto = request.POST.get("inversion", "").strip().replace(",", ".")
    try:
        monto = Decimal(texto) if texto else None
        if monto is not None and (not monto.is_finite() or monto < 0 or monto >= Decimal("1e10")):
            raise InvalidOperation
        servicios.registrar_inversion(int(anuncio_id), monto)
    except (ValueError, InvalidOperation):
        messages.error(request, "Escriba la inversión como un número (por ejemplo 150.50).")
    except servicios.ErrorNegocio as e:
        messages.error(request, e.mensaje)
    else:
        messages.success(request, "Inversión guardada." if monto is not None else "Inversión borrada.")
    return redirect(f"{reverse('leads:campanas')}#anuncio-{anuncio_id}")


# ─────────────────────────────── 015 · Tablero de gestión (supervisor) ───────────────────────────────

@require_http_methods(["GET"])
@con_rol(*SUPERVISION)
def tablero(request):
    """Cada asesor con sus clientes abiertos, de color según lo urgente. Se refresca solo cada 30 s."""
    from cuentas.servicios import asesores_con_carga

    leads = servicios.con_situacion(
        Lead.objects.filter(estado_asignacion__in=[EstadoAsignacion.ASIGNADO, EstadoAsignacion.EN_COLA])
        .select_related("etapa"))
    leads.sort(key=lambda l: (servicios.ORDEN_TONO.get(l.situacion["tono"], 9), l.proxima_accion_en or timezone.now()))
    por_asesor = {}
    for l in leads:
        por_asesor.setdefault(l.asesor_id, []).append(l)
    columnas = [{"asesor": a, "leads": por_asesor.pop(a["id"], [])} for a in asesores_con_carga()]
    for c in columnas:
        c["urgentes"] = sum(1 for l in c["leads"] if l.situacion["tono"] == "rojo")
    en_cola = por_asesor.pop(None, [])
    conteo = {t: sum(1 for l in leads if l.situacion["tono"] == t) for t in ("rojo", "amarillo", "verde", "azul")}
    contexto = {"columnas": columnas, "en_cola": en_cola, "conteo": conteo, "rumbo": request.rumbo,
                "minutos": servicios.leer_configuracion().get("minutos_primera_llamada", 30)}
    plantilla = "leads/_tablero.html" if request.htmx else "leads/tablero.html"
    return render(request, plantilla, contexto)


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
    return render(request, "leads/_alertas_contador.html", {"total": len(servicios.leads_sin_llamar())})


# ─────────────────────────────── SCRUM-44 · Métricas del piloto ───────────────────────────────

MOTIVOS_REASIGNACION = {
    "reintentos_agotados": "Intentos agotados", "sin_primera_llamada": "No llamó a tiempo",
    "asesor_inactivo": "Asesor inactivo", "cola_horario": "Desde la cola de fuera de horario", "manual": "Manual (supervisor)",
}


@require_http_methods(["GET"])
@con_rol(*SUPERVISION)
def metricas(request):
    desde, hasta, inicio, fin = _rango_metricas(request)
    datos = servicios.metricas_piloto(inicio, fin)
    datos["reasignaciones"] = [(MOTIVOS_REASIGNACION.get(m, m), n) for m, n in sorted(datos["reasignaciones"].items())]
    datos["por_campana"] = servicios.metricas_por_campana(inicio, fin)
    datos["embudo"] = servicios.embudo_por_anuncio(inicio, fin)          # SCRUM-99
    datos["horas_calor"], datos["mapa_calor"] = operacion.mapa_de_calor(inicio, fin, servicios.RESULTADOS_CONTACTO)
    datos["resumen_calor"] = operacion.resumen_mapa(datos["mapa_calor"])
    datos["hay_llamadas_calor"] = any(f["llamadas"] for f in datos["mapa_calor"])
    datos["alertas_calidad"] = operacion.alertas_calidad(servicios.RESULTADOS_CONTACTO)        # SCRUM-129
    return render(request, "leads/metricas.html", {
        **datos, "desde": desde, "hasta": hasta, "rumbo": request.rumbo,
        "webhook": servicios.errores_webhook(inicio, fin) if request.rumbo.es_admin else None,
    })


def _rango_metricas(request):
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
    return desde, hasta, inicio, fin


# ─────────────────────────────── SCRUM-93 · Exportar a CSV ───────────────────────────────
# CSV en UTF-8 con BOM y separador ";": Excel en español lo abre directo, con tildes y columnas.

def _respuesta_csv(nombre):
    respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    respuesta.write("﻿")
    return respuesta, csv.writer(respuesta, delimiter=";")


def _celda(valor):
    """Evita que Excel interprete un texto del cliente como fórmula (inyección CSV)."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return "" if valor is None else valor


def _fecha(valor):
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else ""


COLUMNAS_LEADS = ["Id", "Nombre", "Teléfono", "Etapa", "Estado", "Asesor", "Intentos con el asesor", "Intentos totales",
                  "Tipo de visa", "País de interés", "Anuncio de origen", "País de la campaña", "Anuncios distintos",
                  "Canal", "Primer contacto", "Último mensaje", "Próxima llamada", "Cerrado"]


def _es_excel(request):
    """SCRUM-51 · ?formato=xlsx → Excel; si no, CSV (también lo abre Excel)."""
    return request.GET.get("formato") == "xlsx"


@require_http_methods(["GET"])
@con_rol(*SUPERVISION)
def exportar_leads(request):
    """La lista de leads con los mismos filtros y pestaña que se están viendo, en CSV o Excel."""
    from .excel import HojaExcel
    from .forms import ORIGENES

    _activa, qs = _pestana(request, _leads_filtrados(request))
    filas = list(qs[:20000])
    excel = _es_excel(request)
    servicios.registrar_exportacion("leads", len(filas), {k: v for k, v in request.GET.items()})
    nombre = f"rumbo-leads-{timezone.localdate():%Y%m%d}"
    if excel:
        w = HojaExcel("Leads")
        fecha = lambda x: x  # noqa: E731 — Excel guarda la fecha como fecha (se puede ordenar y filtrar)
    else:
        respuesta, w = _respuesta_csv(f"{nombre}.csv")
        fecha = _fecha
    w.writerow(COLUMNAS_LEADS)
    for l in filas:
        w.writerow([_celda(x) for x in (
            l.pk, l.nombre_perfil, l.telefono, l.etapa.nombre, l.get_estado_asignacion_display(),
            l.asesor.usuario.nombre if l.asesor else "", l.intentos_asesor_actual, l.intentos_totales,
            l.tipo_visa, l.pais_interes, l.anuncio_titulo or l.anuncio_clave, l.anuncio_pais, l.n_anuncios,
            ORIGENES.get(l.origen, l.origen),
            fecha(l.primer_contacto_en), fecha(l.ultimo_mensaje_en), fecha(l.proxima_accion_en), fecha(l.cerrado_en))])
    return w.respuesta(f"{nombre}.xlsx") if excel else respuesta


@require_http_methods(["GET"])
@con_rol(*SUPERVISION)
def exportar_metricas(request):
    """Las tablas de Métricas del rango elegido, una debajo de la otra (igual que el correo semanal)."""
    from .reportes import escribir_metricas

    from .excel import HojaExcel

    desde, hasta, _inicio, _fin = _rango_metricas(request)
    nombre = f"rumbo-metricas-{desde:%Y%m%d}-{hasta:%Y%m%d}"
    if _es_excel(request):                                               # SCRUM-51
        w = HojaExcel("Métricas", encabezado_en=0)
    else:
        respuesta, w = _respuesta_csv(f"{nombre}.csv")
    _datos, filas = escribir_metricas(w, desde, hasta)
    servicios.registrar_exportacion("metricas", filas, {"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                                                        "formato": "xlsx" if _es_excel(request) else "csv"})
    return w.respuesta(f"{nombre}.xlsx") if _es_excel(request) else respuesta


# ─────────────────────────────── SCRUM-98 · Panel en vivo ───────────────────────────────

MINUTOS_INACTIVO = 60
ORDEN_ESTADO = {"disponible": 0, "ocupado": 1, "pausa": 2, "fuera_turno": 3}


def orden_urgencia(a):
    """Primero lo que necesita atención: clientes sin gestionar, por llamar, asesor inactivo; después el estado."""
    return (-a["sin_gestionar"], -a["por_llamar"], not a.get("inactivo"), ORDEN_ESTADO.get(a["estado"], 9), a["nombre"])


@require_http_methods(["GET"])
@con_rol(*SUPERVISION)
def en_vivo(request):
    """Quién está disponible, en pausa o desconectado, cuánto tiene cada uno y qué espera. HTMX cada 15 s."""
    hoy = dt.datetime.combine(timezone.localdate(), dt.time.min, timezone.get_current_timezone())
    panel = servicios.panel_en_vivo(hoy)
    ahora = timezone.now()
    for a in panel["asesores"]:
        a["estado_hace"] = servicios.hace_corto(a["estado_desde"], ahora)
        a["ultima_hace"] = servicios.hace_corto(a["ultima_llamada"], ahora)
        # SCRUM-107: disponible y sin llamar hace más de 60 min DE TURNO (desde su última llamada, desde que se
        # conectó o desde que abrió la atención hoy: la noche y el fin de semana no cuentan).
        desde = max(filter(None, [a["ultima_llamada"], a["estado_desde"], panel["inicio_turno"]]))
        a["sin_actividad_min"] = max(0, int((ahora - desde).total_seconds() // 60))
        a["sin_actividad"] = servicios.hace_corto(desde, ahora)
        a["inactivo"] = (panel["abierto"] and a["estado"] == "disponible"
                         and a["sin_actividad_min"] >= MINUTOS_INACTIVO)
    panel["asesores"].sort(key=orden_urgencia)
    contexto = {**panel, "rumbo": request.rumbo, "ahora": ahora, "minutos_inactivo": MINUTOS_INACTIVO}
    plantilla = "leads/_en_vivo.html" if request.htmx else "leads/en_vivo.html"
    return render(request, plantilla, contexto)


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
    con_error = {p for p, campos in ConfiguracionForm.PESTANAS.items() if any(c in form.errors for c in campos)}
    return render(request, "leads/configuracion.html", {
        "form": form, "rumbo": request.rumbo, "pestanas_con_error": con_error,                 # SCRUM-111
        # La primera pestaña con errores, en el orden en que se muestran.
        "pestana_inicial": next((p for p in ConfiguracionForm.PESTANAS if p in con_error), None)})
