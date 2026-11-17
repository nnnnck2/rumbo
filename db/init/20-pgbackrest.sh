#!/bin/bash
# Inicializa el repositorio de respaldos y toma el primer respaldo completo,
# para que exista un punto de recuperación desde el primer minuto.
set -euo pipefail

if [ -z "${PGBACKREST_REPO1_CIPHER_PASS:-}" ]; then
    echo "Falta PGBACKREST_REPO1_CIPHER_PASS (clave de cifrado de los respaldos)" >&2
    exit 1
fi

pgbackrest --stanza=rumbo stanza-create
pgbackrest --stanza=rumbo check

# Roles, migraciones y archivado de WAL listos: se marca la base como inicializada
# (antes del respaldo, para que la marca quede incluida en él y una restauración arranque).
touch "$PGDATA/rumbo_init_completo"

pgbackrest --stanza=rumbo --type=full backup
pgbackrest --stanza=rumbo info
