# Verification: Codex: resumen automático de lecturas y guard de escritura (#670)

## Environment

- Revision: rama `feat/codex-read-summary-write-guard` sobre `05529e3c` (sin PR propio: lo integra la sesión principal).
- Relevant runtime and tool versions: Windows 11, Python 3.11.15 (`.venv` del checkout principal, `PYTHONPATH=src`), Codex CLI 0.169.0, pytest con `-n 1` bajo `~/.claude/scripts/pesado.sh`.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_the_guard_entry_goes_after_the_two_hooks_of_669`, matcher con 7 nombres que casan y 9 que no (control: sin lookaround, regex no exacta), y coherencia con `read_classifier.classify_tool` | pass | `tests/test_codex_reads.py`, 396 passed en la vecindad |
| REQ-002 | lectura entera de prosa en principal y subagente → `deny` válido contra el esquema oficial, cabecera con presupuesto (639 de 800) y comando, ruta absoluta, guard; `Get-Content`, `type`, `cd && cat`; compuestos (`;`, `&&`, `$(…)`) no se deniegan y llevan nota | pass | `test_a_whole_prose_read_is_denied_*`, `test_other_whole_reads_*`, `test_a_compound_command_*` |
| REQ-003 | 9 resúmenes inválidos (None, vacío, espacios, error, dos avisos de segundo plano, truncado en y es, excepción) → pasa y sin guard; control con resumen válido; interruptor apagado (dos variables); backend caído pasa pero conserva el guard; `session_id` inválido (5 casos); `LD_HOOK_ENABLED=0` en el proceso real; entrada rota (test existente sobre `NAMES`) | pass | `test_an_invalid_summary_*`, `test_the_valid_summary_control`, `test_backend_down_*`, `test_the_experiment_switch_off_*`, `test_broken_input_exits_zero_and_silent` |
| REQ-004 | código grande y prosa pequeña pasan; subagente con código grande entero recibe la nota; rango de fichero corto pasa aunque pase del 80 % | pass | `test_large_code_and_small_prose_pass`, `test_a_subagent_reading_large_code_*`, `test_a_range_of_a_short_file_*` |
| REQ-005 | 79 % pasa y 80 % se resume (cabecera con 316 leídas, 3 restantes, máximo 319 y líneas 317-320); rango más allá del final; tras lectura literal entera los rangos pasan; rangos de subagente no suman al principal (control: el principal se resume al 82 %) | pass | `test_ranges_pass_until_*`, `test_a_range_past_the_end_passes`, `test_after_a_literal_whole_read_*`, `test_subagent_ranges_*` |
| REQ-006 | `apply_patch` Update/Delete/Move/Add sobre fichero guardado → `deny`; ruta absoluta, en mayúsculas y `/d/…` (Windows); otro fichero pasa; escrituras por shell (`sed -i`, `>`, `cp`, `apply_patch` por heredoc); un rango literal levanta el guard; alcance por agente en los dos sentidos; otro proceso del hook real deniega (control: sin resumen previo, no imprime nada) | pass | `test_a_patch_on_a_summarized_file_is_refused`, `test_the_patch_path_*`, `test_a_shell_write_*`, `test_a_literal_range_lifts_the_guard`, `test_the_guard_is_per_agent_both_ways`, `test_the_guard_survives_another_hook_process` |
| REQ-007 | lectura MCP grande → nota y nunca `deny` (aunque esté guardado); tools propias de `local-delegate` → nada | pass | `test_a_large_mcp_read_*`, `test_our_own_mcp_tools_are_left_alone` |
| REQ-008 | servidor `/mcp` falso en el proceso: SSE y JSON, secuencia `initialize` → `initialized` → `tools/call` → `DELETE`, `clientInfo`, `Bearer`, `Mcp-Session-Id`; 401 e `isError` → None; daemon lento con plazo 0,5 s → None en < 2,5 s; sin daemon → None; cliente fuera del coste | pass | `test_the_summary_comes_from_*`, `test_a_refused_or_failed_call_*`, `test_a_daemon_that_does_not_answer_*`, `test_no_daemon_gives_none`, `test_the_hook_client_is_out_of_the_claude_cost` |
| REQ-009 | el log de estado no contiene el centinela ni texto del fichero; operaciones `guard`, `range`; prefiltro sin cargar el clasificador (control: con `.md` sí lo carga) | pass | `test_the_state_holds_paths_*`, `test_the_prefilter_*` |
| REQ-010 | `python scripts/dev/codex_hooks_live.py <scratch>` con `CODEX_HOME` temporal: Codex 0.169.0 lista `…\hooks.json:pre_tool_use:1:0` con nuestro comando, `warnings: []`, `errors: []`; `~/.codex` real sin cambios (hashes iguales antes y después) | pass | salida del script, «0 failure(s)» |
| REQ-011 | wiki «Resumen de lecturas y guard de escritura en Codex» (vía, límites con citas, tabla de comportamiento, fallo en abierto, alcance, coste, prueba en vivo con centinela y captura del payload de Windows) y entrada del CHANGELOG | pass | `docs/wiki/Integration-install.md`, `CHANGELOG.md`; `tests/test_wiki.py` en verde |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -n 1` sobre `test_codex_reads`, `test_codex_hooks*`, `test_codex_plugin`, `test_i18n_parity`, `test_hook_texts`, `test_no_uncatalogued_text`, `test_wiki`, `test_attribution`, `test_hook_entry`, `test_hook_shell_absolute_path` | sí, con `pesado.sh` | pass | 396 passed, 1 skipped |
| mutantes (resumen siempre válido, guard desactivado, umbral del 80 % desactivado) sobre `test_codex_reads.py` | sí | pass (los mutantes caen) | 18 failed con el mutante; fuente restaurada (`cmp` igual) |
| `ruff check` y `ruff format --check` de los ficheros tocados | sí | pass | «All checks passed!» |
| `scripts/dev/codex_hooks_live.py` | sí, con `pesado.sh` | pass | «0 failure(s)» |
| latencia del hook (5 corridas, mediana) | sí | 0,124 s (prefiltro) y 0,126 s (clasificador) | `scratchpad/latency.py` |

## Quality checks

- [x] Project-native tests pass (los ficheros afectados y su vecindad; la suite entera la corre el CI del PR común).
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes (ningún token en tests: el servidor falso recibe `test-token`; el hook nunca lee el registro en los tests).
- [x] No unrelated changes are present.

## Deviations and residual risk

- No probado con Codex real ejecutando un turno (necesita la cuenta de la persona): que el modelo use
  el resumen del motivo y no reintente la lectura por otra vía, y la forma exacta del `command` en
  Windows. Va como prueba en vivo en la wiki y en `handoff.md`.
- La lectura literal levanta el guard al permitirla, antes de ejecutarse (Codex no da el código de
  salida a `PostToolUse` de Bash).
- Un tramo de PowerShell `Get-Content f | Select-Object -Skip N -First M` lo cuenta el clasificador
  compartido como 1..M: la cobertura puede quedar por debajo de la real (no deja leer de más).
- Los tests de #669 que fijaban «dos hooks» cuentan ahora los de `SPECS`, con las mismas aserciones
  sobre los dos consultivos.
