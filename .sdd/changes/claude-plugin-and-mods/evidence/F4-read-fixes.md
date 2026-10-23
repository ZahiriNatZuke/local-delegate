# F4-read-fixes — dos defectos del mod de lectura vistos en la prueba interactiva de la 0.41.0

Rama `fix/plugin-read-fixes` desde `main` en `dc2e018` (0.41.0). Van a la 0.41.1.

## Defecto 1 — las decisiones del diálogo no llegaban a la telemetría

**Síntoma (sesión principal, en vivo):** con diálogo y «resumir», el resumen y la guarda llegan,
pero en `~/.claude/hooks/telemetry.jsonl` no hay ni una línea `summarized`, `read_whole` ni
`dismissed`; `auto_summarized`, `warned` y `not_prose` sí. El registro iba solo por
`common.runLd([... 'record-read'])` (read.js:416-423 en `dc2e018`) y `runLd` (common.js:202-218)
se traga el rechazo. La causa exacta (por qué `$.process.run` no escribe tras `$.ui.ask`) **no se
ha visto**; el arreglo no depende de ella.

**Arreglo:**

- `POST /api/hook/record-read` en `web/metrics.py`: token + solo loopback (`_HOOK_CHECKS`, las
  mismas que `/api/hook/classify`), cuerpo `{"payload", "env"}`, 204. Escribe con
  `hook_entry.record_read(entry, environ)`, la misma función que usa ahora `hook record-read` del CLI.
  Esa función corre el `record_decision` del script de la vía viendo el entorno del cliente por un
  `ContextVar` de `hook_common` (`run_with_environ`): `enabled`, `record` y `block_state` miran
  `current_environ()`. No toca `os.environ` (el daemon atiende a la vez). Los scripts
  `suggest_delegate_*.py` no cambian, así que su huella de P-4 tampoco.
- Variables: `hook_entry.RECORD_ENV` = `CLASSIFY_ENV` + `LD_HOOK_TELEMETRY_LOG` + `LD_HOOK_ENABLED`.
  El destino tiene que ser un `.jsonl` con ruta absoluta; si no, 400 y no se escribe nada (el endpoint
  no escribe donde le digan). Sin destino no se escribe, como en el CLI.
- El mod (`readRecord`): primero el daemon (tope 1 s), luego el proceso. Si ninguno la toma:
  `$.ui.log(..., {to: 'debug'})` con la decisión y la vía (sin ruta ni contenido), una línea
  `{ts, hook: "record-read", error: "ModRecordLost", decision}` en `LOG_DIR/hook-failures.jsonl`
  (con el mismo tope de 256 KB que `hook_entry`), y la línea queda pendiente: se reintenta **al
  empezar la siguiente llamada a una tool**, un hook al que no precede ningún diálogo.
- Por qué no se registra antes del diálogo: la decisión no existe hasta que la persona contesta.
  Por eso, si el motor rechazara también `$.http.fetch` tras `$.ui.ask`, la cobertura es el reintento.
- Límite conocido: `band` (`strong`/`suggest`) de las líneas de `Read` lo calcula el script con
  `os.environ["LD_HOOK_READ_STRONG_KB"]`; por el daemon sale con el valor del daemon (por defecto
  100, igual que el del cliente si no lo cambió). Arreglarlo exige tocar `suggest_delegate_read.py`
  y abrir un tramo nuevo de P-4: no se hizo.

## Defecto 2 — las franjas «grandes» se resumen otra vez y el mensaje engaña

**Criterio real, confirmado en el código (`dc2e018`), antes de cambiar nada:**

- `read.js:700-701`: «grande» es el **fichero** (`classified.bytes` = tamaño del fichero,
  `read_classifier.py:660-670`) ≥ `min_bytes` (`LD_HOOK_READ_SUGGEST_KB`, 8 KB).
- `read.js:726-727`: lectura entera de prosa grande → resumen.
- `read.js:729-735`: una franja suma sus líneas a las ya leídas literales del fichero en la sesión
  (`readCoverage`, cada línea una vez); si la unión llega a `READ_WHOLE_SHARE` = 0,8 (`read.js:34`,
  REQ-020), se resume. **No hay criterio por tamaño del tramo**: `offset:1 limit:400` se resumió
  porque cubre el 100 %; `offset:70 limit:200` y `sed -n '140,230p'` porque, con lo leído antes,
  pasaban del 80 %; `offset:10 limit:60` y `sed -n '70,140p'` no llegaban.
- `read.js:576`: la guarda de escritura se libera con **cualquier** lectura literal del fichero
  (una franja de una línea basta). No se cambió: `Edit` necesita además que `old_string` coincida.

El criterio **no cambia** (REQ-020/021). Cambia el texto, que ahora dice la regla real:

- `read.summary.header_budget` (con el número de líneas del fichero): «puedes leer literal hasta
  {lines} de sus {total} líneas en total; desde el 80 %, también se resume», y que con una lectura
  literal del tramo a cambiar ya se puede editar. `{lines}` = `readLiteralBudget(total)`, el máximo
  por debajo del 80 % (79 de 100).
- `read.summary.header_ranges` (una franja resumida): «no es por el tamaño del tramo: con él, lo
  leído llegaría al {pct} % de sus {total} líneas… Llevas {read}; te quedan {left} (el máximo es
  {lines})».
- `read.summary.header` queda para cuando no se puede contar las líneas.
- `read.guard.refused`: lo mismo para `Edit`/`Write`/escrituras de shell.

Desviación respecto al encargo: el encargo proponía «léelo por trozos de hasta ~8 KB (unas N
líneas)», con N sacado de `LD_HOOK_READ_SUGGEST_KB`. Eso sería falso con el criterio actual (los
trozos de 8 KB también se resumen cuando la suma llega al 80 %), así que el mensaje da el número
que sí vale: el de líneas acumuladas.

## Tests (antes fallaban por la razón que dicen)

- `read.test.ts`, 6 nuevos: `dialog_decisions_are_recorded_by_the_daemon_when_the_process_is_refused`
  (un `$` falso cuyo `runLd` devuelve `null` tras `ui.ask`: las tres decisiones llegan por HTTP con
  `LD_HOOK_TELEMETRY_LOG` y `LD_HOOK_ENABLED` en `env`), `the_process_is_the_fallback_when_the_daemon_does_not_record`,
  `a_lost_decision_leaves_a_trace_and_is_retried`, `the_failure_log_is_capped`,
  `the_summary_says_how_much_can_be_read_literally`, `a_range_summary_says_it_was_the_accumulated_share`.
  Antes del cambio: 6 fallos (`Expected ["summarized"] / Received []`, `length 1 / 0`, cabecera vieja).
  Se ajustaron dos existentes del daemon (ahora la decisión también va al daemon).
- `tests/test_hook_record_read_endpoint.py`, 15 casos: misma línea que el CLI en proceso (5
  decisiones/vías) y que el proceso real, entorno de la petición frente al del daemon, sin destino,
  destino no `.jsonl` absoluto → 400, 401 sin token, 403 fuera de loopback, cuerpos malos.
  Antes: `AttributeError: ... no attribute 'RECORD_ENV'`. Mutante (`run_with_environ` sin fijar el
  entorno): 13 de 15 fallan.
- `tests/test_mod_static.py`: las variables de `readRecordVars` son `RECORD_ENV − CLASSIFY_ENV`, y
  el log de fallos del mod es `hook_entry.FAILURE_LOG` con su tope.

Suite: `pytest -n 2` 5203 passed, 28 skipped; `claude plugin test` 94 pass, 0 fail.

## Falta probar en vivo (sesión principal, tras instalar)

1. Diálogo → «resumir», «leer entero» y cerrar: que aparezcan las tres líneas `source: "mod"` en
   `telemetry.jsonl`, y mirar si llegaron por el daemon o por el reintento (si hay
   `ModRecordLost` en `hook-failures.jsonl`, el HTTP también se rechazó tras `$.ui.ask`).
2. Leer por franjas un `.md` de ~18 KB: el resumen de la franja que pasa del 80 % dice el % y las
   líneas que quedan; una franja pequeña posterior pasa literal; `Edit` tras el resumen se rechaza
   con el texto nuevo y se acepta tras una franja literal.
