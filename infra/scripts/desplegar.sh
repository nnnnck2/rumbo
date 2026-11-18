#!/usr/bin/env bash
# Despliegue de Rumbo en el VPS con un solo comando (SCRUM-15):
#   bash /opt/rumbo/infra/scripts/desplegar.sh
# 1) trae la última versión de main   2) levanta la base (y la copia fuera del servidor si está configurada)
# 3) primer certificado si falta        4) levanta nginx, certbot, Redis y, si existe app/, Django + Celery
# 5) instala el cron de respaldos (pide sudo la primera vez)
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RAIZ"

for f in db/.env infra/.env; do
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

echo "▶ Pila pública"
cd "$RAIZ/infra"
bash scripts/obtener_certificado.sh
PERFILES=()
if [ -f "$RAIZ/app/Dockerfile" ] && [ -f "$RAIZ/app/.env" ]; then
    PERFILES=(--profile app)
    echo "  · aplicación Django encontrada: se despliega web + worker + beat"
else
    echo "  · todavía no hay app/ (SCRUM-14): solo nginx, certbot y Redis"
fi
docker compose "${PERFILES[@]}" up -d --build --remove-orphans
if [ ${#PERFILES[@]} -gt 0 ]; then
    docker compose --profile app exec -T web python manage.py collectstatic --noinput
fi

echo "▶ Cron de respaldos"
[ -f /etc/cron.d/rumbo ] || sudo bash scripts/instalar_cron.sh

set -a; . ./.env; set +a
echo "▶ Comprobación"
curl -fsS "https://$DOMINIO/salud" && echo "✔ https://$DOMINIO responde por HTTPS"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://$DOMINIO/")
[ "$code" = "301" ] && echo "✔ HTTP redirige a HTTPS" || echo "⚠ HTTP devolvió $code (se esperaba 301)"
