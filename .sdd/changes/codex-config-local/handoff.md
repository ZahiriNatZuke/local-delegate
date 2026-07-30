# Handoff — `codex-config-local`

## Current state

- SDD status: `closing` → `closed` al mergear la traza.
- Último gate aprobado: `conformance` (veredicto `conforms`).
- Revisión de partida: `main` en `16f8846`. El change **no cambia código**: solo esta traza viaja a
  git.

## What changed

Dos ficheros de configuración **local de esta máquina**, ninguno versionado:

1. `D:\Projects\local-delegate\.codex\config.toml` — fuera el bloque `[mcp_servers.github]` (stdio
   por `npx`), 7 líneas. `github` queda definido una sola vez, por HTTP, en el config global.
   Copia previa en `.codex\config.toml.pre-github-fix-20260730.bak`.
2. `C:\Users\Yohan\.local\bin\rtk.cmd` — nuevo shim que invoca `%USERPROFILE%\rtk.exe`.

Efecto medido: dentro del repo Codex vuelve a cargar sus MCP (antes abortaba **todos**), y `rtk` se
resuelve por nombre en el sandbox donde Codex ejecuta comandos.

## Decisions

- **Se quitó la definición del repo, no la global.** La global sirve a todos los proyectos y es la
  oficial de Copilot con bearer por variable de entorno; la stdio de `npx` no aportaba nada y
  arrancaba un proceso por sesión.
- **La causa del fallo de `rtk` no era el PATH.** Bajo el *restricted token* del sandbox
  (`[windows] sandbox = "elevated"`), `C:\Users\Yohan` **no es enumerable**, y sin enumerar el
  directorio no hay resolución por PATH — aunque la entrada esté en el PATH y el `.exe` se ejecute
  bien por ruta absoluta. Lo que había que cambiar era **dónde vive el shim**, no el PATH.
- **No se relajó el sandbox.** Añadir el perfil del usuario como *readable root* habría funcionado,
  pero le da a un agente lectura de todo el perfil por un shim de 7 líneas.
- **Shim `.cmd`, no copia ni hardlink**, para que una actualización de `rtk` no deje binarios
  desfasados. El `.exe` del raíz sigue ganando fuera del sandbox porque `C:\Users\Yohan` precede a
  `.local\bin` en el PATH: cero regresión en el uso diario.
- **`codex sandbox` es la vía de diagnóstico** para cualquier cosa del entorno de Codex: reproduce su
  entorno restringido **sin gastar cuota del modelo**.

## Next action

Siguiente punto del backlog: **`scripts/update_to_latest.sh` debe reiniciar el daemon MCP**, con el
diseño ya decidido (detección del mecanismo por sistema, LaunchAgent de macOS por escribir,
`--restart-backend` opt-in y el backend intacto por defecto). Su propio change SDD.

## Memory

- Nota canónica del vault: `projects/local-delegate/backlog.md` (se borra de ahí el punto cerrado) y
  el puntero `codex-mcp-choque-proyecto-global.md` de la memoria del proyecto, que hay que corregir:
  contiene el diagnóstico viejo de `rtk` («no está en el PATH»), que esta verificación desmiente.
- Índices por actualizar: `MEMORY.md` del proyecto.
