from decouple import config

from .base import *

DEBUG = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "OPTIONS": {
            "client_encoding": "UTF8",
        },
    }
}

LOGGING["loggers"]["apps"]["level"] = "DEBUG"

# Acceso desde la red local (móviles y otras PCs en la misma red)
ALLOWED_HOSTS = ["*"]
