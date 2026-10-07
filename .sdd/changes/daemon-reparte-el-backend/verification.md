# Verification: Daemon: no se pelea por el modelo, aprovecha el cargado, avisa de la lentitud y deja la residencia configurable

## Environment

- Revision: `27b50c0bf8a2974845f6d360016d7204ba01a404` (rama `feat/daemon-reparte-el-backend`, que
  contiene `origin/main` = `4c7115b`; comprobado con `git merge-base --is-ancestor` el 2026-10-07).
- Relevant runtime and tool versions:
  - Python 3.11.15 (`.venv`), uv 0.10.12.
  - Entorno del repo (`.venv`, igual que `uv.lock`): `mcp` 2.2.0, `anyio` 4.15.1, `starlette` 1.3.1,
    `fastapi` 0.141.1, `uvicorn` 0.54.0.
  - Daemon instalado (`uv tool`, `local-delegate-mcp` v0.32.0): `mcp` **2.3.0**, `anyio` 4.15.1,
    `starlette` 1.7.0. El SDK del daemon no es el del lock; en lo que mira T0.6 (`func_metadata.py:164`,
    `starlette/concurrency.py:34`, `CapacityLimiter(40)`) las dos versiones dicen lo mismo.
  - llama-swap de prueba: `D:\Projects\llms\llama-swap-v255\llama-swap.exe`, `version: v255 (7761aa1),
    built at 2026-09-06T05:46:05Z`.

## Ola 0 — hallazgos de T0 y T1

Hecho el 2026-10-07 (UTC). T0.5 no es de esta tarea.

### T0.1 — Precondición

Se cumple. En `main` (= `origin/main` = `4c7115b`) están #231 (panel), #232 (coste) y el cierre #239.
Los `state.json`:

| Cambio | Estado | Gate `conformance` | Evento en `history` |
| --- | --- | --- | --- |
| `panel-cuentas-y-estados-honestos` | `closed` | `approved` | `approved` 2026-10-06T17:28:25.940Z |
| `coste-api-y-cuota` | `closed` | `approved` | `approved` 2026-10-06T19:58:57.602Z |

Los cinco gates de los dos cambios están `approved`. La rama ya existía; no se creó otra.

### T0.2 — Contratos, con `fichero:línea`

Ninguno cambió de firma ni de sentido: **no hay motivo para parar**.

| Símbolo | Dónde está | Nota |
| --- | --- | --- |
| `_inflight_espera_local(entry_id: int, motivo: str \| None) -> None` | `src/local_delegate/server.py:257-276` | Misma firma que da el plan (`review.md:719` la citaba en `:256`; se movió una línea). Con `None` borra `espera_local`; con un motivo lo escribe |
| Filtro de `/api/inflight` | `server.py:288-334` (`inflight_snapshot`); copia `espera_local` en `:322-325` | Lista blanca de campos en `:310-318`: `turno_en_uso` y `turno_posicion` (T10) tienen que añadirse ahí o no llegan al panel |
| Endpoint `/api/inflight` | `src/local_delegate/web/metrics.py:641-642` (`def inflight()`) | Síncrono: pide hilo al limitador de anyio (T0.6) |
| `estadoModelo` | `metrics.py:1850-1883` | |
| Fila 3 («en cola local») | `metrics.py:1863-1868` | Condición en `:1854`: todas las llamadas del modelo llevan `espera_local` no nulo. Vale para **cualquier** motivo: el texto sale de `PALABRAS_ESPERA[motivo]` o, si no está, del motivo tal cual (`:1865`) |
| `PALABRAS_ESPERA` | `metrics.py:1797` | Solo `plaza` hoy (`review.md:722` la daba en `:1647-1662`; la movieron #231/#232) |
| `renderInflight` | `metrics.py:2028-2067` | Hoy no pinta `espera_local` |
| `ChatResult` | `server.py:783` | |
| `_post_chat(model, payload) -> ChatResult` | `server.py:985`; llamado en `_llamar_modelo` (`:1128`), `:1134` y `:1140` | |
| `_con_respaldo` | `server.py:1147`; llamado en `_run_chat` `:1291` | |
| `_run_chat` | `server.py:1241-1301` | Plaza en `:1283-1300`; publica `espera_local: "plaza"` en `:1286` y la borra en `:1289`. `latency_ms` incluye la espera de plaza (`t0` en `:1283`) |
| `_ModeloVigente` | `server.py:1304`; llama a `_run_chat` en `:1327`; se crea en `:1725` y `:1942` | |
| `_log_event` | `server.py:491-…` (`ts` en `:527`, hora de **fin**) | Tres llamadas: `_chat` `:1465`, `_chat_chunked` `:1788`, `_chat_map_reduce` `:2120` |
| Bloque de `local_status` | `server.py:3338-3435` (decorador en `:3338`, `return` en `:3435`) | |
| `checks.CHECKS` | `src/local_delegate/checks.py:1499` | **22** (contado importando el módulo) |
| Frases de tamaño de `checks.py` | `checks.py:5` («los veintidós elementos»), `:15` («Veintidós checks son una tupla»), `:1492` («Veintidós elementos, en orden de grupo»), `:1536` («Corre los veintidós probes»), `:1550` («los otros veintiuno») | |
| `_NUMERO` | `tests/test_checks.py:1096-1112` (hasta 22); `_NUMERO_SIN_SUSTANTIVO` en `:1113`; test en `:1116-1136` | Un check 23 exige añadir `23: "veintitrés"` aquí |
| `_NUMERO_DE_CHECKS` | `tests/test_wiki.py:35-45` (hasta 22, femenino) | Ídem |
| App del daemon | `src/local_delegate/daemon.py:211-218` | MCP en `:211`, `/daemon/status` en `:217`, panel montado en `/` en `:218` (el plan decía `:211-216`) |

### T0.3 — Línea base de tests

`bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider`, salida volcada al
scratchpad. Última línea: **`1749 passed, 2 skipped, 1 warning in 69.92s (0:01:09)`**, código de
salida 0. Ningún fallo. El aviso es la `DeprecationWarning` de `anyio.abc.BlockingPortal` en
`starlette/testclient.py:53`.

### T0.4 — llama-swap de prueba

`D:\Projects\llms\llama-swap-v255\llama-swap.exe` existe (42 107 392 bytes) y `--version` responde
`version: v255 (7761aa1), built at 2026-09-06T05:46:05Z`.

### T0.5 — Plazos de los clientes MCP

Consultado el 2026-10-07 en la documentación oficial; las frases entre comillas son literales.
No se cambió ninguna configuración.

| Cliente | Plazo | Valor por defecto | Cómo se sube | Fuente |
| --- | --- | --- | --- | --- |
| Claude Code | Total por llamada (reloj de pared) | 28 h si `MCP_TOOL_TIMEOUT` no está puesta | `MCP_TOOL_TIMEOUT` (ms, global) o `timeout` (ms) en la entrada del servidor en `.mcp.json`, que gana a la variable | code.claude.com/docs/en/mcp |
| Claude Code | Inactividad | 5 min en HTTP, SSE y WebSocket; 30 min en stdio | `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` (ms; `0` lo desactiva). Un `timeout` por servidor ≥ 1000 hace de suelo | code.claude.com/docs/en/mcp |
| Claude Code | Arranque | el mayor de 60 s, el plazo de tool del servidor y `MCP_TIMEOUT` | `MCP_TIMEOUT` (ms) | code.claude.com/docs/en/mcp |
| Codex | Total por llamada | 60 s | `tool_timeout_sec` en `[mcp_servers.<id>]` de `config.toml` | learn.chatgpt.com/docs/config-file/config-reference (redirección 308 desde developers.openai.com/codex/config-reference) |
| Codex | Arranque | 10 s | `startup_timeout_sec`, o `startup_timeout_ms` como alias | ídem |

- **Progreso**: el plazo total por servidor «is a hard wall-clock limit per tool call, and progress
  notifications from the server don't extend it». El de inactividad, en cambio, sí cuenta el
  progreso como actividad: «A tool call to an MCP server that sends no response and no progress
  notification for the idle window aborts with an error».
- **Consecuencia para este cambio**: el daemon va por HTTP. En Claude Code, una espera de turno más
  la inferencia que pase **5 min sin respuesta ni notificación de progreso** se corta por
  inactividad, aunque el límite total sea de 28 h. En Codex se corta **todo lo que pase de 60 s**,
  y una operación de 13 trozos ya tarda minutos. Las dos esperas son menores que lo que puede durar
  una operación con turno, así que T16 documenta cómo subirlas: `tool_timeout_sec` en Codex y
  `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` o `timeout` por servidor en Claude Code. Otra opción sería que
  el daemon mande progreso mientras espera turno, pero eso no está en el alcance de esta spec.
- **No documentado**: qué ve el modelo en Codex cuando vence el plazo, y si cancela la petición en
  el servidor.

### T0.6 — Hilos de anyio

- **Las tools síncronas** van a un hilo con `anyio.to_thread.run_sync(functools.partial(fn, **kwargs))`
  sin `limiter` (`.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:164`), o sea
  con el **limitador por defecto** de anyio: `CapacityLimiter(40)`, uno por bucle de eventos
  (`anyio/_backends/_asyncio.py:3158-3163`). Igual en el SDK del daemon (`mcp` 2.3.0). Las 11 tools
  de `server.py` son `def` (ninguna `async def`), así que **cada llamada en curso ocupa un hilo de
  esos 40 mientras dura**, incluida la espera de plaza y la de turno.
- **Lo comparten**, porque MCP y panel van en la misma app y el mismo bucle (`daemon.py:211-218`):
  - los 11 endpoints `def` del panel (`metrics.py`: `events` `:452`, `stats` `:472`, `hooks` `:608`,
    `inflight` `:642`, `backend` `:670`, `backend_stats` `:729`, `status` `:763`, `system` `:811`,
    `favicon` `:851`, `vendor_chart_js` `:867`, `index` `:905`), que FastAPI corre con
    `run_in_threadpool` → `anyio.to_thread.run_sync(func)` sin limitador
    (`starlette/concurrency.py:34`). El panel sondea `/api/inflight` y `/api/backend` cada 2 s por
    pestaña abierta;
  - lo que Starlette mande a hilo por su cuenta con ese mismo `run_sync` (iteradores síncronos,
    `concurrency.py:57`).
  - En el código del paquete no hay ningún `to_thread`, `run_in_threadpool` ni `CapacityLimiter`
    propio (Grep sobre `src/local_delegate`, sin resultados).
- **Pico de operaciones simultáneas, últimos 60 días: 8.** Ventana 2026-08-08T10:31:52Z →
  2026-10-07T10:31:52Z; 291 eventos (del 2026-08-18 al 2026-10-06), 0 líneas ilegibles. Fue el
  2026-10-05T01:09:34Z: 5 `local_extract` en `gemma3-4b` y 3 `local_summarize` en `gemma4-26b-a4b`.
  Distribución de la simultaneidad al arrancar cada evento: 1 → 212, 2 → 47, 3 → 17, 4 → 7, 5 → 3,
  6 → 2, 7 → 2, 8 → 1. Latencia: mediana 28,9 s, p95 133,1 s, máximo 247,5 s.
  - **Método:** script en el scratchpad (`pico_simultaneas.py`, no va al repo) sobre los
    `usage-*.jsonl` de `config.LOG_DIR` (el directorio de datos de usuario por defecto; la variable
    `LOCAL_DELEGATE_LOG_DIR` no está fijada). Cada evento es el intervalo
    `[ts − latency_ms, ts]`: `ts` es la hora de **fin** (la escribe `_log_event` al terminar,
    `server.py:527`, resolución de 1 s) y `latency_ms` la mide `_run_chat` desde antes de pedir plaza
    (`server.py:1283`). Barrido: +1 en cada inicio, −1 en cada fin, y con empate el fin va primero
    (intervalos semiabiertos). Con 1 s de holgura en el fin, para cubrir el redondeo del `ts`, el pico
    sigue siendo 8.
  - **Límites:** el intervalo no cuenta la lectura del fichero de `path` antes de la primera llamada
    (subestima un poco) y solo hay logs de esta PC (la Mac escribe los suyos y aquí no están).
    Con un pico de 8 frente a 40 hilos, el margen es de 5×; T10 lo usa como umbral.

### T0.7 — Ventanas de medición abiertas (T5 y T17 las registran como excluidas)

- **P-4 (enfriamiento)**: abierta desde **2026-09-15T19:26:41Z**, con el tramo del fallo provocado
  excluido (`--excluir 2026-09-15T19:31:14,2026-09-15T19:35:14`). Se mide con
  `scripts/medir_enfriamiento.py` a los 14, 30 y 90 días. Confirmado en
  `.sdd/changes/delegacion-precisa-y-fiable/verification.md:1326` y `:1331`.
- **F1 (adopción del bloqueo de lectura)**: encendido el **2026-09-12**
  (`delegacion-precisa-y-fiable/verification.md:289-291`), medido con `scripts/medir_adopcion.py`
  por tramos de versión de hook: cambio a `a1485d36` el **2026-09-15T21:03:55Z** (`:1426-1430`);
  tramo desde **2026-09-23T12:56Z** (hooks del PR #220, confirmado en
  `.sdd/changes/resumen-por-secciones/verification.md:12`); tramo desde **2026-09-23T01:14Z**
  (hooks de T4), que solo consta en la memoria del repo, no en ningún `verification.md`.
- Los dos scripts existen en `scripts/`.

### T0.8 — Config real de llama-swap

- `sha256` de `D:\Projects\llms\llama-swap\config.yaml` a las 2026-10-07T10:32:11Z:
  `7F763F8538FD719FD3C8DD4FC3C1F6BFBF6C2543FEF3E67C2D8EBAD3A5FB68F0`.
- Copia: `D:\Projects\llms\llama-swap\config.yaml.pre-daemon-reparte-20261007-073211.bak` (el sello
  del nombre va en hora local, UTC−3), con el **mismo** `sha256`. Hecha con `Copy-Item`; el contenido
  no se imprimió.

### T1 — Enmienda de F3

- **Hora de la enmienda: 2026-10-07T10:32:59Z** (`mtime` del fichero tras la escritura).
- Punto añadido al final de «Cambios respecto al original» de
  `.sdd/changes/delegacion-precisa-y-fiable/spec.md` (líneas 245-265; fin de línea LF, conservado):
  la tabla de REQ-037 y el enlace a `../daemon-reparte-el-backend/spec.md`. El texto heredado de F3 no
  se tocó (`git diff --numstat`: 21 líneas añadidas, 0 quitadas).
- **Antes de escribir**, las líneas que cita la tabla decían lo que la tabla dice: REQ-004
  `:283-296`, REQ-017 `:351-352`, REQ-018 `:353-355`, D-3 `:528`, D-4 `:529-530`, combinación D-3/D-4
  `:532-533`, P-3 `:234-235`, VRAM `:505-507`, escenarios `:376`, `:384` y `:435`.
- **Referencias corregidas en la enmienda**: al insertar 21 líneas en la 245, todo lo posterior bajó 21.
  La tabla de la enmienda es la de REQ-037 con los números ya desplazados (REQ-004 `:304-317`,
  REQ-017 `:372-373`, REQ-018 `:374-376`, D-3 `:549`, D-4 `:550-551`, combinación `:553-554`, VRAM
  `:526-528`, escenarios `:397`, `:405` y `:456`); P-3 `:234-235` queda igual porque va antes del punto.
  La propia enmienda lo dice. Comprobado línea a línea contra el fichero ya escrito.
- **`sha256` de la spec de F3 ya escrita**:
  `af3840a03619de288721247569253968e0a362c88c019c74700c1ec56045ed60`.
- Sin transiciones ni aprobaciones del harness. Los eventos `gate: spec, status: approved` de F3 siguen
  siendo los de 2026-09-12T01:52:07.375Z y 2026-09-15T14:27:04.884Z, los dos anteriores a la enmienda:
  el control de T1 (lo ejecuta T17.2) hoy **no pasa**, como debe. La reaprobación la pide la sesión
  principal al usuario (T1.4).

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | | | |

## Quality checks

- [ ] Project-native tests pass.
- [ ] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes.
- [ ] No unrelated changes are present.

## Deviations and residual risk

- Record skipped checks, known limitations, and why the evidence is still sufficient or not.
