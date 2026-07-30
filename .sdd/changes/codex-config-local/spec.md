# Especificación: Arregla los dos hallazgos de configuración de Codex

## Summary

Codex, dentro de `D:\Projects\local-delegate`, carga sus MCP sin abortar y resuelve `rtk` por
nombre en el entorno donde ejecuta comandos. Todo el cambio es configuración local de esta
máquina; al repositorio solo llega la traza SDD.

## Diagnóstico que corrige la nota del backlog (hallazgo 2)

El backlog decía *«`rtk` no está en el PATH que hereda Codex»*. **Es falso**, medido por ejecución:

| Comprobación | Resultado |
|---|---|
| `C:\Users\Yohan` en el PATH persistido (usuario **y** máquina) | **sí** |
| Ruta real del shim | `C:\Users\Yohan\rtk.exe` — **no** `.local\bin\rtk.cmd` |
| `C:\Users\Yohan` en el PATH **dentro** del sandbox de Codex | **sí** (38 entradas) |
| `& 'C:\Users\Yohan\rtk.exe' --version` dentro del sandbox | **`rtk 0.34.0`** — se ejecuta |
| `Get-Command rtk` dentro del sandbox | **no lo encuentra** |
| `Get-ChildItem 'C:\Users\Yohan'` dentro del sandbox | **falla** — no enumerable |
| `Get-ChildItem 'C:\Users\Yohan\.local\bin'` dentro del sandbox | **funciona** (`uvx` resuelve ahí) |

**Causa raíz:** con `[windows] sandbox = "elevated"`, Codex ejecuta bajo un *restricted token* que
**no puede enumerar el raíz del perfil** `C:\Users\Yohan`. La resolución por PATH necesita
enumerar el directorio, así que falla aunque la entrada esté en el PATH y el binario sea
ejecutable por ruta absoluta. El problema es **dónde vive el shim**, no el PATH.

Corolario: las dos vías apuntadas en el backlog no arreglan nada. Añadir al PATH del sistema un
directorio que ya está en el PATH no cambia nada, y `shell_environment_policy` solo maneja
variables de entorno, no permisos del sandbox. Relajar el sandbox (*readable roots* sobre el raíz
del perfil) sí funcionaría, pero amplía el acceso de un agente a todo el perfil por un shim: se
descarta por riesgo.

## Requirements

- **REQ-001:** Con el cwd en `D:\Projects\local-delegate`, `codex mcp list` termina con éxito y no
  emite `failed to load configuration`.
- **REQ-002:** En esa misma listada aparecen los cinco MCP que aporta el `.codex/config.toml` del
  repo — `MCP_DOCKER`, `codegraph`, `git`, `socket-mcp`, `jetbrains` — y también `local-delegate`,
  que viene de la global.
- **REQ-003:** `github` queda definido **una sola vez**, por HTTP, en el `config.toml` global, y
  sigue apareciendo en la listada hecha desde dentro del repo.
- **REQ-004:** Dentro del sandbox de Codex, `Get-Command rtk` devuelve una ruta y `rtk --version`
  imprime su versión, sin usar rutas absolutas.
- **REQ-005:** El arreglo de REQ-004 no duplica el binario: sigue habiendo un único `rtk.exe`, de
  modo que una actualización de `rtk` no deja copias desfasadas.
- **REQ-006:** El repositorio no cambia salvo los artefactos de `.sdd/changes/codex-config-local/`.
  `git status` no muestra ningún otro fichero modificado.

## Acceptance scenarios

### Escenario: los MCP cargan dentro del repo

- **Dado** el cwd en `D:\Projects\local-delegate` y la entrada `github` eliminada del config del repo
- **Cuando** se ejecuta `codex mcp list`
- **Entonces** el comando sale con código 0 y lista los cinco MCP del repo, `local-delegate` y
  `github` (HTTP), sin error de configuración

### Escenario: `rtk` se resuelve donde Codex ejecuta

- **Dado** el shim alcanzable desde un directorio del PATH que el sandbox **sí** puede enumerar
- **Cuando** se ejecuta `codex sandbox pwsh -NoProfile -File <script>` con `Get-Command rtk`
- **Entonces** devuelve la ruta del shim y `rtk --version` imprime `rtk 0.34.0`

### Escenario: la global sigue siendo la fuente de `github`

- **Dado** que `github` solo está definido en `C:\Users\Yohan\.codex\config.toml`
- **Cuando** se lista desde dentro del repo
- **Entonces** su transporte es HTTP contra `api.githubcopilot.com` y su token se sigue tomando de
  la variable de entorno, sin credenciales en ningún fichero del repo

## Edge cases and failure behavior

- **Otro proyecto con la misma trampa:** cualquier `.codex/config.toml` que redefina un servidor
  global con otro transporte reproduce el fallo. Se documenta la regla en la memoria, no se
  construye defensa.
- **`rtk` se actualiza:** el shim invoca por ruta absoluta, así que sigue apuntando al binario
  actualizado. Si el actualizador **mueve** el `.exe`, el shim rompe con un error claro de ruta.
- **El sandbox cambia de política:** si algún día `C:\Users\Yohan` fuese enumerable, el shim queda
  redundante pero inofensivo.

## Non-functional requirements

- **Seguridad:** no se relaja el sandbox de Codex ni se amplían sus *readable roots*. No se
  persiste ningún secreto; el bearer sigue en su variable de entorno.
- **Reversibilidad:** los dos cambios son un bloque de 7 líneas borrado de un fichero local y un
  fichero nuevo. Se copia el config del repo a `.bak` antes de tocarlo.
- **Compatibilidad:** el `.codex/` del repo está en `.gitignore:32`; nada de esto afecta a otras
  máquinas ni a otros usuarios del proyecto.

## Non-goals

- Probar Codex Desktop (la app) y probar `path` server-side desde Codex: siguen en el backlog.
- Cambiar el `AGENTS.md` de Codex o su instrucción de usar RTK.
- Mover o reinstalar `rtk` fuera del raíz del perfil.

## Traceability

| Req | Trabajo previsto | Evidencia |
|---|---|---|
| REQ-001, REQ-002, REQ-003 | Quitar `[mcp_servers.github]` del `.codex/config.toml` del repo | `codex mcp list` desde el repo |
| REQ-004, REQ-005 | Shim `rtk.cmd` en `C:\Users\Yohan\.local\bin` que invoca el `.exe` por ruta absoluta | `codex sandbox` con `Get-Command rtk` y `rtk --version` |
| REQ-006 | Solo se escriben artefactos SDD | `git status --short` |
