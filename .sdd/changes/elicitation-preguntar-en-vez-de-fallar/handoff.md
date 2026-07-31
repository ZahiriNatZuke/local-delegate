# Handoff: preguntar en vez de fallar seco

## Current state

- SDD status: `result-review`, listo para cerrar.
- Último gate aprobado: `conformance`.
- Revisión: rama `feat/elicitation-preguntar`; 539 passed, 1 skipped.

## What changed

`preguntas.py`: un `preguntar(mensaje, Modelo)` que devuelve la respuesta del usuario o `None`, y el
middleware que deja el contexto a su alcance. Tres puntos de uso en `server.py`: backend caído,
modelo fuera del catálogo y `output_format` en blanco. Dos variables nuevas: `LOCAL_DELEGATE_ASK`
(activado) y `LOCAL_DELEGATE_ASK_TIMEOUT` (30 s).

## Decisions

Lo que una sesión futura no puede deducir del código:

- **El plazo va DENTRO de la corrutina, y no es un detalle de estilo.** `anyio.move_on_after`
  alrededor de `from_thread.run` lanza `NoEventLoopError` — desde el hilo de una tool no hay event
  loop que consultar. Y como el `except` se lo tragaría, el síntoma sería «nunca se pregunta», en
  silencio. Está medido en `probe_timeout2.py`.
- **El contexto viaja por `ContextVar`, no por firmas.** Medido que un `ContextVar` puesto por el
  middleware llega a una tool síncrona en el threadpool. Por eso `_post_chat` pregunta sin que
  cambien las 15 firmas de la cadena, y por eso el schema de las tools queda intacto.
- **Desde un middleware hay que usar `ctx.session.elicit_form`, no `ctx.elicit`.**
  `ServerRequestContext` no tiene `.elicit`: eso es del `Context` de alto nivel, que solo llega a
  las tools que lo declaran. La primera implementación falló por esto y el fallo era **silencioso**.
- **Hay que comprobar dos cosas, no una**: la capability y el canal de vuelta. Son independientes.
- **`chunk` y `style` se dejaron fuera a propósito**: listas fijas y documentadas. Solo `model`
  justifica preguntar, porque su lista sale de la configuración de cada instalación.

## Next action

Usarlo de verdad y ver **cómo presenta cada cliente la pregunta** — es lo único que no se puede
saber sin uso real. Después, el **check de `doctor`** sobre los clientes observados, que quedó
encolado del change anterior.

## Memory

- Nota canónica: `projects/local-delegate/overview.md` (vault).
- Índices actualizados: `docs/wiki/Architecture.md`, `README.md`, `CHANGELOG.md`.
