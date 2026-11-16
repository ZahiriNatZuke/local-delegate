# Verification: Codex: matriz de capacidades y alternativas para barra, comandos sin modelo y tools fijadas (#671)

## Environment

- Revision: rama `feat/codex-capability-matrix` sobre `main` `05529e3c`.
- Relevant runtime and tool versions: Python 3.14 del `.venv` del checkout con `PYTHONPATH=src`;
  Codex CLI 0.169.0 (npm, Windows), `CODEX_HOME` temporal en el scratchpad; fuente de Codex
  `rust-v0.169.0` (clon parcial, solo lectura).

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | review de `docs/wiki/Codex-capabilities.md` contra `research.md` | pass | cada fila cita código de Codex o de este repo, o una ejecución; enlazada desde `README.md` («El mod en Codex») y `docs/wiki/Home.md` |
| REQ-002 | `tests/test_codex_direct_tools.py` (flag, sin flag, lista a mano, una línea con espacios y comentario, varias líneas, `--no`, lista vacía, aviso, `update` por pin y por reparación) | pass | 26 passed; control contra `src` de `main`: 20 failed, 6 passed (los 6 son controles negativos o guardas de regresión: sin flag no se inventa la clave, los flags se excluyen, un valor no lista no se arrastra, el camino de pin de `update` que ya conservaba la línea y los dos `doctor` callados) |
| REQ-003 | `test_doctor_says_the_tools_are_direct`, `test_doctor_is_silent_without_deferred` | pass | ídem |
| REQ-004 | `codex debug prompt-input -c mcp_servers.local-delegate.required=true` con la tabla que arman las funciones del instalador (`codex_mcp_block` + `codex_exposure` + `upsert_codex_mcp`; no la CLI, para no escribir fuera del scratchpad), y la receta exacta de la wiki | pass | encendida: 11 tools `mcp__local_delegate__local_*`, 99 691 bytes; apagada: 0 tools, 83 891 bytes; receta: 11 y 0; sin log de uso escrito |
| REQ-005 | review de las secciones «Comandos sin modelo» y «Barra de estado» | pass | `tui/src/slash_command.rs`, `status_line_setup.rs`, `chat_composer.rs`, `tasks/user_shell.rs`; ningún código de producto nuevo para barra ni comandos |
| REQ-006 | review de `CHANGELOG.md` `[Unreleased]` y la fila nueva de `Integration-install.md` | pass | entrada «Codex: matriz de capacidades y tools directas (#671)» |
| REQ-007 | `test_the_new_texts_exist_in_both_languages`, `tests/test_i18n_parity.py` | pass | 5 claves en es y en, distintas entre sí |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test | `bash ~/.claude/scripts/pesado.sh python -m pytest -n 1 -q` con `PYTHONPATH=src`, solo ficheros afectados y vecinos, en cuatro tandas: (1) `test_codex_direct_tools` + `test_install_timeouts` + `test_i18n_parity` + `test_install_clients` + `test_codex_hooks_install` + `test_install_header` + `test_completion_install` + `test_install` + `test_checks`; (2) `test_cli_*` + `test_clients` + `test_doctor*` + `test_update*` + `test_codex_hooks_doctor`; (3) tras los arreglos de la revisión, `test_codex_direct_tools` + `test_install_timeouts` + `test_install` + `test_checks` + `test_install_clients` + `test_update` + `test_doctor` + `test_i18n_parity`; (4) `test_wiki` + `test_cli_english` + `test_doctor_english` | pass | (1) 462 passed, 2 skipped; (2) 396 passed; (3) 468 passed, 1 skipped; (4) 103 passed |
| lint | `ruff check` y `ruff format --check` sobre los ficheros tocados | pass | sin hallazgos |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes (diff revisado a mano y por el revisor de seguridad: solo nombres de categorías y textos fijos).
- [x] No unrelated changes are present.

## Deviations and residual risk

- No se corrió la suite entera (orden de recursos de la PC): solo los ficheros afectados y su
  vecindad; el CI del PR integrado la corre entera.
- Codex Desktop no se probó; la prueba en vivo en el Codex real de la persona usuaria queda
  pendiente (pasos en la wiki).
- El código se empezó a escribir mientras corría la primera revisión del plan; sus bloqueantes se
  aplicaron después en spec, plan, código y tests.
