# HANDOFF — Fix Permisos Eliminación Admin

## Archivos Modificados
- [apps/almacen/admin.py](file:///C:/Users/elier/Documents/Desarollos/LacteOps/apps/almacen/admin.py)
- [apps/bancos/admin.py](file:///C:/Users/elier/Documents/Desarollos/LacteOps/apps/bancos/admin.py)

## Problema Detectado
Al intentar eliminar un `Producto` que tiene movimientos de inventario, el Admin de Django mostraba un error de falta de permisos ("su cuenta no tiene permiso para borrar los siguientes tipos de objetos: Movimiento de Inventario"), incluso para superusuarios.

Esto ocurría porque `MovimientoInventarioAdmin` tenía `has_delete_permission` retornado `False` de forma fija. Aunque la relación es `models.PROTECT`, el `Collector` de Django Admin verifica los permisos de eliminación de todos los objetos relacionados encontrados antes de mostrar la página de confirmación.

## Solución Implementada
Se cambió `has_delete_permission` en `MovimientoInventarioAdmin` y `MovimientoCajaAdmin` para que retorne `request.user.is_superuser`.
- Esto permite que el proceso de eliminación del Admin continúe.
- Si el objeto principal (Producto/Cuenta) tiene movimientos, Django mostrará correctamente que no se puede eliminar por estar protegido (`models.PROTECT`).
- Si no tiene movimientos, permitirá la eliminación.
- La inmutabilidad de los registros de log se mantiene intacta a nivel de modelo mediante el método `delete()` que lanza `NotImplementedError`.

## Verificación
- `python manage.py check`: 0 issues.
- `pytest`: Todos los tests pasaron (Exit code 0).
