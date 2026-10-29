# Plan — Concurrencia y cola de delegaciones de la PC y la Mac en un solo turno visible

Spec: `spec.md` (versión revisada tras `spec-review.md`). Base: `main` en 0.45.0 (`f1d5e22`).
Cinco lotes. El 1 es una entrega previa independiente (puede salir en su propia versión); los
lotes 2–4 forman la entrega del turno remoto; el 5 cierra con docs y la verificación en vivo. Cada
lote va en su rama y su PR, con worktree `D:/Projects/ld-wt-conc-<n>`.

## Reglas comunes a todos los lotes

- `PYTHONPATH=src` en el worktree y comprobar que `local_delegate.__file__` apunta a él; Python de
  `D:/Projects/local-delegate/.venv/Scripts/python.exe`.
- Comandos pesados (pytest, ruff de todo el repo) con `bash ~/.claude/scripts/pesado.sh …`, de uno
  en uno; pytest local con `-n 2` como mucho. Primero los tests del área, la suite completa al final.
- Nada que ejecute el servidor fuera de pytest sin `LOCAL_DELEGATE_LOG` temporal; toda prueba en
  vivo dentro de `local-delegate test-window start/stop`.
- **Sin regresiones:** inventario previo de lo que se toca; los tests existentes **no se
  modifican** (si alguno lo pide, se para y se reabre la spec). Cada test nuevo con control
  positivo: revertir la pieza y anotar **qué assert** cae, en `verification.md` del cambio.
- Código y claves en inglés; textos al usuario en es+en (`resources/i18n/{es,en}/*.json`, mod
  `mod/i18n/{es,en}.json`). Conservar LF/CRLF de cada fichero (`git ls-files --eol`).
- Commits firmados, sin coautoría de Claude. CHANGELOG (Unreleased), README si cambia algo visible y
  `docs/wiki/` en el mismo PR que el comportamiento.
- CI del PR en verde, `gh pr checks` completo (code scanning, Socket, GitGuardian incluidos).

## Lote 1 — `waiting_backend`, su progreso y el `read_timeout` que nombra al culpable

REQ-001..005, REQ-040, REQ-042. Tamaño: **M** (~200 líneas de producto, ~350 de tests, más panel y
mod). Rama `feat/waiting-backend-state`. Independiente de los demás.

1. `src/local_delegate/concurrency.py`
   - Nuevo `send_watch(model, real, on_wait)` (gestor de contexto por envío), **aparte** de la
     muestra única del log (`claim_backend_sample` y `backend_phase` no cambian de contrato): arma
     un temporizador de `BACKEND_SAMPLE_DELAY_S`; si dispara, consulta `/running` y, si el pedido no
     está `ready` (REQ-001: nombre real o enviado; sin poder decidir, no marca), llama
     `on_wait(models)` y re-muestrea cada `BACKEND_WAIT_RESAMPLE_S` hasta `ready` o fin.
   - **Sin carreras:** un `threading.Event` de parada y un número de generación por envío; al salir
     del contexto se marca la parada **antes** de llamar `on_wait(None)`, y toda escritura del hilo
     comprueba la generación bajo el mismo cerrojo, así nada se escribe después de la limpieza
     aunque una consulta tarde más que el `join`.
2. `src/local_delegate/server.py`
   - `_inflight_backend_wait(entry_id, send_no, models | None)`: escribe o borra **solo** la
     subclave de ese envío en `backend_wait` (patrón de `_inflight_local_wait`, l.524).
     `_call_status(backend_wait=…)` con la unión.
   - `_inflight_state` (l.568) e `INFLIGHT_STATES` (l.565): `waiting_backend`.
     `inflight_snapshot` (l.626) publica la unión.
   - `_send` (l.2630): envuelve `_post_chat` en `concurrency.send_watch(...)` en los dos caminos
     (con y sin token), con un contador de envío por entrada. `_slot` (l.2616-2627): al soltar,
     limpieza de seguridad de la subclave del envío.
   - `_post_chat`, rama `ReadTimeout` (l.1893): texto según `probe` (`_LoadProbe`, l.1631; se le
     añade guardar la foto `{modelo: estado}` que ya consulta), luego `loaded_models()`, luego la
     traza; `read_timeout_cause` en `ChatResult` → evento.
3. `src/local_delegate/cancellation.py` `progress_message` (l.154): rama `backend_wait` tras
   `turn`/`slot`.
4. i18n: `mcp.progress.backend_wait`, `mcp.progress.backend_wait_unknown`,
   `mcp.error.read_timeout_swap`, `mcp.error.read_timeout_busy`; panel y mod.
5. Panel (`web/metrics.py`, «En curso», ~l.2976-2997) y mod (`mod/status.js` l.150-190: rango
   `running 0, retrying 1, waiting_backend 2, queued 3`, etiqueta y modelo **pedido**).
6. Docs `Architecture.md`, `Savings-and-metrics.md`; CHANGELOG.

Tests nuevos:

- `tests/test_waiting_backend.py` (patrón de `tests/test_concurrency_log.py`, retraso parcheado):
  (a) pedido no `ready` → `state: "waiting_backend"` y `backend_wait`; (b) re-muestreo a `ready` →
  `running`; (c) fin del envío → sin clave; (d) envío rápido → 0 consultas a `/running`;
  (e) precedencia con `queued`/`retrying`; (f) **dos envíos a la vez** de la misma entrada: el que
  acaba antes no borra la marca del otro; (g) **trozo 2+** de una operación también se marca;
  (h) **carrera**: consulta de `/running` bloqueada más que el `join` → tras la limpieza no queda
  `backend_wait`; (i) sin topología y nombre no reconocible → no marca; (j) `progress_message`.
- `tests/test_read_timeout_cause.py`: los tres textos con `MockTransport` + `ReadTimeout`, la sonda
  como primera fuente, `read_timeout_cause` en el evento y el `host` de `inflight_seen` en el texto.
- `mod/status.test.ts`: rango, etiqueta y estado desconocido como hoy.
- Control positivo: sin la rama de `_inflight_state` cae (a) (`'running' == 'waiting_backend'`); con
  borrado de toda la clave cae (f); sin la guarda de generación cae (h); con muestra inmediata cae
  (d) y `test_affinity`.

Verificación: ruff, tests del área, suite completa `-n 2`, tests del mod como en CI
(`.github/workflows/ci.yml`, paso F2-mod-core), capturas del panel en claro y oscuro con una
entrada `waiting_backend` simulada.

## Lote 2 — Núcleo del turno: operaciones sin hilo, vuelo remoto y cesión

REQ-011 (API de `Turn`), REQ-013, REQ-030 (decisión), REQ-031, REQ-032. Tamaño: **M** (~200
líneas de producto, ~400 de tests). Rama `feat/turn-external-ops`. En paralelo con el lote 1.

**Paso 0 del lote (inventario):** listar los tests de `tests/test_turn.py`,
`tests/test_turn_daemon.py`, `tests/test_affinity*.py` y `tests/test_concurrency_log.py` que dependan
de que `release_slot`/`abandon` **no** reevalúen o de la forma de `Active` (construcción posicional,
`==`, `repr`), y pasarlos con el cambio antes de seguir. Si alguno cae, se para y se reabre la spec.

1. `src/local_delegate/turn.py`
   - `Active.granted_at: float = field(default=0.0, compare=False)` al final; `do_grant` lo pone
     con `now` (`evaluate` ya recibe `now`). `reduce`/`replace` lo conservan.
   - Pura: `must_yield(state, op_id, now, yield_s, clashes) -> bool` (REQ-030 a/b/c, con «la cabeza
     no es concedible y choca con esta operación»).
   - `Turn`: `enqueue`, `poll`, `expire`, `remote_flight`, `wait_change(timeout)` (un contador de
     versión que `_apply` y toda mutación incrementan, bajo `self._cond`), `must_yield(op_id)` con
     el reloj y `TURN_YIELD_S`. `release_slot` y `abandon` llaman a `_apply`.
     `_no_progress_since` devuelve `None` también si hay vuelo remoto.
2. `src/local_delegate/config.py`: `TURN_YIELD_S` (`LOCAL_DELEGATE_TURN_YIELD_S`, 120).
3. `src/local_delegate/server.py` `_OperationTurn.ensure` (l.2400-2415): antes de **las dos** salidas
   tempranas (afinidad, l.2403; mismo modelo, l.2407), si `_turn.must_yield(self.op_id)` y la
   operación no tiene envío propio en vuelo → `self.affinity = None`, `self._reset()`,
   `self.yields += 1` y pedir de nuevo. `log_fields`: `turn_yields` si > 0.

Tests nuevos: `tests/test_turn_remote_core.py`

- `enqueue`/`poll` frente a `request`: mismas concesiones (casos propios del fichero nuevo; no se
  toca `tests/test_turn.py`). `poll` entrega la concesión una vez; `expire` limpia cola, `actives`,
  `_granted` y vuelo; una espera sin hilo se concede **en el mismo** `release_slot` del activo.
- `wait_change` despierta con cada cambio y respeta el plazo.
- `remote_flight` impide la forzada (reloj inyectado); `expire` la vuelve a permitir.
- `must_yield`: cada condición falsa por separado → `False`; dos activas que chocan con la cabeza →
  ceden las dos, cada una al cumplir su propia condición (c).
- **Simulación de inanición (REQ-031)**, reloj falso, `evaluate` + `must_yield`: «Mac» con demanda
  continua de X (operaciones nuevas cada pocos segundos), «PC» pide Y: Y obtiene turno dentro de
  la cota; las X nuevas no la adelantan; con `TURN_YIELD_S=0`, espera a que acaben las X activas.
- En `server`: operación local de muchos trozos con otra esperando → `turn_yields: 1`; con afinidad
  activa también cede; con `TURN_YIELD_S=0`, ninguna cesión.
- Control positivo: sin (c) cae «cede nada más recibir el turno»; sin la reevaluación en
  `release_slot` cae «se concede en el mismo release»; sin el vuelo remoto en `_no_progress_since`
  cae el de la forzada; sin la comprobación en la salida de afinidad cae el test con afinidad.

## Lote 3 — Endpoint de turno en el daemon

REQ-010..017, REQ-024 (servidor), REQ-025 (respuestas), REQ-030 (lado servidor). Tamaño: **L**
(~350 líneas de producto, ~500 de tests). Rama `feat/turn-lease-endpoint`. Depende del lote 2.

**Paso 0 del lote:** confirmar (sin mostrar valores) que el daemon de la PC tiene la clave del
backend en su entorno y que coincide con la de la Mac (lo comprueban la sesión principal en la PC y
el usuario en la Mac comparando un hash corto). Si no, se activa la vía del token del puerto
(REQ-016) y la doc lo dice.

1. `src/local_delegate/turn_leases.py` (nuevo, sin FastAPI): `Lease` (id
   `secrets.token_urlsafe(32)`, `host`, `op`, `model`, `expires_at`, `in_backend`, `yield_since`),
   `acquire`, `heartbeat`, `release`, `reap(now)`; límites de REQ-017; `daemon_id`: **nuevo**,
   generado una vez al arrancar el daemon (constante de módulo, `secrets.token_urlsafe(16)`), escrito
   en `daemon.json` (`daemon._daemon_payload`, `daemon.py:58-67`) y en `/api/daemon`, y devuelto en
   cada respuesta de `/api/turn/*`; `status` por arrendamiento: `granted`/`queued` de `Turn.poll`, `yield` si
   `Turn.must_yield`, y caducidad forzada si ignora `yield` más allá del tope de REQ-030. Escribe su
   entrada de inflight (clave `remote:<host>/<op>`, `in_backend: false` al conceder, en
   `_inflight_live`) y llama a `_note_queue_progress()` en concesión, liberación, caducidad y
   cambio de `in_backend`. Espera larga con `Turn.wait_change(min(restante, heartbeat_s))`.
   Temporizador de limpieza que vive mientras haya arrendamientos.
2. `src/local_delegate/web/turn_api.py` (nuevo, `APIRouter` montado en `metrics.app`): tres rutas
   `POST` **síncronas** (`def`, threadpool), modelos pydantic `extra="forbid"`, tope de cuerpo 4 KB,
   y dependencia `_require_turn_client`: solo `Bearer` (rechaza `Basic` y cookie), `Content-Type:
   application/json`, sin `Origin`, `hmac.compare_digest` contra el token del puerto y la clave del
   backend; 403 `turn_needs_secret` sin ninguno. `LOCAL_DELEGATE_TURN_SERVER=off` → 404.
3. `src/local_delegate/web/auth.py` `PortToken.__call__`: exención por **igualdad exacta** de
   `(scope["method"], scope["path"])` con `TURN_ROUTES` (constante compartida con `turn_api.py`).
4. `src/local_delegate/server.py`: ayudantes de inflight con clave dada (reutilizan
   `_inflight_mutate` y `_inflight_live`).
5. `src/local_delegate/config.py`: `TURN_LEASE_S`, `TURN_MAX_LEASES`, `TURN_SERVER`.

Tests nuevos: `tests/test_turn_api.py` con `TestClient` sobre `daemon.build_app` (patrón de
`tests/test_daemon.py`, cabecera `Host` de loopback, entorno aislado con los helpers `_env*`):

- Autenticación: sin secretos → 403; token del puerto → 200; clave del backend → 200; errónea →
  401; `Basic` válido → 401; cookie de sesión válida → 401; con `Origin` → 403; sin JSON → 415/400.
  Con `WEB_TOKEN` puesto, la clave del backend abre las tres rutas y **no** `/api/inflight` ni
  `/mcp`.
- Enumeración: rutas de la app que casan con `/api/turn/` = exactamente las tres, todas con la
  dependencia. Variantes `/api/turn/x`, `/api/turn/acquire/`, `/api/turn/../inflight`,
  `/api/turn/%2e%2e/inflight`, `//api/turn/acquire`, `GET /api/turn/acquire` → piden el token del
  puerto (401 sin él).
- Ciclo: libre → `granted`; con un local activo que choca → `queued` con posición, entrada en
  `/api/inflight` con `host`, `host_via: "lease"`, `state: "queued"`; al soltar el local, la
  respuesta larga en curso devuelve `granted` sin esperar al plazo; tras conceder, `state:
  "running"` (`in_backend: false`); `release` → fuera.
- Caducidad (reloj inyectado): sin latido 30 s → fuera de cola, `actives` e inflight; latido →
  `expired`; `lease` desconocido → `expired`; una espera local detrás de una remota **no** sale
  por cola saturada mientras los eventos remotos mueven la cola.
- `yield`: activa remota con cabeza que choca y espera ≥ `TURN_YIELD_S` → `yield`; si no suelta en
  el tope → caducada y la cabeza concedida. Si ese cliente vuelve a pedir, queda **al final** de la cola (no
  recupera su sitio).
- `in_backend: true` impide la forzada local; al caducar, no.
- `no_turn` sin topología o con modelo desconocido; 429 al pasar 16/8; 400 con `host` vacío; 413
  con cuerpo grande; `TURN_SERVER=off` → 404.
- `daemon_id` estable entre peticiones y distinto en otro arranque (registro nuevo).
- Carga: 16 esperas largas abiertas a la vez y `/api/inflight` responde en < 1 s (threadpool de
  anyio, 40 hilos; si no, se acorta el tope de la espera larga).
- Ningún evento de uso escrito por el daemon (REQ-015) y la credencial no aparece en respuestas ni
  en el log de errores.
- Control positivo: exención por prefijo en vez de exacta → caen las variantes; aceptar `Basic` →
  cae su test; quitar la dependencia → cae la enumeración; sin `_note_queue_progress` → cae el de
  saturación; sin el tope de `yield` → cae el suyo.

Revisión de seguridad antes del PR: `personal-security-check` + revisión adversarial de la
exención de `PortToken`, la dependencia y el saneado.

## Lote 4 — Cliente del turno remoto e integración en las operaciones

REQ-020..027, REQ-030 (cliente), REQ-032. Tamaño: **L** (~350 líneas de producto, ~550 de tests).
Rama `feat/remote-turn-client`. Depende del 3 (y del 1 para `waiting_backend` en el latido).

1. `src/local_delegate/remote_turn.py` (nuevo): descubrimiento (REQ-021) con la **guarda «nunca a
   sí mismo»** (loopback + `WEB_PORT` propio, o el `daemon_id` que devuelve `acquire` igual al del `daemon.json` local →
   `remote_turn: "self"`); cliente `httpx2` propio con los plazos de REQ-025; credencial (clave del
   backend; `LOCAL_DELEGATE_REMOTE_WEB_TOKEN`/Llavero si existe); caché de «inutilizable» por motivo;
   `RemoteLease`: `acquire(on_wait, should_stop)` (bucle de esperas largas; 429 = seguir esperando),
   hilo de latido `daemon=True` que se para en `release`, `yield_requested`, `lost` (`expired`),
   `release()` idempotente.
2. `src/local_delegate/config.py`: `TURN_URL` (`auto` | `off` | URL).
3. `src/local_delegate/server.py`:
   - `_OperationTurn.ensure`/`ensure_loaded`: con `NO_TURN_REMOTE_BACKEND`, o con `TURN_URL`
     explícita y sin topología local, `RemoteLease` en lugar del turno local, dentro de
     `_waiting_for` (misma contabilidad, `phase("turn")`, saturada con `stalled_s`, cancelación).
     Antes de cada envío: si `yield_requested` → ceder (lote 2); si `lost` → volver a pedir
     (REQ-025 caso 3).
   - `release_slot`: suelta también el arrendamiento.
   - `_send`: cuenta `in_backend` para el latido; `waiting_backend` del lote 1.
   - `log_fields`: `remote_turn`; `turn_wait_ms` y `phases.turn` con la espera remota.
   - `local_status` (l.6959): línea de REQ-027.
4. `src/local_delegate/doctor.py`/`checks.py`: REQ-027.
5. i18n de los textos nuevos.

Tests nuevos:

- `tests/test_remote_turn_client.py`: el daemon del lote 3 en proceso (`TestClient` como transporte
  `httpx2` del cliente): `granted`; `queued` con progreso y `local_wait: "turn"` en el inflight del
  cliente; cancelación que suelta; `expired` a mitad → la siguiente llamada vuelve a pedir; 429 →
  espera y luego `granted`; `yield` → cede antes del siguiente trozo; cada motivo del caso 1 de
  REQ-025 (404, 401, 403, conexión rechazada, JSON roto, `v: 2`) con su `remote_turn` y la caché;
  guarda «a sí mismo» (por puerto y por `daemon_id`). Uso solo local (`BASE_URL` loopback, sin
  `TURN_URL`): **cero** peticiones al transporte (REQ-040).
- `tests/test_two_machines.py` — **dos «máquinas» en una con dos procesos**:
  - Backend falso en Python (`tests/fake_switching_backend.py`, servidor HTTP en un hilo del test,
    puerto libre): dos modelos que chocan, `/v1/chat/completions` con retardo por modelo, un cambio
    de modelo espera a que acaben las peticiones del cargado (como llama-swap) y `/running`; apunta
    el orden de lo que sirvió.
  - **Arranque de cada hijo:** `sys.executable` (el del `.venv`) **sin `-I`**, con un lanzador que
    hace `sys.path.insert(0, "<worktree>/src")` y **comprueba** que `local_delegate.__file__` está
    bajo el worktree (si no, sale con código 3 y el test falla con ese mensaje). Entorno construido
    **desde cero** (no copia de `os.environ`): solo `SystemRoot`/`PATH`/`TEMP`, con `USERPROFILE`, `HOME`, `APPDATA` y `LOCALAPPDATA` apuntando a
    `tmp_path`, y las
    `LOCAL_DELEGATE_*` del test (`LOG_DIR` y `LOG` temporales, `MACHINE_NAME`, `API_KEY` de prueba,
    `WEB_TOKEN` vacío, topología del backend falso), para no heredar el token, el Llavero ni el log
    real. Lanzado con `subprocess.Popen` (pasa por el `GuardedPopen` de `tests/conftest.py:406`).
  - «PC»: `daemon.serve(host, puerto_libre)`, `MACHINE_NAME=pc-test`, `BASE_URL` al backend falso.
  - «Mac»: script que importa `local_delegate.server` con `MACHINE_NAME=mac-test`, el mismo
    `BASE_URL`, `TURN_URL` al daemon (el caso túnel: loopback que cuenta como remoto; la guarda
    «a sí mismo» no salta porque el puerto no es su `WEB_PORT` y el `daemon_id` difiere), sin
    topología, su propio `LOG_DIR`, `TURN_YIELD_S=2`, y lanza dos operaciones de muchos trozos del
    modelo X.
  - El test pide al daemon por `/mcp` una operación del modelo Y.
  - Comprueba: `/api/inflight` del daemon muestra a la vez la local y las de `mac-test` con `host` y
    `state`; la Y termina sin `read_timeout` y dentro de la cota de REQ-031 con los valores del
    test; el orden servido por el backend no intercala X e Y más que lo que permiten las cesiones;
    los logs de las dos «máquinas» tienen `remote_turn`/`phases.turn` y ningún evento duplicado
    (definición: ningún par de eventos con la misma `tool`, `concurrency.requested_model` y
    `phases.backend.start` en los dos logs).
  - Variante: se mata el daemon a mitad → la «Mac» acaba sin turno con `remote_turn:
    "unreachable"`.
  - Ficheros reales intactos: `~/.claude.json` y el `inflight.json`/log reales con el mismo hash antes
    y después del test.
  - Higiene: cada hijo en `try/finally` con `terminate()` → `wait(10)` → `kill()` y comprobación por
    PID (`server._pid_alive`) de que no queda vivo; tope de 120 s por test; el hilo del backend falso
    se para y se une en el `finally`.
- Control positivo: sin `RemoteLease` en `ensure` cae el de dos máquinas (no hay entradas
  `mac-test` en `/api/inflight`); sin latido cae la caducidad; sin la guarda «a sí mismo» cae su
  test; con el `sys.path` del lanzador quitado, el hijo sale con código 3.

## Lote 5 — Documentación, `doctor` y verificación en vivo PC+Mac

REQ-027 (resto), REQ-050. Tamaño: **S** (~150 líneas de docs) + una sesión de medición.

1. `docs/wiki/Remote-backend.md`, `Architecture.md`, `Configuration.md` (`TURN_URL`,
   `TURN_LEASE_S`, `TURN_YIELD_S`, `TURN_SERVER`, `REMOTE_WEB_TOKEN`), `Savings-and-metrics.md`;
   README; CHANGELOG. La recomendación de topología (`spec.md` §6).

**Verificación en vivo** (criterio de la tarjeta). La PC con la versión publicada (la sesión
principal instala y reinicia el daemon; el usuario hace `/mcp`); la Mac la actualiza el usuario.

1. `test-window start` en las dos; `/api/inflight` vacío antes de empezar.
2. Escenario de `measurement-step1.md`: dos `local_explain_code` de la Mac (qwen, ficheros de
   20–40 KB) y, en cuanto salen, un `local_summarize` de 15 K en la PC (gemma). Variante: además una
   delegación desde Claude Desktop de la Mac (su daemon).
3. Criterios fijados antes de medir, con la referencia del paso 1 entre paréntesis:
   - el panel de la PC muestra las tres operaciones a la vez, las de la Mac con `host` y `state`
     (paso 1: solo la de la PC);
   - la operación de la PC termina sin `read_timeout` (paso 1: `read_timeout` a los 180 s) y su
     espera está en `phases.turn`, con `phases.backend` < 60 s (paso 1: backend 180 012 ms);
   - ninguna llamada muere por el corte de 300 s;
   - los logs de las dos máquinas llevan `remote_turn: "granted"` y ningún evento duplicado (misma
     definición que el test);
   - `turn_yields` ≤ 2 por operación y operaciones con `model_swap: true` ≤ 2 (paso 1: 3 de 3).
4. Degradación: parar el daemon de la PC un momento (sesión principal) → la Mac sigue con
   `remote_turn: "unreachable"`; al volver, la siguiente operación sale `granted`.
5. `test-window stop` en las dos; resultado en `verification.md` con la tabla antes/después.

Si un criterio no se cumple en 2 iteraciones: tocar `TURN_YIELD_S`/`TURN_LEASE_S`, documentar el
límite y abrir tarjeta.

## Orden, dependencias y zonas de choque

| Lote | Depende de | Zonas compartidas |
|---|---|---|
| 1 | — | `server.py` (`_inflight_state`, `_send`, `_slot`, `_post_chat`, `_LoadProbe`), `concurrency.py`, `cancellation.py`, panel, mod |
| 2 | — (paralelo con 1) | `turn.py`; `server.py` `_OperationTurn.ensure`/`log_fields` |
| 3 | 2 | `web/auth.py`, `web/metrics.py` (montaje), `server.py` (ayudantes de inflight) |
| 4 | 3 (y 1) | `server.py` `_OperationTurn`, `_send`, `local_status` |
| 5 | 4 publicado | docs |

1 y 2 en paralelo (zonas distintas de `server.py`); 3 y 4 en serie. Mezcla en serie por la sesión
principal.

## Trazabilidad requisito → test → control positivo

| REQ | Lote | Test | Control positivo (assert que cae) |
|---|---|---|---|
| 001, 002 | 1 | `test_waiting_backend.py` (a)–(i) | `'running' == 'waiting_backend'`; marca borrada por el otro envío; clave tras la limpieza |
| 003 | 1 | (j) | texto «procesando» en vez de «esperando…» |
| 004 | 1 | `status.test.ts` + capturas | rango/etiqueta |
| 005 | 1 | `test_read_timeout_cause.py` | texto viejo con modelo cargado distinto |
| 011, 013 | 2 | `test_turn_remote_core.py` | concesión no inmediata tras `release_slot`; forzada con vuelo remoto |
| 030–032 | 2, 3, 4 | simulación + `ensure` + `yield` del endpoint + cliente | cesión sin (c); sin cesión con afinidad; sin tope de `yield` |
| 010, 012, 014–017, 024 | 3 | `test_turn_api.py` | variantes de ruta, `Basic`, enumeración, saturación |
| 020–027 | 4 | `test_remote_turn_client.py`, `test_two_machines.py` | sin `RemoteLease`; guarda «a sí mismo»; caducidad |
| 040–042 | 1–4 | suite existente intacta + «cero peticiones» en local | — |
| 050 | 5 | revisión de docs + verificación en vivo | — |

## Rollback

- Lote 1: revertir el PR; los campos son aditivos y un panel/mod viejo trata el estado nuevo como
  `running`.
- Cesión: `LOCAL_DELEGATE_TURN_YIELD_S=0`, sin publicar nada.
- Turno remoto: en la Mac `LOCAL_DELEGATE_TURN_URL=off`; en la PC `LOCAL_DELEGATE_TURN_SERVER=off`
  (404 → la Mac sigue como hoy). Ninguno exige publicar. Revertir los PR 3 y 4 deja todo como hoy.

## Seguridad

- Endpoint nuevo en un puerto publicado en la tailnet: secreto obligatorio, exención de
  `PortToken` por igualdad exacta de método y ruta, solo `Bearer`, sin `Origin`, JSON, límites de
  tamaño y número, saneado, ids aleatorios de 32 bytes, sin credenciales en respuestas ni logs,
  CodeQL limpio, interruptor de apagado.
- Sin dependencias nuevas (FastAPI, pydantic y `httpx2` ya están); si alguna hiciera falta, Socket
  antes.
