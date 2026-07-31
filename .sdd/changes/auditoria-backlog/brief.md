# Brief: Auditoría del backlog: veredicto por punto

## Problem

El 2026-07-31 se atacaron pendientes del backlog en dos tandas y **seis premisas resultaron
falsas** entre ambas: `update` ya consultaba el índice simple (y el arreglo propuesto habría
empeorado el síntoma), los hooks no estaban registrados dos veces, `update_to_latest.sh` no estaba
huérfano, el dato de clientes «ya estaba» en una máquina donde no existía, el aviso de desfase de
PyPI no apareció, y el `supplyChain` se había dado por descartado con un no-cambio.

Planificar sobre esa nota sale caro. Antes de tocar nada más hay que saber **qué es real**.

## Desired outcome

Un veredicto por punto —CONFIRMADO / FALSO / OBSOLETO / PARCIAL— **con la evidencia de ejecución
que lo respalda**, el backlog reescrito (los FALSO y OBSOLETO se borran, es nota viva) y una
propuesta de orden de ataque con tamaño estimado.

## In scope

- Los 18 puntos del backlog listados en el encargo de la sesión.
- Arreglar lo que resulte CONFIRMADO (ampliación pedida por el usuario a mitad de sesión).

## Out of scope

- El punto 4 (instalador en macOS): no hay Mac aquí, así que no es auditable por ejecución.
- El punto 16 (cómo *pinta* la pregunta de `elicitation` un cliente interactivo): necesita tty.
- Las decisiones ya tomadas del grupo D (blob de Chart.js, truncado de `local_extract`, log en
  UTC, ruleset sin bypass, Codex en la Mac, vendorizar fuentes web).

## Constraints and risks

- **Un pendiente es una hipótesis, no un hecho**: reproducir por ejecución antes de dar por bueno.
- **Un no-resultado no es evidencia** si no se comprueba que la búsqueda podía encontrar algo.
- Un solo change en modo `lite` para toda la auditoría; abrir uno por punto sería ceremonia.
- No publicar a PyPI. `main` protegida: todo por PR y squash, con `ci-gate` requerido.

## Open questions

Resueltas con el usuario durante la sesión:

- **Alcance del arreglo del 401** → config de esta máquina (`--mcp-mode http`) **más** un check
  nuevo que lo detecte. Descartado cambiar el default de `install` para todo el mundo.
- **El 9393 publicado en la tailnet** → el usuario pide **ponerle autenticación**, no quitarlo del
  serve. Es un change propio (cubre dos apps) y no cabe en esta sesión; queda propuesto.
