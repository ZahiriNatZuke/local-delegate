# Result review: El mod de lectura reutiliza el resumen de un fichero sin cambios (#608)

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no — cambio sin autenticación, secretos ni datos nuevos: memoria del proceso del mod y una decisión más en la telemetría local
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | `readSummaryOf` / `readCachedSummary` en `mod/read.js` |
| REQ-002 | yes | yes | relectura tras el resumen; un cambio A→B→A durante el resumen queda como riesgo residual |
| REQ-003 | yes | yes | `MOD_DECISIONS["summary_reused"]`, y sin nota de bloqueo (`MOD_NO_BLOCK_NOTE`) |
| REQ-004 | yes | yes | sin `tools/call`; sin nota de bloqueo, la medición de adopción no lo cruza con otra delegación |
| REQ-005 | yes | yes | el diálogo pregunta igual; «leer entero» no mira la caché |
| REQ-006 | yes | yes | topes de entradas, de caracteres y por fichero, y orden por uso, con test cada uno |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Cada reuso dejaba una nota de bloqueo sin delegación detrás; la siguiente delegación de la misma ruta en 10 min se la quedaba y `measure_adoption` la contaba como «aceptada» | media | — | suspected | arreglado: `MOD_NO_BLOCK_NOTE` en `hook_common` y los dos `record_decision`; test con guarda y control positivo; huellas regeneradas con `bump_version.py --boundaries` |
| F2 | Tope total de caracteres y orden por uso sin test | baja | baja | confirmed | arreglado: `the_summary_cache_caps_its_characters` y `a_reused_summary_is_the_last_to_go`, cada uno falla con su mutante |
| F3 | Doble lectura del fichero también por encima del tope por fichero | baja | baja | confirmed | arreglado: por encima de 1 M caracteres no se compara ni se relee |
| F4 | La entrada de un fichero cambiado seguía ocupando sitio | — | muy baja | suspected | arreglado: un fallo por texto distinto la quita |
| F5 | CHANGELOG decía «misma sesión» y la caché es del proceso | — | redacción | suspected | arreglado: «mientras Claude Code siga abierto» |
| F6 | Un cambio que vuelve al texto original durante el resumen no se detecta | baja | — | suspected | aceptado como riesgo residual (verification.md) |
| F7 | Rutas relativas: la clave y `$.fs.read` pueden resolver distinto | baja | — | suspected | previo al cambio; sin acción |

## Required follow-up

- Ninguno antes de cerrar. Repeticiones entre procesos (28 de 157 en el #608) quedarían para otra tarjeta si hacen falta.

## Revisión independiente posterior (orquestador)

- F8: un resumen con `[local-delegate warning:` se guardaba y se repetiría mientras el fichero no cambie: ya no se guarda (`a_summary_with_a_warning_is_not_kept`, mutante sin la comprobación: 1 llamada en vez de 2).
- F9: el resumen reutilizado repetía el recibo «leído server-side»: se quita y se dice que se reutilizó (`a_reused_summary_says_so_instead_of_the_receipt`, es y en; mutante sin quitarlo: falla).
- F10: un fichero de más de 1 M se leía solo para descartarlo: ahora decide `classified.bytes` (`a_file_over_the_cap_is_not_read_for_the_cache`; mutante que siempre lee: falla).
- Pendiente, al final de la cola: regenerar las huellas de los hooks tras mezclar `main` (#603 cambió los hooks).
