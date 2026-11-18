# Rumbo · Django + Celery (misma imagen para web, worker y beat)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod 755 docker/entrypoint.sh \
 && DJANGO_SECRET_KEY=build DB_PASSWORD=build DJANGO_ALLOWED_HOSTS=build \
    python manage.py collectstatic --noinput \
 && useradd --system --uid 1000 --home /app rumbo \
 && mkdir -p /app/run && chown rumbo:rumbo /app/run

USER rumbo
EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["web"]
