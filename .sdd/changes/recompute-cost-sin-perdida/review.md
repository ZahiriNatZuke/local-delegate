# Result review: recompute-cost no pierde el relleno ni los agregados si la lectura previa falla

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no — sin entrada externa; solo ficheros propios del directorio de logs
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | `json_state.read_before_merge`, reintentos |
| REQ-002 | yes | yes | `UnreadableStateError`, fichero intacto byte a byte |
| REQ-003 | yes | yes | `_previous_aggregates` antes de escribir nada |
| REQ-004 | yes | yes | `cli.recompute_cost.cannot_read` |
| REQ-005 | yes | yes | `set_aside`, `.damaged-*` |
| REQ-006 | yes | yes | `FileLock` `recompute-cost.lock`, `BusyError` |
| REQ-007 | yes | yes | suite completa, tests existentes sin tocar |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | `path.exists()` decide sembrar del viejo; desde 3.13 da `False` si `stat` falla | yes | no | suspected | arreglado: se decide leyendo; test `test_a_failing_stat_does_not_seed_from_the_old_aggregates` (mutante `exists()` → `KeyError: '202608'`) |
| F2 | verification.md vacío | yes | yes | confirmed | rellenado |
| F3 | «no se ha reescrito nada» falso si ya se escribieron meses anteriores | yes | yes | confirmed | texto cambiado a «no se ha reescrito» (ese fichero) en es/en y CHANGELOG |
| F4 | el fichero viejo dañado se copia aunque nunca se reemplaza | yes | no | suspected | arreglado: sin copia para los viejos |
| F5 | `str(last)` podría llevar la ruta | yes | no | suspected | arreglado: `os.strerror(errno)` o el tipo |
| F6 | asserts flojos (`"1" in`, `raises(OSError)`, `>= 1`) | yes | yes | confirmed | endurecidos; añadidos tests de forma equivocada y de cerrojo liberado tras fallo |
| F7 | `.lock` y `.damaged-*` no casan con ningún glob | no | yes | suspected | verificado, sin acción |

## Required follow-up

- Ninguno.
