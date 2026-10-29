# Spec — Concurrencia y cola de delegaciones de la PC y la Mac en un solo turno visible

Fecha: 2026-10-29. Base: `main` en 0.45.0 (`f1d5e22`, con el paso 0, #476, #477 y #479 ya
mezclados). Entradas: `research.md` (opciones A/B/C), `measurement-step1.md` (medición del paso 1)
y la tarjeta del Project 3 (prioridad 1 del 2026-10-29).

## 1. Resumen

**Criterio de la tarjeta:** una sola cola visible en el panel, sin bloqueos para siempre y sin
romper el uso solo local.

La medición confirmó **tres colas sin coordinar** sobre el mismo llama-swap: el daemon de la PC,
cada proceso stdio de Claude Code en la Mac (directo a `:9292` por la tailnet) y el daemon de la Mac
(Claude Desktop por `mcp-remote`). Y una **inanición**: la PC esperó 180 s dentro de llama-swap
mientras la Mac tenía demanda continua de `qwen36-35b-a3b`, y acabó en `read_timeout` con un mensaje
que culpaba a la carga del modelo.

**Mecanismo elegido: opción B del research.** El daemon de la máquina del backend (la PC) expone un
**turno con arrendamiento** por HTTP. Todo proceso de local-delegate que vaya a llamar a un backend
**remoto** pide turno ahí antes de cada operación, lo mantiene con latidos y lo suelta al acabar. La
operación remota entra en el **mismo** `turn.Turn` que las locales, así que la cola es una, respeta
la compatibilidad de modelos de la topología y aparece en `/api/inflight` con su `host`. Si el
daemon no responde, es viejo o no autoriza, el cliente sigue como hoy y lo deja escrito en el log.

La medición no da motivo para otra opción: la C (proxy delante de `:9292`) intercalaría trozos de
operaciones distintas (justo lo que provocó los cambios de modelo de la medición) y no puede mandar
progreso MCP; la A rompe `path` desde la Mac (research §4.A).

Se entrega en dos partes: primero tres mejoras baratas que la medición pide y que no dependen de B
(estado `waiting_backend`, progreso que lo dice y mensaje de `read_timeout` que nombra al culpable);
después el turno remoto con la cesión entre trozos.

## 2. Requisitos

### Parte 1 — Ver la espera dentro del backend (entrega previa, independiente de B)

- **REQ-001 (`waiting_backend` en inflight, por envío).** **Cada envío** (POST) arma su propio
  temporizador de `BACKEND_SAMPLE_DELAY_S` (3 s); la muestra única del log del paso 0
  (`Trace.claim_backend_sample`, `concurrency.py:83`) no cambia y sigue siendo una por operación. Si
  el envío sigue pendiente a los 3 s y `/running` dice que el modelo pedido **no** está `ready`, el
  envío se apunta en la clave `backend_wait` de la entrada de `inflight.json` como
  `{"<n.º de envío>": {modelo: estado, …}}` (máx. 8 modelos por envío; como mucho tantos envíos
  como plazas). `inflight_snapshot` publica la unión (`backend_wait: {modelo: estado}`) y
  `_inflight_state` devuelve **`waiting_backend`** si algún envío de la entrada espera (precedencia:
  `queued` > `retrying` > `waiting_backend` > `running`). `INFLIGHT_STATES` pasa a
  `("running", "retrying", "queued", "waiting_backend")`. «Pedido no `ready`» compara con el nombre
  real (`_real_model_name`) y con el nombre enviado; si en una máquina sin topología (la Mac) ninguno
  de los dos aparece en `/running` y no se puede saber si es un alias, **no** se marca (un falso
  «esperando backend» es peor que ninguno).
- **REQ-002 (seguimiento y fin de la espera).** Mientras un envío esté apuntado y siga pendiente,
  se vuelve a muestrear `/running` cada `BACKEND_WAIT_RESAMPLE_S` (10 s, con la caché de 2 s y el
  tope de 0,5 s del paso 0). Cada envío borra **solo lo suyo** cuando el modelo pedido aparece
  `ready`, cuando termina (con éxito, error o cancelación) y al soltar su plaza. Un envío que no
  espera 3 s no consulta nada (regla de la afinidad, `test_affinity`).
- **REQ-003 (progreso MCP).** Con `backend_wait` puesta, el texto del latido de progreso (#479,
  `Token.progress_message`) dice «esperando a que el backend cambie de modelo (cargado: X)» /
  «waiting for the backend to switch models (loaded: X)», con X los modelos `ready` o `starting`
  distintos del pedido; sin ninguno, «esperando al backend» / «waiting for the backend». La espera de
  turno y de plaza mantienen sus textos y van antes.
- **REQ-004 (panel y mod).** El panel («En curso») pinta `waiting_backend` como espera, con el texto
  de REQ-003 y los modelos cargados, no como «procesando». La banda del mod lo ordena después de
  `running` y `retrying` y antes de `queued`, y dice «ESPERANDO BACKEND» / «WAITING FOR BACKEND»
  con el modelo **pedido** (no el cargado; corrige lo visto el 2026-10-28). Un mod o panel viejo
  que reciba el valor nuevo lo trata como hoy un estado desconocido (`running`): degrada sin romper.
- **REQ-005 (`read_timeout` que nombra al culpable).** Al vencer el plazo de lectura, el mensaje
  usa la foto de `/running` de la sonda que ya existe para ese envío (`_LoadProbe`,
  `server.py:1631`, la misma que decide `error_class` en `server.py:1839`, así texto y clase no se
  contradicen); si la sonda no tiene foto, `concurrency.loaded_models()` (caché de 2 s, tope de
  0,5 s); si tampoco, la muestra de la operación. Elige uno de tres textos (es+en):
  1. el modelo pedido no estaba cargado y había otro `ready`/`starting`: «{model} no respondió en
     {seconds} s: llama-swap tenía cargado {loaded} y no llegó a cambiar de modelo (otra petición
     lo estaba usando{hosts})», donde `{hosts}` es «, desde {host}» si la foto `inflight` del paso 0
     (`inflight_seen`) trae el `host` de las peticiones de ese modelo;
  2. el modelo pedido estaba `ready`: «{model} estaba cargado pero no respondió en {seconds} s
     (backend ocupado o respuesta muy larga)»;
  3. sin muestra (consulta fallida, backend sin `/running`): el texto de hoy.
  `error: "read_timeout"` y `error_class` no cambian; el evento del log gana
  `read_timeout_cause: "model_swap" | "busy" | null`.

### Parte 2 — Una sola cola para todas las máquinas (opción B)

#### Servidor (daemon de la máquina del backend)

- **REQ-010 (endpoint).** El daemon expone, bajo el prefijo `/api/turn/`:
  - `POST /api/turn/acquire` con `{op, host, tool, model, role, chain, chars_in, chunks}` →
    `{v, daemon_id, lease, status, position, in_use, model, forced, lease_s, heartbeat_s, stalled_s}`.
  - `POST /api/turn/heartbeat` con `{lease, in_backend, waiting_backend, chunk, phase}` → la misma
    forma de respuesta.
  - `POST /api/turn/release` con `{lease}` → `{status: "released"}`; idempotente (un `lease`
    desconocido también da 200).
  `status` ∈ `queued`, `granted`, `yield`, `expired`, `no_turn`. `acquire` y `heartbeat` responden
  en cuanto cambia el estado o, como mucho, a los `heartbeat_s` (espera larga acotada; nunca
  bloquean más). Los manejadores son síncronos (corren en el threadpool de Starlette, nunca en el
  bucle async que sirve `/mcp`). `lease` es aleatorio de 32 bytes (`secrets.token_urlsafe(32)`).
  Todos los nombres en inglés.
- **REQ-011 (mismo turno).** Una operación remota entra en el `turn.Turn` del daemon como
  `PendingRequest(id="<host>/<op>", A={m}, role=m, direct={m}, chain_order=chain)`, con `m` el
  modelo resuelto por la topología del daemon. Sin afinidad (el alternativo es decisión local). Si
  el daemon no tiene topología, el backend del daemon no es loopback o el modelo no está en su
  config → `status: "no_turn"` y la operación sigue sin turno, igual que una local sin topología
  (REQ-002 del turno).
  **API nueva de `turn.Turn`, sin bloqueo** (las operaciones remotas no tienen hilo en el daemon):
  `enqueue(request)`, `poll(op_id) -> Grant | (posición, en_uso) | None` (saca la concesión de
  `_granted` al entregarla, como `_wait`), `expire(op_id)` (quita de `queue`, `actives`, `_granted`
  y del vuelo remoto; idempotente), `remote_flight(op_id, bool)`, `must_yield(op_id)` (sobre la
  función pura `turn.must_yield`, REQ-030), `Active.granted_at` (nuevo, `compare=False`) y
  `wait_change(timeout)` (bloquea
  hasta el siguiente cambio de estado del turno o el plazo; lo usa la espera larga del endpoint).
  `release_slot`, `abandon` y `expire` **reevalúan** (`_apply`) además de despertar, para que una
  espera remota sin hilo se conceda en cuanto se libera el turno y no en el siguiente latido. Esto
  cambia cuándo se concede (antes, en el siguiente tic de la espera local, ≤ 1 s); el resultado de
  la concesión es el mismo, y los tests existentes de `tests/test_turn.py` y
  `tests/test_turn_daemon.py` deben pasar sin tocarse (si alguno no, se para y se revisa la spec).
- **REQ-012 (arrendamiento).** Cada `lease` caduca si pasan `TURN_LEASE_S` (30 s por defecto,
  `LOCAL_DELEGATE_TURN_LEASE_S`) sin `acquire` ni `heartbeat`. Al caducar, la operación sale de la
  cola o de `actives` del turno y de `inflight.json`, y deja de contar en vuelo. La caducidad se
  revisa en cada petición al endpoint, en cada tic de una espera local de turno y con un temporizador
  del daemon cada `TURN_LEASE_S / 3` mientras haya arrendamientos vivos (que se para cuando no
  queda ninguno). Un `heartbeat` de un `lease` caducado responde `status: "expired"`. Toda
  concesión, liberación, caducidad y cambio de `in_backend` de una operación remota llama a
  `_note_queue_progress()` (#476), así una espera local detrás de la Mac no se da por saturada
  mientras la cola avanza. Interruptor del servidor: `LOCAL_DELEGATE_TURN_SERVER=off` apaga el
  endpoint (404, como un daemon viejo) sin publicar nada.
- **REQ-013 (red de seguridad).** `TURN_MAX_S` sigue: la cabeza de la cola entra **forzada** si
  lleva `TURN_MAX_S` esperando y el daemon `TURN_MAX_S` sin progreso. Una operación remota que
  declara `in_backend: true` en su último latido cuenta como llamada en vuelo para ese reloj
  (`Turn.in_flight`), así una Mac ocupada no provoca forzadas en la PC; al caducar su arrendamiento
  deja de contar.
- **REQ-014 (visible en inflight).** Mientras exista, cada arrendamiento tiene su entrada en el
  `inflight.json` del daemon con clave `remote:<host>/<op>`, `pid` = el del daemon, `host`,
  `host_via: "lease"`, `tool`, `model`, `chars_in`, `chunks`/`chunk`/`phase` del último latido y
  `local_wait: "turn"` + `turn_position`/`turn_in_use` mientras espera, o `in_backend` y
  `backend_wait` (REQ-001) según el latido; al concederse se escribe `in_backend: false` (si no,
  `_inflight_state` la pintaría `queued`). Su clave está en `_inflight_live` mientras el
  arrendamiento vive (la poda de 1800 s no la toca) y sale con la liberación o la caducidad.
  `/api/inflight`, el panel y `local_status` del daemon la
  ven con el `state` de #477 y REQ-001 y con su `host`. Las claves de una entrada local no cambian
  (`tests/test_inflight_per_session.py`).
- **REQ-015 (sin doble cuenta).** El daemon **no** escribe evento de uso por una operación remota:
  la operación se registra solo en el log de la máquina que la ejecuta. Las estadísticas, el ahorro y
  `/api/stats` no cambian.
- **REQ-016 (autenticación).** Las rutas de `/api/turn/` exigen, **solo** en `Authorization: Bearer`
  (no `Basic` ni cookie de sesión: un navegador no debe poder usarlas), con
  `Content-Type: application/json` y **sin** cabecera `Origin` (como `_require_hook_client`,
  `web/metrics.py:1132`), **el
  token del puerto del daemon** (`LOCAL_DELEGATE_WEB_TOKEN`, entorno o Llavero) **o la clave del
  backend del daemon** (`LOCAL_DELEGATE_API_KEY`, la misma que el cliente remoto ya usa contra
  `:9292`), comparadas en tiempo constante. Motivo: quien tiene la clave del backend ya puede
  ocupar la GPU directamente; el turno no le da nada nuevo, y la Mac no necesita un secreto más.
  - Si el daemon no tiene **ningún** secreto configurado: `403` con `{"error": "turn_needs_secret"}`
    (todas las conexiones de `tailscale serve` llegan desde 127.0.0.1, así que el loopback no
    autentica nada).
  - El middleware `PortToken` deja pasar sin su token **solo** las tres rutas exactas
    (`POST /api/turn/acquire`, `/heartbeat`, `/release`; comparación exacta de ruta y método, no
    de prefijo, sobre la ruta ya normalizada por el servidor), que validan con su propia
    dependencia. Un test enumera las rutas de la app y falla si otra ruta salta `PortToken` o si
    una de las tres no lleva la dependencia, y otro prueba variantes (`/api/turn/x`, `..`,
    `%2e%2e`, `//`, otros métodos) que deben seguir pidiendo el token del puerto. El resto del
    puerto sigue igual.
  - **Dato por confirmar en el lote 3 (primer paso):** que el entorno del daemon de la PC tiene la
    clave del backend y que es la misma que la de la Mac. Si no la tiene, la Mac usa el token del
    puerto de la PC (`LOCAL_DELEGATE_REMOTE_WEB_TOKEN` o Llavero `local-delegate-remote-web-token`),
    y esa es la vía documentada.
  - La guarda del `Host` (421) no cambia: la Mac ya entra con `LOCAL_DELEGATE_WEB_ALLOWED_HOSTS`.
  - Nunca se registra ni se devuelve la credencial.
- **REQ-017 (límites).** Como mucho `TURN_MAX_LEASES` (16) arrendamientos vivos en total y 8 por
  `host`; por encima, `429` con `{"error": "too_many_leases"}`. Cuerpo máx. 4 KB; `host`, `op`,
  `tool` y `model` saneados como `config.clean_machine_name` (máx. 64) y rechazados con `400` si
  quedan vacíos.

#### Cliente (proceso con backend remoto)

- **REQ-020 (cuándo se pide).** Un proceso pide turno remoto cuando su turno local no aplica por
  `NO_TURN_REMOTE_BACKEND` (backend no loopback), o cuando `LOCAL_DELEGATE_TURN_URL` tiene una URL
  explícita (caso del túnel `ssh -L`, que hace parecer loopback un backend remoto). Con
  `LOCAL_DELEGATE_TURN_URL=off` no se pide nunca. En la PC, con backend local, nada cambia: no se
  llama a ningún endpoint. **Nunca a sí mismo:** si la URL resuelta es de loopback y su puerto es
  el `WEB_PORT` propio, o el daemon que responde tiene el mismo id que el de este proceso (campo
  `daemon_id`, nuevo: aleatorio por arranque, escrito en `daemon.json` y `/api/daemon` y devuelto en
  cada respuesta del endpoint; se compara con el `daemon.json` local), no se pide turno remoto
  (`remote_turn: "self"`); con topología local y backend loopback, manda el turno local aunque
  haya `TURN_URL`.
- **REQ-021 (descubrimiento).** Con `LOCAL_DELEGATE_TURN_URL` en `auto` (por defecto), la URL del
  daemon es `config.remote_panel_url()`: mismo esquema y host que `BASE_URL`, con el puerto web
  (`LOCAL_DELEGATE_WEB_PORT`, 9393). Con una URL explícita, esa.
- **REQ-022 (ciclo por operación).** `_OperationTurn` pide turno remoto en el mismo punto donde
  pediría el local (`ensure`, antes de la plaza de la primera llamada y en cada salto de modelo),
  lo mantiene con un hilo de latido cada `heartbeat_s` (lo dice el servidor; 5 s por defecto) que
  manda `in_backend`, `waiting_backend`, `chunk` y `phase`, y lo suelta en el mismo `finally` que
  hoy suelta el turno local (`release_slot`), también si la llamada se cancela o falla. Un salto a
  otro modelo suelta y vuelve a pedir, como en local (REQ-006 del turno).
- **REQ-023 (espera visible y con progreso).** Mientras espera turno remoto, el cliente publica en
  su propio `inflight.json` `local_wait: "turn"` con `turn_position` y `turn_in_use` de la
  respuesta, y el latido de progreso MCP dice el texto de turno de #479 con «en {host del daemon}».
  La cancelación de la llamada sale de la espera y suelta el arrendamiento.
- **REQ-024 (cola saturada).** La espera remota respeta `QUEUE_MAX_WAIT_S` (#476): `stalled_s` es
  `_queue_stalled_s` del servidor (el mismo reloj de `_note_queue_progress`, que ahora mueven
  también los eventos remotos de REQ-012); si supera el límite, sale con `QueueSaturated` y el
  mensaje de turno saturado, nombrando la máquina.
- **REQ-025 (degradación, nunca bloqueo).** Tres casos distintos:
  1. **Daemon inutilizable** — no responde (conexión 3 s, lectura `heartbeat_s + 5` s), 404/405
     (versión vieja o servidor apagado), 401/403, o respuesta ilegible o con `v` mayor: la
     operación **sigue sin turno, como hoy**. Motivo en el evento (`remote_turn: "unreachable" |
     "unsupported" | "unauthorized" | "needs_secret" | "bad_response"`) y, una vez por proceso y
     motivo, en el log de errores. Se recuerda 60 s (404/405: 10 min).
  2. **Daemon vivo pero lleno** — `429`: se **espera** y se reintenta cada `heartbeat_s` (con
     progreso «esperando turno en {host}»), dentro de `QUEUE_MAX_WAIT_S`; no se va sin turno.
  3. **Arrendamiento perdido con el daemon vivo** — `expired` en un latido (caducidad o daemon
     reiniciado): la llamada en curso termina (no se repite), y **antes del siguiente envío se
     vuelve a pedir turno** al final de la cola. Solo si ese nuevo `acquire` cae en el caso 1 se
     sigue sin turno.
  Así, el único camino para llamar al backend sin turno es un daemon inutilizable, que es también
  el caso en que nadie más puede tenerlo.
- **REQ-026 (log).** El evento de uso de una operación con turno remoto lleva
  `remote_turn: "granted" | "forced" | "no_turn" | "self" | <motivo de REQ-025>`, y la fase `turn` del paso 0
  (`concurrency.phases.turn`) mide también la espera remota. `turn_wait_ms` suma la espera remota.
  Una operación local no lleva el campo.
- **REQ-027 (`local_status` y `doctor`).** `local_status` de un proceso con backend remoto añade una
  línea «Turno remoto: activo en <url> | no disponible (<motivo>) | desactivado». `doctor` comprueba
  en la Mac que el daemon remoto responde a `/api/turn/` con la credencial (OK / WARN con el motivo)
  y en la PC que el daemon tiene algún secreto para el endpoint (WARN si no).

#### Reparto justo

- **REQ-030 (cesión entre trozos).** Una operación activa (local o remota) **debe ceder** cuando:
  (a) la cabeza de la cola no es concedible (`grantable(cabeza, actives)` vacío) y su modelo choca
  con el de esta operación — **todas** las activas que chocan con la cabeza ceden, no solo la
  última; (b) la cabeza lleva `TURN_YIELD_S` esperando; (c) la operación tiene el turno desde hace
  al menos `TURN_YIELD_S` (`Active.granted_at`). `TURN_YIELD_S` = 120 s por defecto
  (`LOCAL_DELEGATE_TURN_YIELD_S`; `0` lo apaga). Ceder es: no mandar **ningún envío nuevo** desde
  que se sabe, esperar a que acaben los propios en vuelo, soltar el turno y volver a pedirlo **al
  final** de la cola (la afinidad elegida se olvida y se decide de nuevo al volver). Local: se
  comprueba en `ensure` antes de cada envío, en las dos salidas tempranas (afinidad y mismo
  modelo). Remota: el latido responde `status: "yield"`. **Tope en el servidor:** un arrendamiento
  que sigue activo `heartbeat_s × 2 + HTTP_TIMEOUT` después de recibir `yield` se trata como
  caducado (`expire`): un cliente que ignore la cesión no retiene la cola.
- **REQ-031 (sin inanición).** **Precondición:** todos los clientes del backend son de esta versión
  y ninguno está en el caso 1 de REQ-025. Entonces una operación que espera turno por un modelo que
  choca con los que están en uso obtiene el turno, como mucho, en
  `TURN_YIELD_S + heartbeat_s + HTTP_TIMEOUT + carga del modelo` (el plazo de lectura acota la
  llamada en curso), salvo que `TURN_MAX_S` la fuerce antes. Las que llegan después con el modelo en
  uso no la adelantan (E-1, `turn.py:179`). Con `TURN_YIELD_S=0` la cota no aplica (depende de la
  operación más larga, como hoy) y así se documenta. Se verifica con una simulación de reloj falso
  sobre `evaluate` + `must_yield` (demanda continua de X desde «la Mac», Y pedido por «la PC»), y
  en vivo (lote 5).
- **REQ-032 (registro de la cesión).** El evento de uso cuenta las cesiones (`turn_yields: n`, solo
  si n > 0) y la fase `turn` suma las esperas tras ceder.

### Compatibilidad

- **REQ-040 (uso solo local intacto).** Sin backend remoto ni `LOCAL_DELEGATE_TURN_URL` explícita,
  ningún proceso llama a `/api/turn/`; los tests existentes del turno, la afinidad, inflight y el log
  pasan sin cambios. Diferencias observables en local, todas deliberadas: la cesión de REQ-030
  (apagable con `TURN_YIELD_S=0`), el estado `waiting_backend` y su texto de progreso (REQ-001..004),
  el texto del `read_timeout` (REQ-005) y que `release_slot`/`abandon` reevalúen al momento
  (REQ-011: misma concesión, antes).
- **REQ-041 (versiones mixtas).** Tabla:

  | PC (daemon) | Mac (cliente) | Comportamiento |
  |---|---|---|
  | nueva | nueva | una cola; la Mac visible en el panel de la PC |
  | nueva | ≤ 0.45 | la Mac va directa a `:9292` como hoy; la PC solo la ve en `inflight_seen` |
  | ≤ 0.45 | nueva | `acquire` da 404 → `remote_turn: "unsupported"`, sin turno, aviso una vez |
  | nueva sin secreto | nueva | 403 `turn_needs_secret` → sin turno; `doctor` lo avisa en las dos |

  El protocolo lleva `"v": 1` en las respuestas; un cliente que reciba otra versión mayor degrada
  como `unsupported`.
- **REQ-042 (campos aditivos).** Los campos nuevos del log (`remote_turn`, `turn_yields`,
  `read_timeout_cause`) e inflight (`backend_wait`, `host_via: "lease"`) son aditivos; el panel y
  `/api/stats` leen igual logs viejos, nuevos y mezclados.

### Documentación

- **REQ-050.** `docs/wiki/Architecture.md` («Turno, afinidad y lentitud»: turno remoto, cesión,
  `waiting_backend`), `docs/wiki/Remote-backend.md` (qué pide la Mac, descubrimiento, credencial,
  degradación, recomendación de topología de §6), `docs/wiki/Configuration.md` (`TURN_URL`,
  `TURN_LEASE_S`, `TURN_YIELD_S`, `TURN_SERVER`, `REMOTE_WEB_TOKEN`), `docs/wiki/Savings-and-metrics.md` (campos nuevos) y
  `CHANGELOG.md` (Unreleased).

## 3. Fuera de alcance

- **Plazas globales.** Las plazas (`MAX_CONCURRENT_REQUESTS`) siguen siendo por proceso; el turno
  remoto ordena **operaciones** por modelo, no limita llamadas simultáneas entre máquinas. Si tras la
  entrega se mide cola dentro de llama-swap con el mismo modelo (plaza 0, `wait_ms` alto sin
  `model_swap`), se abre otra tarjeta.
- **Afinidad para operaciones remotas.** Una operación remota pide su modelo, sin alternativos.
- **Proxy de `:9292` en el daemon (opción C) y cerrar `:9292` en la tailnet.** Ver §6: es una
  recomendación con condiciones, no código de este cambio.
- **Clientes ajenos a local-delegate contra `:9292`.** Siguen fuera de la cola; el paso 0 los
  muestra como `host: null`.
- **El camino 1 (MCP `http` de la Mac contra el `/mcp` de la PC).** Ya comparte la cola; `path` se
  resuelve en la PC (research §4.A). No se cambia; la wiki lo desaconseja para tools con `path`.
- **#487** (respuestas truncadas por `finish_reason: length` en `local_explain_code`).

## 4. Riesgos

| Riesgo | Mitigación |
|---|---|
| Superficie nueva en el puerto del daemon, publicado en la tailnet | REQ-016 (secreto obligatorio, excepción de `PortToken` solo para tres rutas POST exactas, solo `Bearer`, sin `Origin`, comprobada por enumeración y variantes de ruta), REQ-017 (límites y saneado). Revisión de seguridad en el plan. |
| Un cliente que muere con el turno deja la cola parada | REQ-012 (caduca en 30 s sin latido) y REQ-013 (forzada). |
| El daemon reiniciado pierde los arrendamientos | Un `lease` desconocido responde `expired` → REQ-025 caso 3 (se vuelve a pedir antes del siguiente envío). |
| La cesión provoca más cambios de modelo (6–14 s cada uno) | Solo tras `TURN_YIELD_S` de espera ajena y de turno propio; apagable; `turn_yields` en el log para medirlo. |
| Latencia añadida en la Mac por operación | Un `acquire` (~ms por la tailnet) con turno libre; con daemon caído, como mucho el plazo de conexión (3 s) y luego 60 s de caché. |
| Hilos del daemon bloqueados por esperas largas | Espera larga acotada a `heartbeat_s`, manejadores en el threadpool y REQ-017 (máx. 16). |
| Un cliente que ignora `yield` | Tope del servidor de REQ-030: tras `heartbeat_s × 2 + HTTP_TIMEOUT`, caducado. |
| El límite 16/8 de REQ-017 no se ha medido | Por la medición, la Mac abrió 2 operaciones a la vez (2 subagentes); 8 por máquina deja margen ×4. Con 429 se espera (REQ-025 caso 2), no se salta la cola. |
| Choque con el código de #476/#477/#479 (cola saturada, `state`, progreso) | Se reutilizan sus piezas (`_queue_limit_s`, `_inflight_state`, `_call_status`); el plan fija las zonas. |
| La clave del backend del daemon no está en su entorno | `doctor` en la PC (REQ-027) y verificación en vivo. |

## 5. Evidencia de partida comprobada

- **La topología de la PC hace chocar los dos modelos de la medición:** con la config de llama-swap
  de la PC, `topology.snapshot().clashes(qwen36-35b-a3b, gemma4-26b-a4b)` da `True` (comprobado el
  2026-10-29, solo lectura). El turno, por tanto, sí ordena el caso medido.
- **Clave del backend en el entorno del daemon de la PC: sin confirmar.** En el entorno de usuario
  de Windows no está `LOCAL_DELEGATE_API_KEY`; puede venir del lanzador del daemon. Es el primer paso
  del lote 3 (REQ-016); si no está, la vía es el token del puerto.
- La medición del paso 1 es una sola ventana: vale como prueba estructural (tres colas, inanición);
  la cota de REQ-031 se contrasta en el lote 2 (simulación) y en el lote 5 (en vivo).

## 6. Recomendación de topología (acción del usuario, no código)

Hoy `tailscale serve` publica `:9292` (llama-swap) y `:9393` (daemon) en la tailnet. Mientras `:9292`
esté abierto, un cliente viejo o ajeno puede saltarse la cola. Recomendación, por orden:

1. **Ahora:** nada que cambiar; esperar a que la Mac tenga la versión con el turno remoto.
2. **Con la Mac actualizada y `remote_turn: "granted"` en su log:** restringir `:9292` en la ACL de
   la tailnet a los dispositivos que usan local-delegate (la Mac), para que nada ajeno lo use.
3. **Más adelante, si se mide tráfico que se salta la cola:** que el daemon publique el backend
   detrás de sí (ruta proxy que exige un arrendamiento vivo) y quitar `:9292` de `tailscale serve`
   (`tailscale serve --https=9292 off`). Eso es la opción C acotada y va en otra tarjeta.

## 7. Trazabilidad

| Requisito | Trabajo (plan) | Evidencia |
|---|---|---|
| REQ-001..004 | Lote 1 | `tests/test_waiting_backend.py`, `status.test.ts`, capturas del panel |
| REQ-005 | Lote 1 | `tests/test_read_timeout_cause.py` |
| REQ-030..032 (núcleo), REQ-013 | Lote 2 | `tests/test_turn_remote_core.py` |
| REQ-010..017 | Lote 3 | `tests/test_turn_api.py` |
| REQ-020..027, REQ-030 (cliente) | Lote 4 | `tests/test_remote_turn_client.py`, `tests/test_two_machines.py` |
| REQ-040..042 | Lotes 1–4 | suite existente intacta |
| REQ-050, REQ-027 | Lote 5 | docs + verificación en vivo PC+Mac |
