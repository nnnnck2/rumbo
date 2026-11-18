#!/usr/bin/env bash
# Despliegue de Rumbo en el VPS con un solo comando (SCRUM-15):
#   bash /opt/rumbo/infra/scripts/desplegar.sh
# 1) trae la última versión de main   2) levanta la base (y la copia fuera del servidor si está configurada)
# 3) levanta Django + Celery + Redis (raíz)  4) primer certificado si falta y levanta nginx + certbot
# 5) instala el cron de respaldos (pide sudo la primera vez)
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RAIZ"

for f in db/.env .env infra/.env; do
    [ -f "$f" ] || { echo "Falta $f (copiar desde ${f}.example y completar)." >&2; exit 1; }
    if grep -q 'cambiar-' "$f"; then echo "Hay claves sin cambiar en $f." >&2; exit 1; fi
done

echo "▶ Código"
git pull --ff-only

echo "▶ Base de datos"
cd "$RAIZ/db"
ARCHIVOS_DB=(-f docker-compose.yml)
if grep -q '^PGBACKREST_REPO2_TYPE=' .env; then
    ARCHIVOS_DB+=(-f docker-compose.fuera-servidor.yml)
    echo "  · copia de respaldos fuera del servidor: activada"
else
    echo "  ⚠ copia de respaldos fuera del servidor: NO configurada (ver db/README.md)"
fi
docker compose "${ARCHIVOS_DB[@]}" up -d --build --wait db
docker compose "${ARCHIVOS_DB[@]}" up -d --wait db-replica
if grep -q '^PGBACKREST_REPO2_TYPE=' .env; then
    docker compose exec -T -u postgres db /scripts/activar_repo2.sh
fi

echo "▶ Aplicación (Django + Celery + Redis)"
cd "$RAIZ"
grep -q '^DJANGO_SETTINGS_MODULE=config.settings.prod' .env     || echo "  ⚠ .env no usa config.settings.prod (HTTPS, HSTS y cookies seguras quedan desactivados)"
docker compose up -d --build --remove-orphans --wait web
docker compose up -d worker beat

echo "▶ Pila pública (nginx + certbot)"
cd "$RAIZ/infra"
bash scripts/obtener_certificado.sh
docker compose up -d --remove-orphans

echo "▶ Cron de respaldos"
[ -f /etc/cron.d/rumbo ] || sudo bash scripts/instalar_cron.sh

set -a; . ./.env; set +a
echo "▶ Comprobación"
curl -fsS "https://$DOMINIO/salud" && echo "✔ https://$DOMINIO responde por HTTPS"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://$DOMINIO/")
[ "$code" = "301" ] && echo "✔ HTTP redirige a HTTPS" || echo "⚠ HTTP devolvió $code (se esperaba 301)"
