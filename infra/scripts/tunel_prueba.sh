#!/usr/bin/env bash
# Túnel HTTPS temporal hacia la app local para probar el webhook con el número de prueba
# de Meta mientras no exista el VPS (SCRUM-9). Usa un "quick tunnel" de Cloudflare:
# sin cuenta, URL aleatoria *.trycloudflare.com que cambia en cada arranque.
#
#   docker compose up -d --build        # la app (raíz), con la base ya levantada
#   bash infra/scripts/tunel_prueba.sh  # Ctrl+C para cerrar el túnel
#
# Requiere en el .env de la raíz:  DJANGO_ALLOWED_HOSTS=...,.trycloudflare.com
# ⚠ Mientras está abierto, la app local es accesible desde internet. Cerrarlo al terminar.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
NOMBRE=rumbo_tunel

grep -q '^DJANGO_ALLOWED_HOSTS=.*\.trycloudflare\.com' "$RAIZ/.env" || {
    echo "Agregue .trycloudflare.com a DJANGO_ALLOWED_HOSTS en $RAIZ/.env y reinicie web:" >&2
    echo "  docker compose up -d web" >&2
    exit 1
}
docker network inspect rumbo_web >/dev/null 2>&1 || {
    echo "No existe la red rumbo_web: levante primero la app (docker compose up -d)." >&2; exit 1; }

docker rm -f "$NOMBRE" >/dev/null 2>&1 || true
trap 'docker rm -f "$NOMBRE" >/dev/null 2>&1; echo; echo "Túnel cerrado."' EXIT INT TERM
docker run -d --name "$NOMBRE" --network rumbo_web cloudflare/cloudflared:2025.10.0 \
    tunnel --no-autoupdate --url http://web:8000 >/dev/null

URL=""
for _ in $(seq 1 30); do
    URL=$(docker logs "$NOMBRE" 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | head -1 || true)
    [ -n "$URL" ] && break
    sleep 1
done
[ -n "$URL" ] || { docker logs "$NOMBRE" 2>&1 | tail -20; exit 1; }

TOKEN=$(grep '^WHATSAPP_VERIFY_TOKEN=' "$RAIZ/.env" | cut -d= -f2-)
cat <<FIN

Túnel abierto. En Meta for Developers → app Rumbo → WhatsApp → Configuración → Webhook:
  URL de devolución de llamada:  $URL/whatsapp/webhook/
  Token de verificación:         $TOKEN
  Luego "Administrar" → suscribir el campo  messages

Ver lo que llega:  docker compose logs -f web worker
Ctrl+C para cerrar el túnel.
FIN
docker logs -f "$NOMBRE" >/dev/null 2>&1
