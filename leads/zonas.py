"""SCRUM-95 · Hora local del cliente según el prefijo de su teléfono.

El país de interés del lead es el DESTINO de la visa (Estados Unidos, España…), no donde vive el
cliente: por eso la hora se calcula con el prefijo internacional del número de WhatsApp.
Para países con varias zonas (EE. UU., México, Brasil…) se usa la de la capital o la más poblada.
"""
import datetime as dt
from zoneinfo import ZoneInfo

# Prefijo E.164 → (país, zona). Los más largos primero al buscar (+1809 antes que +1).
PREFIJOS = {
    "593": ("Ecuador", "America/Guayaquil"),
    "57": ("Colombia", "America/Bogota"),
    "51": ("Perú", "America/Lima"),
    "58": ("Venezuela", "America/Caracas"),
    "591": ("Bolivia", "America/La_Paz"),
    "56": ("Chile", "America/Santiago"),
    "54": ("Argentina", "America/Argentina/Buenos_Aires"),
    "595": ("Paraguay", "America/Asuncion"),
    "598": ("Uruguay", "America/Montevideo"),
    "55": ("Brasil", "America/Sao_Paulo"),
    "52": ("México", "America/Mexico_City"),
    "502": ("Guatemala", "America/Guatemala"),
    "503": ("El Salvador", "America/El_Salvador"),
    "504": ("Honduras", "America/Tegucigalpa"),
    "505": ("Nicaragua", "America/Managua"),
    "506": ("Costa Rica", "America/Costa_Rica"),
    "507": ("Panamá", "America/Panama"),
    "53": ("Cuba", "America/Havana"),
    "1809": ("Rep. Dominicana", "America/Santo_Domingo"),
    "1829": ("Rep. Dominicana", "America/Santo_Domingo"),
    "1849": ("Rep. Dominicana", "America/Santo_Domingo"),
    "1787": ("Puerto Rico", "America/Puerto_Rico"),
    "1939": ("Puerto Rico", "America/Puerto_Rico"),
    "1": ("EE. UU. / Canadá (Este)", "America/New_York"),
    "34": ("España", "Europe/Madrid"),
    "39": ("Italia", "Europe/Rome"),
    "33": ("Francia", "Europe/Paris"),
    "49": ("Alemania", "Europe/Berlin"),
    "44": ("Reino Unido", "Europe/London"),
    "351": ("Portugal", "Europe/Lisbon"),
    "41": ("Suiza", "Europe/Zurich"),
    "31": ("Países Bajos", "Europe/Amsterdam"),
    "32": ("Bélgica", "Europe/Brussels"),
    "61": ("Australia (Este)", "Australia/Sydney"),
}
_ORDEN = sorted(PREFIJOS, key=len, reverse=True)

# Fuera de este rango (hora del cliente) se avisa antes de llamar.
HORA_DESDE = dt.time(8, 0)
HORA_HASTA = dt.time(21, 0)
# SCRUM-102 · Semáforo: verde dentro de [9:00, 19:00), ámbar en los bordes, rojo fuera de [8:00, 21:00).
VERDE_DESDE = dt.time(9, 0)
VERDE_HASTA = dt.time(19, 0)


def tono_hora(hora):
    """verde | ambar | rojo según la hora local del cliente (mismas reglas que static/js/rumbo.js)."""
    if VERDE_DESDE <= hora < VERDE_HASTA:
        return "verde"
    if HORA_DESDE <= hora < HORA_HASTA:
        return "ambar"
    return "rojo"


def zona_del_telefono(telefono):
    """(país, nombre de zona IANA) según el prefijo, o None si no se reconoce."""
    digitos = (telefono or "").lstrip("+")
    if not digitos.isdigit():
        return None
    for prefijo in _ORDEN:
        if digitos.startswith(prefijo):
            return PREFIJOS[prefijo]
    return None


def hora_cliente(telefono, ahora=None):
    """{"pais", "zona", "hora" (datetime local), "inoportuna" (bool)} o None si no se sabe el país."""
    encontrado = zona_del_telefono(telefono)
    if encontrado is None:
        return None
    pais, zona = encontrado
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    local = ahora.astimezone(ZoneInfo(zona))
    tono = tono_hora(local.time())
    return {"pais": pais, "zona": zona, "hora": local, "tono": tono, "inoportuna": tono == "rojo"}
