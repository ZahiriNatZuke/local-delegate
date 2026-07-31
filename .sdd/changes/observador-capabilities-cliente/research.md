# Research: observar qué declara cada cliente MCP

> **Nota sobre el título del change.** Se creó como «...que declara cada cliente MCP **en
> `initialize`**». La medición de más abajo demuestra que **en `initialize` no hay nada que leer**;
> el título quedó fijado antes de medir y se conserva por trazabilidad, pero el enunciado correcto
> es «en la conexión», no «en `initialize`».

Todo lo de aquí está **medido** contra el SDK instalado (`mcp` 2.0.0) con una sonda que monta un
`MCPServer` real y le conecta un `ClientSession` real por streams en memoria. Nada viene de la
documentación ni de leer el código a ojo.

## Current behavior

`grep -i capabilities src/local_delegate/` → **0 ocurrencias**.

**Con control positivo**, porque un no-resultado no es evidencia si no se comprueba que la búsqueda
podía encontrar algo: el mismo grep sobre `import` en `server.py` da **30**. La búsqueda alcanza
`src/`. El cero es real: **el daemon no sabe con qué cliente habla.**

Dato de paso que salió del control: un grep de `FastMCP` da **0** también, y no porque falle la
búsqueda — el SDK 2.x usa `MCPServer` (`server.py:33`). Buscar el nombre viejo habría «confirmado»
una conclusión falsa por segunda vez.

Y lo que hoy sí se registra por llamada no identifica a nadie: `_log_event` toma un `source` que
vale **`"path"` o `"inline"`** (`server.py:1141`), o sea de dónde salió el contenido, no quién llamó.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `server.py:55` (`MCPServer(...)`) | instancia el servidor sin middleware | pasarle `middleware=[...]` | `inspect.signature(MCPServer.__init__)` incluye `middleware` |
| módulo nuevo del observador | no existe | lee `session.client_capabilities`, `client_params`, `protocol_version` por conexión | sonda, tabla de abajo |
| registro en disco | `_log_event` solo anota coste, `source` = path/inline | dato nuevo de identidad de cliente, por conexión | `server.py:362`, `server.py:1141` |
| `doctor` / `checks.py` | 11 checks, ninguno sobre clientes | candidato a check nuevo (fuera de alcance aquí) | memoria del registro de checks |

## El enganche: `ServerMiddleware`, no el interceptor descartado

El SDK trae **dos** piezas distintas y conviene no confundirlas, porque una está descartada:

| Pieza | Dónde corre | Estado en este repo |
| --- | --- | --- |
| `Extension` / `intercept_tool_call` (SEP-2133) | tras validar params, solo en `tools/call` | **descartado** (traza `sdk-fase-3-evaluacion`) |
| `ServerMiddleware` (`server/context.py:146`) | al principio de `_on_request`/`_on_notify`, **en todo mensaje inbound** | **es lo que sirve aquí** |

No hay contradicción con el descarte anterior, y conviene decirlo porque a primera vista la hay.
Aquel se descartó porque la telemetría de coste vive en los **caminos al backend** y el borde MCP no
ve los tokens reales. Aquí el dato que se busca —quién es el cliente y qué negoció— **solo existe en
el borde MCP**. Cada cosa donde está.

## Lo que la sonda midió, y por qué cambia el diseño

Servidor con un middleware observador + un `ClientSession` que se identifica como
`probe-client/9.9.9`:

```
método                        protocolo    client_capabilities   client_info
initialize                    2025-11-25   None                  None
notifications/initialized     2025-11-25   {}                    probe-client 9.9.9
tools/call                    2025-11-25   {}                    probe-client 9.9.9
tools/list                    2025-11-25   {}                    probe-client 9.9.9
```

### Hallazgo 1 — «registrar en `initialize`» NO funciona

Es la formulación con la que entró este trabajo, y **está mal**. Durante `initialize` el middleware
ve `client_capabilities: None` y `client_info: None`: corre **antes** de que el handshake se
comprometa (`server/context.py`: *«`initialize` is observed but not rewritable: the post-chain
handshake commit reads the wire params»*). Quien observe solo ahí **no registra nada**.

El dato está disponible **desde `notifications/initialized` en adelante**, en cualquier mensaje.

### Hallazgo 2 — ninguna de las dos constantes predice lo que se negocia

El brief traía que `LATEST_PROTOCOL_VERSION` es `2026-07-28` y `DEFAULT_NEGOTIATED_VERSION` es
`2025-03-26`, y que «lo que importa es lo que se negocia de verdad». Confirmado, y más fuerte de lo
esperado: lo negociado fue **`2025-11-25`**, que **no es ninguna de las dos**. La versión sale del
cliente, no de las constantes del servidor. Es exactamente por esto que el dato hay que medirlo.

### Hallazgo 3 — `elicitation` es un campo, no una inferencia

`ClientCapabilities` tiene estos campos: `experimental`, `sampling`, **`elicitation`**, `roots`,
`extensions`, `tasks`. La decisión sobre `elicitation` se reduce a leer `caps.elicitation` de cada
cliente real. El `{}` de la sonda es el cliente de prueba, que no declara nada por defecto.

### Hallazgo 4 — hay dos caminos y el moderno no tiene handshake

En la revisión **2026-07-28+** las capabilities viajan en el envelope `_meta` de **cada petición** y
el `client_info` es **opcional** (spec PR #3002): puede haber `client_capabilities` **sin**
`client_params` (`server/connection.py:199-205`, `from_envelope`). Por eso el SDK avisa de preferir
`session.client_capabilities` sobre `client_params.capabilities` (`server/session.py:69-77`), y por
eso el observador debe leer **las dos cosas por separado** y admitir que el nombre del cliente falte.

## Existing conventions

- **Nunca romper una tool por telemetría**: `_log_event` envuelve todo en `try` (`server.py:384`).
  El observador hereda ese criterio.
- **Registro en JSONL** con `ts` ISO en UTC, escritura tolerante a fallos (`server.py:385-390`).
- Lo que corre el usuario va al CLI; lo que corre el repo, a `scripts/`.

## Dependencies and integrations

- `mcp` 2.0.0 — `mcp.server.context.ServerMiddleware`, `mcp.server.session.ServerSession`,
  `mcp.server.connection.Connection`. Todo API pública del paquete.
- Sin dependencias nuevas: es una pieza de stdlib + SDK ya instalado.

## Risks and unknowns

- **El transporte.** La sonda usó streams en memoria; el daemon sirve `streamable_http`. El
  middleware vive en `ServerRunner`, común a los transportes, pero eso es lectura de código: la
  medición con Claude Code y Codex conectados de verdad es la que vale. **Confirmado o no en la
  fase de verificación, no antes.**
- **Ruido.** El middleware ve *todos* los mensajes (`tools/list` incluido, y los clientes lo llaman
  a menudo). Registrar uno por mensaje llenaría el log de líneas idénticas; hay que registrar por
  **conexión**, no por mensaje.
- **`initialize` es zona de deadlock**: el SDK avisa de que esperar una petición al cliente mientras
  se maneja `initialize` bloquea la conexión. Este observador solo lee y escribe local, así que no
  entra en ese caso, pero queda anotado para que nadie le añada después una llamada al cliente.
- **Privacidad**: `client_info` es nombre y versión de un programa, no dato personal. Aun así, el
  registro no debe arrastrar headers ni tokens.

## Sonda

`probe_capabilities.py`, en el scratchpad de la sesión. Reproducible con
`uv run python <ruta>`; imprime la tabla de arriba y los campos de `ClientCapabilities`.
