# Verification: Guard de Codex: escrituras de shell sobre ficheros resumidos

## Environment

- Revision: rama `fix/codex-guard-shell-writes` desde `origin/main` (0253b630).
- Relevant runtime and tool versions: Python 3.11 (.venv del checkout principal con `PYTHONPATH=src`); para REQ-007, el Python de la herramienta instalada (`local-delegate-mcp` 0.55.0, rama de la release) y el de la rama.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests/test_codex_guard_shell_writes.py (17 formas de .NET y ruta absoluta, con control sin guard) | pass | rojas antes (evidence/tests-rojos-antes.txt), verdes después |
| REQ-002 | tests/test_codex_guard_shell_writes.py (9 escrituras y 3 lecturas por variable; controles de reasignación, bucle, `read`, `-OutVariable`) | pass | mutante «el último valor gana» tumbado por el control `$p = 'other.md'; Set-Content $p x; $p = 'notes.md'` |
| REQ-003 | tests/test_codex_guard_shell_writes.py (PowerShell, cmd y bash, con bloques `{ … }`) | pass | mutante `_unbrace` identidad tumba 3 casos |
| REQ-004 | tests/test_codex_guard_shell_writes.py (9 envoltorios y 2 lecturas envueltas que levantan el guard) | pass | rojas antes, verdes después |
| REQ-005 | tests/test_codex_guard_shell_writes.py (31 controles) | pass | mutantes «cd ignorado» y «sin binders» tumbados por su control |
| REQ-006 | tests/test_codex_guard_shell_writes.py (6 órdenes hostiles de 100 000 a 480 000 caracteres) | pass | 0,1 a 0,7 s de CPU cada una, tope 2 s |
| REQ-007 | hook real por stdin con la fixture `pre_tool_use_bash` y la orden de #724, estado guardado sembrado en una carpeta temporal | pass | evidence/hook-real-stdin.txt: con 0.55.0 instalada pasa; con la rama, `deny` con el aviso; los dos controles pasan en ambos |
| REQ-008 | revisión del diff de la docstring, `docs/wiki/Integration-install.md` y CHANGELOG | pass | lista de lo que ve y lo que no en la wiki |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test | `pesado.sh python -m pytest -q -n 2` (suite completa) | pass | 8835 passed, 32 skipped y 1 fallo del léxico de nombres (palabras nuevas sin clasificar), arreglado añadiéndolas a `en`; tras el arreglo y un ajuste de rendimiento, los ficheros afectados: 284 passed |
| lint | `ruff check .` y `ruff format --check .` | pass | sin avisos |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- `uv run --locked pytest` sustituido por el .venv del checkout principal con `PYTHONPATH=src` (worktree).
- REQ-007 no usa `codex exec` (había otra prueba en vivo con Codex en marcha y el encargo lo excluye): el hook se alimenta con el JSON de la fixture, que cumple el esquema oficial de `PreToolUse`.
- Límites conocidos (documentados en la wiki): rutas que no se saben sin ejecutar, `-EncodedCommand`, `StreamWriter`, `[IO.File]::Open` con modo, escrituras de .NET anidadas, `perl -i`, `python -c`, `dd`, `truncate`; los borrados no se tocan.
