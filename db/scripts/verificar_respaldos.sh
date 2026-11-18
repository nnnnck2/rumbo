#!/bin/bash
# Verifica que el archivado de WAL funciona y que los respaldos no están corruptos,
# en repo1 y (si está configurado) en repo2 fuera del servidor.
# Termina con código ≠ 0 si algo falla (sirve para alertas de cron/monitoreo).
set -euo pipefail

repos=(1)
[ -n "${PGBACKREST_REPO2_TYPE:-}" ] && repos+=(2)

# check prueba el archivado de WAL en todos los repositorios configurados
pgbackrest --stanza=rumbo check
for r in "${repos[@]}"; do
    pgbackrest --stanza=rumbo --repo="$r" verify
done
pgbackrest --stanza=rumbo info --output=json | head -c 2000
echo
