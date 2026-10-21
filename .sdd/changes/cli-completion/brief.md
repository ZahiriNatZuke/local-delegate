# Brief común — SDD `cli-completion`

Reglas que aplican a TODOS los agentes de este cambio. Léelo entero antes de empezar; no hace falta
leer el `CLAUDE.md` global ni todo `MEMORY.md`.

## Objetivo

Autocompletado de la CLI `local-delegate` (backlog §1.12, punto 1b, pedido del usuario el
2026-10-20). Recomendación aprobada en el backlog: **generador propio sin dependencias**:

- subcomando `local-delegate completion powershell|zsh|bash` que recorre el parser `argparse` y
  emite el script de autocompletado por la salida estándar;
- PowerShell (`Register-ArgumentCompleter -Native`) en la PC Windows; zsh en la Mac; bash por
  completitud;
- completa subcomandos (todos los niveles), opciones y **valores fijos** (`choices` de argparse:
  roles, lista cerrada de parámetros de `backend-params`, etc.);
- que `install` pueda dejarlo cargado en el perfil del shell (decisión de diseño a fijar en la spec:
  opción explícita, idempotente, con marcador y reversible por `uninstall`);
- descartados: `argcomplete` (dependencia, PowerShell flojo, arranca Python en cada Tab) y `shtab`
  (dependencia, sin PowerShell);
- probarlo **instalado en cada shell**, no solo el script generado (memoria: «probar la pieza no es
  probar el uso»).

## Reglas obligatorias

- **PROHIBIDO usar el MCP `local-delegate`** (`mcp__local-delegate__*`) en esta sesión: orden
  expresa del usuario. Si el hook de lectura bloquea un fichero grande, léelo por franjas con
  `offset`/`limit` o con `sed -n`/`grep`.
- **Todo el código en inglés** (módulos, funciones, opciones, valores, campos); **solo los textos
  de salida al usuario** van por el catálogo i18n (es/en), igual que el resto de la CLI
  (`src/local_delegate/i18n.py` y su catálogo; hay un guardián de textos fuera del catálogo).
- **Sin dependencias nuevas** de runtime.
- **Comandos pesados de uno en uno en la máquina**, desde la tool **Bash** (no PowerShell: ahí
  `bash` es WSL): `bash ~/.claude/scripts/pesado.sh <comando>`. Pesado = pytest de la suite, builds,
  `uv sync`, installs. pytest con `-n 2` como máximo. Tests sueltos de un fichero pueden ir sin
  cerrojo si tardan segundos.
- El repo **mezcla LF y CRLF fichero a fichero**: respeta el fin de línea de cada fichero que
  edites (compruébalo con `git ls-files --eol <fichero>`); `Path.write_text` convierte sin avisar.
- **Commits firmados**, sin línea de coautoría de Claude (regla del usuario que anula la del
  harness). Rama propia por lote, PR contra `main`; `main` exige CI verde, CodeQL sin alertas y
  firma. Verifica TODOS los checks con `gh pr checks <n>` (no basta `gh run list`).
- **No toques** el daemon, la tarea programada, `~/.claude*`, `~/.codex`, ni el perfil real de
  PowerShell/bash/zsh del usuario. Las pruebas de «instalado en el perfil» usan un perfil temporal
  (`$PROFILE` apuntado a un fichero del scratchpad, `HOME`/`ZDOTDIR` temporales).
- **Nada huérfano**: al terminar, ni shells, ni servidores, ni esperas en bucle vivas. Toda espera
  con tope de tiempo. Confírmalo en la entrega.
- Una release toca tres sitios: `CHANGELOG.md`, `README.md` y `docs/wiki/`.
- Si algo que descubres invalida la spec o el plan, **para y repórtalo**; no improvises alcance.

## Entregables

Cada encargo dice su ruta. Todo en español, con `fichero:línea` como evidencia.
