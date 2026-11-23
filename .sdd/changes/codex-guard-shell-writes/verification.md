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
| REQ-006 | tests/test_codex_guard_shell_writes.py (9 órdenes hostiles, proporción de CPU entre 5 000 y 20 000 repeticiones, recolector apagado) y equivalencia de `herestring_spans` con la regex vieja | pass | la proporción absoluta fallaba en el runner de Ubuntu; la regex de here-strings tardaba 6,6 s con 60 000 caracteres y ahora es lineal |
| REQ-007 | hook real por stdin con la fixture `pre_tool_use_bash` y la orden de #724, estado guardado sembrado en una carpeta temporal | pass | evidence/hook-real-stdin.txt: con 0.55.0 instalada pasa; con la rama, `deny` con el aviso; los dos controles pasan en ambos |
| REQ-008 | revisión del diff de la docstring, `docs/wiki/Integration-install.md` y CHANGELOG | pass | lista de lo que ve y lo que no en la wiki |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test | `pesado.sh python -m pytest -q -n 2` (suite completa, dos veces) | pass | 1.ª: 8835 passed (fallo del léxico, arreglado). 2.ª tras la revisión: 8855 passed; los 8 fallos son de la huella del hook de lectura: 2 de `test_hook_boundaries` (arreglados con `bump_version.py --boundaries`) y 6 que comparan un subproceso sin `PYTHONPATH` (importa el `src` del checkout principal en otra rama) con el `src` del worktree; en el CI, donde no hay esa mezcla, pasan. CI del PR: ver «Deviations» |
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
- La revisión de dos jueces (review.md) llevó a 7 arreglos con sus tests; dos mutantes nuevos (lecturas envueltas canalizadas, comillas dobles) tumbados por sus tests.
- El cambio de `herestring_spans` toca `read_classifier` (Claude Code) sin cambiar su resultado: test de equivalencia con 5 000 textos aleatorios.

## Prueba con Codex real (2026-11-23, 19:33 a 19:35 hora de Uruguay)

Codex CLI 0.171.0 en Windows sobre el `~/.codex` real, `main` en `92839abd` instalado con
`uv tool install --force --no-cache ".[llamaswap]"`, `doctor` con los hooks de Codex aprobados 4 de 4,
ventana `test-window` `codex-guard-shell`. Centinela `.md` de 201 líneas (~20 KB) en una carpeta
temporal; `codex exec --json -c 'sandbox_mode="workspace-write"'` y `codex exec resume` en la misma
sesión:

| Paso | Esperado | Visto |
| --- | --- | --- |
| `cat centinela.md` | denegado con el resumen como motivo | `Command blocked by PreToolUse hook: Resumen de … hecho por el modelo local …` |
| `[System.IO.File]::WriteAllText($p, …)` con `$p='centinela.md'` | rechazado | `… solo se ha leido resumido: antes de modificarlo, lee literal el tramo …`; fichero sin cambiar |
| control: `WriteAllText('otro.md', …)` | pasa | exit 0, fichero escrito |
| `Get-Content centinela.md -TotalCount 40` y luego el mismo `WriteAllText` | pasa | exit 0; primera línea cambiada |

Ventana cerrada y centinela borrado tras la prueba.
