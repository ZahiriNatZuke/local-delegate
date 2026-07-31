# Brief: observar qué declara cada cliente MCP

## Problem

El daemon no sabe con qué cliente habla. `grep -i capabilities src/local_delegate/` da **cero**
ocurrencias, comprobado con control positivo (el mismo grep sobre `import` en `server.py` da 30, o
sea la búsqueda alcanza el paquete). Lo único que se registra por llamada es el coste, y su campo
`source` dice de dónde salió el contenido (`"path"`/`"inline"`), no quién llamó.

Eso deja sin respuesta una pregunta con consecuencias: **¿puede el cliente al otro lado responder a
una pregunta hecha desde una tool?** De ella depende si `elicitation` tiene recorrido en este repo,
y la evaluación de la fase 3 del SDK se quedó bloqueada ahí (`.sdd/changes/sdk-fase-3-evaluacion`).

## Desired outcome

El daemon registra, por cliente, las capabilities declaradas y **la revisión de protocolo negociada
de verdad** —no la que sugieren las constantes del SDK—, y lo deja en un JSONL persistente y en el
estado en vivo de `/api/status`. Con eso en la mano se decide `elicitation` con un dato, no con una
suposición.

## In scope

- Observar la conexión y registrar identidad, protocolo y capabilities.
- Línea JSONL por identidad y estado en vivo en `/api/status`.
- Medición real conectando **Claude Code y Codex**.

## Out of scope

- El check de `doctor` — change siguiente, por decisión del usuario: primero el dato, porque qué
  cuenta como fallo solo se puede decidir viéndolo.
- Implementar `elicitation`. Este change la *decide*.
- `auth` / `bearer_auth`, condicionados a exponer el daemon.

## Constraints and risks

- **Nunca romper una tool por observar**: el criterio de `_log_event` («jamás propaga») aplica igual.
- El middleware ve *todos* los mensajes: registrar por mensaje llenaría el log de ruido.
- El SDK ofrece dos piezas parecidas y una está descartada: esto es `ServerMiddleware`, **no** el
  `Extension`/`intercept_tool_call` de SEP-2133.
- Sin dependencias nuevas ni variables de entorno nuevas.

## Open questions

- ~~¿Dónde se registra el dato?~~ Resuelto por el usuario: JSONL **y** estado en vivo.
- ~~¿Entra el check de `doctor`?~~ Resuelto: va en el change siguiente.
- ~~¿Algún cliente soporta `elicitation`?~~ Resuelto por la medición: **los dos** —Claude Code y
  Codex— la declaran.
