from .base import *

DEBUG = False
CORS_ORIGIN_ALLOW_ALL = False

# ── Security headers ────────────────────────────────────────────────────────
# Safe, non-breaking hardening applied unconditionally.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Django admin / any session-cookie auth is HTTPS-only in production.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True

# TLS-topology-dependent controls — env-gated (default OFF) so they can be turned
# on once it's confirmed HTTPS terminates in front of the app with the proxy
# forwarding X-Forwarded-Proto (turning these on behind plain HTTP causes a
# redirect loop). Enable via SECURE_SSL_REDIRECT=1 / SECURE_HSTS_SECONDS=31536000.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
if env.bool("USE_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ── Error logging ───────────────────────────────────────────────────────────
# Django's built-in logging config filters the console handler behind
# require_debug_true, so with DEBUG = False an unhandled 500 is routed only to
# the mail_admins handler — and ADMINS is empty here. The traceback was being
# thrown away, which is why a 500 in the browser left nothing in
# `docker logs hf-backend` to diagnose it with. Send django.request errors to
# stdout so the container log carries them; root stays at WARNING so this does
# not turn into a firehose.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        # exc_info rides along on this one, so the full traceback is printed.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
