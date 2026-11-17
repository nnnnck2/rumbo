#!/bin/bash
# Restauración a un punto en el tiempo (PITR). Se ejecuta en el HOST, junto al docker-compose.yml.
#   ./scripts/restaurar_pitr.sh "2027-01-15 10:42:00-05"
# Detiene la base, restaura el último respaldo anterior a ese momento, reaplica el WAL
# hasta ese segundo y vuelve a abrir la base. Lo posterior a ese momento se descarta.
set -euo pipefail
cd "$(dirname "$0")/.."

objetivo="${1:?Indique la fecha y hora objetivo, p. ej. \"2027-01-15 10:42:00-05\"}"

echo "⚠ Se restaurará la base al estado del $objetivo. Lo posterior se pierde."
if [ "${CONFIRMAR:-}" != "si" ]; then
    read -r -p "Escriba 'si' para continuar: " r
    [ "$r" = "si" ] || { echo "Cancelado."; exit 1; }
fi

docker compose stop db-replica db
docker compose run --rm --no-deps -u postgres --entrypoint pgbackrest db \
    --stanza=rumbo --delta --type=time "--target=$objetivo" --target-action=promote restore
docker compose up -d db

echo "Esperando a que la base termine la recuperación..."
for _ in $(seq 1 60); do
    if docker compose exec -T -u postgres db psql -d rumbo -tAc "SELECT NOT pg_is_in_recovery()" 2>/dev/null | grep -q t; then
        echo "✓ Base restaurada y abierta."
        echo "  La réplica quedó en la línea de tiempo anterior: recréela con"
        echo "  docker compose rm -sf db-replica && docker volume rm <proyecto>_replica_datos && docker compose up -d db-replica"
        exit 0
    fi
    sleep 2
done
echo "✗ La base no terminó la recuperación; revise: docker compose logs db" >&2
exit 1
