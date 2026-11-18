# Rumbo

Reparto automático de leads de WhatsApp para el área de visas de Multivisa.

**Stack:** Python 3.12 · Django 5.2 · PostgreSQL 17 · Celery + Redis · Bootstrap 5 + HTMX · Docker.

```
rumbo/
├── config/              proyecto Django: settings por entorno (base, dev, prod, test), urls, celery
├── core/                transacción + contexto RLS por request, healthcheck, tareas generales
├── whatsapp/            webhook de WhatsApp Cloud API, firma, bandeja de entrada, tareas
├── leads/               modelos (managed=False), admin de solo lectura, acciones del lead y configuración
├── templates/ static/   Bootstrap + HTMX
├── docker/entrypoint.sh web | worker | beat
├── docker-compose.yml   web + worker + beat + redis
├── infra/               VPS: nginx + HTTPS (Let's Encrypt), despliegue y cron de respaldos (ver infra/README.md)
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

## Modelo de datos y admin (SCRUM-21)

Las tablas las crean las migraciones SQL de `db/migraciones`. `leads/models.py` las refleja con `managed = False`: Django las lee pero nunca les hace DDL. Las escrituras de negocio (reparto, etapas, intentos, ventas) van por las funciones SQL, no por `.save()`.

- `python manage.py verificar_modelos` compara los modelos con las columnas reales de `rumbo` y falla si quedaron desalineados. Hay que correrlo después de cada migración SQL nueva.
- El admin (`/admin/`) es **de solo lectura**: leads con sus mensajes, asignaciones, intentos, etapas y notas; asesores; ventas; catálogos; configuración.

### Usuarios

Cada usuario de Django necesita su fila en `rumbo.usuario` con **el mismo id** y un rol (`admin`, `supervisor` o `asesor`). Sin esa fila, la base (RLS) no le muestra nada. Mientras no exista la gestión de usuarios (SCRUM-27), el primer administrador se crea así:

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.get(username='admin').pk)"
cd db && docker compose exec -u postgres db psql -d rumbo -c   "SET ROLE rumbo_owner; INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (<id>, 'Administrador', 'admin')"
```

## Acciones sobre el lead y configuración (SCRUM-30 a 33)

| Ruta | Quién | Qué |
|---|---|---|
| `/leads/` | todos (el asesor ve solo los suyos) | Lista con filtros por etapa, estado, asesor y búsqueda. Supervisor: reasignación en lote |
| `/leads/<id>/` | dueño del lead, supervisor, admin | Ficha mínima con las acciones y el historial |
| `/leads/<id>/intento/` | dueño, supervisor, admin | RF-22: resultado de la llamada (agenda, cambio de etapa, venta, paso al siguiente asesor) |
| `/leads/<id>/etapa/` | dueño, supervisor, admin | RF-25: cambio de etapa (solo transiciones permitidas; descartar exige motivo) |
| `/leads/<id>/reasignar/` | supervisor, admin | RF-16: reasignación manual |
| `/leads/configuracion/` | admin | RF-31: horario, reglas de reparto y reintentos, textos automáticos |

- Toda escritura pasa por las funciones SQL (`leads/servicios.py`); la base valida permisos, reglas y versión. Si dos personas editan el mismo lead, la segunda recibe un aviso y la ficha se recarga.
- Las acciones son bloques reutilizables (`leads/templates/leads/_accion_*.html`) para incluirlos en la ficha completa (SCRUM-29) y en la lista de llamadas (SCRUM-28). Responden con HTMX y también funcionan sin JavaScript.
- La configuración rige desde la siguiente operación: las funciones de la base la leen en cada llamada.

## Número de prueba de Meta (SCRUM-9)

Para probar con WhatsApp real antes de tener el VPS:

1. **Meta for Developers → app Rumbo → WhatsApp → Configuración de la API**: copiar el *token de acceso temporal* (dura 24 h) y el *identificador del número de teléfono* del número de prueba, y agregar su celular en **Para** (máximo 5 destinatarios permitidos). Copiar también la *clave secreta de la app* (Configuración de la app → Básica).
2. En `.env`: `WHATSAPP_ACCESS_TOKEN=<token temporal>`, `WHATSAPP_APP_SECRET=<clave secreta>` y agregar `.trycloudflare.com` a `DJANGO_ALLOWED_HOSTS`. Luego `docker compose up -d`.
3. Dar de alta el número de prueba (solo admin puede escribir en `rumbo.numero_whatsapp`; en desarrollo se hace con el superusuario de la base):

   ```bash
   cd db && docker compose exec -u postgres db psql -d rumbo -c      "INSERT INTO rumbo.numero_whatsapp (telefono, meta_phone_number_id, conectado_api) VALUES ('+1555XXXXXXX', '<phone_number_id>', true)"
   ```

4. **Enviar**: `docker compose exec web python manage.py enviar_whatsapp_prueba --a +5939XXXXXXXX` → llega la plantilla `hello_world` a su celular.
5. **Recibir**: `bash infra/scripts/tunel_prueba.sh` abre un túnel HTTPS temporal y muestra la URL y el token para el webhook en Meta (suscribir el campo `messages`). Responder desde el celular: el mensaje entra por `/whatsapp/webhook/` y crea el lead (`docker compose logs -f web worker`). Ya dentro de la ventana de 24 h se puede contestar con `--texto "..."`. Cerrar el túnel con Ctrl+C al terminar.

## Pruebas

```bash
python manage.py test --settings=config.settings.test    # firma, parser, endpoint y modelos (sin base)
python manage.py verificar_modelos                        # modelos de Django = tablas de la base
bash db/pruebas/probar.sh                                 # garantías de la base (pila desechable)
```

## Secretos (SCRUM-20)

Ningún secreto va en el código. Todo sale de variables de entorno o de `.env`, que está en `.gitignore`. Las variables están documentadas en `.env.example` y `db/.env.example`. En producción se usa `DJANGO_SETTINGS_MODULE=config.settings.prod`: HTTPS obligatorio, HSTS y cookies seguras.

## Ramas

- `main`: lo que está en producción.
- `develop`: integración. Las ramas de trabajo (`feature/SCRUM-xx-...`) salen de `develop` y vuelven a ella con un pull request.
