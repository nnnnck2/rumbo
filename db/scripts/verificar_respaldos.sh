#!/bin/bash
# Verifica que el archivado de WAL funciona y que los respaldos no están corruptos.
# Termina con código ≠ 0 si algo falla (sirve para alertas de cron/monitoreo).
set -euo pipefail
pgbackrest --stanza=rumbo check
pgbackrest --stanza=rumbo verify
pgbackrest --stanza=rumbo info --output=json | head -c 2000
echo
