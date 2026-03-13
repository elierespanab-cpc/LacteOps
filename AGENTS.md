# Instrucciones para Agentes — LacteOps ERP

## ⚠️ RAMA DE TRABAJO OBLIGATORIA

```
git checkout sprint3
```

**Todos los agentes (Claude Code, Codex, Gemini) DEBEN trabajar en la rama `sprint3`.**
No escribir código en `main`. No crear ramas propias salvo indicación explícita del desarrollador.

---

## Contexto del proyecto

- **Stack:** Python 3.11 / Django 4.2 / SQLite (dev) / PostgreSQL 15 (prod) / Jazzmin / Waitress
- **Directorio raíz:** `C:\Users\elier\Documents\Desarollos\LacteOps`
- **Reglas de negocio:** leer `.agents/rules/reglas-globales-1.md` y `.agents/rules/reglas-globales-2.md` antes de cualquier tarea

## Estado actual

| Sprint | Estado | Tests |
|--------|--------|-------|
| Sprint 0 + 1 | ✅ COMPLETO | 60 tests |
| Sprint 2 | ✅ COMPLETO | 75 tests en verde |
| Sprint 3 | 🔄 EN CURSO | meta: ~105 tests |

## Convenciones críticas (no negociables)

- `DecimalField(18,6)` costos / `DecimalField(18,2)` totales — **NUNCA float**
- `transaction.atomic()` + `select_for_update()` en toda operación que modifique stock o saldo
- Modelos transaccionales heredan `AuditableModel`
- `MovimientoInventario`, `MovimientoCaja`, `AuditLog`: **INMUTABLES**
- `generar_numero()` = único punto de numeración
- `registrar_movimiento_caja()` = único punto para modificar saldo_actual

## Antes de empezar cualquier fase

1. `git checkout sprint3`
2. Leer el HANDOFF correspondiente a tu fase (si existe)
3. `python manage.py check` → debe retornar 0 issues
4. Al terminar: crear `HANDOFF_<FASE>.md` en la raíz con archivos modificados, resultado de `check` y decisiones tomadas
