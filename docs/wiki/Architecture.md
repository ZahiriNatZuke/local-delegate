# Architecture

## Visión general

```text
Codex / Claude Code / otros
        │  Streamable HTTP /mcp
        ▼
  local-delegate daemon ──HTTP POST──▶ endpoint OpenAI-compatible
  (MCP + dashboard)       /chat/completions  (llama-swap · Ollama · LM Studio · vLLM)
        │
        ├─ escribe usage-YYYYMM.jsonl
        └─ sirve dashboard web en /
```

`local-delegate` es un servidor MCP (Python + `MCPServer`, del SDK `mcp` 2.x; hasta la 0.12.x era
`FastMCP`, que ese major eliminó). El modo recomendado para varias sesiones
es el daemon singleton Streamable HTTP; el transporte `stdio` sigue disponible sin argumentos para
compatibilidad. Expone 11 tools texto/imagen→texto
(10 texto→texto + `local_describe_image` imagen→texto). Cada tool arma un prompt con *guardrails*,
hace `POST /chat/completions` al endpoint configurado y devuelve **solo texto**.

## Decisiones de diseño

- **Cliente genérico.** El paquete solo asume "un endpoint OpenAI-compatible en una URL"
  (`LOCAL_DELEGATE_BASE_URL`). No sabe ni le importa qué motor lo sirve, en qué hardware, ni con
  qué modelos. Todo lo específico (llama-swap, GPU, GGUF) es configuración + recipes.
- **Texto→texto, sin tool-calling en el modelo local.** Los modelos locales NO usan function
  calling: el server construye el prompt completo y espera texto plano. Esto los hace robustos y
  compatibles con cualquier backend, incluso modelos pequeños.
- **El guardrail.** Cada llamada inyecta un system prompt: *"Responde directo desde el input. NO
  uses herramientas, NO busques en internet. Output EXACTO: <formato>. Nada fuera del formato."*
  Mantiene la salida acotada al formato pedido.
- **`path` server-side = el ahorro real.** `summarize`/`extract`/`lint_summary`/… aceptan `path`:
  el MCP lee el archivo **en tu máquina** y solo devuelve el resultado corto. El contenido grande
  **nunca entra al contexto de Claude** → ahí está la cuota conservada.
- **Roles de modelo.** Las tools enrutan a 3 roles de texto (mecánico, largo, código; el rápido se
  retiró en la 0.30.0) más
  un rol de visión (`local_describe_image`), cada uno un id de modelo configurable. Las que
  dependen del tamaño del input eligen mecánico vs. largo por un umbral
  (`LOCAL_DELEGATE_LONG_INPUT_CHARS`).
- **Backend opt-in.** El auto-arranque de un backend (llama-swap) está **desactivado por defecto**
  (`LOCAL_DELEGATE_AUTOSTART=0`); el paquete asume que tu endpoint ya corre.
- **Un fichero JSONL es toda la telemetría, y OpenTelemetry queda descartado.** Decidido en la
  v0.14.0 tras evaluarlo con el SDK `mcp` 2.x ya migrado, y anotado aquí para no re-evaluarlo desde
  cero. Tres razones, las tres comprobadas ejecutando:
  1. El `OpenTelemetryMiddleware` que el SDK monta por defecto instrumenta el **borde MCP** —*«un
     cliente llamó a `local_summarize`»*—, **no las llamadas al backend**, que es justo lo que hacía
     falta contar. Habría que escribir spans propios igualmente.
  2. Lo que entra como dependencia es `opentelemetry-api`, **la mitad emisora**. Sin
     `opentelemetry-sdk` —que no se instala— los spans son `NonRecordingSpan`: se generan y se
     descartan. El «coste cero» vale para instrumentar, no para recoger.
  3. Recoger de verdad exigiría SDK, exportador y un colector corriendo. El dashboard tiene que
     funcionar **recién instalado y sin configurar servicios**; el `usage-YYYYMM.jsonl` es lo que lo
     permite.

## Qué se usa del SDK `mcp` 2.x, y qué no

Evaluación cerrada el **2026-07-31** sobre el SDK 2.0.0 instalado, comprobando por ejecución y no
leyendo la documentación. Se anota aquí, con el mismo criterio que OpenTelemetry, para no
re-evaluarlo desde cero. Traza en `.sdd/changes/sdk-fase-3-evaluacion/`.

### Se usa

- **`ServerMiddleware`** — dos usos, ambos en el borde MCP porque es donde vive lo que necesitan:
  observar qué cliente hay al otro lado y qué protocolo negoció (`clients.py`), y dejar el contexto
  de la petición al alcance de las capas de abajo (`preguntas.py`).
- **`elicitation`** — preguntar al usuario en vez de fallar seco (`preguntas.py`). **Adoptada tras
  medir que hacía falta**: estuvo bloqueada hasta saber si algún cliente la soportaba, y resultó que
  Claude Code y Codex la declaran los dos. Tres cosas que conviene no redescubrir: el SDK **no
  impone timeout** y un cliente mudo cuelga la tool para siempre; el plazo tiene que ir **dentro de
  la corrutina**, porque `move_on_after` desde el hilo de una tool lanza `NoEventLoopError`; y
  declarar la capability **no** garantiza canal de vuelta, así que hay que comprobar las dos cosas.

### Descartado: `extension` / `intercept_tool_call` (SEP-2133)

El mal llamado «middleware de tools». La premisa que lo justificaba era *«centralizar la telemetría,
que hoy cada tool anota a mano»*, y **es falsa**: `_log_event` se invoca en **tres** sitios de
`server.py` —`_chat`, `_chat_chunked` y `_chat_map_reduce`—, no en once. La telemetría ya está
centralizada, y está **donde ve el coste real**: los caminos de llamada al backend.

Un interceptor vería la llamada a la tool pero **no** los tokens del backend, ni el número de
llamadas, ni los chunks — que es lo que mide el panel. Es la misma objeción que descartó
OpenTelemetry: sustituir tres puntos que ven el coste real por uno que solo ve el borde sería una
regresión.

*Lo que sí serviría, y es otro problema:* un contrato transversal del borde —rechazar llamadas con
el backend caído sin que cada tool lo compruebe, o un límite de uso—. Hoy nadie lo ha pedido.

### Descartado: `caching` (SEP-2549)

Son *hints* para que el cliente cachee respuestas de métodos como `tools/list`. **Nuestro coste no
está ahí**: está en la inferencia del backend, que no se cachea por esta vía. Ahorraría unos
kilobytes de listado y ni un token de modelo.

### Descartado: `subscriptions` (SEP-2575)

`subscriptions/listen` notifica eventos sobre **recursos y prompts**: `ResourceUpdated`,
`ResourcesListChanged`, `PromptsListChanged`. Este servidor no expone **ni uno** — `@mcp.resource` y
`@mcp.prompt` dan cero coincidencias en `src/`; solo hay 11 tools. No es que aporte poco: **no
habría nada que emitir**.

Para que sirviera habría que exponer antes recursos MCP (el estado del backend, los modelos
cargados), que es un cambio de producto con su propia justificación. `subscriptions` sería la
consecuencia, nunca el motivo.

### `auth` va partido en dos, y la distinción importa

- **El servidor de autorización OAuth2** (`provider`, `handlers`, `routes`) — **descartado.** Emite
  authorization codes y access tokens: es para un MCP multiusuario expuesto a internet. Aquí hay un
  usuario y una máquina.
- **`middleware/bearer_auth`** — **condicionado, no descartado.** Es la pieza ligera: validar un
  token por petición. El daemon **sí puede salir de loopback** (`WEB_HOST` es `127.0.0.1` por
  defecto pero lo fija `LOCAL_DELEGATE_WEB_HOST`, `config.py:203`; ya hubo un caso real con
  `0.0.0.0`), y «el dashboard no tiene autenticación» sigue abierto en el backlog. Si alguna vez se
  decide exponer el daemon, se evalúa en su propio change.

**Apunte para ese día, que hoy no está escrito en ningún otro sitio:** exponer el daemon obliga a
cubrir **dos aplicaciones distintas**, no una — el endpoint MCP y el dashboard de métricas
(`metrics.app`). Un middleware del SDK no cubre las dos por sí solo.

*Por qué se deja escrito así:* la primera redacción de esta evaluación metía las dos piezas en el
mismo saco y descartaba `auth` entero de un plumazo, comiéndose la parte que sí puede servir. Un
módulo puede traer dos cosas de tamaño muy distinto.

### Nota sobre la revisión del protocolo

`LATEST_PROTOCOL_VERSION` es `2026-07-28` y `DEFAULT_NEGOTIATED_VERSION` del SDK sigue en
`2025-03-26`, pero **ninguna de las dos predice lo que se negocia de verdad**: medido en vivo,
Claude Code negocia `2025-11-25` y Codex `2025-06-18`. Implementar hoy contra la revisión más nueva
sería escribir código que ningún cliente negocia.

## Turno, afinidad y lentitud

Tres piezas del daemon que solo se encienden con un llama-swap **local** cuya config se puede leer
(`LLAMASWAP_CONFIG` y el extra `[llamaswap]`). Sin eso, o con un backend remoto, el daemon se
comporta como antes de tenerlas.

```text
operación ──▶ turno (¿choca con lo que está en uso?) ──▶ plaza (MAX_CONCURRENT_REQUESTS) ──▶ backend
                  │ espera: local_wait="turn"              │ espera: local_wait="slot"
                  └─ afinidad: ¿hay un alternativo aprobado ya cargado? (solo en la 1.ª llamada)
```

- **Turno.** Se pide **antes** que la plaza, y nunca con una plaza en la mano: así turno y plaza no
  se bloquean mutuamente. El conjunto aceptable de una operación es el modelo del rol más los
  alternativos con celda aprobada (o `{model}` con modelo explícito, o el destino de un salto). La
  primera de la cola se concede si alguno de sus modelos es compatible con lo que está en uso; una
  que llega después solo se adelanta si no choca ni con lo que está en uso ni con lo que piden las de
  delante (E-1), así que nadie espera para siempre. Si la cola no avanza en
  `LOCAL_DELEGATE_TURN_MAX_S` sin llamadas en vuelo, la cabeza se concede forzada. Un salto de
  respaldo suelta la plaza y vuelve a pedir turno. El estado se ve en `local_status`, en
  `/api/inflight` (`local_wait`, `turn_in_use`, `turn_position`) y en el panel.
- **Afinidad.** Con la plaza en la mano, en la primera llamada de la operación y solo si la tool
  tiene celdas aprobadas y ni el rol ni el alternativo están ya en uso por el daemon, se hacen hasta
  tres consultas de 1 s a llama-swap (`/running`, la foto de peticiones en vuelo de `/api/events` y
  `/api/metrics/activity`). La elección es pura (`matrix.choose`): primero el rol si ya está cargado;
  después un alternativo aprobado cargado con margen; si no, el rol. Cualquier fallo de esas
  consultas deja la operación sin afinidad. El detalle para el usuario, con la tabla de celdas, está
  en [Tools](Tools.md#afinidad-usar-el-modelo-que-ya-está-cargado).
- **Espera frente a lentitud.** `_post_chat` conserva los `timings` de llama-server. Cada evento
  separa la inferencia (`inference_ms`) de todo lo demás (`wait_ms`: turno, plaza, cola de
  llama-swap y carga) y compara el `tok_s` del modelo que respondió con su mediana de referencia
  (`pace_rel`, `slow`). Observar nunca rompe una tool: si falla el cálculo, el evento se escribe sin
  esos campos. Ver [Savings & metrics](Savings-and-metrics.md#qué-se-mide).

## Módulos

| Módulo | Rol |
|---|---|
| `server.py` | Las 11 tools, `_chat`/`_post_chat`, guardrail, logging |
| `clients.py` | Observa qué cliente MCP hay al otro lado: capabilities y protocolo negociado, a `clients.jsonl` y a `/api/status` |
| `preguntas.py` | Preguntar al usuario vía `elicitation` cuando el servidor ya sabe el arreglo; devuelve `None` en todo camino malo, así que nunca empeora nada |
| `config.py` | Toda la config por env + `platformdirs` (log de usuario) |
| `autostart.py` | Arranque opt-in de llama-swap (específico de ese backend) |
| `daemon.py` | ASGI singleton: MCP `/mcp`, dashboard `/`, lock y estado por usuario |
| `web/metrics.py` | Dashboard de ahorro (FastAPI, montado por el daemon o embebido en `stdio`) |
| `fallos.py` | Clasificación pura de los fallos del backend (sin red ni estado); lo que no encaja va a `sin_clasificar` |
| `cadenas.py` | Cadenas de respaldo por rol, resueltas con la configuración vigente, con el paso `loaded` (los alternativos aprobados que ya están cargados) y el texto «sin residente» / «residente: X» |
| `topology.py` | Lee los grupos de `LLAMASWAP_CONFIG` en caliente y dice qué modelos chocan, con la regla de llama-swap; si no puede, el motivo de «sin topología» |
| `turn.py` | El turno del daemon: núcleo puro (cola, concesión, E-1, concesión forzada) y su envoltura asíncrona |
| `matrix.py` | Las celdas aprobadas de la afinidad (`CELLS`) y la elección pura `choose(grantable, role, observed, own)` |
| `footprint.py` | La huella de un modelo en la config (GGUF, flags, prompt) con la que se comparan las celdas |
| `pace.py` | Ritmo de referencia por modelo (mediana de `tok_s`) y la regla de `pace_rel`/`slow` |
| `llamaswap_api.py` | Lo que se lee de llama-swap (`/running`, `/api/events`, `/api/metrics/activity`), el estado de `/api/llamaswap/status` y la vigía de recarga |
| `llamaswap_config.py` | Estimador de VRAM/RAM de los grupos (`check-llamaswap`, `init-llamaswap`, `--pin`) |
| `residency.py` | `llamaswap residency`: lectura de la residencia y edición quirúrgica, con copia y reemplazo atómico, del `config.yaml` |
| `enfriamiento.py` | Enfriamiento por modelo compartido entre procesos (`enfriamiento.json`) y registro de episodios (`enfriamiento-eventos.jsonl`) |
| `resources/vendor/` | Chart.js servido **desde el paquete**, con `vendor.json` (versión, origen y SHA-256) como fuente de verdad. Lo vigila `scripts/check_vendor.py` en el CI |

**Una sola librería HTTP: `httpx2`.** Es la que usa el SDK `mcp` 2.x, y el cliente propio del
backend migró a ella en vez de dejar las dos instaladas para siempre. Por eso `respx` salió de la
suite —no la soporta— y su lugar lo ocupa `tests/backend_mock.py`, sobre `httpx2.MockTransport`.
