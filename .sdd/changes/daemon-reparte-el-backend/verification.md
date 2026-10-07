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

## Ola 1 — integración I1 (2026-10-07)

Evidencias de las tres tareas (no se reescriben aquí, solo se enlazan):
[T2](evidencias/T2.md) (llama-swap v255 de prueba), [T3](evidencias/T3.md) (control de lentitud) y
[T4](evidencias/T4.md) (corpus, puntuadores, trampas, reglas, hoja y veredicto). La imagen de la hoja de
prueba es [T4-hoja-sintetica.png](evidencias/T4-hoja-sintetica.png).

### Cifras que consumen otras tareas

- **T2, TTL:** el modelo se descarga entre 3,03 y 3,10 s después del fin de una petición de 3 s con `ttl: 2`
  (entre `ttl` y `ttl` + ~1 s): REQ-013 no se reescribe. Hora en `/api/metrics/activity`: campo
  `timestamp` (no `ts_created`), fin de la petición, truncado al segundo.
- **T2, carrera:** p99 de la ventana decisión-llegada de 1,0 ms con 1 cliente y 3,1 ms con 8; con 1 s de
  tope de las consultas quedan en ~1,003 s, muy por debajo de 5 s: **el margen de 5 s no se sube**.
- **T2, recarga:** `/api/events` se cierra en una recarga válida (la vigía de REQ-039 debe reabrir la
  conexión) y una recarga corta las peticiones en curso aunque el modelo no cambie; la foto `inflight`
  llega en 0,016 a 0,031 s; con alias, la actividad lleva el id real (T15 no necesita el caso «Alias»).
- **T3, lentitud:** 2,13 % de los eventos de la PC marcados como lentos (5 de 235 con referencia; tope 5 %);
  el control positivo marca las tres filas (570, 571 y 573). Mediana normalizada por tramos
  `<2k` 0,967 / `2k–10k` 1,004 / `>10k` 0,949, razón `>10k` / `<2k` = 0,98 (> 0,75): **una sola
  referencia, sin tramos, para el daemon.**
- **T4, corpus:** `benchmarks/afinidad-2026-10/reglas.json` escrito (el usuario aún debe confirmarlo, ver
  «Pendiente antes de T5»); corrida de prueba de
  73 casos (30 `commit_msg` reales, 9 trampa, 28 mecánicos nuevos, 5 de regresión, 1 de techo). El corpus
  real **no está escrito** en el repo (parada por un dato privado dentro de un diff candidato).

### Pasos de la integración

1. **Marcador `llamaswap_real`** registrado en `[tool.pytest.ini_options]` de `pyproject.toml` (clave
   `markers`, descripción en español; el fichero conserva su fin de línea CRLF). El
   `PytestUnknownMarkWarning` de T2 ya no sale: el único aviso que queda de la suite es el
   `DeprecationWarning` de `starlette.testclient` (anyio), anterior a esta ola.
2. **Test de T3 corregido (tocado por la integración).** `test_por_tramos_un_evento_de_12k_a_18_tok_s_no_es_lento`
   (antes `..._a_25_tok_s_...`, con `umbral=0.7`) usa ahora el **umbral por defecto (0,5)** y un evento
   largo a **18 tok/s**; las medianas siguen siendo 40 (20 cortos) y 26 (12 largos). Por tramos: 18/26 =
   0,69, no es lento; con una sola referencia: 18/40 = 0,45, es lento. Pasa (36 tests del fichero).
   **Mutante «una sola referencia»** (la clave de la ventana ignora el tramo aunque `por_tramos=True`):
   el test falla en `assert not lento` (`tests/test_medir_lentitud.py:140`, `assert not True`); también
   falla `test_por_tramos_cada_tramo_pide_su_propio_minimo`. Mutante revertido (el script quedó byte a byte
   igual que el original) y los 36 tests vuelven a pasar. Nota: `evidencias/T3.md` sigue describiendo el
   umbral 0,7 («Dos guiones del plan no mutaban y se cambiaron»); **vale esta corrección**, la evidencia
   no se reescribe.
3. **Suite completa** (`pesado.sh uv run pytest -q -p no:cacheprovider`), última línea literal:
   `1865 passed, 7 skipped, 1 warning in 131.13s (0:02:11)`. Línea base de la ola 0: `1749 passed, 2
   skipped`. Diferencia: **+116 pasan y +5 saltados**. Los nuevos son los de T2 (13), T3 (36), T4
   (`test_huella.py` 9 y los añadidos a `test_analisis_benchmark.py`, `test_hoja_pares.py` y
   `test_corpus.py`). Saltados: los 2 de la base (`chmod` en Windows en `test_checks.py:465` y el de solo
   CI en `test_dashboard_ui.py:596`) más 5 de `tests/test_corpus.py` (`:783`, `:811`, `:827`, `:857`,
   `:880`), esperables porque el corpus real aún no está construido.
   **Playwright:** los tests de `test_dashboard_ui.py` corren dentro de la suite completa (el navegador
   está instalado aquí); además `pesado.sh uv run --group ui pytest -q -p no:cacheprovider -rs
   tests/test_dashboard_ui.py` da `15 passed, 1 skipped in 7.57s` (el repo no tiene un marcador `ui`; el
   grupo `ui` es el de dependencias).
4. **Ruff:** `uv run ruff check .` → `All checks passed!`; `uv run ruff format --check .` → `160 files
   already formatted`.
5. **Config real de llama-swap (comprobación de cierre de ola):** `sha256` de `config.yaml` =
   `7F763F8538FD719FD3C8DD4FC3C1F6BFBF6C2543FEF3E67C2D8EBAD3A5FB68F0`, **igual** que el de T0. No se
   imprimió su contenido ni se tocó.
6. **Datos privados:** revisados `git diff`, los ficheros nuevos (`??`) y `evidencias/*.md`. Sin IPs que no
   sean `127.0.0.1` (la `203.0.113.7` del constructor del corpus es una IP de documentación, RFC 5737),
   sin ids de sesión reales (los de `test_corpus.py` y `construir_corpus.py` son datos falsos o el patrón
   que se filtra), sin PIDs con contexto personal. **Encontrado y quitado (tocado por la integración):**
   `evidencias/T4.md` citaba tres veces la ruta de perfil de Windows con el nombre de usuario real; se
   sustituyó por `<usuario>` con la edición mínima (la lógica de la parada no cambia). La imagen de la hoja
   sintética solo enseña mensajes de commit sintéticos y uno público del repo: nada privado.

### Pendiente antes de T5

Cerrado el 2026-10-07, salvo el último punto:

- **Decisiones del usuario**, en respuesta a la pregunta explícita de la sesión principal:
  - **Privacidad: «Excluir»**. Un diff con datos privados deja de ser candidato.
  - **`chore(release):`: «Lectura literal»**. Solo se excluye el texto exacto `chore: release`, como
    dicen la spec y el plan. Salen 104 candidatos, la cifra de la spec. Entre los 30 casos reales
    entran siete commits de versión.
  - **`reglas.json`: «Confirmado»**, tal cual.
- **Corpus real escrito** en `benchmarks/afinidad-2026-10/` con `--privacidad excluir`;
  `afinidad --comprobar` da `ok`. Los sha256:
  - `trampas.json`: `a9295180be8c597028b50ddae927501dca50f302d35a6bc11ae20ef1a76d9121`
  - `cases.json`: `1bde663ba516b1588f2f8d9fde71ec1b653db2a348c2308c56898e12190cdfbb`
  - `reglas.json`: `3aac45aa83c16be7b006bc73b941252f4fee6727cce64727fd8eb5a304e968bf`

  El detalle está en `evidencias/T4.md`, sección «Estado final tras las decisiones del 2026-10-07».
- Los 5 tests de `tests/test_corpus.py` que antes se saltaban ya pasan.
- **Pendiente para T5: el idioma de las trampas.** Están en español. Si los mensajes reales de los
  modelos salen en inglés, las trampas se notarían y habría que reescribirlas antes de generar la hoja.

## Ola 2 — T5

Evidencia completa en [T5](evidencias/T5.md). **T5 queda parada antes de la hoja** (pasos 6 y 7) por el idioma
de los mensajes de commit (abajo).

### Ventana de la tanda: excluida de P-4 y F1

- **2026-10-07T12:17:21.935591Z → 2026-10-07T12:32:06.828457Z** (UTC), un solo lanzamiento y ninguna
  repetición (`benchmarks/afinidad-2026-10/ventanas-tanda.json`).
- **Queda excluida** de la medición de P-4 (enfriamiento, `scripts/medir_enfriamiento.py --excluir`) y de la de
  F1 (adopción, `scripts/medir_adopcion.py`): todas las peticiones de esa ventana son de la evaluación.

### Delegaciones ajenas

En la copia de `metrics.db` hay 300 filas en la ventana. 261 casan una a una con las peticiones de benchmark y
de calentamiento, y 39 con las 3 corridas del techo (13 pasadas cada una). **Ajenas: 0.** El log de uso del
daemon no tiene entradas en la ventana. **Casos repetidos: 0.**

### Celdas mecánicas (`veredicto-afinidad --solo-mecanicas`)

Comparadas con `gemma3-4b` (rol `mechanical`), con una carga en frío de 3,27 s según la copia de `metrics.db`:

| Tool | Alternativo | Estado | Criterios que no se cumplen |
| --- | --- | --- | --- |
| local_classify | gemma4-26b-a4b | rechazada | calidad, formato |
| local_classify | qwen36-35b-a3b | rechazada | calidad, formato |
| local_extract | gemma4-26b-a4b | rechazada | calidad |
| local_extract | qwen36-35b-a3b | rechazada | calidad |
| local_translate | gemma4-26b-a4b | aprobada | — |
| local_translate | qwen36-35b-a3b | aprobada | — |
| local_lint_summary | gemma4-26b-a4b | aprobada | — |
| local_lint_summary | qwen36-35b-a3b | rechazada | calidad, latencia |
| local_delegate | gemma4-26b-a4b | aprobada | — |
| local_delegate | qwen36-35b-a3b | rechazada | calidad |

El criterio 1 (el corpus discrimina) se cumple en las diez. Los casos de cada criterio están en
`evidencias/T5.md` y en `benchmarks/afinidad-2026-10/veredicto-mecanicas.json`.

### Idioma de los mensajes de commit: parada antes de la hoja

En los 30 casos reales, `gemma4-26b-a4b` contesta en inglés 17 y en español 13. `qwen36-35b-a3b`, en español 23,
en inglés 6, y hay 1 ambiguo. Las trampas están en español, así que contra el 26B el idioma delataría la trampa.
**No se generó la hoja 1** (ni `hoja/` ni `clave/`). Hay que decidir con el usuario cómo se reescriben las
trampas, y eso cambia el sha256 de `trampas.json` que congeló T4.

### Desviaciones

1. **Descartes por sonda que solo afectan a los recursos.** 8 casos de `local_classify` de cada modelo pequeño
   y 2 de cada modelo grande quedaron `descartada` con `zero_vram_samples`: respondieron en menos de un segundo
   y la sonda no llegó a muestrear. Ahora `veredicto-afinidad`, **y solo él**, cuenta las filas descartadas por
   `zero_vram_samples` o `zero_ram_samples`. `multiple_processes`, `process_changed` y un motivo vacío se siguen
   descartando, y el análisis de CP-3/F2 no cambia. La reanudación de `tanda_afinidad.py` tampoco repite esas
   filas. Hay tests y mutantes para los dos cambios; el del veredicto falla con `SinDatos` en la llamada, antes
   del assert de la celda (detalle en `evidencias/T5.md`).
2. **Ruta de perfil en las filas del techo.** `entorno_fijado.LOCAL_DELEGATE_LOG_DIR` llevaba la carpeta del
   usuario (3 filas, ninguna en `response`). Quedó como `~/…`, el resto de cada fila sigue igual, y
   `fila_del_techo` ya la escribe así (con test y mutante).

### Comprobaciones

- `pesado.sh uv run pytest tests/test_tanda_afinidad.py tests/test_analisis_benchmark.py tests/test_hoja_pares.py tests/test_corpus.py -q -p no:cacheprovider`
  → `185 passed in 16.76s`.
- `uv run ruff check .` → `All checks passed!`; `uv run ruff format --check .` → `162 files already formatted`.
- sha256 de `config.yaml` de llama-swap: `7F763F8538FD719FD3C8DD4FC3C1F6BFBF6C2543FEF3E67C2D8EBAD3A5FB68F0`,
  igual que en T0.
- sha256 de `cases.json`, `trampas.json` y `reglas.json`: sin cambios desde T4.

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
