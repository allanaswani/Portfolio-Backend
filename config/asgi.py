import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# Plain Django ASGI. Production serves the app under WSGI (gunicorn config.wsgi)
# and there are no websocket consumers. Channels was removed along with
# Redis/Celery.
application = get_asgi_application()
