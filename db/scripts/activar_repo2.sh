#!/bin/bash
# Activa la copia fuera del servidor (repo2). Idempotente: desplegar.sh lo ejecuta en cada despliegue.
#   docker compose exec -T -u postgres db /scripts/activar_repo2.sh
# 1) crea la stanza en el bucket (si ya existe no hace nada)
# 2) si el bucket todavía no tiene ningún respaldo, toma el primero completo
set -euo pipefail

if [ -z "${PGBACKREST_REPO2_TYPE:-}" ]; then
    echo "repo2 no configurado (falta PGBACKREST_REPO2_TYPE): nada que hacer."
    exit 0
fi

pgbackrest --stanza=rumbo stanza-create
pgbackrest --stanza=rumbo check

if pgbackrest --stanza=rumbo --repo=2 info --output=json | grep -q '"backup":\[\]'; then
    echo "repo2 vacío: tomando el primer respaldo completo fuera del servidor…"
    pgbackrest --stanza=rumbo --repo=2 --type=full backup
fi
pgbackrest --stanza=rumbo --repo=2 info
