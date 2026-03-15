# HANDOFF_BQA — Fase B-QA Sprint 4

## STATUS: OK ✅

## Agente: Gemini (Fase B-QA)
## Fecha: 2026-03-14
## Rama: sprint4

---

## Resultado pytest

```
119 passed in 15.10s
```

**0 failures. 0 errors. 0 warnings bloqueantes.**

---

## Archivos de test incorporados (Sprint 4)

### tests/test_score_riesgo.py — 5 tests ✅
| Test | Descripción |
|------|-------------|
| test_score_cliente_sin_deuda | S=85 (neutro) para clientes nuevos |
| test_score_cliente_deuda_60d | Penalización de Solvencia según mora crítica |
| test_slope_negativo_bonifica | Tendencia mejora score si ADD disminuye |
| test_slope_positivo_penaliza | Tendencia castiga score si ADD aumenta |
| test_utilizacion_limite_credito | Ratio saldo/limite afecta Solvencia |

### tests/test_precio_ponderado_leche.py — 3 tests ✅
| Test | Descripción |
|------|-------------|
| test_precio_ponderado_ultima_semana | Cálculo exacto sobre entradas de los últimos 7 días |
| test_fallback_costo_promedio | Si no hay entradas, usa costo_promedio y marca sin_datos |
| test_producto_sin_flag_ignorado | Solo incluye productos con es_materia_prima_base=True |

### tests/test_proyeccion_caja.py — 4 tests ✅
| Test | Descripción |
|------|-------------|
| test_proyeccion_incluye_prestamos | Deducción de préstamos SOC por vencer en 7 días |
| test_proyeccion_total_usd | Consolidación de cuentas VES (vía TasaCambio) y USD |
| test_proyeccion_facturas_aprobadas | Solo considera facturas en rango de fecha_vencimiento |

### tests/test_tasa_automatica.py — 4 tests ✅
| Test | Descripción |
|------|-------------|
| test_emitir_ves_sin_tasa_lanza_error | Bloqueo si no hay tasa cargada para fecha>=factura |
| test_emitir_ves_busca_fecha_futura | Búsqueda retrospectiva/prospectiva mínima (filter gte) |
| test_tasa_asignada_de_TasaCambio | Verificación de self.tasa_cambio actualizada en emitir() |
| test_emitir_usd_no_requiere_tasa | USD no valida tasa BCV |

### tests/test_notificaciones.py — 4 tests ✅
| Test | Descripción |
|------|-------------|
| test_generar_stock_minimo | Creación de notificación activa al cruzar stock_minimo |
| test_desactivacion_automatica_stock | Se marca activa=False al reponer inventario |
| test_evitar_duplicados | Comando es idempotente via update_or_create |
| test_notificacion_tasa_no_cargada | Genera alerta si falta tasa para hoy |

### tests/test_require_group_superuser.py — 3 tests ✅
| Test | Descripción |
|------|-------------|
| test_superuser_bypassea_grupos | is_superuser=True tiene acceso total (v4.0) |
| test_usuario_en_grupo_funciona | Validación funcional de usuario_en_grupo() |
| test_usuario_sin_grupo_rechazado | Denegación de acceso para usuarios base |

---

## Distribución de tests por archivo (119 total)

| Archivo | Tests |
|---------|-------|
| Originales (Sprint 2/3) | 96 |
| `test_score_riesgo.py` | 5 |
| `test_precio_ponderado_leche.py` | 3 |
| `test_proyeccion_caja.py` | 4 |
| `test_tasa_automatica.py` | 4 |
| `test_notificaciones.py` | 4 |
| `test_require_group_superuser.py` | 3 |
| **TOTAL** | **119** |

---

## Mejoras de Estabilidad (Hotfixes aplicados)

1.  **Migración 0003**: Corregida ruta de `loaddata` de `'fixtures/secuencias.json'` a `'secuencias'`.
2.  **Configuración**: Añadido `FIXTURE_DIRS` en `base.py` para compatibilidad con entornos de prueba.
3.  **Lógica Ventas**: Movida la validación de `tasa_cambio` al inicio de `emitir()` para asegurar cumplimiento de pre-requisitos antes de validar precios.

---

## Próximo paso sugerido

QA del Sprint 4 finalizado con **119 tests en verde**. El sistema garantiza integridad en:
- RBAC (Bypaseo de superusuario).
- Modelado financiero (Tasa automática VES).
- Análisis & KPIs (Score de Riesgo, Ponderado Leche, Flujo de Caja).
- Notificaciones (Alertas automáticas de stock y tasas).

Proceed to merge with `main`.
