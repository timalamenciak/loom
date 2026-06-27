"""Fast local test settings for environments without a running PostgreSQL service."""

from .dev import *  # noqa: F401, F403

DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# WhiteNoise expects a collected STATIC_ROOT, which unit tests do not need.
MIDDLEWARE = [  # noqa: F405
    middleware
    for middleware in MIDDLEWARE  # noqa: F405
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]
