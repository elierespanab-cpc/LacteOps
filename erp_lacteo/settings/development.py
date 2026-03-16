from .base import *

DEBUG = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LOGGING["loggers"]["apps"]["level"] = "DEBUG"

# Acceso desde la red local (móviles y otras PCs en la misma red)
ALLOWED_HOSTS = ["*"]
