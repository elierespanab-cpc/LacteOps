# HANDOFF Fase B1-GEM — Sprint 3 LacteOps

**Fecha:** 2026-03-13
**Agente:** Gemini (Modeling)
**Rama:** `sprint3`

---

## STATUS: OK

### Tareas Completadas

#### 1. Modelado en apps/core
- **TasaCambio**: Creado para el registro histórico y diario de tasas BCV/Usuario. Campo `fecha` con `unique=True`.
- **CategoriaGasto**: Creado como modelo jerárquico (padre-hija) con contextos `FACTURA` y `TESORERIA`. Hereda de `AuditableModel`.

#### 2. Módulo de Socios
- **App**: `apps.socios` creada e instalada.
- **Socio**: Modelo base transaccional creado, hereda de `AuditableModel`.

#### 3. Refactorización de Gastos (apps/compras)
- **GastoServicio**: El campo `categoria_gasto` se ha convertido de `CharField` a `ForeignKey` apuntando a `core.CategoriaGasto`.
- **Limpieza**: Se eliminó `CATEGORIA_CHOICES` del modelo ya que ahora se gestiona vía base de datos.

#### 4. Datos Maestros
- **Secuencias**: Actualizado `fixtures/secuencias.json` para incluir la serie `SOC-` destinada a préstamos de socios.

---

## Migraciones Generadas

| App | Archivo | Tipo | Descripción |
|---|---|---|---|
| **core** | `0005_tasacambio_categoriagasto.py` | Esquema | Creación de modelos de tasas y categorías. |
| **compras** | `0004_migrate_categories.py` | **Data** (RunPython) | Crea categorías por defecto (`FACTURA`) y migra datos existentes de CharField a IDs. |
| **compras** | `0005_alter_gastoservicio_categoria_gasto.py` | Esquema | Convierte formalmente el campo a ForeignKey. |
| **socios** | `0001_initial.py` | Esquema | Creación del modelo Socio. |

---

## Verificación Técnica

- **manage.py check**: `System check identified no issues (0 silenced).` ✅

## Decisiones de Diseño

1. **Separación de Migraciones**: Se optó por una migración de datos intermedia (`0004_migrate_categories`) que puebla las nuevas categorías y actualiza los strings de `GastoServicio` con los IDs correspondientes antes de realizar el `AlterField`. Esto garantiza que la conversión de tipo de dato en la base de datos sea fluida.
2. **Contextos de Categoría**: Se implementó la restricción de `unique_together` en `CategoriaGasto` para nombre y contexto, evitando duplicidad lógica pero permitiendo categorías con mismo nombre en contextos distintos (ej: "Honorarios" tanto en Factura como en Tesorería si fuera necesario).
3. **Hierarchy**: El modelo `CategoriaGasto` incluye el campo `padre` como FK recursiva para soportar el árbol de dos niveles solicitado en los requerimientos.
