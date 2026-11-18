#!/bin/bash
# Respaldo con pgBackRest. Uso: /scripts/respaldo.sh full|diff|incr
# Respalda en repo1 (volumen local) y, si está configurado, también en repo2 (bucket fuera del VPS).
# El cron lo instala infra/scripts/instalar_cron.sh:
#   domingo 03:00 full · lunes–sábado 03:00 diff · todos los días 04:30 verificar_respaldos.sh
# Entre respaldos el WAL se archiva continuamente en todos los repositorios (archive_timeout = 60 s):
# se puede restaurar a cualquier segundo dentro de la retención.
set -euo pipefail
tipo="${1:-diff}"
case "$tipo" in full|diff|incr) ;; *) echo "Tipo inválido: $tipo (full|diff|incr)" >&2; exit 2 ;; esac

repos=(1)
[ -n "${PGBACKREST_REPO2_TYPE:-}" ] && repos+=(2)

fallo=0
for r in "${repos[@]}"; do
    echo "── repo$r · $tipo"
    pgbackrest --stanza=rumbo --repo="$r" --type="$tipo" backup || { echo "FALLO en repo$r" >&2; fallo=1; }
done
pgbackrest --stanza=rumbo info
exit $fallo
