# Anomalías del panel (capturas del 2026-09-30) — veredicto contra el código

Repo `D:\Projects\local-delegate` @ 130afab (0.32.0). Solo lectura. Rutas relativas a `src/local_delegate/`.
Todo el frontend vive embebido en `web/metrics.py` (HTML+JS a partir de la línea ~750).

## Pista nueva que lo ata casi todo: lo que vio llama-swap ese día

Consulté en solo lectura `D:\Projects\llms\llama-swap\metrics.db` (tabla `activity`, la que alimenta
`/api/metrics/stats`). Las peticiones de `qwen36-35b-a3b` de la mañana del 30 (UTC) **no están en el
`usage-202609.jsonl` de la PC**, así que son las de la Mac:

| fin (UTC) | entrada tok | duración |
|---|---|---|
| 12:03:27 | 724 | 55,6 s |
| 12:05:12 | 5371 | 160,4 s |
| 12:07:15 | 407 | 102,3 s |
| 12:08:01 | 5291 | 148,9 s |

- 724 + 5371 = 6095 ≈ «Coste local 6163» de la captura 2; las cuatro suman 11 793 ≈ «11.929» de la captura 1. La media de las cuatro (116,8 s) cuadra con «Latencia media 116.948 ms».
- La captura 2 cae hacia las 12:06:16 UTC: dos terminadas y dos en curso desde hacía 44 s (empezaron a las 12:05:32-33).
- **Después de las 12:08:01 no llega a llama-swap NINGUNA petición más de qwen36 hasta las 21:44.** llama-swap sí apunta las peticiones cuyo cliente corta (las de la PC de las 10:53 salen como `499 client disconnected`, 180 s), así que las llamadas en curso de las capturas 1 y 3 y los 4 fallos de la captura 3 **no llegaron a abrir conexión con llama-swap**. Eso encaja con la VPN que rompe el DNS y no con un llama-swap ocupado.
- Mientras tanto la PC usaba `gemma4-26b-a4b` y `gemma4-12b` (12:05-12:12). Los tres están en el mismo grupo `swap` de `config.yaml` (`swap: true`: solo uno cargado a la vez), así que la Mac y la PC se quitaban el modelo la una a la otra. Ver punto 3.

---

## 1. «CAÍDO» con una llamada en curso — **REFUTADA** la causa propuesta (llama-swap ocupado); la real casi seguro es la red/DNS de la Mac

**Cómo se calcula.** El badge sale de `state.backendUp` (`web/metrics.py:1463-1466`), que el sondeo de 2 s pone a `!!bj.available` (`web/metrics.py:1541`). `/api/backend` (`web/metrics.py:584-613`) toma `available` solo de `server._models_with_status()` (`server.py:2982-2997`): `GET {BASE_URL}/models` con `httpx2.Client(timeout=2.0)` **nuevo en cada sondeo** (`server.py:2985`). Cualquier excepción (`HTTPError` o `ValueError`) da `False, []` sin motivo (`server.py:2989-2990`). No hay reintento ni histéresis: un solo sondeo fallido lo pone en CAÍDO durante 2 s.

**Por qué no es el timeout corto con llama-swap ocupado.**
- La captura 2 es el peor caso de llama-swap (cambiando de modelo con dos peticiones en cola) y el sondeo respondió: CONECTADO.
- Las peticiones en curso de las capturas 1 y 3 no llegaron nunca a llama-swap (no aparecen ni como 499).

**(a) Cómo resuelve la URL.** `BASE_URL` es la cadena tal cual de `LOCAL_DELEGATE_BASE_URL` (`config.py:66`). No se resuelve ni se fija ninguna IP en el código: httpx llama a `getaddrinfo` del sistema cada vez que abre una conexión nueva.
- Las delegaciones usan un cliente de módulo con keep-alive (`server.py:110-122`), pero con el `keepalive_expiry` por defecto de 5 s (comprobado: `httpx2.Limits()` → `keepalive_expiry=5.0`). Entre delegaciones casi siempre se abre conexión nueva y se resuelve el nombre de nuevo.
- Los sondeos (`server.py:2985`, `web/metrics.py:597` y `:627`) crean un cliente nuevo cada vez y siempre resuelven.
- Una petición que ya tenía su TCP abierto sigue viva aunque el DNS se rompa después. Eso explica «procesando + CAÍDO» cuando la conexión era anterior.
- Ojo: «procesando» no prueba que el backend trabaje. La entrada en curso se registra **antes** de tocar la red (`server.py:1236`, `:1524`, `:1741`), así que también cubre una llamada atascada resolviendo el nombre o conectando, que es lo que dicen los datos de llama-swap.
- Agravante: `httpx2.Client(timeout=config.HTTP_TIMEOUT)` con un float pone **180 s también al connect** (`config.py:68`, `server.py:121`). Una IP mala devuelta por el DNS de la VPN se queda colgada hasta 3 minutos.

**(b) ¿Se distingue «no resuelve» de «no responde» y de «responde con error»?** No.
- El panel: todo es `available: false` → «caído», incluido un 401 con el backend vivo (el `raise_for_status` lo convierte en `HTTPError`).
- Las delegaciones: el fallo de DNS es `httpx2.ConnectError` (comprobado en esta PC: `ConnectError: [Errno 11001] getaddrinfo failed`, cadena `httpx2.ConnectError → httpcore2.ConnectError → socket.gaierror`). Cae en `es_backend_ausente` (`fallos.py:111`) y sale «no se pudo conectar al endpoint… ¿Está corriendo tu backend?» con `error="connect_error"` (`server.py:898-906`), sin el texto de la excepción.
- Peor aún: antes de eso pregunta «El backend local no responde en <host>. ¿Lo arranco?» (`server.py:887-897`, espera hasta `ASK_TIMEOUT` = 30 s, `config.py:401`) y, si se acepta, intenta arrancar un llama-swap **en la Mac** (`autostart.ensure_backend`). No mira `config.backend_origin()`.

**(c) ¿`local_status` o `doctor` diagnostican el DNS?** No.
- `local_status` usa el mismo `_models_with_status` y pinta «arriba/CAÍDO» (`server.py:3050-3052`).
- `doctor` pregunta primero al daemon y, si este dice que no, escribe «no responde (según el daemon…)» (`checks.py:154-160`). Solo sin daemon cae a `doctor.backend_probe`, que da «no responde (ConnectError)» (`doctor.py:276-279`).
- En los dos casos la pista es «arranca llama-swap» (`checks.py:1304-1308`), equivocada con cómputo remoto.
- No hay ni una referencia a `gaierror`, `getaddrinfo` ni DNS en el paquete.

**Propuesta.**
- Que `_models_with_status` devuelva un motivo tipificado: `dns` si la cadena de causas contiene `socket.gaierror`, `timeout`, `conexión rechazada`, `http_401` o `http_5xx`.
- `/api/backend`, `local_status`, `doctor` y el `ChatResult` de `connect_error` lo enseñan: «no se resuelve `<host>` (¿VPN o DNS?)», «`<host>` no responde», «responde 401».
- No ofrecer arrancar el backend cuando `backend_origin()=='remote'`, y separar el timeout de connect (p. ej. `httpx2.Timeout(180, connect=10)`).
- Pedir 2 fallos seguidos antes de pasar a CAÍDO.
- Mientras tanto, en la Mac conviene poner la IP 100.x de la tailnet en `LOCAL_DELEGATE_BASE_URL` (o el FQDN `*.ts.net`) para no depender del DNS que secuestra la VPN.

## 2. Con el backend caído cambian la lista y el orden de los modelos — **CONFIRMADA**

- `renderBackend` arma la lista con los ids de `/v1/models` (ordenados alfabéticamente en `server.py:2996`) y luego añade los del catálogo que falten (`web/metrics.py:1486-1490`).
- Con el backend caído `models=[]`, así que solo quedan los 4 del catálogo en orden de rol (`web/metrics.py:647-652`). `qwen35-2b` no tiene rol y desaparece.
- Las chips LOADED/UNLOADED salen de `state.modelStatus`, que se vacía con el sondeo fallido (`web/metrics.py:1547-1548`).
- Detalle: la lista sale de `state.status`, que solo se refresca cada **60 s** (`web/metrics.py:1939`), mientras el badge va cada 2 s. Al volver el backend, el badge se pone verde y la lista sigue en 4 hasta un minuto.

**Propuesta:** guardar la última lista buena de modelos y pintarla atenuada con «sin conexión» en vez de cambiarla, con orden estable (por rol y luego alfabético) en los dos casos.

## 3. «procesando» con chip UNLOADED — **MATIZADA**

- El panel solo conoce `loaded/unloaded`: CSS en `web/metrics.py:985-986`, y la chip pinta tal cual el `status.value` de `/v1/models` (`web/metrics.py:1504`).
- `/running` sí trae un `state` (`starting`, `ready`…), pero «procesando» le gana siempre: `stateTxt = busy ? 'procesando' : …` (`web/metrics.py:1502`). El `starting` nunca se ve mientras haya una llamada en curso.
- `running` se descarta además si el backend está caído (`web/metrics.py:1545`).
- La causa concreta de la captura 2 no es solo «está cargando». A las ~12:06 UTC la PC tenía `gemma4-26b-a4b` en uso (peticiones de 12:05:02 a 12:09:21), y 26b y qwen36 comparten el grupo `swap` (`D:\Projects\llms\llama-swap\config.yaml`, `groups.swap`). qwen36 estaba **desalojado y en cola**, esperando a que la PC soltara el 26b: de ahí las latencias de 102-160 s en la Mac.

**Propuesta:**
- Que la fila combine las tres señales: «en cola (esperando a gemma4-26b)» si está ocupado y sin cargar, «cargando» si `/running` dice `starting`, y «procesando» solo si está `ready`.
- Que la chip acepte estados desconocidos con un estilo neutro.

## 4. «sin datos (requiere llama-swap ≥ v236)» con el backend caído — **CONFIRMADA**

- `/api/backend/stats` responde `{available:false}` ante **cualquier** fallo (red, DNS, timeout de 1 s, 401, 404) (`web/metrics.py:625-633`), y el frontend achaca siempre la causa a la versión (`web/metrics.py:1513-1514`).
- La PC corre llama-swap v255 (hay `llama-swap-v255` y el comentario de `fallos.py:60`), así que el mensaje es falso.
- Además solo se pide cada 60 s (`fetchStatus`, `web/metrics.py:1452-1454` y `:1939`), con un timeout de 1 s por la tailnet que puede saltar aunque haya conexión.

**Propuesta:** devolver un `reason` (`no_conecta` / `404` / `401` / `timeout`), mostrar «backend sin conexión» cuando el badge esté caído y reservar el texto de la versión para el 404. Subir el timeout a 2-3 s.

## 5. Panel Sistema en la Mac — **MATIZADA**: la causa es la plataforma, pero el texto no explica nada útil con cómputo remoto

- `ram_stats` solo implementa win32 y linux (`web/sysinfo.py:28-65`).
- `vram_stats` depende de `nvidia-smi` (`web/sysinfo.py:75-99`).
- `interesting_processes` devuelve `[]` fuera de win32 y linux (`web/sysinfo.py:166-173`). Por eso en la Mac ni siquiera sale el propio daemon con su chip «DAEMON MCP».
- Aunque se implementara macOS, con cómputo remoto el backend vive en la PC: «Ningún proceso del backend detectado» sería cierto pero engañoso.

**Propuesta:**
- Implementar la RAM en macOS (`sysctl hw.memsize` + `vm_stat`) y la lista de procesos (`ps -axo pid,rss,comm`).
- Con `origin=='remote'`, poner en la sección de procesos «El backend corre en `<host>`: su RAM/VRAM se ve en el panel de esa máquina».

## 6. «EN CURSO» enseña una tarea ya terminada — **CONFIRMADA** (por diseño, pero mal rotulado)

Sin llamadas vivas, `renderInflight` pinta la última delegación terminada (con ✓ o ✕) y deja el título «En curso» (`web/metrics.py:1582-1602`).

**Propuesta:** cuando no hay nada vivo, cambiar el título a «Última delegación» (o «En curso — nada; última:»).

## 7. Formato de números — **CONFIRMADA**

- `const F = new Intl.NumberFormat('es')` (`web/metrics.py:1215`). Comprobado con node: `8003 → "8003"`, `11929 → "11.929"`, `5013 → "5013"`, `52549 → "52.549"`. Es el `minimumGroupingDigits=2` del CLDR para `es`; con `{useGrouping:'always'}` da `8.003`.
- Además los decimales salen con **punto** porque no pasan por `F`:
  - «18.6s», «69.3s» (`web/metrics.py:1576` usa `it.elapsed_s` crudo; `:1590` usa `toFixed(1)`);
  - «60.6», «1718.2» tok/s (`web/metrics.py:1518`, `Math.round`);
  - «12.4 / 31.1 GiB» (`web/metrics.py:1613`, `:1624-1625`).
  - Junto a «2.010.642», el punto hace ambiguo «1718.2».
- Latencia: «116.948 ms» (`web/metrics.py:1706`, `:1731`).

**Propuesta:**
- `new Intl.NumberFormat('es',{useGrouping:'always'})` y un `F1` con `maximumFractionDigits:1` para todos los decimales.
- Latencia en segundos a partir de 10 000 ms («116,9 s»).

## 8. «4 estimado(s)» — **CONFIRMADA**, y es peor que el plural

- El texto está en `web/metrics.py:1715` (lo mismo con «delegación(es)» en `:1653`).
- Lo que cuenta no son estimaciones: un evento cuenta como `estimated` si le falta `tokens_in` o `tokens_out` (`server.py:602`), y **todas las llamadas fallidas** caen ahí. En las capturas cuadra exacto: Mac 4 estimados = 4 fallos, PC 2 = 2 fallos.
- Encima, al fallar se apunta `chars_out=len(text)` con el texto del **mensaje de error** (`server.py:1584`, `:1602`). Así «Generado en local» suma los caracteres del error ÷ 4 como si fuera salida del modelo (`server.py:616`).

**Propuesta:**
- Contar como `estimated` solo los eventos `ok=True` sin `usage`.
- Poner `tokens_out=0` y no contar `chars_out` en los fallos.
- Redactar en singular o plural según el número («1 estimado», «4 estimados»).

## 9. «Ahorro por herramienta» vacío en la Mac — **REFUTADA** (no está vacío; la barra queda fuera del recorte)

- El estado vacío de `barH` dibuja un gráfico sin ejes (`x:{display:false}, y:{display:false}`, `web/metrics.py:1805-1809`). En las capturas 1 y 3 se ven las líneas verticales de la rejilla del eje X, que solo existen cuando hay datos (`web/metrics.py:1818`).
- Con una sola categoría (`local_commit_msg`), Chart.js centra la barra en vertical, por debajo del borde inferior de las dos capturas. Conviene pedir una captura con scroll para cerrarlo.
- El filtro tampoco excluye esa tool: `drawToolDonut` filtra `source==='path'` y usa `acct(e).saved` (`web/metrics.py:1822`), la misma regla que el KPI (`server.py:618-631`, espejo JS en `web/metrics.py:1676-1698`).
- Sí hay una divergencia real, menor: un evento con `output_to_file` y `source!='path'` (p. ej. `local_boilerplate` a fichero) suma en el KPI y en el gráfico temporal, pero el `filter(source==='path')` lo saca del gráfico por herramienta.

**Propuesta:** quitar el `filter` de `web/metrics.py:1822` (`acct` ya devuelve 0 cuando no hay ahorro y `agg` descarta los ceros).

Hallazgo relacionado: `_accounting` **no mira `ok`**, así que una delegación fallida con `path` suma `chars_in//4` a «Contexto conservado» (`server.py:618-621`). En la captura 3 pasó de 8003 a 13 726 con 4 fallos de por medio. Cuando la delegación falla, Claude normalmente acaba leyendo el fichero, así que ese ahorro no existió. Decisión de producto: propongo `saved=0` si `ok=False`.

## 10. Tasa de error del 50 % en la Mac — **qué cuenta**: todo `ok=false`, sin distinguir clase

- La tasa es `errors/calls`, y `errors` suma cada evento con `ok=False` (`web/metrics.py:293-294`, `:1704-1707`). Entra todo lo que `_post_chat` devuelve con `ok=False`:
  - `connect_error` (ConnectError, ConnectTimeout y **el fallo de DNS**);
  - `http_error` (otros de transporte);
  - `http_NNN` (4xx/5xx);
  - `read_timeout` (180 s);
  - `bad_response` y las clases del cuerpo (`server.py:868-939`, `fallos.py:114-127`).
- En una delegación troceada, el fallo de un trozo corta todo (`server.py:1576-1578`) y cuenta como **un** fallo.
- Logs: en esta PC no hay rastro de los fallos de la Mac (cada máquina escribe su `usage-*.jsonl`). El 2026-09-30 la PC solo tuvo 3 fallos propios, todos `read_timeout` de 180 s (`local_explain_code` ×2 a las 10:53 UTC y `local_boilerplate` a las 22:02), y su único `local_commit_msg` (21:56) salió bien.
- Pero `metrics.db` de llama-swap demuestra que los 4 fallos de la Mac no llegaron al backend. Por la latencia media (8 llamadas a 106,1 s menos las 4 buenas a ~116,8 s), los fallidos tardaron **~95 s de media**. Encaja con DNS colgado o connect a una IP equivocada con el plazo de 180 s, más los hasta 30 s de la pregunta «¿Lo arranco?».
- Para cerrarlo hace falta el campo `error` de esos 4 eventos en el `usage-202609.jsonl` de la Mac (`connect_error` frente a `http_error` y su `latency_ms`). Hoy el log **no guarda el texto de la excepción** en `connect_error`, así que no se verá el `gaierror`.

**Propuesta:**
- Apuntar en el log `error_detail` (tipo y mensaje, recortado) y la subclase `dns`.
- En el panel, desglosar la tasa de error por causa (red/DNS, timeout, HTTP, modelo) en vez de un único %.

---

## Otras rarezas de las capturas

- **Mac y PC se pisan el grupo `swap`.** `gemma4-26b-a4b`, `qwen36-35b-a3b`, `qwen35-2b` y `gemma4-12b` comparten `groups.swap` con `swap: true`, y todos con `-np 1`. Cuando la Mac pide código y la PC pide resúmenes a la vez, cada petición puede forzar descargar y recargar el otro modelo. Eso explica la latencia media de ~110 s de la Mac. El panel no lo enseña en ninguna parte.
- **«Coste local» y «Contexto conservado» incluyen los fallos** (puntos 8 y 9). La tarjeta «Generado en local» de la captura 3 (207 tok, «4 estimado(s)») mezcla salida real con texto de error.
- **La pregunta «¿Lo arranco?» y la pista de `doctor` «arranca llama-swap» no tienen sentido con cómputo remoto** (`server.py:887-897`, `checks.py:1307`).
- **El 401 se pinta igual que una caída.** `doctor` ya lo distingue (`doctor.py:282-286`); el panel y `local_status` no.
- **El panel es incoherente durante hasta 60 s al reconectar.** El badge va cada 2 s, pero la lista de modelos y las métricas de llama-swap van cada 60 s (`web/metrics.py:1937-1939`).
- **El sondeo de 2 s puede solaparse consigo mismo.** `setInterval(pollInflight,2000)` no espera a la respuesta anterior, y `/api/backend` puede tardar hasta 3 s (1 s de `/running` + 2 s de `/models`, en serie). Con el DNS colgado se apilan peticiones en el threadpool del daemon. Mejor un `setTimeout` encadenado.
- **El badge «CAÍDO» no nombra el host.** Solo va en el `title` (`web/metrics.py:1467`); con cómputo remoto convendría «`<host>` no responde».

## Llamadas `local_*` hechas: 1

- `local_explain_code(path=web/sysinfo.py, question=comportamiento en macOS)`: ahorró ~2900 tokens. Acertó la lógica y erró números de línea, que verifiqué con `grep`.
- No pasé por `local_*` los tramos de `web/metrics.py` y `server.py` porque necesitaba líneas exactas para citar `fichero:línea` y razonar sobre ramas concretas. Los leí por rangos acotados (~600 líneas en total de un fichero de 1971), nunca enteros.
