from decouple import config

from .base import *

DEBUG = False

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

# ── Seguridad de cookies y sesión (DIM-01-002) ──────────────────────────────
SESSION_COOKIE_SECURE = True        # Solo enviar cookie por HTTPS
SESSION_COOKIE_HTTPONLY = True      # No accesible desde JavaScript
SESSION_COOKIE_SAMESITE = "Strict"  # Protección CSRF cross-site
SESSION_COOKIE_AGE = 28800          # Sesión expira a las 8 horas

CSRF_COOKIE_SECURE = True           # Cookie CSRF solo por HTTPS
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="https://localhost",
).split(",")

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
