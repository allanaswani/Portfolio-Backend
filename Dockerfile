# syntax=docker/dockerfile:1
#
# Runtime image for hf_group_backend (Django 6.0.5 / Python 3.13).
# Purpose: run the new backend on a host whose SYSTEM Python is 3.6 and CANNOT
# be upgraded (RHEL uses it for yum/dnf). The container carries its own 3.13,
# so the host Python is irrelevant. See docs/DEPLOY.md.
#
# Secrets are NOT baked in: .env is excluded via .dockerignore and injected at
# runtime with `--env-file`. Migrations are NOT run here — they are a deliberate
# manual step on the shared prod DB (see DEPLOY.md "Full-replace" recipe).

FROM python:3.13.1-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    PORT=9000

WORKDIR /app

# libpq5 for Postgres client libs; curl for container healthchecks.
# (psycopg[binary]/psycopg2-binary ship wheels, so no compiler is needed.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static (admin / DRF / Swagger) into STATIC_ROOT so WhiteNoise can serve
# them. SECRET_KEY here is a THROWAWAY used only so settings import during the
# build — it is NOT the runtime key. The real SECRET_KEY is injected at run time
# via --env-file and never appears in the image or git.
RUN SECRET_KEY="build-only-do-not-use" python manage.py collectstatic --noinput

# Run as non-root.
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 9000

# Gunicorn binds ${PORT} on all interfaces. With `--network=host` at run time
# this IS the host port, so set PORT to whatever port the OLD backend used
# (same-port cutover -> no new firewall rule, no Security ticket).
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 3 --timeout 120 --access-logfile - --error-logfile -"]
