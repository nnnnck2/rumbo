#!/bin/bash
# Réplica en espera activa (hot standby) por streaming replication.
# Si el volumen está vacío, clona el primario con pg_basebackup y crea el slot de replicación.
set -euo pipefail

: "${PRIMARIO_HOST:=db}"
: "${SLOT_REPLICA:=replica1}"
PGDATA=/var/lib/postgresql/data

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "[réplica] esperando al primario ${PRIMARIO_HOST}..."
    until pg_isready -h "$PRIMARIO_HOST" -p 5432 -q; do sleep 2; done

    echo "[réplica] clonando el primario..."
    PGPASSWORD="$RUMBO_REPLICACION_PASSWORD" PGSSLMODE=require \
        pg_basebackup -h "$PRIMARIO_HOST" -U rumbo_replicacion -D "$PGDATA" \
                      -X stream -R -C -S "$SLOT_REPLICA" --checkpoint=fast -P
    chmod 700 "$PGDATA"
fi

exec postgres -c config_file=/etc/postgresql/postgresql.conf
