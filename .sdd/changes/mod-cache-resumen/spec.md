# Specification: El mod de lectura reutiliza el resumen de un fichero sin cambios (#608)

## Summary

Cuando el mod de lectura del plugin ya resumió un fichero en este proceso de Claude Code y el
contenido no ha cambiado, devuelve ese mismo resumen sin volver a llamar a `local_summarize`, y deja
en la telemetría de hooks una decisión propia (`summary_reused`) en vez de una delegación nueva. El
log de uso no recibe fila: el panel y las mediciones no lo cuentan como ahorro nuevo, y la serie de
lecturas sustituidas (P-4) lo sigue contando como lectura sustituida.

Evidencia: issue #608 (Mac, 258 llamadas del mod, 157 repeticiones, 129 en la misma sesión); en
una copia del log de esta PC, 163 llamadas del mod, 32 repeticiones de ruta + `chars_in`, ~990 s de
latencia repetida. `mod/read.js` `readSteer` (l. 888) llama a `readSummarize` (l. 823) cada vez,
sin memoria de resúmenes; `register` (l. 1100) reinicia el estado del módulo.

## Requirements

- **REQ-001** — Una segunda lectura resumible del mismo fichero con el mismo contenido, en el mismo
  proceso del mod, devuelve el resumen guardado sin llamar a `local_summarize`.
  - Request: "Reutilizar el resumen de un fichero que no cambió"
  - Verify: test `read.test.ts` `a_repeated_read_reuses_the_summary`
- **REQ-002** — La clave detecta un cambio de contenido de forma fiable: si el texto del fichero
  cambió (aunque el tamaño sea el mismo), se vuelve a resumir; si el fichero no se puede leer, no
  se usa la caché; si el fichero cambia mientras se resume, ese resumen no se guarda.
  - Request: "clave que detecte un cambio de contenido de forma fiable"
  - Verify: test `read.test.ts` `a_changed_file_is_summarized_again`, `a_file_changed_while_summarizing_is_not_cached`, `an_unreadable_file_is_not_cached`
- **REQ-003** — El reuso se registra con la decisión `summary_reused` (distinta de `summarized` y
  `auto_summarized`), y en la telemetría de hooks cuenta como lectura sustituida
  (`suggested` y `blocked`, `reason: large_prose`), no como decisión desconocida.
  - Request: "registrar el reuso como acierto de caché, distinto de una delegación nueva"
  - Verify: test `read.test.ts` (decisión enviada) y `tests/test_read_classifier.py` (línea escrita)
- **REQ-004** — Un acierto no escribe fila en el log de uso (no hay `tools/call`), así que el
  panel no lo cuenta como delegación ni ahorro nuevo; la fila de la primera delegación queda igual.
  - Request: "de forma que el panel y las mediciones no lo cuenten como ahorro nuevo ni lo pierdan"
  - Verify: review (el acierto no llama a `$.mcp.call`, comprobado en el test de REQ-001) y el test Python de REQ-003
- **REQ-005** — Con diálogo, la persona sigue eligiendo: «leer entero» pasa la lectura real aunque
  haya resumen guardado; «resumir» usa el guardado.
  - Request: derived: no cambiar el comportamiento del diálogo
  - Verify: test `read.test.ts` `the_dialog_still_decides_with_a_cached_summary`
- **REQ-006** — La caché tiene tope (entradas y caracteres) y empieza vacía en cada `register`.
  - Request: derived: memoria acotada en el proceso de Claude Code y tests aislados
  - Verify: test `read.test.ts` `the_summary_cache_is_bounded` y la suite existente intacta

## Acceptance scenarios

### Scenario: el mismo fichero dos veces

- **Given** el mod encendido, sin diálogo, y un `.md` grande resumido una vez
- **When** se vuelve a leer entero sin cambios
- **Then** el resultado lleva el mismo resumen, no hay segunda llamada a `local_summarize` y se registra `summary_reused`

### Scenario: el fichero cambió

- **Given** un `.md` ya resumido
- **When** se edita (mismo tamaño o no) y se vuelve a leer
- **Then** se llama otra vez a `local_summarize` y se registra `auto_summarized`

## Edge cases and failure behavior

- Lectura del fichero fallida: sin caché, comportamiento de antes.
- Resumen fallido: no se guarda nada; la lectura real pasa (como antes).
- Fichero cambiado durante el resumen: se devuelve el resumen (como antes) pero no se guarda.

## Non-functional requirements

- Sin dependencias nuevas; solo memoria del proceso (no disco, no varios procesos: nivel lite).
- Ningún texto del fichero sale a logs ni a telemetría.

## Non-goals

- Caché en el servidor o en el daemon (para las llamadas del modelo) o entre procesos y sesiones.
- Cambiar el esquema del log de uso o el panel.
- La regex `READ_CHAINING` (PR #603).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
