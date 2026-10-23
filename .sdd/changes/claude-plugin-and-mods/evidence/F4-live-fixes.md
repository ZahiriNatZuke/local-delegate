# F4-live-fixes — evidencia

Tres arreglos de la prueba en vivo del 2026-10-23, para la 0.41.1.

## 1. Registro duplicado de una decisión del mod de lectura

**Síntoma.** Una lectura con diálogo y elección «resumir» dejó dos líneas `decision: summarized` en
`~/.claude/hooks/telemetry.jsonl` (mismo `path_sha`, ids `5f154f85448d` a las 11:46:07.138 y
`e1930dc37d9b` a las 11:46:14.055) y un `ModRecordLost` en `hook-failures.jsonl` a las 11:46:07.144,
6 ms después de que la primera línea ya estuviera escrita.

**Causa (con evidencia).**

- `usage-202610.jsonl`: el resumen del mod de ese fichero (16 843 caracteres, `toolu_plugin_a825…`)
  terminó en el segundo 11:46:06; la línea se escribió en 11:46:07.138, unos 1000 ms después, que es
  justo el tope del mod para el daemon (`READ_DAEMON_RECORD_TIMEOUT_MS = 1000`).
- `readWithin` hace una carrera entre la petición y un `sleep`, pero **no cancela la petición**: al
  vencer el tope, el mod da la vía del daemon por fallida aunque el daemon siga y escriba.
- Luego prueba el proceso, que tras `$.ui.ask` el motor rechaza en el acto (el síntoma conocido de la
  0.41.0: `runLd` vuelve `null`). Por eso el rastro sale 6 ms después de la línea del daemon. Si el
  proceso hubiera escrito habría habido **tres** líneas en el primer intento, y hubo una.
- El reintento de la llamada siguiente (11:46:14) vuelve a escribir. Cada escritura sacaba un `id`
  nuevo (`new_id()` en `record_decision`), así que nada podía reconocer la repetición.
- Descartado: el 204 sin cuerpo tomado como fallo (`daemonFetch` devuelve `status: 204` y
  `readRecordByDaemon` lo acepta) y una salida del proceso mal leída (no explicaría el orden ni el
  número de líneas).

**Arreglo.**

- El mod genera el `id` (12 hexadecimales) **una vez** por decisión y lo manda por todas las vías:
  daemon, proceso y reintento (`readRecordId`).
- `record_decision` (lectura y shell) usa ese `id` (`hook_common.mod_record_id`, solo si tiene la
  forma) y no escribe si ya está en los últimos 64 KB del destino (`already_recorded`); la nota del
  bloqueo tampoco se duplica. Un mod sin `id` (0.41.0) escribe como antes.
- `readWithin` distingue el tope vencido (`READ_TIMED_OUT`). Si el daemon se pasa del tope, la línea
  **no** se da por perdida, no se lanza el proceso a la vez (competiría con la escritura del daemon)
  y espera a la siguiente llamada. El reintento va con el mismo `id`. Solo si ese intento también
  falla queda el rastro.
- Queda una carrera teórica: daemon tardío y proceso escribiendo en el mismo milisegundo en el
  segundo intento. Se acepta: haría falta que el daemon tarde más de 1 s dos veces seguidas.

**Tests (fallaban antes por la razón que dicen).**

- `tests/test_hook_record_read_endpoint.py`: `test_the_same_id_is_written_once` (×3, antes había 3
  líneas en vez de 1), `test_a_new_id_is_a_new_line` (antes `KeyError: 'id'`) y
  `test_only_the_tail_is_read`. El de las entradas sin `id` válido es una guarda y ya pasaba.
- `mod/read.test.ts`: `a_daemon_slower_than_its_limit_that_writes_leaves_one_line_*` (con el proceso
  rechazado, antes había rastro; con el proceso vivo, antes se lanzaba el proceso a la vez),
  `every_road_carries_the_same_id` (antes `id` era `undefined`) y
  `a_late_daemon_that_never_writes_is_traced_at_the_retry` (antes el rastro salía en el acto).

## 2. Banda: minutos, avance por trozos y sin «·» suelto

- Más de 60 s: `3 min 16 s` (es) y `3m 16s` (en); menos de 60 s: `14 s`.
- Con `chunks > 1` en `/api/inflight`: `local_summarize 7/9 · 3 min 16 s`.
- Barra sin modelo: `● LISTO  29 delegaciones` (el separador solo va entre partes presentes, después de
  `statusFit`). En `line` no pasaba (guarda nueva). En Desktop, cubierto por el rediseño.
- Tests que fallaban antes: los de minutos y trozos en `bar` y en `line`/en (`196 s`), y el de la
  barra sin modelo (`● LISTO  · 3 delegaciones`).

## 3. Banda de Claude Desktop rediseñada (diseño v2)

- Una sola línea: un `Text` con `Text` anidados en línea, en dos tonos, con el color solo en el punto
  (también en la palabra si está caído o sin servicio). A la derecha, el modo de lectura atenuado.
- Sin píldora con borde, sin fondo, sin `Link` (el panel pide token: el enlace abría en 401), sin
  `gap` y sin props de tipografía. Se quitaron `STATUS_PANEL`, `STATUS_TYPE_PROPS` y
  `statusDeskText`, y la excepción de `localhost` en `tests/test_mod_static.py`, que ahora exige que
  `status.js` no nombre ni `localhost` ni `Link`.
- Textos: «Sin datos del modelo» / «No model data», «+1 más» / «+1 more» (`status.more_title`); se
  retira `status.empty_title` (la línea dice «sin delegaciones aún» en minúscula, tras un `·`).
- Tests de Desktop nuevos (sin `Link`, ni `borderStyle`, ni `size`/`weight`, ni `gap`, una sola `Box`,
  el lado izquierdo es un único `Text` y los cinco estados): con el `status.js` de `main` fallan 5 de 5.
- **Por mirar en vivo:** que Desktop pinte los `Text` anidados de corrido y no apilados. Si los apila,
  el plan B es una fila de `Text` hermanos sin cajas ni `gap` (no implementado).

## Suite

- `claude plugin test`: 117 pass, 0 fail.
- `pytest -n 2`: 5213 passed, 28 skipped.
- `ruff check` y `ruff format --check`: limpios.
- Las huellas de los hooks cambiaron (`suggest_delegate_read.py`, `suggest_delegate_shell.py`):
  `scripts/data/hook_hashes_after.json` regenerado con `bump_version.py --boundaries`. Abre un tramo
  nuevo de P-4.
