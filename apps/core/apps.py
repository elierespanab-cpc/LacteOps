from django.apps import AppConfig
from django.db.models.signals import post_migrate
import logging

logger = logging.getLogger(__name__)

def load_rbac(sender, **kwargs):
    from apps.core.rbac import setup_groups
    from django.core.management import call_command
    try:
        setup_groups()
        call_command('loaddata', 'rbac', verbosity=0)
        logger.info("Grupos RBAC configurados y fixture cargada correctamente.")
    except Exception as e:
        logger.warning("No se pudo configurar RBAC: %s", e)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

    def ready(self):
        post_migrate.connect(load_rbac, sender=self)
