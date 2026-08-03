import environ
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    "django_filters",
    "simple_history",
    "django_rest_passwordreset",
]

LOCAL_APPS = [
    # Mirrored from old backend
    "apps.portfolio",
    "apps.gceo_dashboard",
    "apps.authentication",
    "apps.tl_portfolio",
    "apps.branch_portfolio",
    "apps.hf_collections",
    "apps.hfdi",
    "apps.collections_team_leaders",
    "apps.staff_management",
    "apps.exco_innitiatives",
    "apps.hf_rights_issue",
    "apps.portfolio_management_enrichment",
    # New feature apps
    "apps.analytics",
    "apps.insights",
    "apps.agent",
    "apps.slideshow",
    "apps.mortgages",
    "apps.client_briefs",
    "apps.registry",
    "apps.business_performance",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves collected static (admin / DRF / Swagger CSS) straight from
    # the app process so the container needs no separate static server. Must sit
    # immediately after SecurityMiddleware (WhiteNoise docs).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    # New application DB — all managed models and Django system tables live here
    "default": {
        "ENGINE": env("DB_ENGINE", default="django.db.backends.postgresql"),
        "NAME": env("DB_NAME", default="hf_group_app"),
        "USER": env("DB_USER", default="hf_group_app"),
        "PASSWORD": env("DB_PASSWORD", default=""),
        "HOST": env("DB_HOST", default="127.0.0.1"),
        "PORT": env("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
    },
    # Legacy data warehouse — unmanaged (read-only) models point here
    "datawarehouse": {
        "ENGINE": env("DW_ENGINE", default="django.db.backends.postgresql"),
        "NAME": env("DW_NAME", default="datawarehouse1"),
        "USER": env("DW_USER", default="postgres"),
        "PASSWORD": env("DW_PASSWORD", default=""),
        "HOST": env("DW_HOST", default="127.0.0.1"),
        "PORT": env("DW_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
        "TEST": {
            "MIRROR": "datawarehouse",  # Don't create a test DB for this one
        },
    },
}

DATABASE_ROUTERS = ["core.db_router.HFGroupRouter"]

# Cache — DatabaseCache (no Redis). Backs DRF throttling; a DB table shared by
# all gunicorn workers keeps throttle counts consistent. Create the table with
# `manage.py createcachetable` (also created automatically by the
# slideshow.0002 migration on deploy).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

# Scheduled jobs (formerly Celery beat) now run from host cron:
#   */5 * * * *  manage.py precompute_slides
#   0 */6 * * *  manage.py run_insights_pipeline

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "10000000/day",
        "otp_request": "50/hour",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "PAGE_SIZE": 10,
}

# Simple JWT — mirrors old backend settings
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=env.int("ACCESS_TOKEN_LIFETIME_DAYS", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("REFRESH_TOKEN_LIFETIME_DAYS", default=1)),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
}

# drf-spectacular
SPECTACULAR_SETTINGS = {
    "TITLE": "HF Group Portfolio Management API",
    "DESCRIPTION": "Full backend API for HF Group portfolio management and analytics",
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# CORS — mirrors old backend
CORS_ORIGIN_ALLOW_ALL = env.bool("CORS_ORIGIN_ALLOW_ALL", default=True)
# When ALLOW_ALL is off (production), the frontend origin(s) must be allowlisted
# here or the browser blocks the real request after the preflight. Comma-separated,
# full scheme+host, e.g. CORS_ALLOWED_ORIGINS=https://ceo.hfgroup.co.ke
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=True)
# CSRF trusts these origins for unsafe methods (needed for the Django admin / any
# cookie-auth POST from the frontend domain).
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.portfolio.validators.CustomPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Compress static without manifest-hashing (avoids strict "missing file" errors
# from third-party apps); WhiteNoise serves the result. `collectstatic` writes here.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email — mirrors old backend
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="smtp.office365.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="reports.analytics@hfgroup.co.ke")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Branding + access links baked into outgoing emails (OTP, password reset,
# account provisioning). Env-driven so a rename or a new host never needs a code
# change. FRONTEND_PUBLIC_URL = off-LAN/internet, FRONTEND_LAN_URL = office LAN.
APP_BRAND_NAME = env("APP_BRAND_NAME", default="HFCB")
FRONTEND_PUBLIC_URL = env("FRONTEND_PUBLIC_URL", default="https://ceo.hfgroup.co.ke")
FRONTEND_LAN_URL = env("FRONTEND_LAN_URL", default="http://128.2.1.25:5400")

# ETL report trigger (Trade Finance / Insurance / Drawdowns / Weighted Sales /
# HFDI buttons). The report scripts are owned by the data team and run on the
# HOST — they are NOT in this repo/image. core.script_trigger.ScriptTriggerAPIView
# drops a request file into this queue directory; a host-side cron watcher
# (deploy/host/etl_request_watcher.sh) runs the real report with the host's
# python3.6. In the container, bind-mount the host's
# /data/apps/datascience/etl_requests onto this path (see docs/DEPLOY.md).
ETL_REQUEST_DIR = env("ETL_REQUEST_DIR", default=str(BASE_DIR / "etl_requests"))

# OpenAI
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")

# Anthropic (Claude) — powers the data-grounded AI agent (apps.agent)
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

# Structlog
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
