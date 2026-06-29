import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(
    os.environ.get("APP_DIR") or Path(__file__).resolve().parent.parent.parent
)


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc
    if value < 1:
        raise ImproperlyConfigured(f"{name} must be greater than zero.")
    return value


SECRET_KEY = os.environ.get("SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Loom apps — uncomment as each phase lands
    "apps.accounts",
    "apps.projects",  # Phase 1
    "apps.schemas",  # Phase 2
    "apps.annotation",  # Phase 2 (models) — full UI in Phase 5
    "apps.documents",  # Phase 3
    "apps.ontology",  # Phase 4
    "apps.export",  # Phase 6
    # "apps.llm",        # Phase 12 (seam only, disabled by flag)
    "apps.audit",  # Phase 5
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "loom.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "loom.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "loom"),
        "USER": os.environ.get("DB_USER", "loom"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "loom"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Upload limits are configurable for institutional deployments, but are also
# enforced in the service layer so management commands cannot bypass them.
MAX_PDF_UPLOAD_BYTES = _positive_env_int("LOOM_MAX_PDF_UPLOAD_MB", 100) * 1024 * 1024
MAX_RIS_UPLOAD_BYTES = _positive_env_int("LOOM_MAX_RIS_UPLOAD_MB", 10) * 1024 * 1024
MAX_BUNDLE_UPLOAD_BYTES = (
    _positive_env_int("LOOM_MAX_BUNDLE_UPLOAD_MB", 500) * 1024 * 1024
)
MAX_BUNDLE_UNCOMPRESSED_BYTES = (
    _positive_env_int("LOOM_MAX_BUNDLE_UNCOMPRESSED_MB", 1000) * 1024 * 1024
)
MAX_BUNDLE_FILES = _positive_env_int("LOOM_MAX_BUNDLE_FILES", 1000)
MAX_ZIP_COMPRESSION_RATIO = _positive_env_int("LOOM_MAX_ZIP_COMPRESSION_RATIO", 200)

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# LLM proposal seam — off by default; see apps/llm/
LLM_PROPOSALS_ENABLED = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "apps.annotation": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
