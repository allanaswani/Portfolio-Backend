# syntax=docker/dockerfile:1
#
# Runtime image for hf_group_backend (Django 4.2 LTS / Python 3.12).
# Django 4.2 is used (not 6.x) because prod PostgreSQL is 12.1 and Django 6 requires PG >= 14.
# Purpose: run the new backend on a host whose SYSTEM Python is 3.6 and CANNOT
# be upgraded (RHEL uses it for yum/dnf). The container carries its own 3.13,
# so the host Python is irrelevant. See docs/DEPLOY.md.
#
# Secrets are NOT baked in: .env is excluded via .dockerignore and injected at
# runtime with `--env-file`. Migrations are NOT run here — they are a deliberate
# manual step on the shared prod DB (see DEPLOY.md "Full-replace" recipe).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    PORT=9000

WORKDIR /app

# No apt packages are needed: psycopg[binary]/psycopg2-binary bundle their own
# libpq inside the wheel, so there is nothing to compile or install from the OS.
# (Skipping apt also means the build never touches the Debian repos — which fail
# if the host clock is skewed. Fix the host clock anyway; see docs/DEPLOY.md.)

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
