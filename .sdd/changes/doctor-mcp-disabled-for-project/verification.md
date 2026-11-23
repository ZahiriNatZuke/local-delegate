# Verification: doctor avisa si el MCP local-delegate está deshabilitado para el proyecto en Claude Code (#705)

## Environment

- Revision: rama `fix/691-705-summarize-retry-doctor-disabled` sobre `ce09fc5a` (worktree propio, `PYTHONPATH=src`).
- Relevant runtime and tool versions: Python 3.11.15, pytest con xdist (`-n 2`), ruff; Windows 11.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_disabled_in_this_project_is_a_warning_with_the_remedy (las dos listas) y `doctor --home` simulado | pass | rojo antes; con la rama `[WARN] MCP en Claude Code: … deshabilitado para el proyecto …` (antes `[ OK ]`) |
| REQ-002 | test_disabled_in_another_project_is_ok, test_without_the_keys_it_is_ok, test_odd_types_are_ignored | pass | `ok` en los tres |
| REQ-003 | test_the_nearest_ancestor_entry_applies, test_the_path_is_compared_normalized_on_windows | pass | ancestro más cercano manda; `D:\WORK\APP` empareja con `d:/work/app` |
| REQ-004 | test_doctor_does_not_write_the_file_and_update_does_not_repair_it; hash del `~/.claude.json` real y del simulado antes/después del `doctor` | pass | sin cambios en los dos ficheros; `REPAIRS` solo repara `missing` |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2 --dist loadgroup` (con `pesado.sh`) | 2026-11-23 | pass | 8379 pasados, 31 saltados; el fallo de léxico se arregló |
| `ruff check .` y `ruff format --check` | 2026-11-23 | pass | sin hallazgos |
| `local-delegate doctor --home <HOME simulado>` (instalada) y `python -m local_delegate doctor --home …` (rama) | 2026-11-23 | pass | `[ OK ]` antes, `[WARN]` después |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- La forma de `~/.claude.json` se tomó de un `~/.claude.json` real leyendo solo los nombres de las
  claves de proyecto (sin valores) y de informes públicos de Claude Code; no hay doc oficial de esas
  claves. Si Claude Code las renombra, el aviso deja de salir (vuelve al `ok` de antes, no a un falso
  aviso).
