# Plan de implementación: Arregla los dos hallazgos de configuración de Codex

## Approach

Dos ediciones de configuración local, independientes entre sí, ambas reversibles y ninguna dentro
del repositorio:

1. **`github` con una sola definición.** Se borra el bloque `[mcp_servers.github]` del
   `.codex/config.toml` del repo y se deja la definición HTTP de la global, que es la oficial de
   Copilot y ya trae su bearer por variable de entorno. Se elige quitar la del repo, y no la
   global, porque la global sirve a todos los demás proyectos y la del repo solo duplicaba —
   además la stdio de `npx @modelcontextprotocol/server-github` exige un token en el entorno y
   arranca un proceso por sesión, sin aportar nada frente a la HTTP.

2. **`rtk` resoluble bajo el sandbox.** Se crea `C:\Users\Yohan\.local\bin\rtk.cmd`, un shim de una
   línea que invoca `C:\Users\Yohan\rtk.exe` por ruta absoluta y propaga argumentos y código de
   salida. `.local\bin` ya está en el PATH (usuario y máquina) y **es enumerable** bajo el
   restricted token — demostrado: `uvx` resuelve desde ahí dentro del sandbox. Un shim y no una
   copia del `.exe` (REQ-005: una actualización de `rtk` no debe dejar binarios desfasados) y no un
   hardlink (que quedaría apuntando al inode viejo si el actualizador reemplaza el fichero).

No se toca el sandbox ni sus *readable roots*: arreglaría el síntoma dándole a un agente acceso de
lectura a todo el perfil del usuario.

## Ordered tasks

1. **Copia de seguridad del config local del repo**
   - Ficheros: `D:\Projects\local-delegate\.codex\config.toml` →
     `.codex\config.toml.pre-github-fix-20260730.bak`
   - Requisitos cubiertos: soporte de rollback de REQ-001..003
   - Verificación: el `.bak` existe y su contenido es idéntico al original
   - Rollback: restaurar el `.bak` sobre el original

2. **Quitar el bloque `[mcp_servers.github]` del config del repo**
   - Ficheros: `D:\Projects\local-delegate\.codex\config.toml` (líneas 25-31, 7 líneas)
   - Requisitos: REQ-001, REQ-002, REQ-003
   - Verificación: `codex mcp list` con cwd en el repo sale con código 0 y lista los cinco MCP del
     repo + `local-delegate` + `github`; `codex mcp get github` muestra transporte HTTP
   - Rollback: restaurar el `.bak` de la tarea 1

3. **Crear el shim `rtk.cmd`**
   - Ficheros: `C:\Users\Yohan\.local\bin\rtk.cmd` (nuevo)
   - Requisitos: REQ-004, REQ-005
   - Verificación: `codex sandbox pwsh -NoProfile -File <script>` con `Get-Command rtk` y
     `rtk --version`; y fuera del sandbox, que `rtk` sigue resolviendo y funcionando
   - Rollback: borrar el fichero — no había nada antes en esa ruta (comprobado: `.local\bin` no
     contiene ningún `rtk*`)

4. **Comprobar que el repositorio no se ensucia**
   - Ficheros: ninguno
   - Requisitos: REQ-006
   - Verificación: `git status --short` solo muestra `.sdd/changes/codex-config-local/`
   - Rollback: no aplica

## Test strategy

- **Unit / integration:** no aplica — no hay código del proyecto en este change.
- **End-to-end / manual, por ejecución:**
  - `codex mcp list` desde `D:\Projects\local-delegate` (antes: falla; después: lista).
  - `codex mcp get github` desde dentro del repo, para confirmar el transporte que gana.
  - `codex sandbox pwsh -NoProfile -File diag-rtk2.ps1`, el mismo script que documentó el fallo, para
    que la evidencia sea comparable antes/después.
  - `rtk --version` fuera del sandbox, para descartar que el shim tape al `.exe` con una regresión.
- **Checks del proyecto:** los cuatro pasos del CI (`ruff check .`, `ruff format --check .`,
  `pytest -q`, `extract_dashboard_js.py` + `node --check`) se corren igualmente antes del push, aunque
  este change no toque código, para dejar constancia de que nada se movió.
- **Secretos:** el bloque que se borra contiene `env_vars = ["GITHUB_PERSONAL_ACCESS_TOKEN"]` — un
  **nombre** de variable, no un valor. No hay secretos que redactar. `auth.json` no se lee.

## Migration and compatibility

- El `.codex/` del repo está en `.gitignore:32`: el cambio es local a esta máquina y no llega a
  otras. Ningún otro proyecto se ve afectado, la global no cambia.
- El shim es aditivo: los consumidores actuales de `rtk` (esta sesión incluida) siguen resolviendo
  al mismo binario, ahora posiblemente a través del `.cmd`. Se verifica que no hay regresión.
- Si el usuario quisiera algún día la stdio de `github` en este repo, la vía correcta no es
  redefinir el mismo nombre: es usar un nombre distinto (`github-stdio`), porque el conflicto lo
  provoca la fusión por clave.

## Plan review (adversarial, con las comprobaciones que exigió)

Cuatro objeciones al plan y qué se hizo con cada una:

1. **«El shim `.cmd` puede destrozar argumentos con espacios, comillas o metacaracteres, porque los
   pasa por `cmd.exe`.»** Riesgo real y no descartable en general. Se añade a la verificación una
   invocación con un argumento entrecomillado y con espacios, en vez de darlo por bueno.
2. **«Un `rtk.cmd` en el PATH puede tapar al `.exe` fuera del sandbox y cambiar el comportamiento
   diario.»** No ocurre, y por una razón que conviene dejar escrita: en el PATH,
   `C:\Users\Yohan` aparece **antes** que `C:\Users\Yohan\.local\bin`, y la resolución de Windows
   agota las extensiones **directorio por directorio**. Fuera del sandbox sigue ganando el `.exe`
   del raíz; dentro, ese directorio no es enumerable, se salta, y cae en el shim. El shim solo actúa
   donde hoy no hay nada. Se verifica igualmente que fuera del sandbox no hay regresión.
3. **«Si `CODEX_GITHUB_PERSONAL_ACCESS_TOKEN` no estuviera definida, quitar la stdio cambiaría un
   fallo total por un `github` que no conecta.»** Comprobado antes de tocar nada: la variable existe
   en el entorno de usuario (solo se comprobó su **existencia**, nunca su valor).
4. **«El `.bak` puede acabar en git.»** Comprobado con `git check-ignore -v`: la regla
   `.gitignore:32` es `.codex/`, el directorio entero, así que cubre también el `.bak`.

- [x] Cada requisito tiene tarea y verificación: REQ-001..003 → tarea 2; REQ-004..005 → tarea 3;
      REQ-006 → tarea 4; rollback → tarea 1.
- [x] Las operaciones destructivas tienen salvaguarda: la única edición destructiva (borrar 7 líneas)
      va precedida de un `.bak`; la creación del shim se revierte borrando el fichero.
- [x] Dependencias y cambios de configuración explícitos: dos ficheros locales, ninguno en git.
- [x] Sin trabajo ajeno: no se toca el sandbox, ni `AGENTS.md`, ni la instalación de `rtk`, ni el
      código del proyecto.
