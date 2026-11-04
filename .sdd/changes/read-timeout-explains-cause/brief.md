# Brief: Un read_timeout dice si fue cola, carga o generación y en qué trozo (#572)

## Problem

`local_commit_msg(path=<diff de ~58 KB>)` falló a los 180 s con «qwen36-35b-a3b estaba cargado pero
no respondió en 180 s (backend ocupado o respuesta muy larga)» (issue #572, 2026-11-04 ~14:12 UTC,
daemon 0.48.0). El evento de uso de esa llamada dice: turno 0 ms, plaza 0 ms, fase `backend`
180 019 ms en UN solo envío (`steps: [map]`, el primer trozo), `backend_models` a los 3 s
`{"qwen36-35b-a3b": "starting"}` (`model_swap: true`) y `read_timeout_cause: "busy"` porque la
sonda de los 177 s lo vio `ready`. No había otras llamadas de este daemon entre 13:58 y 14:30.

Hallazgos:
- No hubo cola en el daemon: el plazo de 180 s es por envío (plazo de lectura de cada POST) y no
  cuenta la espera de turno ni de plaza. SÍ cuenta la carga del modelo en llama-swap y cualquier
  cola dentro de llama-swap/llama-server (p. ej. la Mac, que va directa al backend y este log no ve).
- El diff se troceó (58 KB con `max_chars=20000`; uno de 63 KB a las 12:14 dio 7 trozos en 100 s);
  falló el PRIMER trozo, y el evento no lo dice: `chunks`/`pieces` solo se escriben con más de una
  llamada.
- El texto «estaba cargado» engaña: al empezar se estaba cargando. El log no guarda cuándo quedó
  listo, así que no distingue carga de generación.
- Lo normal hoy para ese rol: ~15 s de carga y 15–30 s por trozo. 180 s sin respuesta en el primer
  trozo apunta a contención en el backend que el daemon no ve; subir el plazo no es la respuesta.

## Desired outcome

Que el error de un `read_timeout` diga, con lo que el servidor ya sabe, en qué trozo falló, si el
modelo se estaba cargando y cuándo quedó listo, y si hubo espera de turno antes del envío; y que el
log lo guarde. Sin cambiar plazos.

## In scope

- Texto es+en del `read_timeout` y campos del evento de uso.

## Out of scope

- Cambiar `HTTP_TIMEOUT` o descontar la carga del plazo; ver la cola de la Mac dentro de llama-swap.

## Constraints and risks

- Tests existentes intactos (comparan el texto exacto sin esa información): el texto solo cambia
  cuando hay información nueva.
- Observación best-effort: nunca puede romper la llamada.

## Open questions

- Ninguna.

## Log

- L1 2026-11-04 Original request, verbatim:

  > Tarea: issue #572 — `local_commit_msg(path=<diff ~59 KB>)` se cortó a los 180 s [...] Como
  > mínimo: que el error diga cuál fue la causa con lo que el servidor ya sabe (tiempo esperando
  > turno vs generando, nº de trozo en curso de cuántos) para saber si reintentar sirve, en es+en con
  > el catálogo i18n. Si el plazo no tiene en cuenta el troceado o la espera de turno [...]
  > corrígelo de forma acotada y explícalo. No subas plazos a ciegas.
