"""Django settings for SML ERP.

Every value that differs between machines, or is secret, comes from environment variables.
See `.env.example` at the repository root for the full list.
"""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()

# --- Core -------------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")  # required; no default on purpose
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
APP_VERSION = env("APP_VERSION", default="0.1.0")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "storages",
    "apps.core",
    "apps.masters",
    "apps.accounting",
    "apps.vouchers",
    "apps.payments",
    "apps.sales",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.AbsoluteSessionTimeoutMiddleware",
    "apps.core.audit.AuditMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database (PostgreSQL only) ---------------------------------------------------------
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Users, passwords and sign-in (P0-03) ----------------------------------------------
AUTH_USER_MODEL = "core.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # only to read any older hashes
]
# Key for encrypting secrets stored in the database (authenticator secrets). Required.
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY")
TOTP_ISSUER = env("TOTP_ISSUER", default="SML ERP")

LOGIN_LOCK_THRESHOLD = 5  # failed attempts...
LOGIN_LOCK_WINDOW_MINUTES = 15  # ...within this many minutes...
LOGIN_LOCK_MINUTES = 15  # ...pause sign-in for this long
TWO_FACTOR_PENDING_SECONDS = 300  # time allowed to enter the code after the password
INACTIVE_ACCOUNT_DAYS = env.int("INACTIVE_ACCOUNT_DAYS", default=90)

# Behind Nginx, the client's address is the last X-Forwarded-For entry Nginx adds.
USE_X_FORWARDED_FOR = env.bool("USE_X_FORWARDED_FOR", default=False)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Language and time ------------------------------------------------------------------
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("si", "Sinhala"), ("ta", "Tamil")]
TIME_ZONE = "Asia/Colombo"
USE_I18N = True
USE_TZ = True

# --- Static and uploaded files ----------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files (scanned invoices, drawings) live in S3-compatible storage, never on the
# web server's disk. URLs are signed and expire quickly (spec 2, Security).
AWS_S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default=None)
AWS_ACCESS_KEY_ID = env("S3_ACCESS_KEY", default=None)
AWS_SECRET_ACCESS_KEY = env("S3_SECRET_KEY", default=None)
AWS_STORAGE_BUCKET_NAME = env("S3_BUCKET", default="sml-erp")
AWS_S3_REGION_NAME = env("S3_REGION", default="us-east-1")
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = env.int("S3_URL_EXPIRE_SECONDS", default=300)
AWS_DEFAULT_ACL = None
AWS_S3_FILE_OVERWRITE = False
AWS_S3_ADDRESSING_STYLE = "path"

STORAGES = {
    "default": {"BACKEND": "storages.backends.s3.S3Storage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# --- REST API ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    # Every endpoint requires a fully signed-in user unless it explicitly opts out (rule 8).
    "DEFAULT_PERMISSION_CLASSES": ["apps.core.permissions.IsFullyAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Money and quantities travel as strings, so no floating point rounding (rule 1).
    "COERCE_DECIMAL_TO_STRING": True,
    # Extra brake on sign-in attempts from one address, on top of the account lock.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"login": env("LOGIN_RATE", default="20/minute")},
}
if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(
        "rest_framework.renderers.BrowsableAPIRenderer"
    )

# --- Background jobs --------------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_BEAT_SCHEDULE = {
    # Daily housekeeping for access (spec 1.3), shortly after midnight Sri Lanka time.
    "notify-expired-access": {
        "task": "apps.core.tasks.notify_expired_access",
        "schedule": crontab(hour=0, minute=10),
    },
    "deactivate-inactive-accounts": {
        "task": "apps.core.tasks.deactivate_inactive_accounts",
        "schedule": crontab(hour=0, minute=20),
    },
    # Notification emails not yet sent (e.g. the worker was down when they were made).
    "send-waiting-notification-emails": {
        "task": "apps.core.tasks.send_waiting_notification_emails",
        "schedule": crontab(minute="*/5"),
    },
    # Approvers reminded of documents waiting too long (P1-09), early on working mornings.
    "send-approval-reminders": {
        "task": "apps.core.tasks.send_approval_reminders",
        "schedule": crontab(hour=7, minute=40),
    },
    # Quotations past their validity date (P15-06), just after midnight Sri Lanka time.
    "expire-quotations": {
        "task": "apps.sales.tasks.expire_quotations",
        "schedule": crontab(hour=0, minute=30),
    },
    "tidy-old-notifications": {
        "task": "apps.core.tasks.tidy_old_notifications",
        "schedule": crontab(hour=1, minute=10),
    },
}

# --- Email ------------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="SML ERP <no-reply@localhost>")
# The address people open the ERP at; links in emails start with it.
APP_URL = env("APP_URL", default="http://localhost:8080")

# --- Security ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
# Idle timeout: the session expires after this many minutes without any request.
SESSION_COOKIE_AGE = env.int("SESSION_IDLE_MINUTES", default=30) * 60
SESSION_SAVE_EVERY_REQUEST = True
# Absolute timeout: signed out this many hours after signing in, however active.
SESSION_ABSOLUTE_HOURS = env.int("SESSION_ABSOLUTE_HOURS", default=12)
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"
# SAMEORIGIN: the ERP shows its own scanned PDFs in frames (review page, viewer); other
# sites still cannot frame it (clickjacking).
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CONTENT_TYPE_NOSNIFF = True
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", default=True)
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
