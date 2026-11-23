#!/bin/bash
# SCRUM-42 · Prueba de restauración de respaldos en un ENTORNO APARTE. Se ejecuta en el HOST, junto al
# docker-compose.yml de la base:
#
#   bash scripts/probar_restauracion.sh              # restaura el último respaldo + WAL archivado
#   NUEVO_RESPALDO=full bash scripts/probar_restauracion.sh   # toma antes un respaldo completo
#
# Qué hace (no toca la base en uso ni escribe en el repositorio de respaldos):
#   1. Anota cifras de control de la base en uso (conteos por tabla y último id de auditoría) y fuerza el
#      archivado del WAL, para que el respaldo cubra hasta ese momento.
#   2. Crea un volumen NUEVO y un contenedor aparte, sin red, con el repositorio montado en SOLO LECTURA.
#   3. Restaura con pgBackRest (descifra con la clave de db/.env) y abre esa copia con archive_mode=off
#      (la copia nunca escribe en el repositorio).
#   4. Compara las cifras de control y corre un checksum de páginas en las tablas principales.
#   5. Mide cada paso y deja un informe en logs/restauracion-AAAAMMDD-HHMM.txt. Al final borra la copia
#      (CONSERVAR=1 para dejarla y revisarla).
set -euo pipefail
cd "$(dirname "$0")/.."

proyecto="${COMPOSE_PROJECT_NAME:-rumbo}"
volumen="${proyecto}_restauracion_prueba"
contenedor="${proyecto}-restauracion-prueba"
repo="${proyecto}_respaldos"
imagen="rumbo-postgres:17"
mkdir -p logs
informe="logs/restauracion-$(date +%Y%m%d-%H%M).txt"
exec > >(tee "$informe") 2>&1

set -a; [ -f .env ] && . ./.env; set +a
: "${PGBACKREST_REPO1_CIPHER_PASS:?Falta PGBACKREST_REPO1_CIPHER_PASS (db/.env)}"

ahora() { date +%s.%N; }
dura() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f s", b - a }'; }
psql_uso() { docker compose exec -T -u postgres db psql -d rumbo -qtAX -v ON_ERROR_STOP=1 "$@"; }
psql_copia() { docker exec -u postgres "$contenedor" psql -d rumbo -qtAX -v ON_ERROR_STOP=1 "$@"; }
limpiar() {
    if [ "${CONSERVAR:-}" != "1" ]; then
        docker rm -f "$contenedor" >/dev/null 2>&1 || true
        docker volume rm "$volumen" >/dev/null 2>&1 || true
    fi
}
trap limpiar EXIT

CONTROL="
SELECT 'leads='        || count(*) FROM rumbo.lead
UNION ALL SELECT 'mensajes='     || count(*) FROM rumbo.mensaje_whatsapp
UNION ALL SELECT 'asignaciones=' || count(*) FROM rumbo.asignacion
UNION ALL SELECT 'intentos='     || count(*) FROM rumbo.intento_llamada
UNION ALL SELECT 'ventas='       || count(*) || ' total=' || coalesce(sum(valor), 0) FROM rumbo.venta
UNION ALL SELECT 'usuarios='     || count(*) FROM rumbo.usuario
UNION ALL SELECT 'auditoria_max_id=' || coalesce(max(id), 0) FROM auditoria.registro
UNION ALL SELECT 'migraciones='  || count(*) FROM meta.migracion"

echo "══ Prueba de restauración · $(date '+%Y-%m-%d %H:%M:%S %Z') · proyecto $proyecto"
echo "── Respaldos disponibles"
docker compose exec -T -u postgres db pgbackrest --stanza=rumbo info | sed 's/^/   /'

if [ -n "${NUEVO_RESPALDO:-}" ]; then
    echo "── Respaldo $NUEVO_RESPALDO previo"
    t=$(ahora); docker compose exec -T -u postgres db pgbackrest --stanza=rumbo --type="$NUEVO_RESPALDO" backup >/dev/null
    echo "   listo en $(dura "$t" "$(ahora)")"
fi

echo "── 1. Cifras de control de la base en uso"
psql_uso -c "SELECT pg_switch_wal()" >/dev/null
original="$(psql_uso -c "$CONTROL")"
echo "$original" | sed 's/^/   /'
# Esperar a que el WAL con esas cifras quede archivado (archive-async)
docker compose exec -T -u postgres db pgbackrest --stanza=rumbo check >/dev/null
echo "   WAL archivado (pgbackrest check ok)"

echo "── 2. Entorno aparte: volumen $volumen, contenedor $contenedor (sin red), repositorio en solo lectura"
docker rm -f "$contenedor" >/dev/null 2>&1 || true
docker volume rm "$volumen" >/dev/null 2>&1 || true
docker volume create "$volumen" >/dev/null

echo "── 3. Restaurar"
t0=$(ahora)
docker run --rm --network none -u postgres \
    -v "$volumen":/var/lib/postgresql/data -v "$repo":/var/lib/pgbackrest:ro \
    -e PGBACKREST_REPO1_CIPHER_PASS --entrypoint pgbackrest "$imagen" \
    --stanza=rumbo --type=default --log-level-console=warn restore
t1=$(ahora)
echo "   archivos restaurados en $(dura "$t0" "$t1")"

docker run -d --name "$contenedor" --network none -u postgres \
    -v "$volumen":/var/lib/postgresql/data -v "$repo":/var/lib/pgbackrest:ro \
    -e PGBACKREST_REPO1_CIPHER_PASS --entrypoint postgres "$imagen" \
    -c config_file=/etc/postgresql/postgresql.conf -c archive_mode=off -c listen_addresses='' >/dev/null
for _ in $(seq 1 180); do
    if docker exec -u postgres "$contenedor" psql -d rumbo -qtAX -c "SELECT NOT pg_is_in_recovery()" 2>/dev/null | grep -q t; then
        break
    fi
    sleep 1
done
t2=$(ahora)
psql_copia -c "SELECT NOT pg_is_in_recovery()" | grep -q t || { echo "✗ La copia no terminó la recuperación"; docker logs --tail 40 "$contenedor"; exit 1; }
echo "   WAL reaplicado y base abierta en $(dura "$t1" "$t2")"

echo "── 4. Verificación"
restaurada="$(psql_copia -c "$CONTROL")"
echo "$restaurada" | sed 's/^/   /'
if [ "$original" != "$restaurada" ]; then
    echo "✗ Las cifras de la copia no coinciden con la base en uso:"
    diff <(echo "$original") <(echo "$restaurada") | sed 's/^/   /'
    exit 1
fi
echo "   ✓ cifras idénticas a la base en uso"
# Lee todas las páginas de las tablas principales: con data_checksums una página dañada da error.
for tabla in rumbo.lead rumbo.mensaje_whatsapp rumbo.asignacion rumbo.intento_llamada rumbo.venta auditoria.registro; do
    psql_copia -c "SELECT sum(length(t::text)) FROM $tabla t" >/dev/null
done
echo "   ✓ páginas leídas sin errores de checksum"
psql_copia -c "SELECT 'archive_mode=' || current_setting('archive_mode')" | sed 's/^/   /'

echo "══ ✓ Restauración correcta · tiempo total (restaurar + recuperar + abrir): $(dura "$t0" "$t2")"
echo "   Informe: db/$informe"
