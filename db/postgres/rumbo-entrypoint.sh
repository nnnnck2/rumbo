#!/bin/bash
# Envoltorio del entrypoint oficial. Si una inicialización anterior falló a mitad de camino
# (roles o migraciones incompletos), el entrypoint oficial arrancaría igual con una base
# a medio crear. Aquí se detecta y se niega a arrancar.
set -euo pipefail
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

if [ -s "$PGDATA/PG_VERSION" ] && [ ! -f "$PGDATA/rumbo_init_completo" ]; then
    echo "✗ La inicialización de la base no terminó correctamente en un arranque anterior." >&2
    echo "  Revise el log, corrija el problema y elimine el volumen de datos para reintentar." >&2
    exit 1
fi

exec docker-entrypoint.sh "$@"
