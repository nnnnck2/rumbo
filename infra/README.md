# Rumbo · infraestructura del VPS (SCRUM-15)

Pila pública: **nginx** (HTTPS, proxy inverso) + **certbot** (Let's Encrypt con renovación automática).

En el VPS corren tres pilas de Docker Compose:

| Pila | Archivo | Servicios |
|---|---|---|
| Base | `db/docker-compose.yml` | PostgreSQL primario + réplica + pgBackRest |
| Aplicación | `docker-compose.yml` (raíz) | Django (`web`), Celery `worker` y `beat`, Redis |
| Pública | `infra/docker-compose.yml` | nginx + certbot |

nginx solo ve a `web`, por la red `rumbo_web`. `web`, `worker` y `beat` llegan a la base por `rumbo_db`, y Redis queda en la red interna de la aplicación.

```
Internet ──443──► nginx ══rumbo_web══► web (Django/gunicorn) ══rumbo_db══► db ──► db-replica
          └─80──► nginx: desafío ACME, /salud y redirección a HTTPS
                          worker / beat (Celery) ──► redis (red interna, sin puerto)
```

## Requisitos (SCRUM-12)

- VPS con **Ubuntu 24.04 LTS**, mínimo 2 vCPU / 4 GB RAM / 40 GB de disco.
- Un dominio (o subdominio) con registro **A** apuntando a la IP del VPS.
- Un bucket S3 compatible para la copia de respaldos fuera del servidor (ver `db/README.md`).

## Instalación desde cero

```bash
# 1. En el VPS, como root (una sola vez): Docker, usuario rumbo, cortafuegos, fail2ban, swap…
curl -fsSL https://raw.githubusercontent.com/nnnnck2/rumbo/main/infra/scripts/aprovisionar_vps.sh -o aprovisionar.sh
sudo bash aprovisionar.sh "ssh-ed25519 AAAA… clave-publica"

# 2. Como usuario rumbo: secretos
cd /opt/rumbo
cp db/.env.example db/.env        # claves: openssl rand -base64 32  (+ PGBACKREST_REPO2_*)
cp .env.example .env              # Django y WhatsApp (ver abajo)
cp infra/.env.example infra/.env  # DOMINIO, CORREO_LETSENCRYPT

# 3. Desplegar (también sirve para cada actualización)
bash infra/scripts/desplegar.sh
```

En el `.env` de la raíz, para producción:

```ini
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_ALLOWED_HOSTS=<DOMINIO>
DJANGO_CSRF_TRUSTED_ORIGINS=https://<DOMINIO>
DB_PASSWORD=<RUMBO_APP_PASSWORD de db/.env>
```

`desplegar.sh` hace `git pull`, levanta la base (con la copia fuera del servidor si está configurada), la aplicación (espera a que `web` esté sana), obtiene el primer certificado si falta, levanta nginx + certbot, instala el cron de respaldos y al final comprueba que `https://DOMINIO/salud` responde y que HTTP redirige a HTTPS.

> Para ensayar sin gastar el límite de Let's Encrypt (5 certificados por semana para el mismo dominio), poner `LETSENCRYPT_STAGING=1` en `infra/.env`. Antes del certificado real, borrar el de prueba con `docker compose run --rm --entrypoint sh certbot -c 'rm -rf /etc/letsencrypt/live/* /etc/letsencrypt/archive/* /etc/letsencrypt/renewal/*'`.

## Qué cubre cada criterio de SCRUM-15

| Criterio | Dónde |
|---|---|
| VPS con Docker Compose (web, worker, Redis, PostgreSQL) | `aprovisionar_vps.sh`, `docker-compose.yml`, `infra/docker-compose.yml`, `db/docker-compose.yml` |
| Nginx como proxy inverso | `nginx/templates/rumbo.conf.template` |
| Certificado Let's Encrypt con renovación automática | `obtener_certificado.sh` (primero) + servicio `certbot` (cada 12 h) + nginx se recarga cada 12 h |
| HTTPS y redirección HTTP → HTTPS | bloque `listen 80` → `301 https://…`; HSTS en 443 |
| Despliegue documentado en un comando | `scripts/desplegar.sh` |

## Seguridad

- Solo los puertos 22, 80 y 443 están abiertos (ufw). PostgreSQL y gunicorn escuchan solo en `127.0.0.1` y Redis no publica puertos.
- SSH: sin root ni contraseñas cuando se instala la clave pública; fail2ban bloquea los intentos repetidos.
- Las actualizaciones de seguridad de Ubuntu se instalan automáticamente.
- TLS 1.2/1.3, HSTS, `X-Frame-Options`, `nosniff`, sin versión de nginx.
- Límites de peticiones: general 20/s, `/admin/login/` 5/min, webhook 50/s.
- `/whatsapp/webhook/` reenvía el cuerpo intacto para que Django valide la firma `X-Hub-Signature-256` de Meta (SCRUM-19).
- Los estáticos los sirve Django con WhiteNoise (con caché de larga duración), así que nginx no necesita un volumen propio.

## Operación

| Tarea | Comando (en `/opt/rumbo/infra`) |
|---|---|
| Ver estado | `docker compose ps` (en la raíz: la aplicación) |
| Logs de nginx | `docker compose logs -f nginx` |
| Forzar renovación (prueba) | `docker compose run --rm certbot renew --dry-run` |
| Log de respaldos | `tail -f /var/log/rumbo/respaldos.log` |
