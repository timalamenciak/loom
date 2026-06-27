import os

from .base import *  # noqa: F401, F403

DEBUG = os.environ.get("DEBUG", "True").strip().lower() in {"1", "true", "yes", "on"}
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-do-not-use-in-prod")
ALLOWED_HOSTS = ["*"]

# Skip compressed manifest storage in dev so collectstatic isn't required
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
