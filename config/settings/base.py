"""Settings comunes. Todo secreto o valor que cambie por entorno sale de variables de
entorno o del archivo .env (SCRUM-20). Ver .env.example."""
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# En local se lee .env; en Docker/producción las variables ya vienen del entorno
# (las del entorno tienen prioridad sobre el archivo).
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "core",
    "whatsapp",
    "leads",
    "cuentas",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Después de autenticar: abre la transacción del request y fija rumbo.usuario_id (RLS).
    "core.middleware.ContextoRumboMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cuentas.context_processors.rumbo",
            ],
        },
    },
]

# ── Base de datos ────────────────────────────────────────────────────────────────
# Conecta como rumbo_app (mínimo privilegio, RLS). La estructura de negocio la crean
# las migraciones SQL de db/migraciones; Django solo crea sus tablas en el esquema
# `django` (ver 011_esquema_django.sql).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="rumbo"),
        "USER": env("DB_USER", default="rumbo_app"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST", default="127.0.0.1"),
        "PORT": env.int("DB_PORT", default=5432),
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            # La base rechaza conexiones sin TLS. En producción usar verify-full + certificado real.
            "sslmode": env("DB_SSLMODE", default="require"),
            "options": "-c search_path=django,rumbo,pg_catalog",
            "application_name": env("DB_APPLICATION_NAME", default="rumbo-django"),
        },
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LOGIN_URL = "cuentas:login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "cuentas:login"

# ── WhatsApp Cloud API (Meta) ─────────────────────────────────────────────────────
# Token que se escribe en Meta al configurar el webhook (verificación GET).
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", default="")
# App Secret de la app de Meta: firma X-Hub-Signature-256 de cada POST (RF-02).
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET", default="")
# Token de acceso para enviar mensajes (se usa en sprints siguientes).
WHATSAPP_ACCESS_TOKEN = env("WHATSAPP_ACCESS_TOKEN", default="")
WHATSAPP_API_VERSION = env("WHATSAPP_API_VERSION", default="v21.0")

# ── Conversions API de Meta (SCRUM-92) ─────────────────────────────────────────────
# Sin estas tres variables no se envía nada a Meta (los eventos esperan hasta 7 días).
META_DATASET_ID = env("META_DATASET_ID", default="")          # Dataset (pixel) del Administrador de eventos
META_CAPI_TOKEN = env("META_CAPI_TOKEN", default="")          # Token de acceso de la Conversions API
META_WABA_ID = env("META_WABA_ID", default="")                # Id de la cuenta de WhatsApp Business
META_CAPI_TEST_CODE = env("META_CAPI_TEST_CODE", default="")  # Solo para probar en "Eventos de prueba"

# ── Celery + Redis (SCRUM-17) ─────────────────────────────────────────────────────
REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_RESULT_EXPIRES = 60 * 60 * 24 * 7          # resultados guardados una semana
CELERY_RESULT_EXTENDED = True                     # guarda nombre, args y worker de cada tarea
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_ACKS_LATE = True                      # si el worker muere, la tarea se reentrega
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 120
CELERY_TASK_SOFT_TIME_LIMIT = 90
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    # Red de seguridad: si el encolado desde el webhook falló, la bandeja se vacía igual.
    "procesar-webhook": {"task": "whatsapp.procesar_eventos_webhook", "schedule": 30.0},
    # RF-14
    "reasignar-sin-primera-llamada": {"task": "core.reasignar_sin_primera_llamada", "schedule": 60.0},
    # 017: avisos por tiempo (quedan 10 min, hora de llamar, llamadas atrasadas)
    "generar-avisos": {"task": "core.generar_avisos", "schedule": 60.0},
    # RF-13: cada 5 minutos (incluye las 9:00, apertura del horario).
    "liberar-cola": {"task": "core.liberar_cola", "schedule": crontab(minute="*/5")},
    # SCRUM-92: citas y ventas de leads de anuncios → Conversions API de Meta
    "enviar-conversiones": {"task": "whatsapp.enviar_conversiones", "schedule": 60.0},
}

# ── Logging ───────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "rumbo": {"handlers": ["console"], "level": env("RUMBO_LOG_LEVEL", default="INFO"), "propagate": False},
    },
}
