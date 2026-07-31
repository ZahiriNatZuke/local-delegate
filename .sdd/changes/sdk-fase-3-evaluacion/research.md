# Research: Evaluación de la fase 3 del SDK `mcp` 2.x

Todo lo de aquí está comprobado contra el **SDK instalado** (`mcp` 2.0.0) y contra `server.py`, no
leído de la documentación.

## Aviso de método, porque este research empezó con un error mío

La primera comprobación fue un `grep -i middleware` sobre el repo, que dio **cero ocurrencias**, y
concluí que el SDK no tenía nada de eso. **Era falso, y por método:** ripgrep respeta `.gitignore` y
`.venv/` está ignorado, así que **ni siquiera entró en el paquete**. Buscando desde Python:

```
rutas con middleware en el nombre:  server/auth/middleware
ficheros .py que lo mencionan:      20
```

Vale como recordatorio de la regla de la casa: **un no-resultado no es evidencia si no se comprueba
que la búsqueda podía encontrar algo.**

## Lo que existe de verdad

| Módulo | Qué es | SEP / revisión |
| --- | --- | --- |
| `mcp.server.extension` | interfaz de extensiones con **`intercept_tool_call`** | SEP-2133 |
| `mcp.server.elicitation` | pedir datos al usuario a través del cliente | — |
| `mcp.server.auth` | servidor de autorización OAuth2 (`bearer_auth`, `auth_context`, `routes`) | — |
| `mcp.server.caching` | *hints* de caché por método (`CACHEABLE_METHODS`, `apply_cache_hint`) | SEP-2549, rev. **2026-07-28** |
| `mcp.server.subscriptions` | `subscriptions/listen`, bus de eventos del servidor | SEP-2575, rev. **2026-07-28** |

**No hay un «middleware» de tools.** El concepto está en `Extension`, cuya doc lo dice explícito:
*«the server applies a closed set of contribution kinds: tools, resources, new request methods, and
**one `tools/call` interceptor**»*.

Dato que acota las dos últimas: `LATEST_PROTOCOL_VERSION` es **2026-07-28** (hace tres días) pero
`DEFAULT_NEGOTIATED_VERSION` del propio SDK sigue en **2025-03-26**.

## Veredicto por capacidad

### 1. `extension` / `intercept_tool_call` — **NO se hace (por telemetría)**

El motivo que se le atribuía era «centralizar la telemetría, que hoy cada tool anota a mano».
**Esa premisa es falsa, y se comprueba contando:** `_log_event` se invoca en **tres** sitios de
`server.py`, no en once, y los tres son:

```
línea  678 -> def _chat(
línea  870 -> def _chat_chunked(
línea 1002 -> def _chat_map_reduce(
```

O sea: la telemetría **ya está centralizada**, y lo está exactamente donde tiene que estar — en los
**caminos de llamada al backend**, no en el borde MCP. Un `intercept_tool_call` vería la llamada a la
tool, pero **no** los tokens reales del backend, ni el número de llamadas, ni los chunks, que es lo
que mide el panel desde el PR #48.

Es **la misma objeción que descartó OpenTelemetry**, y aplicarla aquí es coherente, no perezoso:
sustituir tres puntos que ven el coste real por uno que solo ve el borde sería una regresión.

**Lo que quedaría por mirar aparte, y no es esto:** un interceptor sí serviría para un contrato
transversal del borde —rechazar llamadas con el backend caído sin que cada tool lo compruebe, o un
límite de uso—. Eso es otro problema, y hoy nadie lo ha pedido.

### 2. `elicitation` — **decisión bloqueada por una medición que falta**

Es la capacidad con más sentido de las cinco: permitiría que una tool **pregunte** en vez de adivinar
o fallar seco (backend caído → «¿lo arranco?»; delegación ambigua → pedir el formato).

**Pero depende del cliente, y no está medido.** El daemon ni siquiera mira las capabilities del que
se conecta: `grep -r "capabilities" src/local_delegate/` → **0 ocurrencias**. Y si el cliente no lo
soporta, una tool esperando una respuesta que no llega es **peor** que fallar rápido.

**Experimento propuesto, barato y concluyente:** registrar en el daemon las `capabilities` y la
revisión de protocolo que declara cada cliente en `initialize`, y conectar Claude Code y Codex. Es
útil por sí mismo —hoy no sabemos con qué hablamos— y decide esta capacidad y las dos siguientes.

### 3. `auth` — **NO se hace**

Es un servidor de autorización OAuth2 completo. Este daemon escucha en **loopback**, con un usuario
y una máquina; el `SECURITY.md` ya asume ese modelo. Montar OAuth aquí es infraestructura pesada
para un problema que no existe.

**Cuándo cambiaría:** solo si el daemon se expusiera fuera de loopback. Y ahí ya hay precedente de
que ese camino tiene sus propias trampas — el 421 por el header `Host` con `WEB_HOST=0.0.0.0`.

### 4. `caching` — **NO se hace**

Son hints para que el cliente cachee respuestas de métodos como `tools/list`. **Nuestro coste no
está ahí**: está en la inferencia del backend, que no es cacheable por esta vía. Ahorraría unos
kilobytes de listado y ni un token de modelo.

### 5. `subscriptions` — **NO se hace**

`subscriptions/listen` sirve para que el cliente escuche cambios del servidor (recursos, prompts).
El dashboard **ya tiene su propio canal** y su propia contabilidad; no hay nada que un cliente MCP
necesite escuchar aquí.

Además, junto con `caching`, pertenece a la revisión **2026-07-28**, publicada hace tres días, con el
propio SDK negociando por defecto **2025-03-26**: implementarlas hoy sería escribir código que
probablemente ningún cliente negocia.

## Resumen

| Capacidad | Veredicto |
| --- | --- |
| `extension` / interceptor | **no**, por la objeción del PR #48, ahora medida |
| `elicitation` | **pendiente de una medición**, la única con recorrido |
| `auth` | **no**, loopback |
| `caching` | **no**, el coste no está ahí |
| `subscriptions` | **no**, sin nada que escuchar y revisión demasiado nueva |

De cinco, **cuatro se descartan con motivo escrito** y una queda a expensas de un experimento que
además vale por sí solo. Es el resultado esperable de convertir una lista heredada en un
diagnóstico.
