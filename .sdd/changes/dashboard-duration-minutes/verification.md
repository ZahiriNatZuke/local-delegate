# Verificación: duraciones del panel en minutos y horas

## Entorno

- Rama `fix/dashboard-duration-minutes` desde `origin/main` (`a93408f`), worktree `D:/Projects/ld-wt-dur`.
- Windows 11, Python 3.11 (uv), node del PATH, Playwright 1.63.0 (`uv run --with`, no está en el
  `.venv` del worktree).

## Control positivo

Los tests nuevos se corrieron primero contra el `fmtSec` de `main` y fallaron por el formato:
`'116,9 s' == '1 min 57 s'`, `'60,0 s' != '1 min'` (índice de 59 960 ms, es y en), y la tarjeta de
latencia sin `exact:`. El de REQ-004 falló por la extracción (`fmtSecExact` no existía), como se
esperaba.

## Evidencia

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | `test_fmtSec_uses_minutes_and_hours_with_exact_rounding[es]`: los 14 casos de la tabla + `null` → «–» | pasa | `tests/test_dashboard_js.py` |
| REQ-002 | mismos casos: 59 940 → «59,9 s», 59 960 → «1 min», 60 000 → «1 min», 3 599 400 → «59 min 59 s», 3 599 600 → «1 h», 3 600 000 → «1 h» | pasa | ídem |
| REQ-003 | mismo test con `[en]`: «59.9 s», «0.1 s», «< 0.1 s» | pasa | ídem |
| REQ-004 | `test_only_the_exact_formatter_converts_milliseconds_to_seconds`; los cinco sitios siguen llamando a `fmtSec` | pasa | ídem |
| REQ-005 | `test_latency_card_keeps_exact_seconds_in_title` (`title="116,9 s"`, visible «1 min 57 s»); en vivo, `title` «1.002,3 s» / «1,002.3 s» con «16 min 42 s» visible | pasa | ídem y capturas |
| Escenario tarea en curso | en vivo con `elapsed_s` ≈ 947: «15 min 52 s · 120.000 car.» | pasa | `evidence/inflight-*.png`, `evidence/panel-es-*.png` |
| Escenario filas largas | actividad: «1 h 5 min» (espera 1 h · inferencia 5 min), «15 min 47 s», «1 min 57 s», «45,3 s», «2,0 s»; sin desbordar en claro ni en oscuro | pasa | `evidence/activity-*.png` |

Las capturas se hicieron con un `LOG_DIR` temporal sembrado y la app de métricas sola en `:9494`
(nunca el daemon del 9393), en claro y oscuro (`ld-theme`), es y en, y se miraron una a una.

## Controles de calidad

- [x] Suite completa: `pesado.sh uv run pytest -n 2 -q` → 4 128 passed, 28 skipped.
- [x] UI con Playwright (`tests/test_dashboard_ui.py`, en serie como en el CI): 62 passed,
  1 skipped. Con `-n 2` cuatro fallan con «el dashboard no llegó a levantar» por puertos fijos
  compartidos entre workers; el CI los corre en serie.
- [x] `uv run ruff check .` y `uv run ruff format --check .` limpios.
- [x] `metrics.py` sigue en CRLF (`git ls-files --eol`).
- [x] Detector de nombres en español: nombres nuevos (`seconds`, tests) clasificados.
- [x] Sin cambios ajenos: `metrics.py`, `tests/test_dashboard_js.py`, una línea en
  `CHANGELOG.md` › «Corrige», y esta carpeta SDD.

## Desviaciones y riesgo residual

- El `title` exacto se añadió solo a la tarjeta de latencia, que es la única de los cinco sitios
  que ya tenía `title` con el valor; la actividad y la tarea en curso no tenían `title`.
- El desglose espera/inferencia redondea cada parte por su cuenta («espera 1 min 40 s ·
  inferencia 16,9 s» para 1 min 57 s): es lo esperado con un único formateador.
