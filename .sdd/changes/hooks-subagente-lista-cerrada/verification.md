# Verification: Hooks y bloque gestionado ante subagentes con lista cerrada de tools (#664)

## Environment

- Revision: rama `fix/hooks-subagente-lista-cerrada`, sobre `main` en `402f99e3`.
- Relevant runtime and tool versions: Windows 11, Python 3.11 del `.venv` del repo, pytest con
  xdist (`-n 2`), ruff. El `.venv` importa `local_delegate` del checkout principal: la entrega
  `plugin` (`python -I -m local_delegate.hook`) se probó aparte con un lanzador que importa el
  `src` del worktree.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests de prosa, código, shell y definición del proyecto desde `cwd`, en las dos entregas | pass | antes del arreglo 13 fallos (`'deny' is None`, `'context' is None`, recordatorio emitido); después, verdes en settings y en plugin (16 de 16) |
| REQ-002 | casos `names-local`, `inherits`, `star`, tipo sin definición, `agent_type` raros y 14 formas de YAML | pass | `test_closed_subagent_is_not_sent_to_local_tools`, `test_yaml_forms_never_give_a_false_closed`, `test_a_local_tool_use_beats_the_definition` |
| REQ-003 | `tool_use` y delta propios ganan; el uso del principal no cuenta | pass | `test_own_transcript_decides_and_main_does_not`, `test_a_local_tool_use_beats_the_definition` |
| REQ-004 | `SubagentStart` calla con la lista cerrada y avisa con la abierta | pass | `test_subagent_start_skips_the_reminder_for_a_closed_list` |
| REQ-005 | el párrafo existe en bloque y skill, es y en, con `tools:`, la tool y `offset`/`limit` | pass | `test_block_and_skill_say_what_to_do_without_tool_search`; `test_skill_parity.py` verde |
| REQ-006 | `install --home <temporal> --target claude --enable-read-hook --claude-delivery settings` y los hooks instalados con un subagente cerrado y uno abierto | pass | bloque nuevo escrito; `Read` cerrado anota `mcp_absent`, abierto recibe la sugerencia; `SubagentStart` nada / recordatorio; hashes de `settings.json`, `CLAUDE.md` y `.claude.json` reales iguales antes y después |
| REQ-007 | revisión de CHANGELOG «Unreleased», `Claude-plugin.md` e `Integration-install.md` | pass | entradas añadidas; finales de línea por fichero conservados (`git ls-files --eol`) |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -n 2` (suite completa) | una vez, con el cerrojo `pesado.sh` | pass | 7788 passed, 31 skipped; los 6 rojos eran los 5 casos `plugin` (el `.venv` importa el checkout principal, probados aparte en verde) y un nombre de fichero en español de un test, ya corregido |
| `pytest tests/test_hooks_mcp_absent.py tests/test_detect_spanish_names.py` | tras los cambios de la revisión | pass | 84 passed (settings) y 16 passed (plugin, lanzador del worktree) |
| `ruff check src tests scripts` y `ruff format --check` | sí | pass | sin hallazgos |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- El orden de búsqueda de las definiciones (de `cwd` hacia arriba y luego el usuario) aproxima el de
  Claude Code; no mira las definiciones de `--agents` ni las de plugins. Un nombre repetido en una
  carpeta que Claude Code no lee podría dar un «cerrado» falso, mitigado porque un `tool_use` o un
  delta propio con las `local_*` gana a la definición.
- El mod (`mod/read.js`) no cambia: ver `review.md`.
