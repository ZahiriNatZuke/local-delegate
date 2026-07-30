# Verificación — `codex-config-local`

Todo **por ejecución**. La herramienta clave del diagnóstico fue `codex sandbox`, que corre comandos
en el mismo entorno restringido que usa el agente **sin gastar cuota del modelo**.

## Entorno

- `main` en `16f8846`, limpia. Daemon 0.13.1 en `127.0.0.1:9393`.
- Codex CLI bundled del Desktop; `[windows] sandbox = "elevated"` en el config global.
- Ficheros tocados, los dos **fuera de git**: `D:\Projects\local-delegate\.codex\config.toml`
  (7 líneas menos) y `C:\Users\Yohan\.local\bin\rtk.cmd` (nuevo).

## Resultado: **los dos hallazgos cerrados**

| Req | Comprobación | Antes | Después |
|---|---|---|---|
| REQ-001 | `codex mcp list` con cwd en el repo | `Error: failed to load configuration / url is not supported for stdio in mcp_servers.github` | **exit 0**, lista completa |
| REQ-002 | Los cinco MCP del repo en la listada | — | `MCP_DOCKER`, `codegraph`, `git`, `socket-mcp`, `jetbrains` ✓ y `local-delegate` (`http://127.0.0.1:9393/mcp`) ✓ |
| REQ-003 | `github` una sola vez | duplicado con transportes incompatibles | una entrada, `https://api.githubcopilot.com/mcp/`, `Auth: Bearer token`, bearer por `CODEX_GITHUB_PERSONAL_ACCESS_TOKEN` |
| REQ-004 | `Get-Command rtk` **dentro** del sandbox | *«The term 'rtk' is not recognized»* | `C:\Users\Yohan\.local\bin\rtk.cmd`, `rtk 0.34.0`, exit 0 |
| REQ-005 | Un solo binario | — | el shim invoca `%USERPROFILE%\rtk.exe`; no hay copia ni hardlink |
| REQ-006 | `git status --short` | — | solo `?? .sdd/changes/codex-config-local/` |

## La causa raíz no era la anotada

El backlog decía *«`rtk` no está en el PATH que hereda Codex»*. Medido dentro del sandbox:

- `C:\Users\Yohan` **sí** está en su PATH (38 entradas).
- `& 'C:\Users\Yohan\rtk.exe' --version` → **`rtk 0.34.0`**: el binario se ejecuta perfectamente.
- `Get-Command rtk` → **no lo encuentra**.
- `Get-ChildItem 'C:\Users\Yohan'` → **falla**; `Get-ChildItem 'C:\Users\Yohan\.local\bin'` → funciona.

O sea: bajo el *restricted token* del sandbox el raíz del perfil **no es enumerable**, y la
resolución por PATH necesita enumerar el directorio. El problema era **dónde vive el shim**, no el
PATH. Ni añadir al PATH del sistema (ya estaba) ni `shell_environment_policy` (solo maneja
variables) lo habrían arreglado.

Dato de apoyo: dentro del sandbox `uvx` **sí** resuelve, y está justo en `.local\bin`.

## Las dos predicciones de la revisión del plan, comprobadas

1. **Quoting del shim.** `rtk read "…\con espacios.txt"` dentro del sandbox devolvió el contenido
   (`linea uno | linea dos`). Los argumentos con espacios y comillas sobreviven a `cmd.exe`.
2. **Cero regresión fuera del sandbox.** El mismo script fuera resuelve a
   `C:\Users\Yohan\rtk.exe` — el `.exe` del raíz sigue ganando, porque `C:\Users\Yohan` precede a
   `.local\bin` en el PATH y la resolución agota extensiones directorio por directorio. El shim solo
   actúa donde antes no había nada.

## Quality checks

- [x] Tests del proyecto: `uv run pytest -q --basetemp=…` → **277 passed** in 4.20s.
- [x] Lint y formato: `uv run ruff check .` → `All checks passed!`;
      `uv run ruff format --check .` → `46 files already formatted`.
- [x] JS del dashboard: `scripts/extract_dashboard_js.py` + `node --check` → 39 395 chars, exit 0.
- [x] Secretos: ninguno leído, copiado ni citado. De las variables del bearer solo se comprobó su
      **existencia** (`[bool]`), nunca su valor. `auth.json` no se abrió.
- [x] Sin cambios ajenos: `git status --short` solo muestra la traza SDD de este change.
- [x] El sandbox de Codex **no** se relajó: no se añadieron *readable roots*. La alternativa de dar
      lectura del perfil entero a un agente se descartó a propósito.
- [x] `git check-ignore -v` confirma que `.gitignore:32` es `.codex/` y cubre también el `.bak`.
- [x] Rollback listo: `.codex\config.toml.pre-github-fix-20260730.bak` (hash verificado idéntico
      antes de editar) y borrar `rtk.cmd`.

## Deviations and residual risk

- Solo se verificó con el **CLI bundled**, no con **Codex Desktop**. Comparten `config.toml`, así que
  el arreglo de `github` debería aplicarle igual; sin comprobar.
- Si el actualizador de `rtk` **mueve** el `.exe` fuera del raíz del perfil, el shim rompe con un
  error de ruta. Es visible y de arreglo trivial.
- La trampa de fondo sigue viva para cualquier otro proyecto: redefinir en un `.codex/config.toml`
  un servidor que ya existe en la global **con otro transporte** aborta la carga entera. La vía
  correcta es usar otro nombre de servidor. Queda anotado en memoria, no se construye defensa.
- No se corrió ningún check nuevo sobre `rtk` en el CI: el shim es configuración de esta máquina y
  no tiene representación en el repositorio.
