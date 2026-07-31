# Result review: El check del daemon compara versiones por desigualdad

## Verdict

`conforms` — los seis requisitos implementados y verificados, cada uno con su test, y los tres
mutantes rompen el test que les toca.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 iguales → `ok` | sí | sí | sin cambios respecto a antes |
| REQ-002 daemon viejo → reiniciar | sí | sí | comportamiento anterior, conservado |
| REQ-003 daemon nuevo → actualizar | sí | sí | **el caso que faltaba** |
| REQ-004 comparación numérica | sí | sí | `0.9.0` vs `0.18.0` |
| REQ-005 incomparables sin `fix_hint` | sí | sí | no se sugiere un arreglo que podría ser el falso |
| REQ-006 exit code sin cambios | sí | sí | los tres caminos siguen en `warn` |

## Findings

1. **(sin acción) El defecto simétrico no está en `cli.published`.** Comprobado leyéndola: ya usa
   `_compare_versions` y distingue los tres órdenes. El fallo era solo de `_probe_daemon`.
2. **(observación) El mensaje llevaba mal desde que se introdujo el check.** No salió antes porque
   el caso frecuente es el otro sentido —daemon atrasado tras actualizar—; el inverso solo aparece
   con una instalación **editable** por delante del CLI publicado, o sea la máquina de desarrollo
   justo el día que se publica.
3. **(anotado) El `detail` es texto de interfaz** y nadie lo parsea, así que cambiar la redacción no
   rompe nada. Regla ya escrita en el repo.

## Required follow-up

Ninguno para este change.

Aparte y sin relación con él: `service.backend` sale `[ -- ]` con 401 cuando `doctor` corre desde un
shell sin `LOCAL_DELEGATE_API_KEY`, aunque el daemon sí esté autenticado. Es otro asunto, se trata
por separado.
