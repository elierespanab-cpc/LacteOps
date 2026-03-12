import logging
from django.core.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

def aprobar_precio(detalle_lista, usuario):
    """
    Aprueba un precio en una lista de precios.
    Si la lista requiere aprobación, el usuario debe pertenecer al grupo Master o Administrador.
    """
    if detalle_lista.lista.requiere_aprobacion:
        # Check permissions
        if not usuario.groups.filter(name__in=['Master', 'Administrador']).exists():
            raise PermissionDenied("Aprobación de precios requiere grupo Master o Administrador.")

    detalle_lista.aprobado = True
    detalle_lista.aprobado_por = usuario
    detalle_lista.save(update_fields=['aprobado', 'aprobado_por'])
