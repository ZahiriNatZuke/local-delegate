# Brief: preguntar en vez de fallar seco

## Problem

Tres sitios del servidor fallan con un error de texto **aunque ya sepan la solución**: el backend
está caído y hay un arranque disponible; el modelo pedido no existe y la lista de válidos va en el
propio mensaje de error; `output_format` viene vacío y nadie lo comprueba.

## Desired outcome

En esos tres casos la tool **pregunta** al usuario a través del cliente MCP y actúa según la
respuesta, sin que preguntar pueda empeorar nada.

## In scope

- `elicitation` del protocolo MCP, con plazo, interruptor y degradación total.
- Los tres casos de arriba.

## Out of scope

- Preguntar en el resto de las tools.
- Elicitation en modo URL o formularios de varios pasos.
- Recordar la respuesta entre llamadas.

## Constraints and risks

- Las 11 tools son **síncronas** y `elicit` es una corrutina.
- El SDK **no impone timeout**: un cliente mudo cuelga la tool para siempre.
- Declarar la capability no garantiza canal de vuelta.
- Ninguna tool puede cambiar su schema público.

## Open questions

- ~~¿Algún cliente soporta `elicitation`?~~ Sí: Claude Code y Codex, medido en el change
  `observador-capabilities-cliente`.
- ~~¿Dónde se usa?~~ Decidido por el usuario: backend caído, parámetro inválido con lista finita y
  formato vacío.
- ~~¿«Delegación sin formato»?~~ **No existe**: `output_format` es obligatorio. El caso real es que
  venga vacío.
