# Verification: Doctor detecta el plugin de Claude importado en Codex: hooks.json con modules rechazado (#668)

## Environment

- Revision: rama `fix/codex-plugin-claude-incompatible` sobre `b4669c85`
- Relevant runtime and tool versions: Python 3.11 del `.venv` del checkout principal con `PYTHONPATH=src`; ruff del mismo `.venv`; Codex CLI 0.169.0 (npm, Windows); código de Codex leído en `openai/codex` etiqueta `rust-v0.169.0`

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | validador contra fixtures, formas sueltas, `type` no textual, control positivo con todos los eventos y tipos | pass | tests/test_codex_plugin.py; mutantes «modules aceptado», «args aceptado» y «user_config ignorado» matados |
| REQ-002 | cada fixture y el `hooks.json` empaquetado cargados como plugin en Codex 0.169.0 real (`codex plugin marketplace add` + `codex plugin add` + `hooks/list` del app-server) con un `CODEX_HOME` temporal por caso | pass | empaquetado y `hooks_modules`: 0 hooks y aviso «unknown field `modules`, expected `description` or `hooks` at line 3 column 11»; `hooks_unknown_type`: 0 hooks y «unknown variant `http`»; `hooks_args_user_config`: 1 hook con comando `${user_config.ld_bin}` sin argumentos, sin aviso; `hooks_codex_native`: 2 hooks, sin aviso, `trustStatus` untrusted. Hash de `~/.codex/config.toml` igual antes y después |
| REQ-003 | check con el plugin empaquetado habilitado, con `args`, con tabla sin `enabled`, dos marketplaces | pass | tests/test_codex_plugin.py; mutante «rechazo como ok» matado |
| REQ-004 | sin plugin, deshabilitado, solo en caché, sin hooks, formato de Codex, sin Codex | pass | tests/test_codex_plugin.py; mutante «enabled ignorado» matado. «Solo en caché = no carga» y «tabla sin `enabled` = habilitado» citados de `loader.rs` (`configured_plugins`, `unwrap_or(true)`) |
| REQ-005 | instantánea del HOME, `config.toml` roto tras habilitar, JSON roto, no UTF-8, anidado hondo, sin permiso, fichero donde va carpeta | pass | test_the_check_only_reads y los tests de robustez de tests/test_codex_plugin.py |
| REQ-006 | `install` con destino Codex en HOME temporal | pass | test_install_for_codex_writes_no_plugin |
| REQ-007 | recuento 36 en docstring, tests de contrato, wiki y textos es/en | pass | tests/test_checks.py, tests/test_wiki.py, tests/test_doctor.py, tests/test_doctor_english.py, tests/test_i18n_parity.py |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| ruff check (ficheros tocados) | sí | pass | All checks passed |
| ruff format (ficheros tocados) | sí | pass | formateados |
| pytest de la zona (codex_plugin, checks, wiki, doctor, doctor_english, i18n, detect_spanish_names) | sí | pass | 347 passed, 1 skipped tras los arreglos de la revisión |
| mutantes de control positivo (5) | sí | pass | los 5 matados antes y después de la revisión, ficheros restaurados |
| pytest suite entera con -n 2 | sí | pass tras arreglo | 7741 passed, 1 failed: cuatro palabras nuevas sin clasificar en el léxico (incompatible, market, marketplaces, subdirs), clasificadas como inglés; el test pasa |
| Codex 0.169.0 real con CODEX_HOME temporal | sí | pass | fila de REQ-002 |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- No se probó el despacho de un hook en Codex: exigiría aprobar su confianza, y el encargo prohíbe
  saltarse esa revisión o escribir `trusted_hash`. La carga se probó con `hooks/list`, que es lo
  que Codex lee al arrancar. El despacho real queda para la entrega nativa (#669).
- Las reglas copian Codex 0.169.0; una versión posterior puede aceptar o rechazar otras claves.
  El texto del check nombra la versión con la que se comparó.
- No se validan los tipos de valor (un `command` numérico): Codex también rechazaría esos
  ficheros; el `ok` de formato correcto ya dice que no prueba carga.
