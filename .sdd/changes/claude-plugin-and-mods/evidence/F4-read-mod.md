# Evidencia — F4-read-mod (mod de lectura con elección)

Lote de la ola 5. REQ-020, REQ-021 (v3: sin diálogo el mod resume solo) y REQ-022. Base `main`
`a528294`, rama `feat/plugin-F4-read-mod`.

## Qué hay

- `<plugin>/mod/read.js`: un hook `tool.call` que solo se registra con `read_mod_enabled === true`.
  Filtro barato (nombre de tool y primer token) → `hook classify` por `runLd` → si
  `read_switch == "on"`:
  - lectura `whole`, o franjas cuya unión llega a 0,8 de las líneas, de un fichero ≥ 8 KB: con
    diálogo, `$.ui.ask` con «resumir / leer entero»; sin diálogo o en un subagente (`agentId`),
    resumen directo. El resumen sale de `$.mcp.call('local-delegate', 'local_summarize', { path })`,
    igual que `/local-summarize`, y se devuelve como `{ result }` con la forma de la tool (`Read`:
    `{ type: 'text', file: {…} }`; `Bash`/`PowerShell`: `{ stdout, stderr, interrupted }`);
  - `unclassifiable` o una tool cuyo resultado el mod no sabe sustituir: pasa y lleva un aviso en
    `context`;
  - guarda de REQ-022 sobre `Edit`/`Write`/`NotebookEdit` y las escrituras de shell
    (`kind == "write"`), persistida en `dataPath('read-guard/<session_id>.json')`.
- Cada decisión va a `hook record-read` con `decision` ∈ `summarized`, `auto_summarized`,
  `read_whole`, `dismissed`, `summary_failed`, `warned`.
- Latido: una vez por carga, `heartbeat({ pieces, read_mod_active: true })`, conservando el
  `pieces` que escribió `register.js`.

## Pruebas

`claude plugin test <plugin>`: 50 pass, 0 fail (11 nuevos en `read.test.ts`). Con un `read.js`
vacío los 11 fallaban (`no tool.call hook` y, en `off_by_default`, el control con el interruptor
encendido).

Mutantes (`scratchpad/mutants.py`), cada uno cae en el assert que le toca:

| Mutante | Falla |
| --- | --- |
| Sumar franjas en vez de unirlas | `accumulates_ranges_to_whole` (`nexts` esperado 3) |
| Guarda sin persistir | `guard_survives_resume` (fichero de la guarda) |
| Sin diálogo deniega | `auto_summary_without_dialog` (y los que dependen del resumen) |
| Ignorar `read_switch` | `respects_read_switch_off` |
| La lectura real no levanta la guarda | `allows_write_after_real_read` |
| Un subagente pregunta | `auto_summary_without_dialog` (`asks` esperado 0) |

Suite: `pytest -n 2` 4424 pass + el arreglo del nombre de clave (ver abajo); `ruff check` y
`ruff format --check` limpios; `claude plugin validate --strict` pasa.

## Fuera de la lista «Posee»

- `mod/i18n/es.json` y `en.json`: seis claves `read.*` (los textos van por catálogo).
- `tests/test_mod_static.py`: el fixture del `register.js` ya no puede dar `read` por ausente con la
  pieza presente; ahora excluye `read.js` de la copia para seguir probando una pieza ausente.
- `.github/workflows/ci.yml`: `read` en la lista de ficheros de `plugin test` que deben correr.

## Lecturas del contrato elegidas

- `range` = `[primera, última]` de líneas 1-based (`última` null = hasta el final), como
  `measure_read_paths.py`; también acepta `{start, end}`.
- El total de líneas sale del `totalLines` de un `Read` anterior o se cuenta con `$.fs.read`.
- `--list-tools`: acepta lista JSON, `{ tools }` o una por línea; sin respuesta, `Read`, `Bash`,
  `PowerShell`, `Grep`.

## Para la prueba en vivo (F4-live)

- Que el motor acepte el `{ result }` sustituido de `Read` y `Bash` (la doc de `ToolCallResult` lo
  permite y lo valida contra el esquema de salida de la tool).
- Que el aviso en `context` llegue al modelo cuando el hook devuelve el resultado de `next` con
  `ref`.
- `register.js` escribe el latido de `session.start` después de `onSessionStart` y lo pisa: por eso
  `read_mod_active` se escribe en la primera llamada clasificada, no al arrancar.

## Llamadas `local_*`

Ninguna en este lote: los ficheros grandes se leyeron por tramos con `sed`/`Read` porque hacía
falta el texto literal (API de mods, contrato), y la salida de tests se filtró con `grep`/`tail`.
