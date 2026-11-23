# Verification: Modelo de visión por defecto: qwen36-35b-a3b-vision

## Environment

- Revision: rama `feat/vision-default-qwen36`, rebasada sobre `origin/main` (con #719).
- Relevant runtime and tool versions: Python 3.11 (.venv del checkout principal, `PYTHONPATH=src`), node para las funciones JS del panel, Playwright/Chromium headless para las capturas.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests/test_vision_default.py (defecto, constante ligera, la variable elige la ligera) | pass | rojos antes del cambio (`'gemma4-12b' == 'qwen36-35b-a3b-vision'`), verdes después |
| REQ-002 | tests/test_checks_role_models.py (4 tests nuevos) y mutante `light_served = False` | pass | el mutante tumba 3 de los 4 por su assert; los tests previos siguen intactos |
| REQ-003 | tests/test_dashboard_states.py (etiqueta en es y en, CSS apagado) | pass | rojos antes (sin `roleLabelsHtml` ni `.mrole.none`), verdes después |
| REQ-004 | capturas con scripts/dev/capture_dashboard.py contra la app de métricas del árbol | pass | evidence/panel-backend-light.png y evidence/panel-backend-dark.png: «SIN ROL» apagada en `gemma4-12b` y `qwen35-2b`, «VISIÓN» en `qwen36-35b-a3b-vision` |
| REQ-005 | tests/test_vision_default.py (README, wiki, recetas, skill es/en, CHANGELOG) | pass | rojos antes, verdes después |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test | `pesado.sh python -m pytest -q -n 2` (el .venv del checkout principal con `PYTHONPATH=src`, en vez de `uv run --locked pytest`) | pass | suite completa tras el rebase; ver «Deviations» |
| lint | `ruff check` y `ruff format --check` sobre los ficheros tocados | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- `tests/test_fallback.py` y `tests/test_panel_stdio_token_and_empty_host.py` fijaban el defecto viejo de visión: se actualizan al nuevo (el defecto cambió a propósito).
- El corpus `benchmarks/catalogo-2026-09` registra el modelo de cada caso: se declara el cambio en `MODEL_BOUNDARIES` de `scripts/build_corpus.py` (aviso, no error, como las fronteras de prompt) y un test nuevo comprueba que sin la declaración vuelve a ser error. El corpus no se regenera.
- `test_locate_hostile_input.py::test_a_hostile_line_costs_linearly[double_quote_escapes]` falló una vez por tiempos con la máquina cargada (40 > 25) y pasó al repetirlo; no toca este cambio.
- No se probó contra el backend real (el daemon no se reinicia en este encargo).
