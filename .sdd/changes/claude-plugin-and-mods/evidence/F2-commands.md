# F2-commands — Comandos sin turno del modelo (REQ-014)

Fecha: 2026-10-22 · Windows 11 · CLI 2.1.307 · worktree `D:/Projects/ld-wt-f2-commands`, rama `feat/f2-commands`.

## Qué hay

- `<plugin>/mod/commands.js`: exporta `register(on, options, common)`. Con `commands_enabled=false` no
  registra nada. En `session.start` registra `/local-summarize`, `/local-commit` y `/local-lint`
  (una llamada literal por nombre: así `validate` dice «answers its own command» y no los cuenta como
  hooks que bloquean). Cada `command.run` responde por sí mismo con `{ text }` (y `exitCode: 1` en
  los errores, útil en `claude -p "/local-lint …"`); nunca llama a `next`.
  - `/local-summarize <ruta>` → `$.mcp.call('local-delegate', 'local_summarize', { path })` con la
    ruta hecha absoluta sobre `$.session.cwd()` (el MCP lee del lado del daemon, que tiene otro cwd).
  - `/local-commit` → `$.process.run(['git','diff','--cached'])`, volcado a
    `common.dataPath('tmp/<sello>-commit.diff')`, `local_commit_msg({ path })` y **solo muestra** el
    mensaje bajo una cabecera que dice que no se ha hecho ningún commit.
  - `/local-lint <fichero|comando>` → si el argumento (sin comillas) es un fichero, lo resume; si no,
    lo parte con las reglas de Windows (si el cwd es una ruta de Windows) o POSIX, lo corre con
    `timeoutMs: 30000`, vuelca `$ cmd`, stdout, stderr y el código a un temporal y llama a
    `local_lint_summary`.
  - Temporales: en un `finally`, se **vacían** con `$.fs.write(path, '')` y luego se **borran** con
    `common.runLd(['-I','-c', <os.remove>, path])`. `$.fs` no tiene borrado (medido en los tipos de
    2.1.307), así que el borrado pasa por el intérprete de `ld_bin`; si `runLd` da null, el fichero
    queda vacío.
  - `process.run` no disponible o vetado: se sabe cuando la llamada rechaza y `common.runLd(['-I','-c',''])`
    da null. Entonces `/local-commit` lo dice y `/local-lint` solo acepta un fichero y lo dice.
  - MCP caído (`$.mcp.call` rechaza) → `commands.error.mcp_down` (apunta a `local-delegate doctor`);
    error de la tool (`isError` o prefijo `[local-delegate error]`) → `commands.error.tool_failed`.
- `<plugin>/mod/i18n/{es,en}.json`: 18 claves `commands.*`, planas.
- `tests/test_mod_i18n_parity.py`: paridad (claves, vacías, marcadores `{x}`, identificadores entre
  comillas invertidas), control positivo del comprobador, y que cada `t('…')` de las piezas existe en
  los dos idiomas (con guarda de que el patrón encuentra llamadas).

## Trampas medidas aquí (para F2-mod-core y los lotes siguientes)

1. **`$` solo puede llegar a funciones declaradas en el nivel superior del fichero.** La primera
   versión tenía los helpers dentro de `register` y `claude plugin validate` la rechazó: «$ is passed
   to "summarize", which is not a function declared at the top of this file». Por eso los helpers son
   de nivel superior con prefijo `commands` (no chocan al concatenar).
2. **Prohibido `$?.` y el acceso calculado sobre `$`** («a computed or optional member access on
   $»). No se puede preguntar `typeof $.process.run`; la disponibilidad se deduce del rechazo.
3. **Forma concatenada comprobada**: `commands.js` con `export function register` renombrado y un
   `export const register` que la llama dentro de un `try` pasa `validate` (carpeta
   `scratchpad/f2c-concat`). Si `build_mod.py` envolviera cada pieza entera en una función o IIFE,
   los helpers dejarían de ser de nivel superior y el punto 1 lo rechazaría.
4. **`claude plugin test` no carga `.json`** («is not named like code»): los catálogos no se pueden
   importar en el mod; `common.t` tendrá que incrustarlos (`build_mod.py`) o leerlos con `$.fs`.
5. **El plugin real todavía no tiene `modules`**: `claude plugin test <plugin>` falla con «no hooks
   module to load» hasta que mezcle F2-mod-core.

## Cómo se corrieron los tests del mod

El runner del mod (y el `register.js` del plugin) es de F2-mod-core, que no ha mezclado. Sin añadir
dependencias: `scratchpad/f2c-run.sh` copia `commands.js` y `commands.test.ts` a un mod desechable
(`scratchpad/f2c-harness`, con un `register.js` que importa la pieza de forma estática y le pasa un
`common` mínimo), corre `claude plugin validate .` y `claude plugin test .` (CLI 2.1.307), todo con
`pesado.sh`. Los tests doblan `$` y `common` (la interfaz del plan); no usan el `$`/`on` del kit.

- Rojo (pieza vacía): 15 fallan, 1 pasa (`switch_off_registers_nothing`, que con la pieza vacía es
  cierto por construcción).
- Verde: **16 pass, 0 fail**. `validate`: pasa (solo avisos del directorio por README/LICENSE del
  mod desechable).
- Tests del plan: `splits_windows_args`, `splits_posix_args`, `lint_without_process_run_accepts_only_file`,
  `commit_only_shows_message`, `commit_temp_file_removed`, `daemon_down_clear_error`,
  `texts_follow_language`; más `posix_unclosed_quote_is_refused`, `lint_file_is_summarized_without_running_it`,
  `lint_command_output_goes_to_a_file_then_is_removed`, `lint_command_that_cannot_run_says_why`,
  `commit_with_nothing_staged_calls_nothing`, `commit_without_process_run_says_so`,
  `summarize_calls_local_summarize_with_absolute_path`, `summarize_missing_file_and_usage` y
  `switch_off_registers_nothing`.
- `commit_temp_file_removed` cubre tres salidas de la llamada (bien, `isError`, rechazo) y comprueba
  que el temporal tenía el diff cuando se llamó a la tool, que ya no existe y que el borrado fue sobre
  esa ruta; y, sin `runLd`, que queda vacío.

## Mutantes

1. Borrar solo si la llamada salió bien (sin `finally`): falla **solo** `commit_temp_file_removed`,
   en `expect(tempFiles(env), 'tool_error').toEqual([])` (recibe la ruta del `.diff`). Se comprobó con
   `grep` que el fichero mutado tenía la línea nueva.
2. Quitar la regla `""` dentro de comillas de Windows: falla **solo** `splits_windows_args`, en el
   `toEqual` del argv (recibe `gh` en vez de `g"h`).
3. Quitar `commands.lint.bad_quotes` de `en.json`: fallan `test_mod_catalogs_have_same_keys`
   («falta en en») y `test_every_key_a_piece_asks_for_exists`.

## Suite

`pesado.sh uv run pytest -n 2 -q`: 4335 pasados, 28 saltados, 1 fallo:
`test_detect_spanish_names::…outside_the_exception_list` por la palabra `staged` de la clave
`commands.commit.nothing_staged`; se renombró a `commands.commit.no_changes` (sin tocar el léxico) y
ese test y la paridad pasan (49 pasados). `ruff check` y `ruff format --check`: limpios.

## Llamadas `local_*`

- `local_commit_msg(path=<diff del lote>)`: borrador del mensaje de commit (retocado a mano).
- No hubo más: los ficheros que leí eran cortos o necesitaba su texto literal (la interfaz fijada del plan, los tipos del motor), y la salida de pytest la filtré con `grep` (un solo fallo).
