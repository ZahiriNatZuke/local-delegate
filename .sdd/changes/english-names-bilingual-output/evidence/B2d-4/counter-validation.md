# B2d-4: validación del contador de fidelidad contra revisión a mano (2026-10-17)

Hecha **antes** de aplicar el contador nuevo a la medición, como pide la regla anti-sesgo del
encargo. El cambio (`scripts/score_lint_fidelity.py`, `PYTEST_NODE`): en un log de pytest, el
número de tests **distintos** de cada fichero y el total de tests distintos cuentan como cifras que
el log respalda. Motivo: B31 (`en-log-pytest-chunking-density.txt`, salida `-rA`) nombra cada test
dos veces (línea de progreso y resumen corto), así que `test_chunking.py` sale en 82 líneas y
`test_density.py` en 32, y el contador viejo marcaba como inventados el «41» y el «16» de las
respuestas, que son los tests reales de cada fichero (41 + 16 = los 57 de la línea de total).

Método: 18 cifras de respuestas ya guardadas (`B2d-3/runs/` y `B2d-4/runs/`), elegidas para cubrir
los dos lados: las que el cambio toca (B31) y cifras de otros logs, inventadas y reales. Para cada
una, la anoté a mano leyendo el log (columna «A mano») y después la pasé por los dos contadores con
`validate_counter.py` (el viejo es `score_lint_fidelity_before.py`, copia literal del de `810f90a`).
Salida completa: `counter-validation.json`.

| # | Respuesta | Cifra | A mano | Por qué | Viejo | Nuevo |
|---|---|---|---|---|---|---|
| 1 | `B2d-4/compact/B31-r1` | 41 | del log | 41 tests distintos de `test_chunking.py` | inventada ✗ | del log ✓ |
| 2 | `B2d-4/compact/B31-r1` | 16 | del log | 16 tests distintos de `test_density.py` | inventada ✗ | del log ✓ |
| 3 | `B2d-3/step1/B31-r1` | 41 | del log | ídem | inventada ✗ | del log ✓ |
| 4 | `B2d-3/step1/B31-r1` | 16 | del log | ídem | inventada ✗ | del log ✓ |
| 5 | `B2d-3/base/B31-r1` | 44 | inventada | `test_chunking.py` tiene 41 | inventada ✓ | inventada ✓ |
| 6 | `B2d-3/base/B31-r1` | 13 | inventada | `test_density.py` tiene 16 | inventada ✓ | inventada ✓ |
| 7 | `B2d-4/compact/B31-r2` | 57 | del log | línea de total «57 passed» | del log ✓ | del log ✓ |
| 8 | `B2d-4/compact/A12-r2` | 6 | inventada | «6 instances»: hay 11 líneas `system` y 2 `max_tokens` | inventada ✓ | inventada ✓ |
| 9 | `B2d-3/step1/A15-r1` | three | inventada | el log tiene 2 D103 | inventada ✓ | inventada ✓ |
| 10 | `B2d-3/step1/A15-r1` | 36 | del log | línea 36 del primer D103 | del log ✓ | del log ✓ |
| 11 | `B2d-3/step1/A15-r1` | nine | inventada | el log tiene 6 T201 | del log ✗ | del log ✗ |
| 12 | `B2d-3/base/B35-r1` | 4 | inventada | «Resumen de Ruff (4 errores)»: el log no lo da | inventada ✓ | inventada ✓ |
| 13 | `B2d-3/base/B35-r1` | 72 | inventada | los bloques son de 45 y 40 líneas | inventada ✓ | inventada ✓ |
| 14 | `B2d-4/main-remeasure/A12-r1` | 19,000 | inventada | «19,000 lines»: el log tiene 15 | inventada ✓ | inventada ✓ |
| 15 | `B2d-4/compact/A13-r1` | 0 | inventada | «0 issues»: el log no escribe ningún 0 | inventada ✓ | inventada ✓ |
| 16 | `B2d-3/step1/B33-r1` | 52 | del log | posición `login.page.ts(52,24)` | inventada ✗ | inventada ✗ |
| 17 | `B2d-3/step1/B33-r1` | 127 | del log | posición `tech-stack.component.ts(127,5)` | inventada ✗ | inventada ✗ |
| 18 | `B2d-3/step1/A13-r2` | 255 | del log | «llama-swap: v255» | inventada ✗ | inventada ✗ |

## Resultado

| | Coincide con la revisión a mano | Control negativo (inventadas que siguen contando) |
|---|---|---|
| Contador viejo | 10 de 18 | 8 de 9 |
| **Contador nuevo** | **14 de 18** | **8 de 9** |

- **El cambio hace lo que dice y solo eso:** arregla las 4 filas de B31 y no suelta ninguna
  inventada; en el mismo log, el «44» y el «13» de la base (recuentos por fichero equivocados)
  siguen contando como inventados. Entre todas las respuestas guardadas de B2d-3 y B2d-4, las
  únicas cifras que cambian de veredicto son esas: el «41» y el «16» de B31 en `step1` y en
  `compact` (3 repeticiones cada una).
- **Fallos que quedan, los dos contadores por igual** (no los toca este cambio, y no se arreglan
  aquí a la vista de los fallos):
  - **Demasiado estricto** (3): las posiciones de `tsc` (`(52,24)` se lee como un solo número,
    `52.24`) y una versión pegada a una letra (`v255`). Cifras reales contadas como inventadas.
  - **Demasiado laxo** (1): «nine» T201 pasa porque el log tiene un 9 suelto (columna `:9:`). Es
    el límite conocido del contador: una cifra pequeña casi siempre está en algún sitio del log.
- Se aplica a la medición. Los fallos que quedan entran en las dos versiones que se comparan
  (misma vara), y se anotan en `live.md` para la siguiente revisión del contador.

## Re-cuento con los dos contadores (sin llamadas nuevas)

| Versión | Contador viejo | Contador nuevo |
|---|---|---|
| base (B2d-3, `7a17941`) | 9, 20, 6 (11,67) | 9, 20, 6 (11,67) |
| 1b (B2d-3, `20faa5e`) | 2, 5, 4 (3,67) | 2, 5, 4 (3,67) |
| 1b re-medido, 1.ª ronda (`5a5a7c0`) | 5, 5, 6 (5,33) | 5, 5, 6 (5,33) |
| compactado, 1.ª ronda (`ea5b27a`) | 20, 5, 5 (10,0) | 18, 3, 3 (8,0) |

Ficheros: `runs/rescore-*.json` y `runs/compact/score-answers.json` (contador viejo) y
`runs/rescore2-*.json` (nuevo).
