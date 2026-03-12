# -*- coding: utf-8 -*-
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from functools import wraps

def setup_groups():
    """
    Crea los grupos base del sistema y asigna permisos si es necesario.
    """
    grupos = [
        'Master',
        'Administrador',
        'Jefe Producción',
        'Asistente Compras',
        'Asistente Ventas'
    ]
    for nombre in grupos:
        Group.objects.get_or_create(name=nombre)

def require_group(*grupos):
    """
    Decorador de vista para verificar que el usuario pertenece a uno de los grupos dados.
    Si el usuario es superusuario, siempre se le permite el acceso.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser:
                return func(request, *args, **kwargs)
            
            if not request.user.groups.filter(name__in=grupos).exists():
                raise PermissionDenied(f"No tiene permisos requeridos. Debe pertenecer a uno de: {', '.join(grupos)}.")
            
            return func(request, *args, **kwargs)
        return wrapper
    return decorator
