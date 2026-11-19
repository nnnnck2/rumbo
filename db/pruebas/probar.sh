#!/bin/bash
# Levanta una pila de PRUEBA desechable (volúmenes propios, puertos 55432/55433), corre todas
# las pruebas y la elimina. No toca la base de desarrollo.
#   bash pruebas/probar.sh            → todo
#   CONSERVAR=1 bash pruebas/probar.sh → no borra la pila al terminar
set -euo pipefail
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=rumbo_pruebas DB_PUERTO=55432 DB_REPLICA_PUERTO=55433
clave() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; }
export POSTGRES_PASSWORD="$(clave)" RUMBO_MIGRATOR_PASSWORD="$(clave)" RUMBO_APP_PASSWORD="$(clave)" \
       RUMBO_CALLFLOW_PASSWORD="$(clave)" RUMBO_REPLICACION_PASSWORD="$(clave)" PGBACKREST_REPO1_CIPHER_PASS="$(clave)"

# Las variables exportadas tienen prioridad sobre un posible db/.env de desarrollo.
dc()   { docker compose "$@"; }
psql_db() { dc exec -T -u postgres db psql -d rumbo -v ON_ERROR_STOP=1 -qtA "$@"; }
titulo() { printf '\n\033[1m══ %s ══\033[0m\n' "$1"; }

limpiar() { [ "${CONSERVAR:-}" = "1" ] || dc down -v --remove-orphans >/dev/null 2>&1 || true; }
trap limpiar EXIT

titulo "Construyendo y levantando la base de prueba"
dc down -v --remove-orphans >/dev/null 2>&1 || true
dc up -d --build --wait db
dc logs db 2>&1 | grep -E "aplicando|migraciones al día|backup command end|stanza-create command end" || true

titulo "Pruebas SQL"
for f in pruebas/[0-9][0-9]_*.sql; do
    echo "· $(basename "$f")"
    cat pruebas/_comun.sql "$f" | dc exec -T -u postgres db psql -d rumbo -v ON_ERROR_STOP=1 -q 2>&1 \
        | sed -n 's/^.*NOTICE:  /    /p; /ERROR/p'
    [ "${PIPESTATUS[1]}" -eq 0 ] || { echo "✗ falló $f"; exit 1; }
done

titulo "Concurrencia"
dc exec -T -u postgres db bash -s < pruebas/concurrencia.sh 2>&1 | sed -n 's/^.*NOTICE:  /    /p; /^ok/p; /^→/p; /FALL/p'
[ "${PIPESTATUS[0]}" -eq 0 ] || { echo "✗ falló concurrencia"; exit 1; }

titulo "Seguridad de conexión"
# Conexión sin TLS rechazada, con TLS aceptada (desde otro contenedor de la red)
red="${COMPOSE_PROJECT_NAME}_db"
if docker run --rm --network "$red" -e PGPASSWORD="$RUMBO_APP_PASSWORD" postgres:17.6-bookworm \
     psql "host=db dbname=rumbo user=rumbo_app sslmode=disable" -c "SELECT 1" >/dev/null 2>&1; then
    echo "✗ se aceptó una conexión sin TLS"; exit 1
fi
echo "    ok · conexión sin TLS rechazada"
docker run --rm --network "$red" -e PGPASSWORD="$RUMBO_APP_PASSWORD" postgres:17.6-bookworm \
     psql "host=db dbname=rumbo user=rumbo_app sslmode=require" -tAc "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()" | grep -q t
echo "    ok · conexión de la app con TLS aceptada"
if docker run --rm --network "$red" -e PGPASSWORD="$POSTGRES_PASSWORD" postgres:17.6-bookworm \
     psql "host=db dbname=rumbo user=postgres sslmode=require" -c "SELECT 1" >/dev/null 2>&1; then
    echo "✗ el superusuario pudo entrar por red"; exit 1
fi
echo "    ok · el superusuario no puede conectarse por red"
if docker run --rm --network "$red" -e PGPASSWORD="$RUMBO_APP_PASSWORD" postgres:17.6-bookworm \
     psql "host=db dbname=rumbo user=rumbo_app password=incorrecta sslmode=require" -c "SELECT 1" >/dev/null 2>&1; then
    echo "✗ se aceptó una contraseña incorrecta"; exit 1
fi
echo "    ok · contraseña incorrecta rechazada"

titulo "Alta disponibilidad: réplica en streaming"
dc up -d --wait db-replica
psql_db -c "SET ROLE rumbo_owner" -c "INSERT INTO rumbo.motivo_descarte (codigo, nombre) VALUES ('prueba_replica', 'Prueba réplica')"
for _ in $(seq 1 30); do
    if dc exec -T -u postgres db-replica psql -d rumbo -qtA -c "SELECT 1 FROM rumbo.motivo_descarte WHERE codigo = 'prueba_replica'" | grep -q 1; then
        echo "    ok · el cambio llegó a la réplica"; break
    fi
    sleep 1
done
dc exec -T -u postgres db-replica psql -d rumbo -qtA -c "SELECT 1 FROM rumbo.motivo_descarte WHERE codigo = 'prueba_replica'" | grep -q 1 \
    || { echo "✗ el cambio no llegó a la réplica"; exit 1; }
estado="$(psql_db -c "SELECT state || '/' || sync_state FROM pg_stat_replication")"
echo "    ok · replicación: $estado"
if dc exec -T -u postgres db-replica psql -d rumbo -c "SET ROLE rumbo_owner; INSERT INTO rumbo.motivo_descarte VALUES ('x','x')" >/dev/null 2>&1; then
    echo "✗ la réplica aceptó una escritura"; exit 1
fi
echo "    ok · la réplica es de solo lectura"

titulo "Respaldos y recuperación a un punto en el tiempo (PITR)"
psql_db -c "SET ROLE rumbo_owner" -c "INSERT INTO rumbo.motivo_descarte (codigo, nombre) VALUES ('pitr_antes', 'Antes del punto')"
sleep 2
objetivo="$(psql_db -c "SELECT now()")"
sleep 2
psql_db -c "SET ROLE rumbo_owner" -c "INSERT INTO rumbo.motivo_descarte (codigo, nombre) VALUES ('pitr_despues', 'Después del punto (error a deshacer)')"
psql_db -c "SELECT pg_switch_wal()" >/dev/null
dc exec -T -u postgres db pgbackrest --stanza=rumbo check >/dev/null
echo "    punto objetivo: $objetivo"
CONFIRMAR=si bash scripts/restaurar_pitr.sh "$objetivo" >/dev/null
psql_db -c "SELECT count(*) FROM rumbo.motivo_descarte WHERE codigo = 'pitr_antes'"   | grep -qx 1 || { echo "✗ PITR perdió datos anteriores al punto"; exit 1; }
psql_db -c "SELECT count(*) FROM rumbo.motivo_descarte WHERE codigo = 'pitr_despues'" | grep -qx 0 || { echo "✗ PITR no deshizo los datos posteriores"; exit 1; }
echo "    ok · restaurado al segundo exacto: lo anterior está, lo posterior se deshizo"
psql_db -c "SELECT count(*) FROM rumbo.lead" >/dev/null && echo "    ok · base abierta en lectura/escritura tras la restauración"

titulo "✓ Todas las pruebas pasaron"
