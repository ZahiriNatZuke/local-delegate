# Plan de implementación: restos menores

## Enfoque

Cinco lotes con ficheros disjuntos; L1–L4 en paralelo, cada uno en su worktree y su PR. L5 (medición
en vivo contra el backend, GPU) va después, solo, porque compite por la GPU y el turno del daemon.
La sesión principal revisa y mezcla cada PR (squash) cuando `gh pr checks` está verde y CodeQL a 0.
Reglas comunes en `brief.md`.

| Lote | Worktree / rama | Ficheros | REQ |
|---|---|---|---|
| L1 autocompletado | `D:/Projects/ld-wt-l1` / `fix/completion-leftovers` | `install.py`, `shell_profiles.py`, `cli.py`, `update.py`, `completion.py`, i18n `install`/`cli`, `tests/test_completion_*`, `tests/test_shell_profiles.py`, `tests/conftest.py` (fixture) | 005–011 |
| L2 doctor | `D:/Projects/ld-wt-l2` / `fix/doctor-utf8-and-backup` | `checks.py` (+ módulo de `doctor` si el check vive en otro), i18n `doctor`, `tests/test_checks.py`, `docs/wiki/` (página de `doctor`) | 012, 013 |
| L3 panel | `D:/Projects/ld-wt-l3` / `fix/dashboard-theme-and-booleans` | `web/metrics.py`, `tests/test_dashboard_js.py` y tests UI del panel, capturas en `evidence/` | 001, 002 |
| L4 test de parámetros | `D:/Projects/ld-wt-l4` / `test/backend-params-once-per-operation` | solo tests (`tests/test_backend_params*.py` o el que corresponda) | 003 |
| L5 medición | sin worktree para medir; rama `docs/code-reasoning-budget` para la wiki | `docs/wiki/` (página de `backend-params`), `evidence/` | 004 |

## Tareas por lote

Cada lote: (1) tests primero y comprobación de que fallan por el assert correcto; (2) cambio;
(3) suite completa con `pesado.sh` + `-n 2`, `uv run ruff check .`, `uv run ruff format --check .`,
`git ls-files --eol` sin cambios de fin de línea; (4) línea en `CHANGELOG.md` `[Unreleased]`;
(5) commit firmado, PR, `gh pr checks` y CodeQL; (6) `evidence/<lote>.md`.

- **L3** añade verificación visual: app de métricas sola en `:9494` con `LOG_DIR` sembrado (ver
  `docs/wiki/Publishing.md` «Captura contra el repo»), nunca el daemon del 9393; capturas con
  `prefers-color-scheme` claro y oscuro sin elección guardada, y con elección guardada contraria al
  sistema; mirarlas.
- **L4** demuestra el control positivo: un mutante que resuelva por llamada hace fallar el test por
  el assert de los parámetros (no por otra cosa) y se revierte.
- **L5**: `local-delegate test-window start --label «L5 presupuesto code»` antes y `stop <id>`
  después; criterio fijado por escrito antes de medir; `--repeat 3`; las respuestas no pasan por el
  contexto (script que las guarda a fichero, como `evidence/B2d-2/run_live.py`).

## Estrategia de pruebas

- Unidad/integración: tests nuevos por REQ; suite completa por lote.
- Manual: capturas del panel (L3); `doctor` con HOME simulado y ficheros sembrados (L2); `install`
  y `uninstall` con HOME simulado (L1).
- Seguridad: hook `ggshield` pre-push; el aviso de la `.bak` no imprime contenido.

## Migración y compatibilidad

- `doctor` gana dos avisos que solo aparecen si hay algo que avisar: en esta PC, la `.bak` existe y
  dará WARN hasta que el usuario la borre (esperado). Sin cambios de API ni de campos JSON.

## Revisión del plan

- [x] Cada REQ tiene lote y verificación.
- [x] Ficheros disjuntos entre lotes paralelos (solo `CHANGELOG.md` compartido: rebasar).
- [x] Sin dependencias nuevas; vuelta atrás por revert de cada PR.
- [x] Comandos pesados serializados con `pesado.sh`; L5 aparte por la GPU.
