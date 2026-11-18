#!/bin/sh
# web    → aplica las migraciones de Django (esquema django) y levanta gunicorn
# worker → worker de Celery
# beat   → Celery beat (tareas programadas)
set -eu

case "${1:-web}" in
    web)
        python manage.py migrate --noinput
        exec gunicorn config.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-3}" \
            --timeout 30 \
            --access-logfile -
        ;;
    worker)
        exec celery -A config worker -l "${CELERY_LOG_LEVEL:-info}" --concurrency "${CELERY_CONCURRENCY:-2}"
        ;;
    beat)
        exec celery -A config beat -l "${CELERY_LOG_LEVEL:-info}" --schedule /app/run/celerybeat-schedule
        ;;
    *)
        exec "$@"
        ;;
esac
