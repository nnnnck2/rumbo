# PostgreSQL 17 + pgBackRest (respaldos y PITR)
# Contexto de construcción: la carpeta db/  (docker compose lo configura).
FROM postgres:17.6-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends pgbackrest openssl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /etc/postgresql/ssl /etc/pgbackrest /var/lib/pgbackrest /var/log/pgbackrest /var/spool/pgbackrest \
 # Certificado autofirmado SOLO para desarrollo. En producción se monta el certificado real
 # en /etc/postgresql/ssl (ver docker-compose.yml).
 && openssl req -new -x509 -days 825 -nodes -subj "/CN=rumbo-db" \
        -keyout /etc/postgresql/ssl/server.key -out /etc/postgresql/ssl/server.crt \
 && chown -R postgres:postgres /etc/postgresql/ssl /var/lib/pgbackrest /var/log/pgbackrest /var/spool/pgbackrest \
 && chmod 600 /etc/postgresql/ssl/server.key \
 && chmod 750 /var/lib/pgbackrest

COPY postgres/postgresql.conf       /etc/postgresql/postgresql.conf
COPY postgres/pg_hba.conf           /etc/postgresql/pg_hba.conf
COPY postgres/pgbackrest.conf       /etc/pgbackrest/pgbackrest.conf
COPY postgres/replica-entrypoint.sh /usr/local/bin/replica-entrypoint.sh
COPY postgres/rumbo-entrypoint.sh   /usr/local/bin/rumbo-entrypoint.sh
COPY init/                          /docker-entrypoint-initdb.d/
COPY migraciones/                   /migraciones/
COPY scripts/                       /scripts/

# Los scripts se ejecutan (no se "source-an") y los archivos quedan solo lectura.
RUN chmod 755 /usr/local/bin/replica-entrypoint.sh /usr/local/bin/rumbo-entrypoint.sh /docker-entrypoint-initdb.d/*.sh /scripts/*.sh \
 && chmod 644 /etc/pgbackrest/pgbackrest.conf /etc/postgresql/*.conf /migraciones/*.sql \
 && sed -i 's/\r$//' /usr/local/bin/*.sh /docker-entrypoint-initdb.d/*.sh /scripts/*.sh

ENTRYPOINT ["rumbo-entrypoint.sh"]
CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
