from pathlib import Path
import os

from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY")
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.core",
    "apps.almacen",
    "apps.compras",
    "apps.ventas",
    "apps.produccion",
    "apps.bancos",
    "apps.reportes",
    "apps.socios",
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

ROOT_URLCONF = "erp_lacteo.urls"

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

WSGI_APPLICATION = "erp_lacteo.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "es-ve"
TIME_ZONE = "America/Caracas"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
MEDIA_URL = "/media/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "apps" / "static"]
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# REGLA: modificaciones en modelos que heredan de AuditableModel deben hacerse via instancia.save(),
# nunca via QuerySet.update().

LOG_DIR = BASE_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "verbose",
            "filename": str(LOG_DIR / "LacteOps.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
        },
    },
    "loggers": {
        "apps": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": True,
        },
        "django": {
            "handlers": ["console", "file"],
            "level": "WARNING",
            "propagate": True,
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
}

JAZZMIN_SETTINGS = {
    "site_title": "LacteOps",
    "site_header": "LacteOps ERP",
    "site_brand": "LacteOps",
    "welcome_sign": "Bienvenido a LacteOps",
    "theme": "default",
    "navigation_expanded": False,
    "collapsible_nav": True,
    "order_with_respect_to": [
        "ventas",
        "compras",
        "produccion",
        "almacen",
        "bancos",
        "socios",
        "reportes",
        "core",
        "auth",
    ],
    "hide_models": ["reportes.ReporteLink"],
    "icons": {
        "almacen.producto": "fas fa-boxes",
        "almacen.movimientoinventario": "fas fa-exchange-alt",
        "almacen.ajusteinventario": "fas fa-balance-scale",
        "compras.facturacompra": "fas fa-file-invoice-dollar",
        "compras.gastoservicio": "fas fa-file-invoice",
        "ventas.facturaventa": "fas fa-receipt",
        "ventas.listaprecio": "fas fa-tags",
        "ventas.detallelista": "fas fa-tag",
        "produccion.ordenproduccion": "fas fa-industry",
        "produccion.salidaorden": "fas fa-boxes",
        "core.configuracionempresa": "fas fa-building",
        "bancos.cuentabancaria": "fas fa-university",
        "bancos.movimientocaja": "fas fa-money-bill-wave",
        "bancos.transferenciacuentas": "fas fa-random",
        "bancos.movimientotesoreria": "fas fa-exchange-alt",
        "bancos.periodoreexpresado": "fas fa-calendar-check",
        "core.tasacambio": "fas fa-dollar-sign",
        "core.categoriagasto": "fas fa-tags",
        "core.auditlog": "fas fa-history",
        "socios.socio": "fas fa-user-tie",
        "socios.prestamoporsocio": "fas fa-hand-holding-usd",
    },
    "custom_links": {
        "reportes": [
            {"name": "Ventas", "url": "reportes:ventas", "icon": "fas fa-chart-line"},
            {"name": "Cuentas por Cobrar", "url": "reportes:cxc", "icon": "fas fa-hand-holding-usd"},
            {"name": "Compras", "url": "reportes:compras", "icon": "fas fa-shopping-cart"},
            {"name": "Cuentas por Pagar", "url": "reportes:cxp", "icon": "fas fa-file-invoice-dollar"},
            {"name": "Producción", "url": "reportes:produccion", "icon": "fas fa-industry"},
            {"name": "Gastos y Servicios", "url": "reportes:gastos", "icon": "fas fa-receipt"},
            {"name": "Capital de Trabajo", "url": "reportes:capital_trabajo", "icon": "fas fa-chart-pie"},
        ]
    }
}
DEFAULT_CHARSET = 'utf-8'

# Redirigir login_required al login del Admin
LOGIN_URL = "/admin/login/"

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
