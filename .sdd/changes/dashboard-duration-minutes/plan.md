# Plan de implementación: duraciones del panel en minutos y horas

## Enfoque

Un solo lote, en un worktree `D:/Projects/ld-wt-dur`, rama `fix/dashboard-duration-minutes` desde
`origin/main`. Se cambia solo el formateador JS dentro de `HTML` en
`src/local_delegate/web/metrics.py` (CRLF; se conserva) y la llamada de la tarjeta de latencia.

Diseño:

- `fmtSecExact(ms)`: lo que hoy hace `fmtSec` (nulo → «–», < 50 ms → «< 0,1 s», si no
  `F1.format(ms/1000) + ' s'`).
- `fmtSec(ms)`: decide el tramo redondeando en la unidad que pinta.
  1. `tenths = Math.round(ms/100)`; si `tenths < 600` → `fmtSecExact(ms)`.
  2. `secs = Math.round(ms/1000)`; si `secs < 3600` → `M min` + (` S s` si S > 0).
  3. `mins = Math.round(ms/60000)`; `H h` + (` M min` si M > 0).
  Así 59 960 ms da «1 min» y 3 599 600 ms da «1 h» (REQ-002).
- `kpiCard` acepta un `exact` opcional para el `title`; la tarjeta de latencia pasa
  `exact: escHooks(fmtSecExact(lat))` (REQ-005). Las demás tarjetas no cambian.
- Los otros cuatro sitios ya llaman a `fmtSec`: no se tocan (REQ-004).

## Tareas ordenadas

1. **T1 — Tests primero** (`tests/test_dashboard_js.py`)
   - Añadir `fmtSecExact` a la extracción de `_formatters()` (solo si existe, como el resto).
   - Test paramétrico con la tabla de la spec en es y en en (node sobre la definición real).
   - Ajustar el caso viejo `fmtSec(116948) == "116,9 s"` a «1 min 57 s» y añadir el exacto con
     `fmtSecExact`.
   - Test del `title` de la tarjeta de latencia: ejecutar `kpiCard` con `exact` o, si el arnés no
     lo permite, comprobar en `HTML` que la llamada de latencia pasa `exact:` con `fmtSecExact`.
   - Test estático (REQ-004): `F1.format(` seguido de `/ 1000` solo aparece dentro de
     `fmtSecExact`.
   - Verificación: correrlos contra el `fmtSec` actual y comprobar que fallan **por el assert del
     formato** (no por la extracción).
   - Vuelta atrás: revertir el fichero de tests.
2. **T2 — Implementación** (`src/local_delegate/web/metrics.py`)
   - `fmtSecExact` + nuevo `fmtSec`; `exact` en `kpiCard`; llamada de la tarjeta de latencia.
   - Línea en `CHANGELOG.md` › `[Unreleased]` › «Corrige» (rebasar si choca con el otro SDD).
   - Verificación: T1 en verde; suite completa con
     `bash ~/.claude/scripts/pesado.sh uv run pytest -n 2 -q` (salida a fichero, resumen con
     `local_lint_summary`); `uv run ruff check .` y `uv run ruff format --check .`;
     `git ls-files --eol` sigue en `crlf` para `metrics.py`.
   - Vuelta atrás: revertir el commit.
3. **T3 — Verificación visual**
   - `LOG_DIR` temporal con eventos sembrados: filas de 45 s, > 1 min (116 948 ms) y > 1 h
     (3 900 000 ms) y una delegación en curso de > 15 min (`elapsed_s` ≈ 947,2).
   - App de métricas sola en `:9494` (uvicorn, como en `docs/wiki/Publishing.md`), nunca el daemon
     del 9393; navegador headless con el cerrojo `pesado.sh`.
   - Capturas en claro y oscuro (`localStorage` `ld-theme`) en
     `.sdd/changes/dashboard-duration-minutes/evidence/` del worktree; mirarlas.
   - Parar servidor y navegador al acabar.
4. **T4 — Cierre**: `verification.md`, commit firmado `fix(dashboard): …` sin coautoría, PR en
   español, CI con tope de 40 min, `gh pr checks` verde, CodeQL del PR vacío, hilos resueltos,
   squash-merge, limpieza del worktree.

## Estrategia de pruebas

- Unidad: tests con node de la tabla (es/en), fronteras y `title`.
- Integración: suite completa (`tests/test_dashboard_js.py` y resto del panel).
- Manual/E2E: capturas claro/oscuro con datos sembrados.
- Seguridad: hook `ggshield` pre-push; sin secretos ni datos reales en las capturas (datos
  sembrados).

## Migración y compatibilidad

- Solo cambia el texto pintado; ninguna API, campo JSON ni clave i18n. Tests que esperaban
  segundos para valores ≥ 60 s se ajustan en T1.

## Revisión del plan

- [x] Cada requisito tiene tarea y verificación (ver trazabilidad de la spec).
- [x] Sin operaciones destructivas; vuelta atrás por revert.
- [x] Sin dependencias ni configuración nuevas.
- [x] Sin trabajo ajeno (README, wiki y daemon fuera).
