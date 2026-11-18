"""RF-02 · Verificación de la firma X-Hub-Signature-256 que Meta pone en cada POST.

Meta firma el cuerpo crudo con HMAC-SHA256 usando el App Secret de la app:
    X-Hub-Signature-256: sha256=<hex>
"""
import hashlib
import hmac

PREFIJO = "sha256="


def calcular_firma(cuerpo: bytes, secreto: str) -> str:
    return PREFIJO + hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def verificar_firma(cuerpo: bytes, cabecera: str | None, secreto: str) -> tuple[bool, str]:
    """Devuelve (válida, motivo). Sin secreto configurado se rechaza todo (falla cerrada)."""
    if not secreto:
        return False, "WHATSAPP_APP_SECRET no configurado"
    if not cabecera:
        return False, "sin cabecera X-Hub-Signature-256"
    if not cabecera.startswith(PREFIJO):
        return False, "formato de firma desconocido"
    esperada = calcular_firma(cuerpo, secreto)
    # compare_digest: tiempo constante, no filtra cuántos caracteres coinciden.
    if not hmac.compare_digest(esperada.encode("ascii"), cabecera.strip().lower().encode("ascii", "replace")):
        return False, "firma inválida"
    return True, "ok"
