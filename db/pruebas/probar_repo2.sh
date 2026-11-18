#!/bin/bash
# Prueba de la copia fuera del servidor (repo2) con un servidor S3 local (VersityGW) (SCRUM-16).
# Pila desechable propia: no toca la base de desarrollo ni la de probar.sh.
#   bash pruebas/probar_repo2.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1   # Git Bash en Windows: no convertir /scripts/... a rutas de Windows

export COMPOSE_PROJECT_NAME=rumbo_repo2 DB_PUERTO=56432 DB_REPLICA_PUERTO=56433
clave() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; }
export POSTGRES_PASSWORD="$(clave)" RUMBO_MIGRATOR_PASSWORD="$(clave)" RUMBO_APP_PASSWORD="$(clave)" \
       RUMBO_CALLFLOW_PASSWORD="$(clave)" RUMBO_REPLICACION_PASSWORD="$(clave)" PGBACKREST_REPO1_CIPHER_PASS="$(clave)"
export PGBACKREST_REPO2_TYPE=s3 PGBACKREST_REPO2_S3_BUCKET=rumbo-respaldos PGBACKREST_REPO2_S3_ENDPOINT=s3 \
       PGBACKREST_REPO2_S3_REGION=us-east-1 PGBACKREST_REPO2_S3_URI_STYLE=path \
       PGBACKREST_REPO2_S3_KEY=rumboprueba PGBACKREST_REPO2_S3_KEY_SECRET="$(clave)" \
       PGBACKREST_REPO2_CIPHER_PASS="$(clave)"

RED="${COMPOSE_PROJECT_NAME}_db"
RED_S3=rumbo_repo2_s3
MINIO=rumbo_repo2_s3srv
CERTS=""
dc() { docker compose -f docker-compose.yml -f docker-compose.fuera-servidor.yml -f pruebas/repo2-s3.override.yml "$@"; }
titulo() { printf '\n\033[1m══ %s ══\033[0m\n' "$1"; }

limpiar() {
    docker rm -f "$MINIO" >/dev/null 2>&1 || true
    dc down -v --remove-orphans >/dev/null 2>&1 || true
    docker network rm "$RED_S3" >/dev/null 2>&1 || true
    if [ -n "$CERTS" ]; then rm -rf "$CERTS"; fi
}
trap limpiar EXIT
limpiar
CERTS="$(mktemp -d)"
# En Windows (Git Bash) Docker necesita la ruta nativa
command -v cygpath >/dev/null && CERTS_DOCKER="$(cygpath -m "$CERTS")" || CERTS_DOCKER="$CERTS"

titulo "Servidor S3 de prueba (VersityGW) con TLS"
docker network create "$RED_S3" >/dev/null
MSYS_NO_PATHCONV=1 docker run --rm -v "$CERTS_DOCKER:/c" alpine/openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -subj "/CN=s3" -addext "subjectAltName=DNS:s3" -keyout /c/private.key -out /c/public.crt 2>/dev/null
MSYS_NO_PATHCONV=1 docker run -d --name "$MINIO" --network "$RED_S3" --network-alias s3 \
    -e ROOT_ACCESS_KEY="$PGBACKREST_REPO2_S3_KEY" -e ROOT_SECRET_KEY="$PGBACKREST_REPO2_S3_KEY_SECRET" \
    -v "$CERTS_DOCKER:/c:ro" --tmpfs /datos versity/versitygw:v1.0.16 \
    --port :443 --cert /c/public.crt --key /c/private.key posix /datos >/dev/null
listo=0
for _ in $(seq 1 15); do
    if docker run --rm --network "$RED_S3" -e AWS_ACCESS_KEY_ID="$PGBACKREST_REPO2_S3_KEY" \
        -e AWS_SECRET_ACCESS_KEY="$PGBACKREST_REPO2_S3_KEY_SECRET" -e AWS_DEFAULT_REGION=us-east-1 \
        amazon/aws-cli:2.27.0 --endpoint-url https://s3 --no-verify-ssl s3 mb "s3://$PGBACKREST_REPO2_S3_BUCKET" \
        >/dev/null 2>&1; then listo=1; break; fi
    sleep 2
done
[ "$listo" = 1 ] || { echo "✗ no se pudo crear el bucket"; docker logs "$MINIO" 2>&1 | tail -10; exit 1; }
echo "bucket listo"

titulo "Base con repo2"
dc up --no-start --build db
docker network connect --alias s3 "$RED" "$MINIO"
dc up -d --wait db || { dc logs db 2>&1 | tail -40; exit 1; }

titulo "activar_repo2.sh (primera vez: stanza + respaldo completo en el bucket)"
dc exec -T -u postgres db /scripts/activar_repo2.sh | tail -12

titulo "activar_repo2.sh (segunda vez: idempotente, no debe repetir el completo)"
salida=$(dc exec -T -u postgres db /scripts/activar_repo2.sh)
if echo "$salida" | grep -q "tomando el primer respaldo"; then echo "✗ repitió el respaldo completo"; exit 1; fi
echo "ok"

titulo "respaldo.sh diff → debe respaldar en repo1 y repo2"
dc exec -T -u postgres db /scripts/respaldo.sh diff | grep -E "^── repo|FALLO" || true

titulo "verificar_respaldos.sh"
dc exec -T -u postgres db /scripts/verificar_respaldos.sh >/dev/null && echo "ok: check + verify en ambos repos"

titulo "Estado del bucket"
dc exec -T -u postgres db pgbackrest --stanza=rumbo --repo=2 info | sed -n '1,20p'
n=$(dc exec -T -u postgres db pgbackrest --stanza=rumbo --repo=2 info --output=json | grep -o '"type":"diff"' | wc -l)
[ "$n" -ge 1 ] && echo "✔ repo2 tiene completo + diferencial" || { echo "✗ falta el diferencial en repo2"; exit 1; }
