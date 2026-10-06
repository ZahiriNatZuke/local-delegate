# Research: el panel cuenta bien, dice la causa real y se presenta coherente

Repo `D:\Projects\local-delegate` @ `130afab` (0.32.0), rama `feat/panel-honesto`. Rutas relativas
a `src/local_delegate/` salvo que se diga otra cosa. Cada causa de `insumos/` se volvió a mirar en
el código; las pruebas de red se hicieron **de verdad** en esta PC (Windows 11, Python 3.11.15,
`httpx2` 2.13.0) con scripts desechables del scratchpad (`sonda_fallos.py`, `sonda_fallos2.py`,
`neto.py`). Convención: **[V]** verificado aquí, **[I]** inferido, **[?]** sin verificar.

## 1. Veredicto sobre las causas de los insumos

| # | Causa propuesta | Veredicto | Evidencia |
|---|---|---|---|
| 1 | Un fallo suma a «Contexto conservado» | **[V] confirmada** | `server.py:618-621`: `_accounting` no mira `ok`; con `source=path` suma `chars_in // 4` |
| 2 | «Generado en local» suma el mensaje de error | **[V] confirmada** | `server.py:1283`, `:1602`, `:1933`: los tres caminos registran `chars_out=len(text)` también con `ok=False`, y `text` es el mensaje de error; `server.py:616` lo estima ÷ 4 porque un fallo no trae `tokens_out` |
| 3 | «N estimado(s)» cuenta los fallos | **[V] confirmada** | `server.py:602`: `estimated` = falta `tokens_in` o `tokens_out`. En el log real de la PC **los 7 estimados de septiembre son los 7 fallos** (`neto.py`) |
| 4 | «Contexto conservado» es bruto | **[V] confirmada** | `server.py:618-631` no resta nada; medido abajo (§3) |
| 5 | Badge «caído» sin causa | **[V] confirmada** | `web/metrics.py:1463-1466` pinta `up?'conectado':'caído'`; `server.py:2989-2990` traga cualquier `HTTPError`/`ValueError` como `False, []`, incluido el 401 |
| 6 | `local_status` y `doctor` no distinguen DNS | **[V] confirmada** | `server.py:3050-3052` (arriba/CAÍDO); `doctor.py:276-279` da solo el nombre de la excepción; `checks.py:157-160` reescribe el «no» del daemon como «no responde»; ninguna referencia a `gaierror` en el paquete |
| 7 | `doctor` ofrece arrancar un backend remoto | **[V] confirmada** | `checks.py:1304-1308`: la pista «arranca llama-swap» sale sin mirar `config.backend_origin()` |
| 8 | Las delegaciones preguntan «¿Lo arranco?» con cómputo remoto | **[V] confirmada** | `server.py:878-897`: `es_backend_ausente` → pregunta y `autostart.ensure_backend`; `autostart.py:43-85` no mira el origen |
| 9 | «sin datos (requiere llama-swap ≥ v236)» ante cualquier fallo | **[V] confirmada** | `web/metrics.py:625-633` devuelve `{available:false}` sin motivo; `:1513-1514` siempre culpa a la versión |
| 10 | La lista de modelos cambia con y sin conexión | **[V] confirmada** | `web/metrics.py:1486-1490` (backend + catálogo), `server.py:2996` (alfabético), `:1547-1548` vacía los estados; la lista sale de `/api/status`, que va cada 60 s (`:1939`) |
| 11 | «procesando» tapa el estado real | **[V] confirmada, y hay más** | `web/metrics.py:1502`. Además: en llama-swap v255 `/v1/models` da `loaded` también para `starting` y `stopping` (ver §4), así que hoy un modelo **cargando** sale «montado» con chip LOADED (`:1500-1502`) |
| 12 | «EN CURSO» con una tarea terminada | **[V] confirmada** | `web/metrics.py:1602`: el título del panel es «En curso» también cuando pinta la última terminada (`:1585-1598`). El indicador de cabecera (`:1651-1653`) sí es correcto: solo dice EN CURSO con llamadas vivas |
| 13 | Panel Sistema engañoso con cómputo remoto / macOS | **[V] confirmada** | `web/sysinfo.py:28-65` (RAM solo win32/linux), `:159-173` (procesos `[]` fuera de win32/linux); `web/metrics.py:1626` y `:1631` no saben del origen ni de la plataforma; `/api/system` (`:683-692`) no devuelve ni origen ni plataforma |
| 14 | El sondeo de 2 s se solapa | **[V] confirmada** | `web/metrics.py:1937` `setInterval(pollInflight,2000)`; `/api/backend` hace `/running` (1 s) y `/models` (2 s) en serie (`:596-604`); además `pollInflight` se llama desde `visibilitychange` y «Refrescar» (`:1921`, `:1946`) sin guarda |
| 15 | Tipografía por clase y no por rol | **[V] confirmada** | Las 7 desviaciones de `insumos/tipografia-panel.md` existen en las líneas citadas (`:758`, `:843`, `:948`, `:1021`, `:1044`, `:1058`, `:1368`, `:1377`, `:1406`, `:1419`, `:1423`, `:1431`, `:1435`, `:1631`, `:1634`, `:1878`) |
| 16 | Miles sin separador y decimales con punto | **[V] confirmada** | `web/metrics.py:1215` `new Intl.NumberFormat('es')`. Node 24.18.0: `8003 → "8003"`, con `{useGrouping:'always'}` → `"8.003"`. Decimales con punto en `:1518`, `:1576`, `:1590`, `:1613`, `:1624-1625`, `:1707` |
| 17 | Latencia en ms con miles | **[V] confirmada** | `web/metrics.py:1731` (KPI) y `:1892` (tabla de actividad) |
| 18 | Plurales «(s)» | **[V] confirmada, tres sitios** | `web/metrics.py:1342` («archivo(s) leído(s)»), `:1653` («delegación(es)»), `:1715` («estimado(s)») |
| 19 | «Ahorro por herramienta» filtra `source==='path'` | **[V] confirmada (menor)** | `web/metrics.py:1822`: un `output_to_file` inline suma en el KPI y no en ese gráfico |

**Hipótesis del brief sobre la Mac (VPN):** **[I] ruta, no DNS, y no se puede cerrar con el log
actual.** Las pruebas de §2 enseñan que un nombre que no resuelve falla en 0,12 s, y que un SYN sin
respuesta acaba en el plazo de conexión **del kernel** (21 s en Windows, medido; ~75 s en macOS por
`net.inet.tcp.keepinit`, [I]) con `ConnectTimeout`. Los ~75 s encajan con lo segundo. Pero
`connect_error` se escribe igual para `ConnectError` y `ConnectTimeout` (`server.py:898-906`) y el
log no guarda la excepción, así que **el log de la Mac no puede distinguirlo**. Por eso la spec
añade al log la causa de conexión: la próxima vez sí se podrá.

## 2. Qué excepción da `httpx2` en cada fallo, en esta PC [V]

Prueba real, sin dobles (`scratchpad/sonda_fallos.py` y `sonda_fallos2.py`):

| Caso | Plazo | Tarda | Excepción `httpx2` | Causa raíz en la cadena |
|---|---|---|---|---|
| Nombre que no resuelve (`no-existe-xyz.invalid`) | 5 s | 0,12 s | `ConnectError` | `socket.gaierror` errno 11001 |
| Puerto cerrado en `127.0.0.1:9` | 5 s / 3 s | **2,0 s** | `ConnectError` | `ConnectionRefusedError` WinError 10061 |
| Puerto cerrado en `127.0.0.1:9` | **2 s / 1 s** | 2,0 / 1,1 s | **`ConnectTimeout`** | `TimeoutError` sin errno |
| Puerto cerrado en `localhost:9` (prueba `::1` y luego `127.0.0.1`) | 5 s | **4,1 s** | `ConnectError` | `ConnectionRefusedError` 10061 |
| IP sin ruta `10.255.255.1` | connect 2 s | 2,0 s | `ConnectTimeout` | `TimeoutError` sin errno |
| IP sin ruta `10.255.255.1` | 60 s | **21,0 s** (plazo del kernel) | `ConnectTimeout` | `TimeoutError` WinError 10060 |
| IPv6 sin ruta (`[2001:db8::1]`) | 5 s | 0,02 s | `ConnectError` | `OSError` WinError 10051 (red inalcanzable) |
| TEST-NET-1 `192.0.2.1` (`sonda_fallos3.py`) | connect 0,5 s | 0,58 s | `ConnectTimeout` | `TimeoutError` |
| Puerto de `127.0.0.1` recién liberado (`sonda_fallos3.py`) | connect 3 s | 2,05 s | `ConnectError` | `ConnectionRefusedError` 10061 |
| Puerto cerrado en la IP propia **no** loopback (la IP 100.x de la tailnet; `sonda_fallos4.py`) | connect 3 s | 2,14 s | `ConnectError` | `ConnectionRefusedError` |
| Lo mismo | **connect 1 s** | 1,01 s | **`ConnectTimeout`** | `TimeoutError` |
| Backend real `127.0.0.1:9292/v1/models` sin credencial | 5 s | 0,02 s | respuesta **401** → `raise_for_status` da `HTTPStatusError` | cuerpo `{"src":"llama-swap","error":{"message":"unauthorized: invalid or missing API key",…}}` |
| Mismo backend, `/running` y `/api/metrics/stats` sin credencial | 5 s | 0,02 s | **401** | mismo cuerpo |

Tres hallazgos que cambian el diseño:

1. **En Windows, una conexión rechazada tarda ~2 s** (el SO reintenta el SYN tras el RST), también
   contra una IP que no es de loopback, y 4 s con `localhost`. Con el plazo de 2 s de `_models_with_status` (`server.py:2985`) y el de 1 s de
   `/running` (`web/metrics.py:597`), «nadie escucha» **llega como `ConnectTimeout`**: un
   clasificador que solo mirara el tipo diría «no contesta (ruta/VPN)» con el backend local
   apagado. Hace falta (a) un plazo de conexión de sondeo > 2 s, que es lo que salva el caso
   remoto (un llama-swap apagado en la PC visto desde otra máquina Windows), y (b) leer un
   `ConnectTimeout` contra un host de loopback como «nadie escucha», que cubre `localhost` (4 s):
   en loopback no hay ruta que perder.
2. El mapa de `httpcore2` lo explica: `httpcore2/_backends/sync.py:198-200` (`connect_tcp`;
   la primera versión citaba `:150-152`, que es `start_tls` con el mismo mapa) convierte
   `socket.timeout` (= `TimeoutError`) en `ConnectTimeout` y cualquier otro `OSError` en
   `ConnectError`. Por eso el plazo **del kernel** (WinError 10060, ETIMEDOUT en macOS) también
   sale como `ConnectTimeout`, igual que el del cliente.
3. «Sin ruta» de verdad (red inalcanzable, 10051/10065, `ENETUNREACH`/`EHOSTUNREACH`) es inmediato
   y sale como `ConnectError` con ese errno; lo que en la práctica produce una VPN que se traga el
   tráfico es un **timeout**, no un «sin ruta». Son dos causas distintas y el clasificador las
   separa.

No probado [?]: un DNS que **se cuelga** (servidor DNS inalcanzable). `getaddrinfo` no respeta el
plazo de `httpx2`, así que ese sondeo podría tardar lo que diga el resolvedor del SO. Queda como
riesgo (el sondeo encadenado de la spec evita que se apilen).

## 3. Contabilidad: cifras reales con la regla actual y la propuesta [V]

`scratchpad/neto.py` recorre los `usage-*.jsonl` de esta PC (`config.LOG_DIR` =
`%USERPROFILE%\AppData\Local\local-delegate`) con el `_accounting` de hoy y con la regla de la
spec (REQ-001 a REQ-004). En tokens (chars ÷ 4):

| Mes | Eventos / fallos | Bruto hoy | Bruto sin fallos | Devuelto | **Neto** | Estimados hoy → spec | Coste local hoy → spec |
|---|---|---|---|---|---|---|---|
| 2026-07 | 117 / 4 | 263 842 | 248 281 | 20 918 | 227 363 | 8 → 4 | 314 470 → 298 839 |
| 2026-08 | 18 / 2 | 261 048 | 178 756 (**−32 %**) | 1 005 | 177 751 | 1 → 0 | 339 619 → 298 473 |
| 2026-09 | 143 / 7 | 983 871 | 873 270 (−11 %) | 72 342 | **800 928** | 7 → 0 | 1 283 211 → 1 172 213 |
| 2026-10 (en curso) | 124 / 2 | 635 194 | 625 968 | 39 385 | 586 583 | 2 → 0 | 925 128 → 915 902 |

- Septiembre está cerrado, así que sus cifras son **reproducibles** y sirven de control en la
  verificación (un `_accounting` mal cambiado da otro número).
- En septiembre un solo evento tiene neto negativo (devolvió más de lo que leyó).
- `viabilidad-cuota.md` §1 daba 976 509 de bruto y 72 126 de devuelto para septiembre; aquí salen
  983 871 y 72 342 con el `_accounting` del repo. La diferencia (0,7 % y 0,3 %) no cambia nada; se
  anota porque son dos mediciones del mismo dato.
- Los fallos con tokens reales existen: una delegación troceada que falla a mitad acumula los
  `tokens_in`/`tokens_out` de los trozos que sí se hicieron (`server.py:1536-1543`,
  `_accumulate`), y la GPU los gastó. Un fallo de una sola llamada nunca trae tokens (`server.py:
  898-941`, `:736`).
- `chars_out` es lo que la tool devolvió **antes** de la coletilla de ahorro (`server.py:1316-1319`,
  `:1616-1619`, que se añade después de `_log_event`) y, con `write_to`, es el código escrito al
  fichero, no el recibo (`server.py:1283` frente a `:1308-1313`). La spec fija qué se hace con
  cada caso.

## 4. llama-swap v255: qué expone de verdad [V]

Leído en el código de la etiqueta `v255` (`mostlygeek/llama-swap`, commit `7761aa1`), descargado al
scratchpad (`ls255/`):

- Estados de proceso (`internal/process/process.go:14-20`): `stopped`, `starting`, `ready`,
  `stopping`, `shutdown`.
- `GET /running` (`internal/server/api.go:351-368`, ruta en `server.go:348`) lista los procesos
  que **no** están `stopped` ni `shutdown` (`internal/router/base.go:366-377`), cada uno con
  `model`, `state`, `cmd`, `proxy`, `ttl`, `name`, `description`. O sea: `starting`, `ready` o
  `stopping`.
- `GET /v1/models` marca `status: "loaded"` a todo lo que esté en ese mapa (`api.go:141-149`):
  **`loaded` incluye `starting` y `stopping`**. Solo `/running` distingue «cargando» de «listo».
- **La cola no se expone por ningún GET.** El planificador FIFO
  (`internal/router/scheduler/fifo.go:118-135`) encola una petición si cargar su modelo obligaría a
  desalojar a otro con peticiones en curso, y su posición solo sale como texto
  («Queue position: #N», `base.go:542`) en el flujo de «loading» de peticiones **en streaming** con
  `sendLoadingState` (`base.go:529`). Las de local-delegate no son streaming. Las peticiones en
  vuelo se publican por SSE en `/api/events` (`InflightRequestEntry`, `internal/swaputil/events.go:
  60-72`), sin campo de cola.

**Respuesta a la pregunta abierta 2:** «esperando turno» no se lee de llama-swap; se **deduce**
cruzando dos señales que el panel ya tiene: la llamada en vuelo de local-delegate (`/api/inflight`,
registrada antes de tocar la red, `server.py:1236`) y `/running`:

| Llamada en vuelo a M | M en `/running` | Lectura |
|---|---|---|
| sí | `starting` | cargando |
| sí | `ready` | procesando |
| sí | `stopping` o ausente | esperando turno (llama-swap aún no lo carga: otro modelo del grupo ocupa el sitio, o está a punto de empezar) |
| — | `/running` no disponible (backend que no es llama-swap, 404) | no se puede distinguir: «en curso» |

Con cómputo remoto vale igual: la llamada en vuelo es la de esta máquina y `/running` es el del
backend remoto, que es justo el cruce que explica la captura 2 de la Mac (qwen36 desalojado
mientras la PC usaba gemma4-26b, mismo grupo `swap`).

## 5. Respuesta a las preguntas abiertas del brief

1. **¿El neto descuenta las relecturas?** **No: solo la respuesta de la tool.** Las relecturas no
   están en el log de uso; viven en los transcripts de Claude Code (no en los de Codex, Desktop o
   la Mac), solo los últimos ~30 días, y la medición de `viabilidad-cuota.md` §1.3 las deja entre
   el ~3 % y el ~30 % según la heurística. Restar un número así sería inventarlo. El panel lo dice
   en el tooltip («no descuenta relecturas») y la medición de relecturas queda para el cambio
   `coste-api-y-cuota`, que ya cruza transcripts.
2. **¿Cómo distinguir esperando turno de cargando con v255?** Ver §4: cruzando la llamada en
   vuelo con el `state` de `/running`; `loaded` de `/v1/models` no sirve para eso.
3. **¿`doctor` y `local_status` comparten el clasificador con el panel sin duplicarlo?** **Sí.**
   `fallos.py` ya es el módulo puro de clasificación (sin red ni configuración, `fallos.py:1-31`),
   así que la función nueva vive ahí y la usan los cuatro caminos: el sondeo del daemon
   (`/api/backend`, `/api/status`, `local_status`), `doctor.backend_probe` cuando no hay daemon,
   `checks` a través de lo que el daemon ya le devuelve (`daemon.query_backend`, `daemon.py:164-188`,
   lee `/api/backend` entero, así que le llegan `causa` y `detalle` sin código nuevo en el
   cliente), y `_post_chat` para el mensaje de `connect_error`.

## 6. Mapa de impacto

| Área | Responsabilidad hoy | Cambio | Evidencia |
|---|---|---|---|
| `server.py` `_accounting` | Contabilidad por evento (única en Python) | Fallos sin ahorro ni estimación; `returned` y `net` | `:579-643` |
| `server.py` `local_status` | Texto de diagnóstico | Línea de ahorro con neto; línea de backend con causa | `:3050-3061`, `:3080-3101` |
| `server.py` `_models_with_status` / `_llamaswap_running` | Sondeo de `/models` y `/running` | Sondeo con causa, plazo de conexión > 2 s, última lista buena | `:2982-3017` |
| `server.py` `_post_chat` | Fallo de conexión de una delegación | Mensaje con host y causa; campo de log; sin pregunta ni autoarranque con cómputo remoto | `:868-906` |
| `server.py` `_log_event` | Formato del log | Campo opcional `fallo_conexion` | `:453-574` |
| `fallos.py` | Clasificador puro | Función nueva de causa de conexión + textos | `:82-127` |
| `config.py` | Constantes | Plazo del sondeo (constante, sin variable de entorno) | `:66-68` |
| `doctor.py` `backend_probe` | Sondeo sin daemon | Usa el clasificador | `:265-290` |
| `checks.py` | Check `service.backend` | Pista según causa y origen; `UNKNOWN` por causa, no por prefijo de texto | `:138-161`, `:1296-1308`, `:306-307` |
| `web/metrics.py` (Python) | `_aggregate`, `/api/backend`, `/api/backend/stats`, `/api/status`, `/api/system` | Totales nuevos; causa y detalle; lista estable; plataforma y origen | `:209-403`, `:584-692` |
| `web/metrics.py` (JS/CSS/HTML) | Panel | `acct` espejo, KPI neto, estados, sondeo encadenado, tipografía, formato | `:758-1955` |
| `scripts/dev/capture_dashboard.py` | Mock de `/api/*` para la captura | Claves nuevas de `/api/stats` y `/api/backend` | `:209-225` |
| `docs/wiki/Savings-and-metrics.md`, `Troubleshooting.md`, `Daemon.md`, `Remote-backend.md` | Documentación | Regla de cuentas, estados, causas | — |
| `CHANGELOG.md` | `[Unreleased]` (CRLF) | Entrada `Fixed`/`Changed` | `:7-21` |

**Finales de línea** (`git ls-files --eol`): `server.py`, `web/metrics.py` y `CHANGELOG.md` son
**CRLF**; `fallos.py`, `config.py`, `doctor.py`, `checks.py`, `web/sysinfo.py`,
`tests/test_metrics.py` y la wiki (salvo `Integration-install.md`) son **LF**.

## 7. Convenciones a conservar

- Una sola implementación de las cuentas en Python (`web/metrics.py:203-206` la toma de
  `server.py`) y su espejo `acct` en JS atado por `test_paridad_acct_entre_python_y_el_js_del_panel`
  (`tests/test_metrics.py:648-737`), que ya trae una guarda de «esto comprobó algo» (`:733-736`).
- `fallos.py` no hace red ni lee configuración; recibe la excepción y devuelve un valor.
- Los dobles de red en la suite van por `tests/backend_mock.py` (`MockTransport`); una ruta no
  registrada falla el test en vez de salir a la red.
- Los tests de JS ejecutan la función con node (`tests/test_dashboard_js.py`); los de cableado,
  con Playwright (`tests/test_dashboard_ui.py`, que en CI no se salta).
- `test_captura.py:88-110` exige mock para todo `/api/*` nuevo que pida la página. Esta spec **no
  añade endpoints**, solo claves; aun así el mock de `capture_dashboard.py` se pone al día para que
  la captura de la próxima release no salga con el KPI neto a 0.
- No se añaden variables de entorno (los plazos nuevos son constantes), así que los guardianes de
  `tests/test_aislamiento_entorno.py` no cambian.

## 8. Riesgos y desconocidos

- **[V] Tests existentes que cambian a propósito:** `tests/test_metrics.py:519-530` compara el dict
  entero de `_accounting` (rompe al añadir claves); `:672` (fallo troceado) cambia de ahorro;
  `tests/test_checks.py:753`, `:768` y `tests/test_update.py:214` doblan `backend_models` con la
  tupla de dos; `tests/test_doctor.py` dobla `backend_probe`; `tests/test_metrics.py:228-243` y
  `tests/test_observabilidad_respaldo.py:136` usan `_models_with_status`.
- **[I] Un `ConnectTimeout` en loopback leído como «nadie escucha»** podría tapar otra causa rara
  (un cortafuegos que descarte en loopback, una cola de `accept` llena). Se acepta: en los dos
  casos la acción es la misma (mirar el proceso local), y el detalle conserva el nombre de la
  excepción.
- **[?] DNS colgado**: ver §2.
- **[I] La lista estable se guarda en memoria del daemon**: si el daemon arranca con el backend
  caído no hay lista que conservar y solo se ve el catálogo. Persistirla en disco no compensa.
- **[V] Fuera de alcance y anotado:** separar el plazo de conexión de las **delegaciones**
  (`config.py:68`, `server.py:121`: 180 s también para conectar) y pedir dos sondeos fallidos antes
  de pasar a «caído». Los dos los propone `anomalias-panel.md` y no están en el brief.
- **[V] Captura del README**: el panel cambia de aspecto; la captura se regenera en la próxima
  release, no aquí (`test_captura.py:78-86` solo exige la versión).

## Llamadas a `local-delegate`

- `local_summarize(path=docs/wiki/Savings-and-metrics.md, focus=secciones del panel)`: para saber
  qué secciones de la wiki toca la tarea de docs sin leer la página entera (~4200 tokens que no
  entraron).
- No pasé por `local_*` el código de `server.py`, `web/metrics.py`, `fallos.py`, `checks.py` ni los
  insumos: el encargo pide verificar `fichero:línea` exactos, y un resumen no da líneas (en el
  insumo de anomalías el modelo local erró números de línea). Los leí por franjas acotadas.
