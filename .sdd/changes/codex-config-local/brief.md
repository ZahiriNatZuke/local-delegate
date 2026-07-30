# Brief: Arregla los dos hallazgos de configuración de Codex

## Problem

Al probar Codex contra el daemon migrado (change `probar-codex-daemon`, 2026-07-30) salieron dos
defectos de configuración **de esta máquina**, ajenos al código del repo:

1. **Estando el cwd en `D:\Projects\local-delegate`, Codex no carga NINGÚN MCP.** Reproducido hoy:

   ```
   Error: failed to load configuration
   Caused by: url is not supported for stdio
       in `mcp_servers.github`
   ```

   El servidor `github` está definido dos veces con transportes incompatibles:
   `url = "https://api.githubcopilot.com/mcp/"` + `bearer_token_env_var` en
   `C:\Users\Yohan\.codex\config.toml:168-170`, y `command = "npx"` (stdio) en
   `D:\Projects\local-delegate\.codex\config.toml:25-31`. Codex **fusiona** proyecto + global, la
   entrada acaba con `command` **y** `url`, y aborta la carga **entera**. Desde `C:\` funciona.

2. **`rtk` no se resuelve en el shell que usa Codex.** Su `AGENTS.md` le dice usarlo, lo intenta,
   recibe *«The term 'rtk' is not recognized»* y pierde un turno con sus tokens cada sesión.

## Desired outcome

Dentro del repo, `codex mcp list` lista los MCP del proyecto y de la global sin abortar, y `rtk`
se resuelve por nombre en el entorno donde Codex ejecuta comandos.

## In scope

- La entrada `github` del `.codex/config.toml` del repo (fichero local, `.gitignore:32`).
- Hacer `rtk` resoluble en el entorno de ejecución de Codex.
- La traza SDD, que es lo único de este change que viaja a git.

## Out of scope

- Tocar el código del proyecto, sus tests o su empaquetado.
- El `config.toml` global de Codex más allá de dejarlo como fuente única de `github`.
- Codex Desktop (la app) y el fleco de `path` server-side desde Codex: quedan en el backlog.

## Constraints and risks

- **Ni `auth.json` ni ningún token se leen, copian ni se citan.** El bearer de `github` vive en una
  variable de entorno referenciada por nombre; ese nombre no es un secreto y su valor no se toca.
- Quitar la entrada del repo deja `github` **solo** por HTTP. Hay que comprobar que los otros cinco
  MCP del repo (MCP_DOCKER, codegraph, git, socket-mcp, jetbrains) siguen resolviéndose.
- La causa real del hallazgo 2 **no es la anotada en el backlog** — ver `spec.md`. Las dos vías que
  se traían apuntadas (PATH del sistema, `shell_environment_policy`) no lo arreglarían.

## Open questions

Ninguna: el diagnóstico de los dos hallazgos está cerrado por ejecución antes de especificar.
