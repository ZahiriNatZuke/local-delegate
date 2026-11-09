# Result review: Las escrituras concurrentes a la telemetria no pierden ni corrompen lineas

## Review level

- Level: deep
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: yes
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | `append_line` en `record` |
| REQ-002 | yes | yes | hilos del mismo proceso |
| REQ-003 | yes | yes | `record_block` bajo cerrojo |
| REQ-004 | yes | yes | `_log_failure` |
| REQ-005 | yes | yes | `unless=` en el camino del mod |
| REQ-006 | yes | yes | salto de línea reparado |
| REQ-007 | yes | yes | lectores apartan no-objetos |
| REQ-008 | yes | yes | espera acotada |
| REQ-009 | yes | yes | firmas sin cambios; suite local; matriz de CI en el PR |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | `unless=None` en `record`: dedupe sin enchufar | yes | yes | confirmed | era el mutante del control positivo, puesto mientras leían; restaurado y verificado (`grep unless=_id_needle`) |
| F2 | import de `hook_entry` tras la barrera: los procesos arrancan desfasados | no | yes | suspected | arreglado: imports y carga de módulos antes de la barrera |
| F3 | barrera con `sleep(0.5)` y sin `finally` que mate procesos | no | yes | suspected | arreglado: ficheros `ready` con tope y `kill` en `finally` |
| F4 | fichero creado 0o644: otro usuario en `/tmp` compartido podría retener el cerrojo | no | no | suspected | (revisor de seguridad) arreglado: 0o600 y test POSIX |
| F5 | espera total de un hook bloqueado: hasta ~2 s (nota + línea) | yes | yes | confirmed | aceptado: sigue acotada; documentado |
| F6 | tope de tamaño del log de fallos se comprueba fuera del cerrojo | yes | no | suspected | aceptado: puede pasarse por unas líneas, sin pérdida |
| F7 | `readRecordLost` del mod sigue reescribiendo `hook-failures.jsonl` | no | yes | suspected | fuera de alcance (otro dueño hoy, API sin append); seguimiento |
| F8 | copias viejas de `hook_common.py` sin cerrojo | no | yes | suspected | límite conocido; se corrige al reinstalar/actualizar |

## Required follow-up

- Tarjeta para el mod: que `readRecordLost` deje de reescribir `hook-failures.jsonl`.
