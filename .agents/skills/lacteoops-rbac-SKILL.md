# lacteoops-rbac

## Descripción
Matriz completa de roles y permisos del sistema LacteoOps. Úsala cuando trabajas en permisos, vistas, decoradores de acceso, validaciones de rol, middleware de autorización, o cualquier lógica que dependa de quién puede hacer qué.

## Úsala cuando
- Construyes o modificas vistas que requieren control de acceso
- Implementas permisos en la API REST o en el Admin
- Validas si un usuario puede ejecutar una acción específica
- Diseñas formularios o interfaces que muestran/ocultan campos según el rol
- Escribes tests que verifican que un rol NO puede acceder a algo

## No la uses cuando
- La tarea es puramente de modelos de datos sin lógica de permisos
- La tarea es de cálculos financieros (usa reglas-globales.md)
- La tarea es de scaffolding o estructura de proyecto

---

## ROLES DEL SISTEMA (5 roles)

### MASTER (Representante Legal)
Acceso de consulta completo a todos los módulos.

Acciones exclusivas que solo Master puede ejecutar:
- Aprobar ajustes de inventario de monto alto (umbral configurable)
- Aprobar anulaciones de documentos ya procesados (facturas aprobadas, OP cerradas)
- Cambios en recetas de producción
- Configurar comisiones de agentes de ventas
- Ejecutar Hard Close (cierre definitivo de período)
- Habilitar producción con stock negativo en casos excepcionales

Restricción crítica: Master NO registra transacciones operativas directamente.

---

### ADMINISTRADOR (Gestión Financiera y Tesorería)
Acceso completo a: Tesorería, Presupuesto, Reportes gerenciales, CxC, CxP.

Puede ejecutar:
- Aprobar facturas de compra (cambio de estado RECIBIDA → APROBADA)
- Aprobar ajustes de inventario de monto bajo
- Autorizar sobreejecución presupuestaria
- Registrar cobros de clientes
- Registrar pagos a proveedores
- Ejecutar Soft Close (cierre suave de período — bloquea ordinarios, permite APC)

No puede:
- Crear facturas de compra ni de venta
- Registrar producción ni consumos
- Aprobar ajustes de monto alto (eso es Master)

---

### JEFE DE PRODUCCIÓN
Acceso completo a: Producción (OP, Recetas, CIF), Inventarios (Kardex, Almacenes, Conteos).

Puede ejecutar:
- Crear, abrir y cerrar Órdenes de Producción
- Registrar consumos de materias primas
- Solicitar ajustes de inventario (quedan en estado PENDIENTE)
- Realizar conteos físicos de inventario

No puede:
- Aprobar sus propios ajustes de inventario (segregación obligatoria)
- Acceder a Tesorería, Compras ni Ventas
- Aprobar facturas

---

### ASISTENTE DE COMPRAS
Acceso a: Módulo Compras, Maestro Proveedores, Reportes de Compras y CxP.

Puede ejecutar:
- Registrar facturas de compra (estado inicial: RECIBIDA)
- Crear y gestionar proveedores
- Crear Órdenes de Compra
- Consultar reportes de compras y cuentas por pagar

No puede:
- Aprobar sus propias facturas (segregación obligatoria)
- Acceder a Ventas, Tesorería ni Producción
- Registrar pagos

---

### ASISTENTE DE VENTAS
Acceso a: Módulo Ventas, Maestro Clientes, Maestro Agentes de Ventas, Reportes de Ventas y CxC.

Puede ejecutar:
- Emitir facturas de venta (estado inicial: EMITIDA — descarga inventario)
- Crear y gestionar clientes
- Crear pedidos y remisiones
- Consultar reportes de ventas y cuentas por cobrar

No puede:
- Registrar cobros (eso es Administrador)
- Acceder a Compras, Tesorería ni Producción
- Configurar comisiones de agentes (eso es Master)

---

## TABLA DE SEGREGACIÓN CRÍTICA

Toda acción con doble control (quien registra ≠ quien aprueba):

| Acción                        | Registra             | Aprueba               |
|-------------------------------|----------------------|-----------------------|
| Factura de Compra             | Asistente Compras    | Administrador         |
| Pago a Proveedor              | Administrador        | —                     |
| Factura de Venta              | Asistente Ventas     | —                     |
| Cobro de Cliente              | Administrador        | —                     |
| Ajuste Inventario monto bajo  | Jefe Producción      | Administrador         |
| Ajuste Inventario monto alto  | Jefe Producción      | Master                |
| Soft Close                    | Administrador        | —                     |
| Hard Close                    | —                    | Master                |
| Anulación doc. procesado      | Rol origen           | Master                |
| Cambio en Receta              | Jefe Producción      | Master                |

---

## REGLA DE ORO DE SEGREGACIÓN

Ningún usuario puede registrar Y aprobar la misma transacción.
Esta regla no tiene excepciones, ni siquiera para Master.
Si el sistema detecta que el aprobador es el mismo que el registrador,
debe bloquear la operación con un error descriptivo.

---

## IMPLEMENTACIÓN EN DJANGO (Sprint 1+)

En el Sprint 0 se usa superusuario. A partir del Sprint 1:
- Cada rol se implementa como un Group de Django
- Los permisos se asignan a nivel de Group, no de User
- Un User solo puede pertenecer a un Group (un rol)
- Los decoradores @permission_required o @user_passes_test
  verifican el Group del usuario antes de ejecutar cualquier vista o acción
- Las Admin Actions también deben verificar permisos antes de ejecutar
