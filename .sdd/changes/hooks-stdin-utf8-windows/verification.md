# Verification: Hooks de la entrega por settings leen y escriben UTF-8 en Windows

## Environment

- Revision: rama `fix/hooks-stdin-utf8-windows` sobre `89551158`.
- Windows 11; tests con el `.venv` propio del worktree (Python 3.11, `local_delegate` del worktree, también con `-I`); hooks instalados con el `python` del PATH (3.14.4, `sys.stdin.encoding == cp1252`).

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test `test_read_hook_finds_a_file_with_a_non_ascii_path` + prueba instalada casos 1 y 3 | pass | antes: sin salida y sin telemetría; después: `deny` + línea `large_prose` con `size_kb` |
| REQ-002 | test `test_prompt_hook_reads_accented_words_of_the_host_only_rule` + prueba instalada caso 2 | pass | antes: aviso `summarize`; después: sin salida, `suggested: false` |
| REQ-003 | test `test_prompt_hook_survives_a_letter_outside_cp1252` + prueba instalada caso 3 | pass | antes: sin línea; después: línea con `prompt_chars` correcto |
| REQ-004 | review | pass | `install.py` sin cambios; el comando registrado sigue siendo `python "<script>"` y la prueba instalada lo usa tal cual |
| REQ-005 | test `test_read_hook_records_why_it_stops_when_the_file_is_missing` + prueba instalada caso 4 | pass | antes: sin línea; después: `reason: "no_file"` |
| REQ-006 | test `test_utf8_stdio_switches_a_cp1252_pipe_to_utf8` + prueba instalada | pass | `stdout` decodifica en UTF-8 y trae la ruta con `ñ` íntegra (`path_echoed_intact=True`) |
| REQ-007 | `installed_probe.py` en HOME temporal, comando del settings por `sh -c`, stdin UTF-8 en bytes | pass | scratchpad `utf8hooks/before.txt` (3 fallos) y `after.txt` (0) |
| REQ-008 | review | pass | `utf8_stdio()` solo se llama dentro de `main()` de cada hook |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -n 2` (suite completa, `.venv` del worktree) | sí | pass (1 excepción) | 6312 passed, 30 skipped, 1 failed: `test_build_hook.py::test_sdist_carries_what_regenerates_the_mod`, el sdist construido dentro de un worktree mete ficheros ignorados (trampa conocida, sin relación con el cambio; queda para el CI) |
| `ruff check src tests/test_hook_stdin_utf8.py` | sí | pass | All checks passed |
| `ruff format --check` (ficheros tocados) | sí | pass | |
| `scripts/bump_version.py --boundaries` | sí | pass | `hook_hashes_after.json` regenerado (29 huellas) |

## Quality checks

- [ ] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Primera corrida de la suite con el `.venv` del checkout principal: 4 fallos de equivalencia plugin/settings porque `python -I -m local_delegate.hook` importaba `main` (trampa conocida del worktree); con el `.venv` del worktree pasan.
- El test de `StringIO` es una guarda de no regresión: no puede fallar sin el arreglo.
- La telemetría del hook de lectura gana líneas `no_file` que antes no existían: el total de eventos de lectura del panel sube en esa medida (son lecturas reales que antes se perdían).
