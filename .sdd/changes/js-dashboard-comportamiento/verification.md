# Verification: El JS del panel se prueba ejecutandolo

## Environment

- Base `e59c554` (`main`, tras el PR #111); rama `test/js-dashboard-comportamiento`.
- node v24, `TZ=America/Havana` forzada dentro de los tests.

## Evidence

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001..005 | los seis presets de `computeRange` | ✅ 5 tests |
| REQ-002 | «hoy» en medianoche local | ✅ hora/min/seg = 0,0,0 y el ISO **no** es `T00:00:00` |
| REQ-003 | 7 y 30 días incluyen hoy | ✅ cuenta exacta de días |
| REQ-004 | el último día entero | ✅ `to` a las 23:59:59 |
| REQ-006 | clave del día local | ✅ `2026-03-10T02:00:00Z` → `2026-03-09` local, `2026-03-10` en UTC |
| REQ-007 | `byDay` | ✅ agrupa, ordena e ignora fechas ilegibles |
| REQ-008 | `agg` | ✅ suma, descarta ceros, ordena descendente |
| REQ-009 | `fmtHace` | ✅ las diez fronteras |
| REQ-010 | zona fijada | ✅ sin ella, el mutante de UTC no caería |

### Verificación al revés: 10 mutantes, 9 cazados y 1 inaplicable

| Mutante | Quién lo caza |
| --- | --- |
| `localDayKey` con `toISOString()` | **dos** tests: el del día local y el de `byDay` |
| «hoy» en medianoche UTC | `test_hoy_empieza_en_TU_medianoche_*` |
| off-by-one en el preset de 7 días | `test_los_presets_de_dias_incluyen_hoy[7-7]` |
| el rango personalizado corta el último día | `test_el_rango_personalizado_*` |
| `agg` deja pasar los ceros | `test_agg_descarta_las_categorias_a_cero` |
| `agg` ordena al revés | `test_agg_suma_por_clave_*` |
| `fmtHace` se pasa una frontera | `test_fmtHace_cambia_de_unidad_*` |
| `byDay` revienta con `ts` ilegible | `test_byDay_ignora_un_ts_ilegible_*` |
| **`byDay` sale sin ordenar** | `test_byDay_agrupa_*` (tras arreglarlo) |
| preset desconocido → «todo el histórico» | *no se pudo aplicar*: el patrón del mutante no casaba |

**El de `byDay` sin ordenar no caía en la primera pasada**, y por un fallo del test: los eventos
de prueba ya entraban en orden cronológico, así que quitar el `sort` no cambiaba el resultado. Se
reescribieron en orden inverso —que además es como llegan del backend, más recientes primero— y
ahora cae. **Cuarta vez en esta sesión que aparece el mismo patrón: el test no podía ver lo que
decía comprobar.**

## Quality checks

- [x] `uv run pytest -q` → **652 passed, 1 skipped** (640 al empezar el change).
- [x] `uv run ruff check .` → `All checks passed!`
- [x] `uv run ruff format --check .` → `68 files already formatted`
- [x] Sin secretos.
- [x] `metrics.py` **no se toca**: el diff son tests y CHANGELOG.

## Deviations and residual risk

- **Un mutante no se pudo aplicar** por un patrón mal escrito, no porque el test fallara. El
  requisito que cubre (REQ-005) sí tiene su test.
- **No se prueba la interacción real**: clics, cambio de página en la tabla, foco. Eso sí pediría
  un navegador, y queda fuera por decisión.
- **Los tests se acoplan al texto del código** (recortan por la cabecera de la función). Es el
  precio ya aceptado por el test de paridad; renombrar una función rompe el test, que es un fallo
  ruidoso y no silencioso.
- **`subprocess` con entorno recortado mata a node en Windows** (SIGABRT). El entorno se hereda
  entero con `TZ` encima, y queda anotado en el propio código para que nadie lo «optimice».
