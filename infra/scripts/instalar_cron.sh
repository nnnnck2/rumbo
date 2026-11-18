#!/usr/bin/env bash
# Programa los respaldos de la base en el VPS (SCRUM-16). Ejecutar con sudo.
#   Domingo 03:00      respaldo completo
#   Lunes–sábado 03:00 respaldo diferencial
#   Todos los días 04:30 verificación (check + verify); si falla queda en el log con "FALLO"
# El WAL se archiva de forma continua (cada 60 s como máximo) entre respaldos.
# Hora del servidor: America/Guayaquil (la fija aprovisionar_vps.sh).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Ejecutar con sudo." >&2; exit 1; }

RAIZ="${RAIZ:-/opt/rumbo}"
USUARIO="${USUARIO:-rumbo}"
LOG=/var/log/rumbo/respaldos.log
install -d -o "$USUARIO" -g "$USUARIO" /var/log/rumbo

EXEC="cd $RAIZ/db && docker compose exec -T -u postgres db"

cat > /etc/cron.d/rumbo <<CRON
# Rumbo · respaldos de PostgreSQL (generado por infra/scripts/instalar_cron.sh)
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

0  3 * * 0    $USUARIO  { date; $EXEC /scripts/respaldo.sh full || echo "FALLO respaldo full"; } >> $LOG 2>&1
0  3 * * 1-6  $USUARIO  { date; $EXEC /scripts/respaldo.sh diff || echo "FALLO respaldo diff"; } >> $LOG 2>&1
30 4 * * *    $USUARIO  { date; $EXEC /scripts/verificar_respaldos.sh || echo "FALLO verificación"; } >> $LOG 2>&1
CRON
chmod 644 /etc/cron.d/rumbo

cat > /etc/logrotate.d/rumbo <<ROT
$LOG {
    weekly
    rotate 12
    compress
    missingok
    notifempty
}
ROT

systemctl reload cron 2>/dev/null || true
echo "✔ Cron instalado en /etc/cron.d/rumbo (log: $LOG)"
