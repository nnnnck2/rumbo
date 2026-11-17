#!/bin/bash
# Se ejecuta UNA vez, al crear el volumen de datos (docker-entrypoint-initdb.d).
# Crea roles con mínimo privilegio, extensiones y endurece la base.
set -euo pipefail

for v in RUMBO_MIGRATOR_PASSWORD RUMBO_APP_PASSWORD RUMBO_CALLFLOW_PASSWORD RUMBO_REPLICACION_PASSWORD; do
    valor="${!v:-}"
    if [ "${#valor}" -lt 16 ]; then
        echo "La variable $v falta o tiene menos de 16 caracteres" >&2
        exit 1
    fi
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v pw_migrator="$RUMBO_MIGRATOR_PASSWORD" \
     -v pw_app="$RUMBO_APP_PASSWORD" \
     -v pw_callflow="$RUMBO_CALLFLOW_PASSWORD" \
     -v pw_replicacion="$RUMBO_REPLICACION_PASSWORD" <<'SQL'
-- Dueño de todos los objetos. No inicia sesión.
CREATE ROLE rumbo_owner NOLOGIN;

-- Aplica migraciones; entra directamente como rumbo_owner.
CREATE ROLE rumbo_migrator LOGIN PASSWORD :'pw_migrator' IN ROLE rumbo_owner;
ALTER ROLE rumbo_migrator SET role = 'rumbo_owner';
ALTER ROLE rumbo_migrator SET lock_timeout = '10s';

-- Django + Celery
CREATE ROLE rumbo_app LOGIN PASSWORD :'pw_app' CONNECTION LIMIT 60;
ALTER ROLE rumbo_app SET search_path = rumbo, pg_catalog;
ALTER ROLE rumbo_app SET statement_timeout = '15s';
ALTER ROLE rumbo_app SET lock_timeout = '5s';
ALTER ROLE rumbo_app SET idle_in_transaction_session_timeout = '30s';

-- CALLFLOW: solo lectura de las vistas api.*
CREATE ROLE rumbo_callflow LOGIN PASSWORD :'pw_callflow' CONNECTION LIMIT 5;
ALTER ROLE rumbo_callflow SET search_path = api, pg_catalog;
ALTER ROLE rumbo_callflow SET default_transaction_read_only = on;
ALTER ROLE rumbo_callflow SET statement_timeout = '30s';

-- Réplica
CREATE ROLE rumbo_replicacion LOGIN REPLICATION PASSWORD :'pw_replicacion' CONNECTION LIMIT 3;

-- Base: nadie conecta salvo los roles de Rumbo; nadie crea objetos en public.
ALTER DATABASE rumbo OWNER TO rumbo_owner;
REVOKE ALL ON DATABASE rumbo FROM PUBLIC;
GRANT CONNECT ON DATABASE rumbo TO rumbo_migrator, rumbo_app, rumbo_callflow;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CREATE ON DATABASE rumbo TO rumbo_owner;

-- Extensiones (requieren superusuario)
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- La base "postgres" tampoco es accesible para PUBLIC.
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
SQL
