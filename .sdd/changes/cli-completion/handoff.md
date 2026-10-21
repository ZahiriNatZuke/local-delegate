# Handoff: Autocompletado de la CLI (completion powershell|zsh|bash)

## Current state

- SDD status: cerrado (gates spec, plan, quality, conformance y memory aprobados).
- Last completed gate: memory.
- Current revision: `main` en `3540860` (#369) más la PR de cierre (#368).

## What changed

- `local-delegate completion powershell|bash|zsh` imprime un script estático generado desde
  `build_parser()` (`src/local_delegate/completion.py`, plantillas en
  `src/local_delegate/resources/completion/`). Nunca llama a Python al pulsar Tab.
- `install --shell-completion [auto|powershell|zsh|bash]` (repetible, con `--dry-run`) escribe el
  fichero en el directorio de datos, un bloque gestionado en cada perfil y el manifiesto
  `installed.json`; enseña ruta y política por edición de PowerShell. `uninstall` lo revierte
  byte a byte (completo, o solo eso con `--shell-completion`).
- `doctor` tiene el check `scaffold.shell_completion` (26 checks); `update` regenera el fichero en
  el idioma configurado, también sin clientes.
- E2E del autocompletado instalado en Windows, Ubuntu y macOS (`scripts/check_install_e2e.py`).
- PRs: #359 (docs SDD), #360 (modelo), #361 (perfiles), #362 (PowerShell), #363 (bash/zsh),
  #364 (install), #366 (doctor/update), #367 (E2E), #365 (docs), #369 (arreglo de la
  verificación en vivo), #368 (cierre).

## Decisions

- Script estático porque arrancar el paquete cuesta ~1 s; PowerShell solo ASCII (5.1 rompe las
  tildes sin BOM).
- Fichero aparte + bloque que lo carga, nunca el script dentro del perfil.
- Ediciones de PowerShell con política `Restricted`/`AllSigned`/`Undefined` se saltan con aviso.
- `doctor` compara contra el idioma guardado en el manifiesto (mismo veredicto en es y en).
- No se escribió en el perfil real del usuario en este SDD.

## Next action

- Release con el autocompletado: decidirlo.
- Después, instalarlo en el perfil real de esta PC con `local-delegate install --shell-completion`
  (paso manual opcional descrito en `verification.md`).
- Restos menores en el backlog §1.14.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-10-21-autocompletado-de-la-cli.md`.
- Indexes updated: backlog §1.12 (1b hecho) y §1.14; `MEMORY.md` del proyecto.
