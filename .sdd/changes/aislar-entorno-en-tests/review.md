# Result review: La suite no puede heredar el entorno de quien la corre

## Verdict

`conforms` — los seis requisitos implementados y verificados, cada uno contra ejecución real y no
contra inspección.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | 34 variables registradas solas; la enumeración manual previa veía 14 |
| REQ-002 | sí | sí | `_leer` es la única aparición de `os.environ` en `config.py`; guardián AST |
| REQ-003 | sí | sí | Sin duplicar defaults: el aislamiento recarga el módulo |
| REQ-004 | sí | sí | `25 passed` con `LOCAL_DELEGATE_WEB_TOKEN` puesta (antes 4 fallos) |
| REQ-005 | sí | sí | Dos mutantes + control positivo del inventario |
| REQ-006 | sí | sí | `725 passed, 2 skipped` en los dos entornos; 13/13 checks en la PR #135 |

## Findings

1. **El inventario automático se pagó solo en la primera medición.** El mutante del aislamiento
   destapó que las variables contaminando esta máquina eran cuatro y no dos: `LOCAL_DELEGATE_AUTOSTART`
   y `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS` también estaban definidas. Una lista escrita a mano
   habría cubierto las dos que yo había visto y habría dejado las otras dos vivas, con el mismo
   aspecto de «arreglado».
2. **Enumerar a ojo subestimó el alcance a la mitad** (14 de 34). El `grep` inicial solo capturaba
   `_env(`, no `_env_int`/`_env_flag`/`_env_float`. Cuando la pregunta es «cuántos sitios hay»,
   preguntárselo al programa es mejor que contarlos leyendo.
3. **`gh pr checks` completo, no `gh run list`** — aplicado desde el principio en esta PR, tal como
   lo dejó escrito la revisión de la #133. Los 13 checks incluyen el `CodeQL` que no aparece en el
   listado de workflows.

## Required follow-up

Ninguno. El único límite conocido —lo que otros módulos capturan en tiempo de import— está
declarado en el brief, medido, y hoy no afecta a ningún test.
