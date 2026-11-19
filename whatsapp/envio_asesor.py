"""SCRUM-114 · El asesor responde por WhatsApp desde la ficha, con el número de la empresa.

Se envía en el momento (no por Celery) para que el asesor vea enseguida si salió o por qué no.
Se usa la conexión del request: la base valida el rol y que el lead sea del asesor
(rumbo.registrar_mensaje_saliente) y lo registra con su número asignado.
"""
import datetime as dt
import re

from django.db import DatabaseError, connection
from django.utils import timezone

from . import cliente

VENTANA = dt.timedelta(hours=24)
LIMITE = 4096


class NoEnviado(Exception):
    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


def ventana_abierta(lead, ahora=None):
    """(abierta, cierra_en): WhatsApp permite texto libre hasta 24 h después del último mensaje del cliente."""
    ultimo = lead.mensajes.filter(direccion="entrante").order_by("-ocurrido_en").values_list("ocurrido_en", flat=True).first()
    if not ultimo:
        return False, None
    cierra = ultimo + VENTANA
    return (ahora or timezone.now()) < cierra, cierra


def numero_de_envio(lead):
    """phone_number_id del número del asesor dueño del lead (el que verá el cliente)."""
    asesor = lead.asesor
    numero = asesor.numero_whatsapp if asesor else None
    return numero.meta_phone_number_id if numero else None


def enviar(lead, texto):
    texto = (texto or "").strip()
    if not texto:
        raise NoEnviado("Escriba el mensaje.")
    if len(texto) > LIMITE:
        raise NoEnviado(f"El mensaje es muy largo (máximo {LIMITE} caracteres).")
    abierta, _ = ventana_abierta(lead)
    if not abierta:
        raise NoEnviado("El cliente no escribe hace más de 24 h: WhatsApp solo permite plantillas aprobadas. "
                        "Llámelo o espere a que escriba.")
    pnid = numero_de_envio(lead)
    if not pnid:
        raise NoEnviado("El asesor de este cliente no tiene un número de WhatsApp conectado. Pídalo al administrador.")
    try:
        status, respuesta = cliente.llamar_api(pnid, cliente.cuerpo_texto(lead.telefono, texto))
    except cliente.SinToken:
        raise NoEnviado("WhatsApp no está configurado en este servidor (falta el token).")
    except OSError:
        raise NoEnviado("No hay conexión con WhatsApp. Intente de nuevo en un momento.")
    wamid = cliente.wamid(respuesta)
    if status != 200 or not wamid:
        raise NoEnviado(cliente.explicar_error(respuesta, status))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT rumbo.registrar_mensaje_saliente(%s, %s, %s)", [lead.pk, wamid, texto])
    except DatabaseError as exc:
        # Ya salió hacia el cliente: lo dejamos dicho para que no lo reenvíe.
        raise NoEnviado("El mensaje se envió pero no se pudo registrar en la ficha. Avise al administrador.") from exc
    return wamid


def completar(texto, lead, asesor, documentos=None, cita=None):
    """Reemplaza {nombre}, {asesor}, {documentos} y {cita} en una respuesta rápida."""
    nombre = (lead.nombre_perfil or "").split()
    reemplazos = {"{nombre}": nombre[0] if nombre else "", "{asesor}": asesor or "su asesor",
                  "{documentos}": ", ".join(documentos) if documentos else "los documentos pendientes",
                  "{cita}": cita or "la fecha acordada"}
    for k, v in reemplazos.items():
        texto = texto.replace(k, v)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r" +([,.!?])", r"\1", texto).strip()
