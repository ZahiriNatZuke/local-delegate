# Research — Concurrencia y cola de delegaciones de la PC y la Mac en un solo turno visible

Fecha: 2026-10-29. Base: `main` en 0.44.2 (`6f2fac5`) más el paso 0 de esta carpeta
(`feat/concurrency-log-fields`). Las referencias `fichero:línea` son de la rama del paso 0.

## 1. Pregunta

El 2026-10-28 una delegación de la PC esperó 275,9 s sin que nadie supiera a quién esperaba: la
Mac tenía `qwen36-35b-a3b` cargado y ocupado en el llama-swap de la PC, la PC pedía
`gemma4-26b-a4b`, y ni el turno del daemon ni el panel lo veían. Otra murió por el corte de 300 s
del cliente porque el servidor no manda progreso mientras espera. Hay que decidir cómo tener **una
sola cola visible en el panel, sin bloqueos para siempre y sin romper el uso solo local**.

## 2. Cómo funciona hoy (mapa de impacto)

### 2.1 Turno del daemon (solo PC, solo backend local)

- El turno es un estado único **por proceso**: `server._turn = _new_turn()`
  (`src/local_delegate/server.py:1727-1730`), un `turn.Turn` con `threading.Condition`
  (`src/local_delegate/turn.py:349-370`). No es una FIFO simple: concede por **conjunto de modelos
  compatibles** (`turn.grantable`, `turn.py:143`; E-1, `turn.py:179`) según la relación de choques
  de la topología de llama-swap.
- Red de seguridad: la cabeza de la cola se concede **forzada** si lleva `TURN_MAX_S` (600 s,
  `config.py:407`) esperando y el daemon `TURN_MAX_S` sin progreso (`turn.must_force`,
  `turn.py:168-176`). El reloj de progreso no corre mientras haya llamadas propias en vuelo
  (`Turn.in_flight`, `turn.py:396`; usado en `server._send`, `server.py:2294-2325`).
- **Sin turno si el backend no es loopback**: `_topology()` devuelve
  `NoTopology(NO_TURN_REMOTE_BACKEND)` (`server.py:1764-1771`), y `_OperationTurn.ensure` sigue sin
  pedir turno (`server.py:2093-2108`, «Sin turno para todo lo que quede con este modelo»).
  Es el caso de la Mac: su `BASE_URL` es `https://<pc>:9292/v1` (`docs/wiki/Remote-backend.md:24`).
- Por operación: `_OperationTurn` (`server.py:1981`), creado en las tres operaciones (`_chat`
  `server.py:3080`, `_chat_chunked` `server.py:3703`, `_chat_map_reduce` `server.py:4014`). El
  turno se pide antes que la plaza y dura toda la operación (todos sus trozos).

### 2.2 Plazas

- `_chat_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_REQUESTS)` (`server.py:165`;
  2 por defecto, `config.py:95`), **por proceso**. `_slot()` (`server.py:2263`) publica
  `local_wait: "slot"` en `inflight.json` mientras espera.
- En la PC todos los clientes de Claude Code y Codex entran por el daemon HTTP (`install --mcp-mode
  http`), así que comparten turno y plazas.

### 2.3 Puente de Claude Desktop (PC)

- `local-delegate desktop-bridge` reenvía cada mensaje JSON-RPC al `/mcp` del daemon con el token
  del registro (`src/local_delegate/desktop_bridge.py:1-25`, `daemon_url()` `:75`). Por tanto
  Desktop **ya** está dentro del turno único desde la 0.40.0: es el precedente de la opción A en
  local.

### 2.4 Los caminos de la Mac (dos, y pueden convivir)

**Corrección del 2026-10-29 (sesión principal y usuario):** varias delegaciones que estaban esta
mañana en `/api/inflight` del daemon de la PC (ids `9064:3..8`, mismo pid del daemon) **venían de la
Mac**. La hipótesis de la tarjeta («la Mac no pasa por el turno del daemon») no vale en general:
hay dos caminos y no se da por hecho ninguno.

- **Camino 1 — `/mcp` del daemon de la PC por HTTP (tailnet).** Posible desde la 0.42: el 421 se
  abre con `LOCAL_DELEGATE_WEB_ALLOWED_HOSTS` (`config.py:556`, `daemon.py:215-221`) y el token va en
  la cabecera (`config.py:576-589`). Una llamada por aquí entra en el **mismo** turno y las mismas
  plazas que las de la PC, aparece en `/api/inflight` del daemon y escribe su línea en el log **de
  la PC**. Hasta el paso 0 esa entrada no decía de dónde venía: `_inflight_start`
  (`server.py:306-341`) no guardaba ni cliente ni máquina, y `client` en el log es el nombre del
  cliente MCP («claude-code»), igual en las dos máquinas. Ojo: por este camino `path` se resuelve en
  la PC (`server._read_input`, `server.py:588-594`), así que una `local_summarize(path="/Users/…")`
  desde la Mac falla o lee otra cosa: hay que comprobar qué tools y con qué argumentos usó.
- **Camino 2 — MCP propio en stdio en la Mac contra `:9292`.** Lo que describe
  `docs/wiki/Remote-backend.md:24` y `:166-175` (entrada `"type": "stdio"`, `BASE_URL` al llama-swap
  de la PC). Un proceso por sesión de Claude Code, cada uno con 2 plazas y **sin turno** (backend
  remoto: `server.py:1764-1771`); su `inflight.json` y su log viven en la Mac
  (`server._inflight_file`, `server.py:235-236`). La espera real contra la PC es la cola interna de
  llama-swap, que para el daemon es solo un POST largo; lo único que la PC ve es la foto `inflight`
  de `/api/events`, y solo en la afinidad (`server._affinity_observe`).
- **Cómo averiguar cuál usa (sin suponer):**
  1. En la Mac, `claude mcp get local-delegate` (o `~/.claude.json`, clave `mcpServers.local-delegate`):
     `"type": "http"` con URL `https://<pc>…:9393/mcp` = camino 1; `"type": "stdio"` con `uvx …` =
     camino 2. Mirar también otros clientes de la Mac (Codex `~/.codex/config.toml`, Claude Desktop):
     cada uno puede ir por un camino distinto.
  2. Con el paso 0 desplegado en la PC: cada entrada del log y de `/api/inflight` del daemon trae
     `host`/`host_via`. Una de la Mac por el camino 1 sale con `host_via` (`ip` = dirección de la
     tailnet `100.x`; `forwarded` si entra por `tailscale serve`, que conecta desde loopback y pasa
     `X-Forwarded-For` — por comprobar en el paso 1; `header` si su entrada lleva
     `X-Local-Delegate-Host`). Una de la PC no lleva `host_via`.
  3. Camino 2: con la Mac en el paso 0, sus POST a llama-swap llevan `X-Local-Delegate-Host` y la
     foto `inflight` las muestra con ese `host` (`inflight_seen`); en el log de la Mac, `host` es la
     Mac y no hay `phases.turn`.
  4. Log de accesos del daemon: no hay; uvicorn arranca con `access_log=False` (`daemon.py:321-327`,
     así que no hay registro de peticiones HTTP). Antes del paso 0, la única pista es `tailscale serve`
     (`tailscale serve status`) o activar el access log de uvicorn en una prueba marcada.

### 2.5 Acceso al daemon desde la tailnet

- `/mcp` y el panel comparten guarda: `host_guard.transport_security(host)` en el
  `streamable_http_app` (`src/local_delegate/daemon.py:218-222`) y el middleware ASGI que da 421 a un
  `Host` ajeno (`src/local_delegate/web/host_guard.py:133-151`). Desde la 0.42,
  `LOCAL_DELEGATE_WEB_ALLOWED_HOSTS` (`config.py:556`) abre `/mcp` y panel para el nombre de la
  tailnet a la vez (`daemon.py:215-217`). El 421 ya no es un bloqueo técnico.
- Autenticación: `LOCAL_DELEGATE_WEB_TOKEN` (`config.py:576-589`) protege **todo** el puerto si está
  puesto; la guarda anti-rebinding no es control de acceso (`config.py:583-585`). La Mac ya guarda
  el token del daemon en el Llavero (`docs/wiki/Remote-backend.md:82`).

### 2.6 Progreso MCP

- No hay ningún envío de progreso MCP en `server.py` (sin `report_progress`). Durante el turno, la
  plaza o la cola de llama-swap la llamada calla, y Claude Code la aborta a los 300 s («sent no
  response or progress for 300s»). Este mismo research lo sufrió: un `local_summarize` de una nota
  del vault, lanzado desde este agente a la vez que la suite de tests, se abortó a los 300 s, y
después un `local_commit_msg` de un diff de 38 KB, también a los 300 s.
- **Evidencia de la PC sola, sin la Mac (2026-10-29, 12:09 UTC, foto de `/api/inflight` tomada por
  la sesión principal):** 6 delegaciones en vuelo, 2 corriendo y 4 en cola de turno con esperas de
  hasta 905 s, una de ellas ya abandonada por el cliente (el corte de 300 s) y aún en la cola. La
  causa: dos `local_explain_code` de ~340 000 caracteres (25 trozos cada uno) que retuvieron el
  turno unos 28 min. Conclusiones para el diseño: (a) la cola atascada y el corte por falta de
  progreso ocurren **sin la Mac**, así que la entrega de progreso MCP no depende de la opción
  elegida; (b) una llamada abandonada no debe seguir ocupando sitio en la cola (issue nuevo abierto
  por la sesión principal); (c) el turno por operación da el turno a una operación de muchos trozos
  durante toda su duración: la spec debe decidir si una operación larga cede entre trozos (relación
  con la cesión de la opción B).

### 2.7 Lo que añade el paso 0 (esta rama)

`host` en cada entrada (y `host_via` cuando la llamada llegó al `/mcp` del daemon desde otra
máquina, también en `/api/inflight`), `concurrency.phases` (turn/slot/backend con inicio y fin UTC),
`requested_model`, `backend_models` (de `/running` antes del primer POST), `model_swap`,
`inflight_seen` con la máquina de cada petición, y la cabecera `X-Local-Delegate-Host` en toda
petición al backend. Documentado en `docs/wiki/Savings-and-metrics.md` («Concurrencia: máquina de
origen y fases»). Límite conocido: no se ha comprobado contra un llama-swap real que `req_headers`
de la foto `inflight` traiga la cabecera nueva (el código y el fixture dicen que trae todas las
cabeceras; `llamaswap_api.py:10-15`). Se comprueba en el paso 1.

## 3. Hipótesis de la tarjeta, contrastada con el código

«Dos procesos con turnos y semáforos independientes que solo se ven por llama-swap»: **cierta solo
para el camino 2**. Por el camino 1 la Mac ya comparte turno y plazas con la PC (lo que explica que
sus llamadas aparecieran en `/api/inflight` del daemon), pero sin decir de qué máquina venían. Por
el camino 2 es peor que la hipótesis: un proceso por sesión de la Mac, cada uno con 2 plazas y sin
turno, y la cola real es la de llama-swap, sin posición ni motivo visibles. La medición del paso 1
tiene que establecer cuál usa cada cliente de la Mac antes de diseñar.

## 4. Opciones

Criterio: (1) una sola cola visible en el panel; (2) nadie espera para siempre; (3) el uso solo
local no cambia ni se rompe; y, del caso del 28-oct, (4) progreso MCP durante cualquier espera.

### A. La Mac usa el daemon MCP de la PC por HTTP

- **Cómo:** la entrada MCP de la Mac pasa de stdio a `http` contra `https://<pc>:9393/mcp` con el
  token, como el puente de Desktop en la PC.
- **A favor:** un solo turno, una sola cola y un solo log sin escribir código de turno nuevo; el 421
  ya se resuelve con `WEB_ALLOWED_HOSTS` y el token ya existe.
- **En contra, bloqueante:** `path` se lee **en el proceso del MCP** (`server._read_input`,
  `server.py:588-594`, y `_check_allowed_dir` `:522`). Con el MCP en la PC, `local_summarize(path=
  "/Users/…")` buscaría el fichero en la PC: falla. `path` es justo el camino del ahorro (el
  contenido no entra al contexto), y `write_to`/`target` de `local_boilerplate` escribirían en la
  PC. La Mac tendría que mandar el texto inline (gasta contexto, anula el ahorro) o haría falta
  subir ficheros al daemon (nueva superficie de ataque, cuota de tamaño). También: el mod y los
  hooks de la Mac miran su daemon local; perder el MCP de la PC (PC apagada, tailnet caída) deja a
  la Mac sin ninguna tool, no solo sin backend.
- **Veredicto:** no cumple sin rediseñar `path`; descartada como solución general. Pero **ya está
  en uso de hecho** para parte del tráfico de la Mac (§2.4, camino 1): la spec debe decidir si se
  normaliza (con `path` resuelto en el cliente, p. ej. el MCP de la Mac leyendo el fichero y
  mandando el texto al daemon) o si se desaconseja y se migra a B.

### B. Endpoint de turno/cesión en el daemon de la PC (recomendada)

- **Cómo:** el daemon expone, detrás del mismo token y la misma guarda de host, algo como
  `POST /api/turn/acquire {op_id, host, models, role}` → espera larga con latidos (posición, en
  uso, motivo) → `{grant_id, model, lease_s}`; `POST /api/turn/heartbeat`, `POST /api/turn/release`.
  La operación remota entra en el **mismo** `turn.Turn` que las locales (como `PendingRequest`
  con `op_id = "<host>:<pid>:<n>"`) y en `inflight.json` con `host`, así que el panel y
  `local_status` la ven en la cola. El MCP de la Mac lo pide antes de su primera llamada al
  backend cuando el backend es remoto y el daemon remoto responde (descubrimiento: mismo host que
  `BASE_URL` con el puerto web, como `config.remote_panel_url`).
- **Sin bloqueos para siempre:** la concesión es un **arrendamiento** con caducidad (p. ej. 60 s sin
  latido = liberado), y la red de seguridad `TURN_MAX_S` sigue aplicando; si el daemon no responde
  o rechaza (versión vieja, 401, 421, tailnet caída), la Mac **sigue como hoy** sin turno tras un
  tope corto (degradación, no bloqueo). Una Mac que muere a mitad deja de latir y su turno cae solo.
- **Progreso:** mientras espera la concesión, el MCP de la Mac recibe latidos y puede emitir
  progreso MCP con la posición; el mismo mecanismo resuelve el corte de 300 s en local (latido del
  turno/plaza/backend → `report_progress`).
- **A favor:** `path`, hooks y mod de la Mac no cambian; la cola es una y la decide el código que ya
  existe (`turn.py`, con la compatibilidad por modelos, mejor que una FIFO); el uso solo local no
  cambia (sin backend remoto no se llama al endpoint; en la PC el daemon usa el turno en proceso).
- **En contra / riesgos:** (1) superficie nueva en el puerto del daemon, que exige el token
  (`WEB_TOKEN` vacío por defecto: sin token, el endpoint debe negarse a conceder a clientes no
  loopback); (2) el reloj de «sin progreso» de `must_force` no ve las llamadas de la Mac en vuelo
  salvo que el latido las cuente como `in_flight` (hay que hacerlo, o una Mac ocupada provoca
  forzadas en la PC); (3) dos plazas de la PC no limitan a la Mac: el arrendamiento debe ocupar
  plaza o llevar su propio contador; (4) compatibilidad de versiones: Mac nueva con PC vieja →
  404 → sin turno, como hoy; (5) clientes que no son local-delegate (otro programa contra
  `:9292`) siguen fuera de la cola, pero el paso 0 los hace visibles como `host: null`.

### C. Proxy en la PC delante de llama-swap (`:9292`)

- **Cómo:** un proxy (en el daemon o aparte) escucha en `:9292`, llama-swap se mueve a otro puerto
  y el proxy aplica el turno a cada petición antes de reenviarla.
- **A favor:** aplica a **todo** cliente, incluso ajeno a local-delegate; la Mac no cambia nada.
- **En contra:** (1) el proxy ve **peticiones**, no **operaciones**: no sabe que 12 trozos de un
  map-reduce son una sola operación, así que intercala trozos de dos operaciones de modelos
  distintos y provoca justo los cambios de modelo que el turno por operación evita (o hay que
  inventar una cabecera de operación, que solo mandaría local-delegate: entonces es B por otra
  vía); (2) cambia la topología del usuario (puertos, `tailscale serve`, la config de llama-swap y
  su `/ui`, `/api/events`, `/upstream` que el proxy tendría que reenviar sin romper el streaming
  SSE); (3) si el proxy cae, cae todo el backend de las dos máquinas; (4) no puede mandar progreso
  MCP al cliente (solo el MCP de la Mac puede), así que el corte de 300 s sigue; (5) latencia y
  carga extra en cada token si hay streaming.
- **Veredicto:** el más invasivo y el que peor respeta la unidad «operación». Descartada salvo que
  la medición muestre muchos clientes ajenos.

### Tabla resumen

| Criterio | A (MCP remoto) | B (endpoint de turno) | C (proxy) |
|---|---|---|---|
| Una cola visible | Sí | Sí (con `host`) | Sí, por petición |
| Sin bloqueo para siempre | Sí (turno actual) | Sí (arrendamiento + forzada + degradación) | Depende del proxy |
| Uso solo local intacto | Sí | Sí | No (mueve puertos) |
| `path` desde la Mac | **No** | Sí | Sí |
| Progreso MCP en la espera | En la PC sí | Sí (latidos) | No |
| Coste | Bajo, pero rompe `path` | Medio | Alto |

## 5. Recomendación

**Opción B**, en dos entregas, **condicionada a la medición del paso 1** (que primero tiene que
decir qué camino usa cada cliente de la Mac; si todo fuera ya por el camino 1, la cola única existe y
lo que falta es progreso, cesión entre trozos y que `path` funcione desde la Mac): (1) progreso MCP durante
toda espera (turno, plaza, backend) también en local, que no depende de la topología y arregla el
corte de 300 s; (2) el endpoint de turno con arrendamiento y degradación, la operación remota
dentro del mismo `turn.Turn` y en `inflight.json` con `host`. Si la medición muestra que casi todas
las esperas son de cambio de modelo entre una operación de la PC y otra de la Mac, B es suficiente;
si aparecen muchos clientes con `host: null` (ajenos), se reevalúa C.

Riesgos a vigilar en la spec: token obligatorio para clientes no loopback; que el latido cuente
como llamada en vuelo para `must_force`; cupo de plazas de la Mac; versión mixta PC/Mac; zona de
choque con el Frente 2 (#477, estados `running/queued/retrying` de `/api/inflight`), que debe
incluir el estado de una operación remota.

## 6. Plan de medición del paso 1

**Requisito previo:** la PC y la Mac con una versión que incluya el paso 0 (la 0.45.0 o la rama
instalada). Relojes de ambas en hora (NTP; en macOS `sntp -sS time.apple.com` si hace falta).

**Escenario** (reproduce el 28-oct): una delegación de la PC con modelo A y dos de la Mac con
modelo B, lanzadas a la vez. Con los roles por defecto, `local_summarize` va al rol `long`/
`mechanical` (en la PC, `gemma4-26b-a4b`) y `local_explain_code` al rol `code`
(`qwen36-35b-a3b`). Si los roles de la Mac resuelven a otro modelo, basta que A ≠ B: comprobarlo con
`local_status` en cada máquina antes de empezar.

**Paso previo en las dos máquinas:** fijar qué camino usa cada cliente de la Mac (§2.4, «Cómo
averiguar cuál usa»). Si la Mac tiene clientes por los dos caminos, medir los dos escenarios.

**Pasos en la PC (sesión principal):**

1. `local-delegate test-window start --label "paso 1 concurrencia PC+Mac"` → guardar el id.
2. Avisar a la Mac (paso de abajo) y, en cuanto la Mac diga «lanzado», pedir en Claude Code:
   `local_summarize(path=<un fichero de 30-60 KB>)`. Mientras corre, mirar el panel
   (`http://127.0.0.1:9393`) y `local_status`: anotar si aparece alguna espera y qué modelo pinta
   la barra del mod.
3. Al terminar todo: `local-delegate test-window stop <id>`.
4. Copiar el `usage-AAAAMM.jsonl` de la Mac a la PC (o pegar sus 2-3 líneas nuevas) y cruzar.

**Prompt listo para pegar en Claude Code de la Mac:**

```text
Vamos a medir la concurrencia de local-delegate entre esta Mac y la PC (paso 1 de la tarjeta
«Concurrencia y cola PC+Mac»). No cambies configuración ni reinstales nada.

1. Comprueba la versión con `local-delegate --version`: tiene que ser la 0.45.0 o posterior (la que
   escribe `host` y `concurrency` en el log). Si es anterior, para y dímelo.
   Después ejecuta `claude mcp get local-delegate` y dime si la entrada es `stdio` o `http` (y la
   URL si es `http`; NO me muestres tokens ni cabeceras con secretos). Mira también si Codex o
   Claude Desktop de esta Mac tienen `local-delegate` configurado y por qué camino.
2. Ejecuta `local-delegate test-window start --label "paso 1 concurrencia PC+Mac (Mac)"` y guarda el id.
3. Llama a `local_status` y dime qué modelo resuelve el rol `code` y qué modelos ve cargados.
4. Lanza A LA VEZ, en dos subagentes en paralelo (o dos llamadas seguidas sin esperar la primera),
   dos `local_explain_code` con `path` a dos ficheros de código distintos de 20-40 KB de cualquier
   repo de esta Mac, con la pregunta «¿qué hace este fichero?». Dime «lanzado» en cuanto salgan.
5. Cuando terminen (o fallen), ejecuta `local-delegate test-window stop <id>`.
6. Muéstrame, tal cual, las últimas 3 líneas del log de uso de este mes
   (`~/Library/Application Support/local-delegate/usage-$(date -u +%Y%m).jsonl`; si
   `LOCAL_DELEGATE_LOG_DIR` o `LOCAL_DELEGATE_LOG` están puestas, el fichero está allí) y dime para cada una: `host`, `ok`, `latency_ms`,
   `concurrency.phases` (inicio, fin y ms de `slot` y `backend`), `backend_models` y `model_swap`.
```

**Qué mirar al cruzar (orden por `concurrency.phases.backend.start`):**

- ¿Se solapan los intervalos `backend` de la PC y de la Mac? ¿Cuál tiene `model_swap: true`?
  La que tiene `true` y empezó con el otro modelo cargado esperó el cambio dentro de llama-swap.
- `latency_ms` frente a `inference_ms` y `wait_ms`: cuánto de la espera fue cola de llama-swap.
- En el log y en `/api/inflight` de la PC: ¿hay entradas con `host_via`? Si las hay, esas llamadas
  de la Mac fueron por el camino 1 (y su `host` dice desde dónde: IP de la tailnet, `forwarded` o
  nombre).
- En la PC: `phases.turn` y `phases.slot` (≈ 0 si el daemon no esperaba a nadie suyo) y, si hubo
  afinidad, `inflight_seen`: ¿trae `host` de la Mac? Si siempre sale `null`, llama-swap no expone la
  cabecera en la foto y hay que decirlo en la spec.
- En la Mac: que no haya `phases.turn` (backend remoto) y cuánto esperó en `slot` la segunda de sus
  dos llamadas (2 plazas por proceso: si van en la misma sesión, deberían ir a la vez).
- Panel de la PC y `local_status` durante la prueba: ¿mostraron alguna espera? (esperado hoy: no).
- ¿Alguna llamada murió a los 300 s sin progreso? (confirma la entrega 1 de la recomendación).

## 7. Estado

Research hecho. Spec del cambio de arquitectura **pendiente de la medición del paso 1**. El paso 0
(instrumentación) tiene su spec y plan ligeros aprobados por revisión propia
(`spec-step0.md`, `plan-step0.md`) y va en su propio PR.
