#!/bin/bash
# Respaldo con pgBackRest. Uso: /scripts/respaldo.sh full|diff|incr
# Programación recomendada en el VPS (crontab del host):
#   0 3 * * 0   docker compose -f /opt/rumbo/db/docker-compose.yml exec -T -u postgres db /scripts/respaldo.sh full
#   0 3 * * 1-6 docker compose -f /opt/rumbo/db/docker-compose.yml exec -T -u postgres db /scripts/respaldo.sh diff
#   30 4 * * *  docker compose -f /opt/rumbo/db/docker-compose.yml exec -T -u postgres db /scripts/verificar_respaldos.sh
# Entre respaldos el WAL se archiva continuamente (archive_timeout = 60 s): se puede
# restaurar a cualquier segundo dentro de la retención.
set -euo pipefail
tipo="${1:-diff}"
case "$tipo" in full|diff|incr) ;; *) echo "Tipo inválido: $tipo (full|diff|incr)" >&2; exit 2 ;; esac
pgbackrest --stanza=rumbo --type="$tipo" backup
pgbackrest --stanza=rumbo info
