# Research: Analisis del upgrade al SDK mcp 2.x: ajuste de lo implementado y mejoras aprovechables

Toda la evidencia sale de **leer el wheel `mcp-2.0.0-py3-none-any.whl`** descargado de PyPI, no de
documentación ni de suposiciones. Las referencias `server.py:N` son del SDK salvo que se diga
`local_delegate/`.

## Current behavior

Hoy el paquete usa una superficie **mínima** del SDK, y esa es la mejor noticia del análisis:

| Uso actual | Dónde |
| --- | --- |
| `from mcp.server.fastmcp import FastMCP` | `local_delegate/server.py:32` |
| `mcp = FastMCP("local-delegate")` | `local_delegate/server.py:36` |
| `@mcp.tool()` × 11, **sin argumentos** | `local_delegate/server.py:1000`–`1634` |
| `mcp.run()` (stdio) | `local_delegate/server.py:1758` |
| `settings.streamable_http_path = MCP_PATH` | `local_delegate/daemon.py:116` |
| `streamable_http_app()` | `local_delegate/daemon.py:117` |

**No se usa `Context`**, ni prompts, ni resources, ni el servidor lowlevel. Los modelos locales no
hacen tool-calling: el server arma el prompt y llama al endpoint.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| Import y clase | `FastMCP` | **Renombrado.** `MCPServer` en `mcp.server.mcpserver` | `mcp/server/mcpserver/__init__.py` exporta `MCPServer` |
| Constructor | `FastMCP("local-delegate")` | Compatible, y **acepta `version=`** | `server.py:147-176` |
| `@mcp.tool()` | 11 tools sin argumentos | **Compatible.** La firma añade opcionales (`title`, `annotations`, `icons`, `meta`, `structured_output`) | `server.py:621-630` |
| `mcp.run()` | stdio | **Compatible.** `run(transport="stdio")` sigue siendo el caso por defecto | `server.py:357` |
| `streamable_http_app()` | ASGI del daemon | **Sigue existiendo** | `server.py:1218` |
| `settings.streamable_http_path` | ruta del MCP en el daemon | **ROMPE.** `Settings` ya no tiene campos de transporte; la ruta es argumento de `streamable_http_app(streamable_http_path=...)` | `server.py:101-124` vs `server.py:1219` |

**Conclusión del impacto: un solo punto rompe de verdad** — `daemon.py:116`. El resto es renombrar
el import y la clase. La migración es de superficie pequeña, al contrario de lo que se asumió al
poner el techo (entonces no estaba verificado; ahora sí).

## Mejoras que trae 2.x y encajan con deuda ya anotada

Ordenadas por relación con problemas que el proyecto **ya tiene apuntados**, no por vistosidad:

| Mejora del SDK | Qué resuelve aquí | Evidencia |
| --- | --- | --- |
| **`version=` en el constructor** | El defecto conocido: `serverInfo` reporta hoy la versión del **SDK**, no la del paquete. Un handshake no sirve para saber qué versión corre | `server.py:154` |
| **`annotations: ToolAnnotations`** | Declarar las tools como read-only / no destructivas, que el cliente puede usar para decidir sin preguntar | `server.py:625` |
| **`structured_output`** en `tool()` | `local_extract` devuelve JSON como **texto**. Con salida estructurada el cliente recibe un objeto validado en vez de una cadena que hay que parsear | `server.py:628` |
| **`middleware: Sequence[ServerMiddleware]`** | El backpressure y los guardrails están cosidos a mano dentro de `_run_chat`. Un middleware los saca del camino feliz | `server.py:176` |
| **OpenTelemetry** (`mcp/server/_otel.py`) | La deuda de métricas: la contabilidad del chunking sesga los números (N llamadas = 1 evento) y la telemetría de hooks está desconectada del dashboard | módulo nuevo `_otel.py` |
| **`cache_hints`** (`CacheableMethod`, `CacheHint`) | Listados de tools cacheables; menos ida y vuelta en cada arranque de cliente | `server.py:177`, `mcp/server/caching.py` |
| **Elicitation** (`Elicit`, `AcceptedElicitation`, …) | Pedir confirmación al usuario **a mitad de una tool**. Encaja con delegaciones caras: montar un modelo de 14B cuando la VRAM está justa | `mcp/server/mcpserver/resolve.py` |
| **`auth` / `TokenVerifier`** | El daemon expone MCP por HTTP en loopback sin autenticación; hoy está mitigado solo por el bind | `server.py:155-156` |
| **`title`, `description`, `website_url`, `icons`** | Presentación del server en los clientes | `server.py:150-153` |
| **`request_state_security`** (AESGCM sellado) | Estado sellado entre peticiones, con el nombre del server como *audience* | `server.py:172` |
| **`extensions` / `ToolBinding`** | Agrupar tools en extensiones reutilizables | `mcp/server/extension.py` |
| **`subscriptions`** (`SubscriptionBus`) | Fan-out de eventos; hoy el dashboard sondea | `server.py:175` |

## Existing conventions

- Todo en español; el repo explica **por qué**, no **qué**.
- Cambios grandes por SDD, con PR y CI verde en los tres sistemas.
- Regla dura: no publicar a PyPI sin confirmación explícita.
- El paquete es **cliente genérico**: nada específico de un backend o máquina entra al código.
- `install-smoke` ya vigila que el paquete instalado arranque con dependencias resueltas libremente.

## Dependencies and integrations

- 2.0.0 trae **`mcp-types` como paquete aparte** (`from mcp_types import Icon`). Es dependencia
  transitiva de `mcp`; no hay que declararla. Verificado en la instalación de prueba, que trajo
  `mcp==2.0.0` **y** `mcp-types==2.0.0`.

### El coste real de 2.x no está en el código: está en el árbol de dependencias

Comparando `requires_dist` de las dos versiones en PyPI:

| | `mcp` 1.29.0 | `mcp` 2.0.0 |
| --- | --- | --- |
| Cliente HTTP | `httpx`, `httpx-sse` | **`httpx2>=2.5.0`** |
| Nuevas obligatorias | — | `opentelemetry-api`, `pyjwt[crypto]`, `jsonschema`, `python-multipart`, `mcp-types`, `uvicorn`, `anyio`, `typing-inspection` |
| Solo en Windows | — | **`pywin32>=311`** |
| pydantic | `>=2.11` | `>=2.12` |
| Ya no usa | `pydantic-settings` | — |

Tres consecuencias que pesan más que renombrar una clase:

1. **`httpx` y `httpx2` convivirían en el mismo entorno.** El paquete usa `httpx` **directamente**
   para el cliente OpenAI-compatible (`httpx>=0.27` en `pyproject.toml`), y el SDK pasaría a usar
   `httpx2`. Dos librerías HTTP instaladas a la vez. Funciona —son paquetes distintos— pero hay que
   decidir a conciencia si el cliente propio migra también a `httpx2` o si se asume la duplicidad.
   El aviso ya estaba a la vista: la suite emite
   `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead`.
2. **`opentelemetry-api` pasa a ser obligatoria.** La telemetría deja de ser opcional: entra en el
   árbol la instale quien la instale.
3. **`pywin32` en Windows.** Dependencia pesada y con historial de fricción en instalaciones, en la
   plataforma donde corre el daemon del usuario.

Para un paquete cuyo argumento es ser **ligero** (hoy: `mcp`, `httpx`, `platformdirs`, `fastapi`,
`uvicorn`, `filelock`) y que mide su `supplyChain` en Socket, pasar de ese conjunto a uno con
`pyjwt[crypto]`, `jsonschema` y OpenTelemetry dentro **no es neutro**.

### `httpx2`: qué es, y qué se lleva por delante

- Es **de pydantic** (`github.com/pydantic/httpx2`), *"The next generation HTTP client"*, hoy en
  **2.9.1**. No es un fork oscuro.
- El módulo top-level se llama **`httpx2`**: no es drop-in por nombre, hay que cambiar los imports.
- Expone `Client`, `AsyncClient`, `MockTransport`, `ASGITransport`, `WSGITransport` — la API es
  análoga a la de `httpx`.
- **`respx` NO lo soporta.** `respx` 0.23.1 sigue declarando `httpx>=0.25.0`. Como el proyecto
  mockea el backend con `respx`, migrar el cliente obliga a **sustituirlo**, previsiblemente por
  el `MockTransport` nativo de `httpx2`.
- Alcance medido: **122 ocurrencias de `respx`/`httpx` en 5 ficheros de tests** (`test_core.py` 58,
  `test_metrics.py` 23, `test_chunking.py` 18, `test_vision.py` 14, `test_map_reduce.py` 9).

### Depscore de todo lo que entra (Socket, 2026-07-28)

| Paquete | license | maint | quality | supplyChain | vuln |
| --- | --- | --- | --- | --- | --- |
| `httpx2` 2.9.1 | 100 | 100 | 100 | **100** | 100 |
| `mcp` 2.0.0 | 100 | 100 | 100 | 98 | 100 |
| `mcp-types` 2.0.0 | 100 | 100 | 100 | 100 | 100 |
| `pyjwt` 2.13.0 | 100 | 100 | 100 | 100 | 100 |
| `python-multipart` 0.0.32 | 100 | 100 | 100 | 99 | 100 |
| `jsonschema` 4.26.0 | 100 | 100 | 100 | 98 | 100 |
| `opentelemetry-api` 1.44.0 | 100 | 100 | 100 | 98 | 100 |
| **`pywin32` 312** | **70** | 100 | 100 | **73** | 100 |

**`pywin32` es el único punto flojo, y no es evitable:** `mcp` 2.x lo declara obligatorio en
`sys_platform == "win32"`, justo la plataforma donde corre el daemon del usuario. Roza el umbral de
0.7 de la política de dependencias del proyecto. Tiene una ironía: este repo ya **evitó** pywin32 a
propósito —`_pid_alive` usa `ctypes` en vez de esa librería— y 2.x la mete por la puerta de atrás.

El resto entra limpio. En particular `httpx2` marca **100 en todo**, así que la decisión de quedarse
con una sola librería HTTP no compra deuda de supply chain: la reduce respecto a arrastrar las dos.
- El techo `mcp>=1.2,<2` es lo que hay que levantar, y es el **único** motivo por el que hoy no se
  puede usar 2.x.
- Clientes afectados: Claude Code y Codex por stdio, y el daemon HTTP compartido en `:9393`. El
  cambio de `daemon.py` afecta solo al segundo.

## Risks and unknowns

**Confirmado leyendo el wheel:**
- `MCPServer` existe, con `version=`, y `streamable_http_app()` acepta `streamable_http_path`.
- Los 11 decoradores actuales no necesitan cambios.
- `Settings` perdió los campos de transporte: es el único punto de rotura real.

**No verificado todavía — hace falta ejecutar, no leer:**
- Que el handshake y las 11 tools **se comportan igual** bajo 2.x. Leer una firma no prueba
  comportamiento.
- Si `run()` mantiene exactamente la misma semántica de arranque en stdio.
- Si el nivel de protocolo negociado cambia y afecta a clientes viejos.
- Si la suite (233 tests) pasa sin tocar: hay tests que montan el server. Ojo: `respx` mockea
  `httpx`, y el SDK pasaría a `httpx2`.

**Descartado como bloqueante (verificado en PyPI):**
- `mcp` 2.0.0 pide `python>=3.10` (el proyecto ya exige `>=3.11`) y `pydantic>=2.12.0`. Ninguna de
  las dos bloquea.

**Riesgo de proceso:** el SDK 2.0.0 se publicó **el mismo día** que reventó la 0.12.1. Un major
recién salido acumula parches en las primeras semanas. Migrar ya significa ser de los primeros en
encontrar sus fallos — y este paquete acaba de aprender lo que cuesta eso.
