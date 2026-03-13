from django.db import models

class ReporteLink(models.Model):
    """
    Modelo dummy para forzar la aparición de la sección de Reportes en el sidebar de Jazzmin.
    No gestionado por el ORM (no crea tabla en BD).
    """
    nombre = models.CharField(max_length=50)

    class Meta:
        managed = False
        verbose_name = "Enlace de Reporte"
        verbose_name_plural = "Reportes"
