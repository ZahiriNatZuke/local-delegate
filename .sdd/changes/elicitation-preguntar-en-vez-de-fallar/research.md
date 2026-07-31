# Research: que una tool pregunte en vez de adivinar o fallar seco

Todo medido con una sonda que monta un `MCPServer` real y le conecta un `ClientSession` real
(`probe_elicit.py`, scratchpad de la sesión). Nada leído de la documentación.

## Current behavior

Dos sitios donde hoy el servidor decide solo, y decide mal:

1. **Backend caído.** Cualquier tool contra un backend que no responde devuelve un error seco. El
   auto-arranque existe (`autostart.py`) pero está **desactivado por defecto**
   (`LOCAL_DELEGATE_AUTOSTART=0`, decisión de arquitectura: «backend opt-in»). O sea: el servidor
   sabe arrancarlo y sabe que está caído, y aun así no puede hacer nada porque nadie le dijo que
   sí.
2. **`local_delegate` sin formato.** Es la tool de escape genérica; si la tarea no dice el formato
   de salida, el guardrail lo adivina.

**La premisa del change ya está comprobada:** el change `observador-capabilities-cliente` midió que
**Claude Code y Codex declaran los dos `elicitation`**:

```
claude-code        2.1.220              protocolo 2025-11-25   caps: elicitation, roots
codex-mcp-client   0.146.0-alpha.3.1    protocolo 2025-06-18   caps: elicitation
```

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| las 11 tools | no reciben contexto de petición | las afectadas declaran `ctx: Context` | medido: no altera su schema público |
| `_chat` y compañía | fallan seco con el backend caído | punto donde preguntar | `server.py:678` y ss. |
| `autostart.py` | arranque opt-in, hoy inalcanzable en caliente | pasa a ser alcanzable con permiso del usuario | `LOCAL_DELEGATE_AUTOSTART` |
| `local_delegate` | adivina el formato | lo pregunta cuando no está claro | `server.py:1294` |

## Lo medido, escenario por escenario

| Escenario | Resultado |
| --- | --- |
| cliente acepta | `action=accept`, `data=arrancar=True` |
| cliente declina | `action=decline`, `data=None` |
| cliente cancela | `action=cancel`, `data=None` |
| cliente sin soporte de `elicitation` | `ctx.client_capabilities.elicitation` es `None` → se detecta y se falla rápido |
| **cliente que no responde nunca** | **la tool se queda colgada; el SDK no impone timeout** |

### Hallazgo 1 — sin timeout propio, esto es peor que el fallo que arregla

El quinto escenario es el que decide el diseño. Un cliente que declara la capability y luego no
contesta **cuelga la tool indefinidamente**: la sonda tuvo que cortar desde fuera a los 8 segundos.
No hay plazo en el SDK.

O sea, la objeción que ya figuraba en la evaluación de la fase 3 —«una tool esperando una respuesta
que no llega es peor que fallar rápido»— **no era teórica**. Cualquier implementación necesita
**timeout propio**, y agotarlo debe significar «sigue como si no hubiera preguntado», no «falla».

### Hallazgo 2 — declarar la capability no garantiza que se pueda preguntar

`ServerSession.elicit_form` documenta que lanza `NoBackChannelError` cuando *«la conexión no tiene
canal de vuelta para peticiones iniciadas por el servidor»*. Y en la revisión **2026-07-28+** el
protocolo **prohíbe** las peticiones iniciadas por el servidor: `has_standalone_channel` puede ser
cierto y `send_raw_request` negarse igual (`connection.py:320-330`).

Hay que comprobar **dos** cosas, no una: la capability (`ctx.client_capabilities.elicitation`) y el
canal (`ctx.session.can_send_request`). En la sonda las dos dieron `True`, pero son independientes.

### Hallazgo 3 — añadir `ctx` no cambia el contrato de la tool

Es la duda que podía tumbar el enfoque, y está resuelta por medición. Comparando el schema de dos
tools idénticas, una con `ctx: Context` y otra sin él:

```
sin ctx: ['path', 'texto']      con ctx: ['path', 'texto']
```

Lo único que difiere es el `title` del schema, que sale del **nombre de la función**
(`sin_ctxArguments` vs `con_ctxArguments`), no de la presencia de `ctx`. El SDK excluye el
parámetro (`context_kwarg`, `skip_names` en `tools/base.py`). **Los clientes no ven `ctx`.**

### Hallazgo 4 — las tools son SÍNCRONAS, y aun así pueden preguntar

Este era el obstáculo capaz de tumbar el enfoque, y no se vio hasta mirar el código de verdad: las
11 tools son `def`, no `async def`, y `_post_chat` —donde se detecta el backend caído
(`server.py:524`)— también. `ctx.elicit()` es una corrutina. A primera vista, preguntar exigiría
convertir toda la cadena a async.

**No hace falta.** Medido: desde el hilo en el que el SDK ejecuta una tool síncrona,
`anyio.from_thread.run(ctx.elicit, mensaje, Modelo)` **funciona**:

```
1. elicit desde tool sincrona -> OK action=accept data=arrancar=True
```

### Hallazgo 5 — el contexto llega a la capa profunda sin tocar ni una firma

Segundo obstáculo: `_post_chat` está tres capas por debajo de la tool (tool → `_chat` →
`_post_chat`). Pasarle el `ctx` por parámetro obligaría a tocar 11 tools + 3 funciones de chat + 1.

**Tampoco hace falta.** Un `ContextVar` puesto por un `ServerMiddleware` **sí se ve** desde una tool
síncrona que no declara `ctx`:

```
2. ContextVar en capa profunda -> contextvar_visible=True tipo=ServerRequestContext
```

anyio copia el contexto al hilo del threadpool. Consecuencia directa: **REQ-008 se cumple por
construcción**, porque no hay que cambiar la firma de ninguna tool.

### Hallazgo 6 — la API buena es `Context.elicit` con un modelo Pydantic

- `ServerSession.elicit()` está **deprecada** a favor de `elicit_form()`.
- `Context.elicit(message, schema)` quiere **una clase Pydantic**, no un dict de JSON Schema —
  pasarle un dict revienta con `AttributeError: 'dict' object has no attribute
  'model_json_schema'`. Solo admite tipos primitivos, por especificación.
- Devuelve `ElicitationResult` con `.action` (`accept`/`decline`/`cancel`) y `.data`, que solo se
  puebla si la acción fue `accept`.

## Existing conventions

- **Nada de telemetría ni de infraestructura puede romper una tool** (`_log_event`, `clients.py`).
  Una pregunta que falla debe degradar al comportamiento de hoy, no empeorar nada.
- **Backend opt-in** es una decisión de arquitectura escrita: preguntar «¿lo arranco?» **no** la
  contradice —sigue sin arrancar nada sin permiso—, pero conviene decirlo explícito para que no
  parezca que se revierte.
- El daemon sirve a varios clientes; lo que se pregunte debe ser por petición, no global.

## Dependencies and integrations

- Sin dependencias nuevas: `Context` y `elicit` son del SDK ya instalado; Pydantic ya está.
- `autostart.py` ya existe y ya sabe arrancar el backend.

## Risks and unknowns

- **Confirmado por medición**: sin timeout se cuelga; el schema no cambia; los dos clientes
  soportan la capability; hay cuatro resultados posibles y solo uno trae datos.
- **Sin medir todavía**: cómo presenta cada cliente la pregunta al usuario (Claude Code vs Codex),
  y si un cliente en modo no interactivo responde `decline` automáticamente o se queda callado —
  esto último es justo lo que hace obligatorio el timeout.
- **Riesgo de producto, no técnico**: preguntar el formato en `local_delegate` puede volverse
  pesado si salta a menudo. Hay que acotar cuándo se considera «ambigua» una tarea.
