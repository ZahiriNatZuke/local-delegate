# Brief: Ctrl+C sobre el MCP stdio sale limpio en vez de con traceback

## Problem

Reportado por el usuario: lanzar `local-delegate` en una terminal y cortarlo con `Ctrl+C` llena la
consola de errores.

**Reproducido inyectando la interrupción donde la mete un `Ctrl+C` real** —en la llamada
bloqueante que espera— y comparando los dos caminos:

| Camino | `KeyboardInterrupt` | Salida |
| --- | --- | --- |
| `local-delegate` (stdio, `server.main`) | **sale sin capturar** | **traceback** |
| `local-delegate serve` (`daemon.serve`) | capturado | rc 0, limpia |

`mcp.run()` en `server.py` estaba desnudo. Y en una terminal real el ruido es **peor** que en el
arnés: el SDK corre sobre anyio, así que lo que se imprime es un `ExceptionGroup` anidado con el
rastro de las tareas del grupo, no una línea.

**Lo que hace este defecto interesante:** `daemon.serve` ya capturaba esa interrupción, con un
comentario explicando el porqué. No fue no saber qué hacer — fue arreglar un camino y no el otro.

## Desired outcome

`Ctrl+C` para el proceso en silencio y con código 0, por los dos caminos.

## In scope

- Capturar la interrupción en `server.main()`.
- Un test que compruebe **los dos caminos juntos**.

## Out of scope

- **El código de salida `3` que devuelve `serve` ante `CTRL_BREAK_EVENT`** en Windows. Es otro
  síntoma, medido de pasada y no diagnosticado: `CTRL_BREAK` no es `CTRL_C` y el proceso muere por
  otra vía. Se anota en el backlog en vez de arreglarlo a ciegas.
- El ruido `HTTP Request: … 401` de `httpx2` a nivel INFO, que aparece en la misma salida y ya
  está clasificado aparte.

## Constraints and risks

- **Riesgo de silenciar de más:** capturar `KeyboardInterrupt` en el punto de entrada podría
  esconder una interrupción durante el arranque. Se acota a `mcp.run()`, que es donde el proceso
  espera, y no envuelve la inicialización.
- **Lo que se reprodujo NO es una consola real.** En Windows solo `CTRL_C_EVENT` genera
  `KeyboardInterrupt`, y no se puede mandar a un hijo concreto sin afectar al propio grupo. La
  interrupción se inyectó en el mismo punto donde la entrega el sistema, que es lo que importa
  para este arreglo, pero conviene decirlo.

## Open questions

- Ninguna que bloquee. El `rc 3` queda anotado como pendiente aparte.
