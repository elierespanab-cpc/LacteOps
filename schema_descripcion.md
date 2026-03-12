# Descripción del Esquema y Relaciones de Base de Datos

En la arquitectura del sistema LacteOps, se han diseñado políticas estrictas en el comportamiento de integridad referencial (`on_delete`) para garantizar consistencia financiera y evitar manipulación accidental de datos sensibles.

## 1. Relaciones con Restricción Suave (`on_delete=models.SET_NULL`)

### Modelo `AuditLog`
- **Llave foránea:** `usuario` a `settings.AUTH_USER_MODEL`.
- **Justificación:** Los registros de auditoría son inmutables y constituyen un diario inviolable y permanente de control. Si un usuario es eliminado del sistema, la base de datos debe almacenar el rastro de sus operaciones realizadas asignando el valor a `null` (como preservación histórica) y **NUNCA** eliminar los registros de log en caso de borrado de usuario (`str(usuario)` o su IP quedan documentados indirectamente). No se permite `CASCADE` en `AuditLog` por razones obvias de auditoría legal y financiera.

## 2. Relaciones con Restricción Fuerte (`on_delete=models.PROTECT`)

Se aplicó sistemáticamente hacia la mayoría de los registros de catálogos y transacciones ya que estos afectan directamente al cálculo del kardex, inventario y cuentas de naturaleza deudora/acreedora.
- **Relaciones de Transacciones a Maestros:**
  - `FacturaCompra` -> `Proveedor`
  - `FacturaVenta` -> `Cliente`
  - `OrdenProduccion` -> `Receta`
- **Relaciones de Detalles a Maestros:**
  - `Producto` -> `Categoria`, `UnidadMedida`
  - `Detalles` e `Insumos` -> `Producto`, `UnidadMedida`
- **Relaciones de Pagos/Cobros a Transacciones:**
  - `Pago` -> `FacturaCompra`
  - `Cobro` -> `FacturaVenta`
- **Justificación:** Los maestros de inventario (Producto), sujetos de crédito (Clientes/Proveedores) o entidades transaccionales base (Facturas, Órdenes) no pueden eliminarse bajo ninguna circunstancia si poseen operaciones asociadas. Modificar la integridad histórica eliminaría el fundamento del costo promedio registrado y de las cuentas por pagar/cobrar. La eliminación errónea se rechaza mediante una excepción controlada (ProtectedError).

## 3. Relaciones en Cascada (`on_delete=models.CASCADE`)

Solo se utiliza en relaciones de composición estricta (Patrón de Cabecera-Detalle), donde el registro hijo no tiene sentido existencial fuera del padre. 
- **Casos de Uso Aplicados:**
  - `DetalleFacturaCompra` -> `FacturaCompra`
  - `DetalleFacturaVenta` -> `FacturaVenta`
  - `RecetaDetalle` -> `Receta`
  - `ConsumoOP` -> `OrdenProduccion`
- **Justificación:** Un detalle de factura no existe independientemente de su factura. Si, durante el limitado margen que le permite la lógica transaccional, una factura es eliminada (e.g. en un estado Draft u operación revertida de bajo nivel por un administrador absoluto), sus líneas deben ser purgadas y destruidas de manera atómica junto con la factura principal. Las restricciones de negocio asegurarán que una vez asentado el documento (cerrado/cobrado/aprobado) esto no suceda directamente desde la UI normal, pero a nivel de base de datos la cascada preserva la unidad de la cabecera con sus detalles.

Estas directrices previenen la posibilidad de huérfanos transaccionales en operaciones contables de alta sensibilidad y bloquean la purga silenciosa de registros peritados.
