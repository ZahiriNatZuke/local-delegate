# F2-mod-core — Esqueleto del mod y tools fijas

REQ-013, REQ-016 y REQ-009 (check `mod.loaded`; `doctor` pasa de 32 a 33). Medido con la CLI
2.1.307 de esta PC (`claude plugin validate --strict` y `claude plugin test`, `CLAUDE_CONFIG_DIR`
del scratchpad). El job `plugin` del CI lo repite con la mínima, 2.1.292, en los tres SO.

## Lo que el validador del motor acepta o rechaza (medido en este lote, 2.1.307)

Plugins de borrador en el scratchpad (`va`…`ve`), cada uno con `validate --json`:

| Forma | Resultado |
|---|---|
| `register.js` en la raíz del plugin, `hooks.json` con `"modules": ["../register.js"]` | aceptado |
| Piezas pegadas dentro de un IIFE/cierre y `piece.register(on, …)` | **rechazado**: `on` solo se pasa a funciones declaradas o importadas por nombre en el nivel superior |
| Usar el valor que devuelve una función que recibió `on` (`x = register_p(on) === 'off'`) | **rechazado**: «the value of … is kept» |
| Pasar `$` a un método (`common.heartbeat($)`, también con `import * as common`) | **rechazado**: «$ itself is passed as an argument» |
| Pasar `$` a una función importada por nombre (`import { beat } from './mod/c.js'`; `beat($)`) | aceptado |
| Una pieza que importa por nombre de `./common.js` y llama `beat($)` dentro de su hook | aceptado |
| Un objeto con cierres sobre `$` construido dentro del hook (`{ write: (p, t) => $.fs.write(p, t) }`) | aceptado |
| Dos `on('session.start', …)` sin matcher en el mismo módulo (register.js + commands.js) | **rechazado**: «registered twice without a matcher» |
| El texto `import (` en un comentario | lo cuenta como `import()` dinámico nuestro chequeo; se evita en comentarios |
| `plugin test`: una plugin en línea (`plugins: [...]`) se escribe a su propia carpeta | no puede capturar nada del fichero de test (ni importar `common.js`) |
| `plugin test`: `ld_bin` es obligatoria | cada test pasa `{ options: { ld_bin } }`, o el módulo no carga |
| `plugin test`: `$.fs.write` llega al hook con separadores del SO | el test normaliza `\` → `/` |

## Diseño resultante (desviación de la interfaz del plan)

- `scripts/build_mod.py` genera `register.js` (no se versiona) con **`import` estáticos solo de las
  piezas presentes** y la llamada a cada `register(on, options)` dentro de su propio `try`. Las
  ausentes quedan `absent`; la que lanza, `failed`; la apagada por `userConfig`, `off`. Una pieza
  solo declara en su nivel superior (`check_piece`: funciones y `const`; importa solo de
  `./common.js`; no engancha `session.start`), así que importarla no puede lanzar.
- **`register.js` tiene el único `session.start`**: llama `hasDialog(e)`, el `onSessionStart($, e)`
  que exporte cada pieza encendida (en su `try`) y escribe el latido.
- **`mod/common.js` exporta funciones con nombre que reciben `$`**: `token($)`,
  `daemonFetch($, path, init)`, `t(key, vars)`, `runLd($, args, stdin, timeoutMs)`,
  `dataPath($, name)`, `hasDialog(e)`, `heartbeat($, fields)`, más `setup(options, extras)`.
  `engineCommon($)` devuelve la interfaz del plan sin `$` (`runLd(args)`, `dataPath(name)`, …) como
  cierres; se construye dentro del hook. `runLd` corre `[ld_bin, ...args]`, como dice el plan.
- `commands.js` (F2-commands, tocado solo para esto): importa `engineCommon`, cada hook usa
  `common || engineCommon($)` (el test sigue pasando su doble), y su `session.start` pasa a
  `export async function onSessionStart($, e, common)`. `commands.test.ts`: una línea, llama
  `onSessionStart` en vez de buscar el hook.
- Catálogos: `build_mod.py` incrusta `mod/i18n/{es,en}.json` en `register.js` (`plugin test` no carga
  `.json`).
- Latido: `<CLAUDE_CONFIG_DIR o ~/.claude>/plugins/data/local-delegate-local-delegate/heartbeats/<sesión>.json`
  con `session_id`, `version`, `entrypoint`, `process_run`, `dialog`, `read_mod_enabled`, `pieces`
  y `at`. El borrado de latidos de más de 7 días que pide la decisión 9 **no se hace en el mod**
  (`$.fs` no tiene borrado); `doctor` trata como viejo uno de más de 7 días.
- Variables que lee el mod: `LOCAL_DELEGATE_WEB_TOKEN` (el único secreto) y, para la ruta de datos y
  el latido, `CLAUDE_CONFIG_DIR`, `USERPROFILE`, `HOME`, `CLAUDE_CODE_ENTRYPOINT`. Lista cerrada en
  `test_mod_static.py`.
- Puerto del daemon fijo en 9393 (`config.WEB_PORT` por defecto): leer `LOCAL_DELEGATE_WEB_PORT`
  ampliaría REQ-016. Límite documentado en la wiki.

## Runner de los tests TS (para F2-commands y los lotes de F3/F4)

```bash
uv run python scripts/build_mod.py
claude plugin validate --strict --json src/local_delegate/resources/claude-plugin/local-delegate
claude plugin test src/local_delegate/resources/claude-plugin/local-delegate
```

Con `CLAUDE_CONFIG_DIR` aislado y `pesado.sh`. Corre los tres ficheros (`pinned-tools`, `common`,
`commands`); el CI exige que aparezcan los tres y `0 fail`, con control negativo (mod roto ⇒ falla).

## Resultados

- `claude plugin validate --strict --json`: `success: true`, sin errores ni avisos.
- `claude plugin test`: 29 pass, 0 fail, 3 ficheros.
- Tests Python nuevos: `test_mod_static.py` (11, la parte con `node` corre `register.js` con una
  pieza que lanza: las otras quedan `on`, la rota `failed`, `read` `absent`) y 4 de `mod.loaded` en
  `test_checks_plugin.py`. Fallaban primero por `KeyError: 'mod.loaded'`.
- Suite completa: 4351 passed, 28 skipped. `ruff check` y `ruff format --check` limpios.

## Mutantes

| Mutante | Lo caza | Assert |
|---|---|---|
| `daemonFetch` sin la guarda de ruta | `common.test.ts::daemonFetch_rejects_non_loopback` | `toBe(null)`: `//evil.example/…` llegó al daemon (200) |
| `build_mod.py` sin `try` alrededor de la pieza | `test_register_loads_pieces_dynamically_inside_try` | `try {\n register_pinned_tools(on, options)` no está |
| `mod.loaded` ignora las piezas `failed` | `test_mod_failed_piece_or_stale_heartbeat_warns` | `'ok' == 'warn'` |

Los tres mutan de verdad (fichero distinto antes de correr) y se restauraron.

## Llamadas `local_*`

- `local_summarize(path=evidence/T0.md)`.
- `local_lint_summary(path=<scratchpad>/f2core/pytest.log)`.
- `local_commit_msg(path=<diff>)` para el borrador del commit.
