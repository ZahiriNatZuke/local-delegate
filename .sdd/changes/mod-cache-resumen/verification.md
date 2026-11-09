# Verification: El mod de lectura reutiliza el resumen de un fichero sin cambios (#608)

## Environment

- Revision: rama `fix/mod-cache-resumen` sobre `origin/main` 0aaa4bb1
- Relevant runtime and tool versions: Windows 11, `.venv` propio del worktree (`uv sync --locked`), `claude plugin test` de la CLI instalada

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `claude plugin test`: `a_repeated_read_reuses_the_summary` | pass | sin el arreglo falla en `mcpCalls toHaveLength(1)` (recibe 3); con él, 160 pass |
| REQ-002 | `claude plugin test`: `a_changed_file_is_summarized_again`, `a_file_changed_while_summarizing_is_not_cached`, `an_unreadable_file_is_not_cached` | pass | el primero falla sin el arreglo (3 llamadas en vez de 2); mutante sin relectura posterior: falla el segundo (1 en vez de 2); mutante que cachea un fichero ilegible: falla el tercero (1 en vez de 2) |
| REQ-003 | `test_record_read_counts_a_reused_summary_as_a_replaced_read` (vías `read_whole` y `shell_cat`) y `test_record_read_knows_every_mod_decision` | pass | sin la fila en `MOD_DECISIONS` fallan: `reason` `mod_decision` != `large_prose` y `['summary_reused'] == []`; con `MOD_NO_BLOCK_NOTE` vacío fallan los dos parámetros en `notes == []` |
| REQ-004 | review: un acierto no llama a `$.mcp.call` (assert de REQ-001), luego no hay `tools/call` ni fila en el log de uso; la línea de hooks es la de una lectura sustituida (REQ-003) | pass | `read.js` `readSummaryOf`; tests de REQ-001 y REQ-003 |
| REQ-005 | `claude plugin test`: `the_dialog_still_decides_with_a_cached_summary` | pass | sin el arreglo falla en `mcpCalls toHaveLength(1)` (recibe 2); decisiones `summarized`, `read_whole`, `summary_reused` |
| REQ-006 | `claude plugin test`: `the_summary_cache_is_bounded`, `a_reused_summary_is_the_last_to_go`, `the_summary_cache_caps_its_characters` y suite JS existente intacta | pass | sin el arreglo falla en `toHaveLength(17)`; sin la reinserción, el de orden falla (18 en vez de 17); sin el tope total, el de caracteres falla (5 en vez de 6); los 154 tests JS previos sin cambios en verde |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `uv run --locked pytest` (como `.venv/Scripts/python -m pytest -q -n 2`, por `pesado.sh`) | yes | pass | 6625 passed, 30 skipped en 299 s |
| `claude plugin test <plugin>` tras `build_mod.py` | yes | pass | 162 pass, 0 fail |
| `ruff check .` y `ruff format --check .` | yes | pass | All checks passed; 446 files already formatted |
| `build_mod.py --check` | yes | pass | exit 0 |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Sin prueba en vivo en una sesión real de Claude Code con backend: el camino se prueba por el hook `tool.call` con el `$` falso de la suite del mod.
- La caché vive en el proceso: no cubre repeticiones entre sesiones distintas (28 de 157 en el #608). Ir a disco o a varios procesos sería nivel standard; fuera de alcance.
- Un fichero que cambia y vuelve a su texto original mientras se resume no se detecta (hallazgo F6): raro y aceptado.
- Un resumen reutilizado no refleja un cambio de configuración del servidor (modelo, idioma) hecho a mitad de sesión; se acepta.
- Una `test_read_classifier.py` corrida sola no se colecciona (falta `path_rules` en `sys.path`) también en `main`: es previo y ajeno; dentro de la suite completa pasa.

## Final result

- Merged in `main` as `42d1c420` (PR #614, 2026-11-09T18:43:09Z).
- `main` CI on `42d1c420`: all check runs green.
- `main` at `c25e608f`: CI (run 42678307325 Wiki, 42678307752 CI), CodeQL and Vendor audit green on `c25e608f`.
- Closed on 2026-11-09 in the 0.50.0 release PR (`release/0.50.0`).
