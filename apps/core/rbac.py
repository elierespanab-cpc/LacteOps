# -*- coding: utf-8 -*-
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from functools import wraps

def setup_groups():
    """
    Crea los grupos base del sistema y asigna permisos si es necesario.

    B9: Master y Administrador reciben 'reportes.view_reportelink' para que la
    sección de reportes sea visible en el sidebar de Jazzmin y las vistas estén
    disponibles para esos roles.
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

    # Asignar view_reportelink a Master y Administrador
    try:
        perm = Permission.objects.get(codename='view_reportelink', content_type__app_label='reportes')
        for nombre in ('Master', 'Administrador'):
            grupo = Group.objects.get(name=nombre)
            grupo.permissions.add(perm)
    except Permission.DoesNotExist:
        # La migración que crea el permiso aún no se ha ejecutado; se ignorará
        # y el permiso se asignará en la siguiente migración/deploy.
        pass

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

def usuario_en_grupo(usuario, *grupos):
    """
    Versión funcional (no decorador) de require_group.
    Retorna True si el usuario pertenece a alguno de los grupos,
    o si es superusuario. Retorna False en caso contrario.
    No lanza excepciones.
    """
    if hasattr(usuario, 'is_superuser') and usuario.is_superuser:
        return True
    return usuario.groups.filter(name__in=grupos).exists()
