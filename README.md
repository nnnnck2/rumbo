# Rumbo

Reparto automático de leads de WhatsApp para el área de visas de Multivisa.

**Stack:** Python 3.12 · Django 5.2 · PostgreSQL 17 · Celery + Redis · Bootstrap 5 + HTMX · Docker.

```
rumbo/
├── config/              proyecto Django: settings por entorno (base, dev, prod, test), urls, celery
├── core/                transacción + contexto RLS por request, healthcheck, tareas generales
├── whatsapp/            webhook de WhatsApp Cloud API, firma, bandeja de entrada, tareas
├── templates/ static/   Bootstrap + HTMX
├── docker/entrypoint.sh web | worker | beat
├── docker-compose.yml   web + worker + beat + redis
└── db/                  base de datos PostgreSQL (ver db/README.md)
```

## Levantar en local

Requisitos: Python 3.12, Docker Desktop y Git.

```bash
# 1. Base de datos (una vez)
cd db
cp .env.example .env          # claves reales
docker compose up -d --build
cd ..

# 2. Aplicación
python -m venv .venv
.venv\Scripts\activate         # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env           # DB_PASSWORD = RUMBO_APP_PASSWORD de db/.env
python manage.py migrate       # crea las tablas de Django en el esquema "django"
python manage.py createsuperuser
python manage.py runserver
```

`DB_PORT` del `.env` debe coincidir con el puerto que publica la base (`DB_PUERTO` en `db/.env`, por defecto 5432). Si en la máquina ya hay un PostgreSQL instalado en el 5432, publique la base en otro puerto (por ejemplo 5434) en los dos archivos.

Redis y Celery en local (opcional con `runserver`; en Docker ya vienen):

```bash
docker compose up -d redis
celery -A config worker -l info --pool=solo     # --pool=solo en Windows
celery -A config beat -l info
```

## Todo en Docker

```bash
cd db && docker compose up -d --build && cd ..   # la base primero (crea la red rumbo_db)
docker compose up -d --build                     # web, worker, beat y redis
docker compose ps                                # los cuatro deben estar "healthy"/"Up"
docker compose exec web python manage.py probar_celery
```

- `web` aplica las migraciones de Django al arrancar y sirve con gunicorn en `127.0.0.1:8000`.
- `worker` procesa la bandeja del webhook y las tareas programadas.
- `beat` programa: bandeja del webhook cada 30 s, `reasignar_sin_primera_llamada` cada minuto y `liberar_cola` cada 5 minutos.
- Todos tienen `restart: unless-stopped`: si un proceso cae, Docker lo vuelve a levantar.

Si la base de desarrollo ya existía antes de la migración `011_esquema_django.sql`, aplíquela así:

```bash
cd db && docker compose up -d --build && docker compose exec -u postgres db bash /scripts/migrar.sh
```

## Webhook de WhatsApp (RF-01, RF-02)

| | |
|---|---|
| URL | `https://<dominio>/whatsapp/webhook/` |
| GET | Verificación de Meta: responde `hub.challenge` si `hub.verify_token` = `WHATSAPP_VERIFY_TOKEN` |
| POST | Valida `X-Hub-Signature-256` con `WHATSAPP_APP_SECRET`. Sin firma o con firma inválida: **403** y queda en el log `rumbo.seguridad` |

Flujo de un POST válido:

1. Se guarda el evento crudo en `rumbo.webhook_evento` (idempotente por hash del cuerpo: si Meta reintenta, no se duplica) y se responde **200** al instante.
2. Se encola `whatsapp.procesar_eventos_webhook`. Si Redis no respondiera, beat lo recoge en ≤ 30 s.
3. El worker toma los eventos con `SKIP LOCKED`, y por cada mensaje llama a `rumbo.registrar_mensaje_entrante`, que crea el lead sin duplicados, guarda el mensaje y reparte. Un evento que falla queda con su error y se reintenta hasta 10 veces.

En Meta for Developers → WhatsApp → Configuración: URL de devolución = la de arriba, token de verificación = `WHATSAPP_VERIFY_TOKEN`, suscribir el campo **messages**. El número de la empresa debe estar en `rumbo.numero_whatsapp` con su `meta_phone_number_id`. Si no hay id, se busca por el número visible.

Probar sin Meta (pasa por el webhook real y escribe en la base):

```bash
python manage.py simular_mensaje_whatsapp --telefono +593991234567 --texto "Hola"
python manage.py simular_mensaje_whatsapp --firma-invalida      # debe responder 403
```

## Pruebas

```bash
python manage.py test --settings=config.settings.test    # firma, parser y endpoint (sin base)
bash db/pruebas/probar.sh                                 # garantías de la base (pila desechable)
```

## Secretos (SCRUM-20)

Ningún secreto va en el código. Todo sale de variables de entorno o de `.env`, que está en `.gitignore`. Las variables están documentadas en `.env.example` y `db/.env.example`. En producción se usa `DJANGO_SETTINGS_MODULE=config.settings.prod`: HTTPS obligatorio, HSTS y cookies seguras.

## Ramas

- `main`: lo que está en producción.
- `develop`: integración. Las ramas de trabajo (`feature/SCRUM-xx-...`) salen de `develop` y vuelven a ella con un pull request.
