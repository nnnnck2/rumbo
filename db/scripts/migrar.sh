#!/bin/bash
# Aplica las migraciones pendientes de /migraciones en orden.
#   · Cada archivo corre en UNA transacción (si falla algo, no queda nada a medias).
#   · Se guarda el checksum: si alguien edita una migración ya aplicada, se detiene.
# Uso dentro del contenedor:  /scripts/migrar.sh
set -euo pipefail

export PGDATABASE="${PGDATABASE:-rumbo}"
export PGUSER=rumbo_migrator
export PGPASSWORD="${RUMBO_MIGRATOR_PASSWORD:?Falta RUMBO_MIGRATOR_PASSWORD}"
DIR="${MIGRACIONES_DIR:-/migraciones}"

psql -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE SCHEMA IF NOT EXISTS meta;
REVOKE ALL ON SCHEMA meta FROM PUBLIC;
CREATE TABLE IF NOT EXISTS meta.migracion (
    version     text PRIMARY KEY,
    checksum    text NOT NULL,
    aplicada_en timestamptz NOT NULL DEFAULT now()
);
SQL

for archivo in "$DIR"/*.sql; do
    version="$(basename "$archivo" .sql)"
    suma="$(sha256sum "$archivo" | cut -c1-64)"
    previa="$(psql -tAX -c "SELECT checksum FROM meta.migracion WHERE version = '${version//\'/}'")"

    if [ -n "$previa" ]; then
        if [ "$previa" != "$suma" ]; then
            echo "✗ $version ya fue aplicada pero el archivo cambió. Cree una migración nueva." >&2
            exit 1
        fi
        continue
    fi

    echo "→ aplicando $version"
    psql -v ON_ERROR_STOP=1 -q -1 \
         -f "$archivo" \
         -c "INSERT INTO meta.migracion (version, checksum) VALUES ('${version//\'/}', '$suma')"
done
echo "✓ migraciones al día"
