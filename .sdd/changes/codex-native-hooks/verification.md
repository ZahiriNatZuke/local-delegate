# Verification: Entrega Codex nativa: hooks de usuario, instalador y diagnóstico (#669, núcleo; la atribución por sesión va aparte)

## Environment

- Revision: rama `feat/codex-native-hooks` sobre `origin/main` (`402f99e3`), cambios sin commit al verificar
- Relevant runtime and tool versions: Windows 11, Python 3.11.15 (`.venv` del checkout principal con `PYTHONPATH=src`), pytest con xdist `-n 2`, `jsonschema` 4.26.0, Codex CLI 0.169.0

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `tests/test_codex_hooks.py` (entradas, citado del intérprete por plataforma, grupos que no son nuestros) | pass | dos grupos sin matcher, un manejador `command` con `timeout` 30; `check_hooks_file` sin hallazgos; seis formas ajenas (con `commandWindows`, con otro manejador, `prompt`, vacío, hook de Claude) no cuentan como nuestras |
| REQ-002 | payloads con los campos requeridos de los esquemas de `rust-v0.169.0` validados con `jsonschema`; salidas validadas contra el esquema de salida; control negativo con los textos de Claude; mutante | pass | el control de esquema falla sin `agent_id`; el mutante (textos de Claude en lugar de los de Codex) tumba 4 tests |
| REQ-003 | stdin vacío, no JSON, lista, bytes inválidos; `LD_HOOK_ENABLED=0`; corte de backend abierto (con guarda de que se abrió); manejador que lanza `RuntimeError` o `SystemExit(2)`; intérprete inexistente por `cmd.exe /C` | pass | salida 0 y sin texto; una línea en `hook-failures.jsonl` con solo `ts`, `hook`, `error`; intérprete inexistente sale con un código distinto de 0 y 2. El test del comando real por `cmd.exe /C` se salta en este checkout (ver desviaciones) |
| REQ-004 | sandbox con `LD_HOOK_TELEMETRY_LOG`; control con el hook `prompt` de Claude | pass | los `codex-*` no crean la telemetría y dejan `{nombre: hora UTC}`; el hook de Claude en el mismo sandbox sí la crea |
| REQ-005 | `tests/test_codex_hooks_install.py`: fusión pura y `plan_install`/`apply` sobre HOME simulado | pass | grupos ajenos sin moverse; reescritura en su índice; duplicado a hueco o fuera; `commandWindows` ajeno; segunda pasada idéntica; `.bak` una vez; CRLF conservado; BOM, clave rechazada, JSON roto y no objeto se rechazan sin tocar el fichero; sin `uv tool` no escribe; `--dry-run` imprime y no escribe; reinstalar ocupa el hueco |
| REQ-006 | `update.plan_repairs` con `codex.hooks` en `warn`, `ok` y `unknown`, y en un HOME sin `~/.codex` | pass | solo `warn` planifica la acción; nunca crea `~/.codex` |
| REQ-007 | `plan_uninstall` sobre HOME simulado | pass | fichero creado por `install` se borra (y su `.bak`); con un grupo del usuario detrás queda `{"hooks": []}` y el del usuario sigue en el índice 1; `config.toml` byte a byte igual; sin fichero, no hace nada |
| REQ-008 | `tests/test_codex_hooks_doctor.py` y recuentos en `test_checks`, `test_doctor`, `test_doctor_english`, `test_wiki` | pass | `unknown` sin Codex o ilegible; `ok` sin hooks nuestros; aprobados cuenta solo nuestras claves (control: la clave un grupo más allá no cuenta); vistos desde la marca; aviso de `[hooks]` solo con grupos de eventos; `warn` con intérprete viejo o ausente o con uno que falta; BOM y clave rechazada en `warn`; el HOME queda igual (instantánea); 37 checks |
| REQ-009 | CHANGELOG («Unreleased»), README, `docs/wiki/Integration-install.md` (sección «Hooks de Codex» y fila de `doctor`), textos es/en | pass | `test_wiki.py`, `test_i18n_parity.py`, `test_detect_spanish_names.py` en verde |
| REQ-010 | `scripts/dev/codex_hooks_live.py` contra Codex CLI 0.169.0 con `CODEX_HOME` temporal | pass | 0 fallos: Codex lista nuestras dos claves sin aprobar; la segunda instalación no escribe; tras `uninstall` el grupo del usuario conserva `user_prompt_submit:1:0` sin avisos ni errores; al reinstalar el nuestro vuelve al índice 0; con BOM Codex avisa «failed to parse hooks config … expected value at line 1 column 1», no carga nada, e `install` no escribe. Hashes del `~/.codex` real iguales antes y después (`config.toml` `f38433…7402a`, `hooks.json` `420f05…79bf`) |
| REQ-011 | pasos de la prueba de confianza escritos en la wiki y en `handoff.md` | skip | la aprobación en `/hooks` la hace la persona; no se simula ni se escribe ningún `trusted_hash` |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest` de los ficheros del área (`-n 2`) | yes | pass | 603 passed, 2 skipped (antes de clasificar `comspec`; después, `test_detect_spanish_names` 46 passed) |
| `pytest -q -n 2` (suite completa, árbol final) | yes | pass | 7842 passed, 32 skipped en 383 s. Una pasada anterior dio 2 fallos (`test_hook_texts` no veía las claves de `codex_hooks.py`; `cwds` sin clasificar en el detector), arreglados |
| `ruff check src tests scripts` / `ruff format --check src tests scripts` | yes | pass | «All checks passed!»; «413 files already formatted» |
| `uv lock --check` | yes | pass | el lock solo gana las dos líneas de `jsonschema` |
| `python scripts/dev/codex_hooks_live.py <tmp>` | yes | pass | 15 comprobaciones, 0 fallos, tras los cambios de la revisión |
| mutante de REQ-002: cambiar en `codex_hooks.run` `codex.prompt.mechanical` y `codex.subagent.start` por `prompt.mechanical` y `subagent.start`, y correr `pytest tests/test_codex_hooks.py` | yes | pass | 4 tests fallan con el mutante; con el código real, todos pasan |
| escaneo de secretos y datos personales del diff (grep de claves, tokens y nombres) | yes | pass | nada nuevo; las coincidencias son de ficheros ya publicados |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- El intérprete de los hooks sale de `Options.claude_ld_bin` y no de una opción `codex_ld_bin` nueva: es el mismo entorno `uv tool`, `update` ya lo pasa y `doctor` ya lo compara (`expected_ld_bin`).
- `test_the_generated_command_runs_through_the_codex_shell` se salta en un worktree: el intérprete aislado (`-I`) importa el paquete del checkout principal. Con `CI` definido falla en vez de saltarse, así que en el CI (instalación del propio árbol) tiene que correr. La prueba real equivalente es REQ-010 más la prueba de confianza del usuario.
- `test_update.py::test_the_uv_tool_warning_changes_neither_the_plan_nor_the_exit_code` falló una vez con `-n 2` (modo MCP `stdio` contra `http` entre dos pasadas) y pasa solo y con `test_update.py` entero en paralelo; no toca nada de este cambio.
- Que Codex despache de verdad los hooks exige aprobarlos en `/hooks`: queda para la persona (REQ-011).
- Tras la revisión, un fichero que Codex rechaza (BOM o clave que no conoce) no cuenta como fallo de `install`/`update`: lo dicen y siguen, para que `update` no salga con 1 en cada pasada ni se salte el paso del daemon. Un fichero que no es un objeto JSON sigue siendo fallo, como en el resto de configs.
- Riesgos residuales aceptados: tras una reparación de `update` sobre un fichero creado por `install` queda un `.bak` con solo lo nuestro, y `uninstall` deja entonces `{"hooks": {}}` y ese `.bak`; `merge` compara el intérprete por texto (un `install` manual con la misma ruta escrita de otra forma obliga a aprobar otra vez, y el mensaje lo dice); `enabled = false` en `[hooks.state]` no se mira (siguiente PR).
