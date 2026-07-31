# Result review: `doctor` pregunta al daemon por el backend

## Verdict

`conforms-with-notes` — los siete requisitos implementados y verificados, incluida la ejecución real
en la máquina que reportó el problema. Las notas son un hallazgo colateral ya corregido y un riesgo
aceptado.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 `query_backend` | sí | sí | misma forma que `query_daemon` |
| REQ-002 sin `available` → `None` | sí | sí | no se inventa una caída |
| REQ-003 se pregunta primero al daemon | sí | sí | también por ejecución real |
| REQ-004 `available: true` → `ok` sin 401 | sí | sí | el caso reportado, resuelto |
| REQ-005 `available: false` → aviso | sí | sí | exit 1, no `[ -- ]` |
| REQ-006 sin daemon, todo como antes | sí | sí | dos tests, uno preexistente |
| REQ-007 la clave no se toca | sí | sí | 0 coincidencias de `API_KEY`/`auth_headers` en el diff |

## Findings

1. **(corregido, medio) Un test existente estaba saliendo a la red.**
   `test_run_doctor_keeps_the_previous_output` falló al introducir el colaborador nuevo porque
   `_stub_environment` no lo doblaba: consultaba el daemon **real**. Verde en CI (sin daemon) y otra
   cosa en la máquina de desarrollo. Es el **mismo patrón** que apareció hoy con `clients.jsonl` —
   ya van dos en una sesión, y sale siempre que un colaborador por defecto habla con el exterior.
2. **(corregido, bajo) El arnés de verificación mintió antes que el código.**
   `subprocess.run(text=True)` decodifica en cp1252 y la salida de pytest es UTF-8, así que
   `proc.stdout` llegaba `None` y el veredicto habría sido «nadie se entera». Segunda vez hoy que el
   script de mutación falla en falso; ambas veces la señal era un resultado *demasiado* limpio.
3. **(aceptado) Dos llamadas HTTP en el peor caso.** Solo sin daemon, y el diagnóstico no es un
   camino caliente.
4. **(sin acción) El exit code puede bajar de 1 a 0** en máquinas cuyo único aviso era este 401. Es
   el objetivo del change, no un efecto secundario: esas máquinas estaban sanas.

## Required follow-up

Ninguno. Para el backlog, la observación del hallazgo 1: **cada colaborador por defecto del
`Context` que hable con el exterior necesita estar doblado en los dos arneses** (`make_ctx` de
`test_checks.py` y `_stub_environment` de `test_doctor.py`); hoy se olvidó en dos de dos casos
nuevos.
