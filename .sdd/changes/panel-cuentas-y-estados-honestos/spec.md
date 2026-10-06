# Specification: el panel cuenta bien, dice la causa real y se presenta coherente

## Summary

Las cifras del panel y de `local_status` dejan de contar como ahorro, generación o estimación lo
que fue un fallo, y el ahorro de contexto se enseña **neto**: lo leído server-side menos lo que la
tool devolvió al contexto. La contabilidad expone por evento el desglose **en caracteres** (texto,
imagen, salida a fichero y devuelto), y la conversión a tokens de Claude pasa por **una sola
función**, que el cambio `coste-api-y-cuota` sustituirá. Cuando el backend no está disponible, el
panel, `local_status`, `doctor` y el error de una delegación dicen **qué** falla y **dónde**
(host), con la misma clasificación, y nadie ofrece arrancar un backend que corre en otra máquina.
Una delegación deja de esperar 180 s para descubrir que no puede conectar: el plazo de conexión
baja a 10 s. Los estados del panel (lista de modelos, estado de cada modelo, «En curso», Sistema)
dicen lo que de verdad pasa, el badge solo dice «caído» tras dos sondeos fallidos seguidos, el
sondeo no se solapa, y la presentación sigue una sola regla tipográfica y numérica.

Evidencia y cifras de partida: `research.md`. Decisiones del usuario: `brief.md` («Decisiones del
usuario (2026-10-06)»). Sin release.

## Requirements

### A. Contabilidad (Python `_accounting` y su espejo JS `acct`)

- **REQ-001: una regla, escrita una vez para las dos copias.** `_accounting` (Python, en
  `server.py`) y `acct` (JS, en `web/metrics.py`) implementan exactamente la **Regla de
  contabilidad** de abajo y devuelven los campos del **Contrato con `coste-api-y-cuota`** (nombres
  exactos en la tabla de esa sección). El test de paridad
  (`test_paridad_acct_entre_python_y_el_js_del_panel`) cumple las tres condiciones siguientes:
  - **Casos mínimos**, uno por fila: fallo sin tokens con `chars_out: 144`; fallo troceado con
    tokens; `ok: null`; evento **sin** clave `ok` (con `source: "path"` y `chars_in: 4000`);
    `ok: 0`; neto positivo; neto negativo; `output_to_file` con `source: "path"`; `output_to_file`
    con `source: "inline"`; imagen por `path` con `tokens_in`; imagen por `path` sin `tokens_in`;
    texto por `path` con `chars_in: 3`.
  - **Campos comparados**: todos los del contrato, en las dos copias, leyendo el JS con `.get(...)`
    para que un campo ausente falle por el assert y no por `KeyError`.
  - **Guarda «esto comprobó algo»**: entre los resultados de Python hay al menos un `net < 0`, un
    fallo con `tokens_in > 0`, un caso sin clave `ok`, un `bytes_saved_image > 0` y un
    `chars_saved_output > 0`.
- **REQ-002: un fallo no ahorra, no se estima y no genera texto.** Un evento fallido aporta 0 a
  todos los campos de ahorro y devuelto (en caracteres y en tokens), no cuenta como estimado, y sus
  `tokens_in`/`tokens_out` son solo los que reportó el backend (0 si no reportó ninguno). Sigue
  contando sus llamadas al backend.
- **REQ-003: neto en `/api/stats`.** `/api/stats` añade `tokens_returned` (Σ `returned`) y
  `tokens_context_net` (Σ `net`), y las sumas del desglose en caracteres del contrato.
  `tokens_context_saved` sigue existiendo con el significado de **bruto**, ya sin fallos.
  `by_tool`, `by_backend` y `by_client` añaden `tokens_net`.
- **REQ-004: el panel enseña el neto, también cuando es negativo.** El KPI «Contexto conservado»
  muestra `tokens_context_net`; su pista dice el bruto y el devuelto («bruto 873.270 − devuelto
  72.342»), y su tooltip dice que no descuenta relecturas. Los gráficos que hoy usan
  `acct(e).saved` usan `acct(e).net`, y la columna de ahorro de «Quién delegó» usa `tokens_net`.
  Qué hace cada gráfico con un neto negativo:
  - **«Ahorro por herramienta»** deja de filtrar por `source==='path'` y enseña toda herramienta
    con neto **distinto de 0** (no solo mayor que 0); una barra negativa sale a la izquierda del 0
    y el tooltip lleva el signo. Los demás usos de `agg` (por modelo, por origen) siguen
    descartando las categorías a cero o menos, como hoy.
  - **Chispa del KPI**: sin `min:0` en el eje; un acumulado negativo se ve por debajo del 0.
  - **Serie por día**: ya admite negativos (`beginAtZero`); no cambia.
- **REQ-005: `local_status` cuenta igual que el panel.** Su línea de log dice el neto y el bruto
  del mes actual con la misma función (`~N tokens netos (bruto ~M)`).
- **REQ-006: un solo predicado de fallo.** «Tasa de error» y «Delegaciones» no cambian de
  significado, pero el predicado de fallo es el de la regla (`ok` exactamente `false`) en todos los
  sitios: `_aggregate` (errores por tool y totales; hoy `bool(r.get("ok", True))`, que cuenta
  `ok: null` como error), el respaldo de `render` cuando falta `total.errors` (hoy `!e.ok`) y el
  punto de la tabla de actividad (hoy `e.ok?'ok':'err'`).
- **REQ-007: desglose en caracteres por evento.** `_accounting` y `acct` devuelven, por evento,
  los caracteres ahorrados de texto, los bytes de imagen ahorrados, los caracteres ahorrados de
  salida a fichero y los caracteres devueltos al contexto, más los campos del evento que necesita
  quien convierte (`failed`, `tool`, `model`, `source`, `unit`). Nombres, unidades y definición
  exactos: tabla del **Contrato con `coste-api-y-cuota`**.
- **REQ-008: una sola función convierte a tokens de Claude.** La conversión de lo ahorrado y lo
  devuelto a tokens de Claude pasa **solo** por `tokens_claude(cantidad, *, tipo, evento)` en
  Python y su espejo `tokensClaude(cantidad, tipo, e)` en JS. Ni `_accounting` ni `acct` dividen
  por `CHARS_PER_TOKEN`/`CPT` para calcular `saved`, `returned` o `net`. Este cambio la implementa
  con la regla de hoy (tabla del contrato). Los tokens del modelo **local** (`tokens_in`,
  `tokens_out`, coste local) **no** pasan por ella: siguen con `CHARS_PER_TOKEN`.

#### Regla de contabilidad (normativa; idéntica en Python y JS)

`CPT = 4` (`config.CHARS_PER_TOKEN`); `÷` es división entera hacia abajo (`//` en Python,
`Math.floor(x/CPT)` en JS, la función `tok` que ya existe). «Reportado» = el campo existe en el
evento y no es nulo.

```
failed     := el campo `ok` existe y vale false          (Python: row.get("ok") is False;  JS: e.ok === false)
calls      := chunks, o 1 si falta                         (sin cambio; también en fallos)
unit       := input_unit, o "bytes" si tool == local_describe_image, o "chars"   (sin cambio)
estimable  := unit == "chars"

Coste del modelo LOCAL (no pasa por tokens_claude):
  si failed: tokens_in  := tokens_in reportado, o 0
             tokens_out := tokens_out reportado, o 0
             estimated  := false
  si no:     tokens_in  := tokens_in reportado,  o (chars_in ÷ CPT si estimable, si no 0)   (sin cambio)
             tokens_out := tokens_out reportado, o chars_out ÷ CPT                          (sin cambio)
             estimated  := falta tokens_in o falta tokens_out                               (sin cambio)

Desglose en caracteres (todo 0 si failed):
  chars_saved_text   := chars_in   si source == "path" y estimable
  bytes_saved_image  := chars_in   si source == "path" y no estimable        (la imagen; el log guarda BYTES)
  chars_saved_output := chars_out  si output_to_file                          (el texto escrito al fichero)
  reclama            := source == "path" y no output_to_file y
                        ((estimable y chars_in > 0) o (no estimable y tokens_in reportado > 0))
  chars_returned     := chars_out  si reclama
  (cada campo vale 0 cuando su condición no se cumple)

Tokens de Claude (todo 0 si failed):
  saved    := tokens_claude(chars_saved_text,   tipo="text",   evento)   si source == "path" y estimable
            + tokens_claude(bytes_saved_image,  tipo="image",  evento)   si source == "path" y no estimable
            + tokens_claude(chars_saved_output, tipo="output", evento)   si output_to_file
            (cada sumando vale 0 cuando su condición no se cumple)
  returned := tokens_claude(chars_returned, tipo="returned", evento)
  net      := saved − returned   (puede ser negativo; no se recorta)

fallback, cause: sin cambio.
```

Con la `tokens_claude` de hoy, esta regla da **los mismos** `saved`, `returned` y `net` que la
primera versión de la spec en todo evento salvo uno: un texto por `path` con `0 < chars_in < 4`
(bruto 0) ahora resta su devuelto. Comprobado sobre los cuatro meses reales de esta PC: no hay
ningún evento así, y las cifras de julio a octubre salen idénticas (script de solo lectura,
`scratchpad/contrato.py`).

Qué cuenta y qué no, dicho en claro:

| Concepto | Cuenta | No cuenta |
|---|---|---|
| Bruto (`saved`) | Entrada leída server-side de delegaciones que salieron bien, una vez por delegación; salida escrita a fichero | Fallos; entrada `inline`; el trabajo extra de trocear |
| Devuelto (`returned`) | Lo que la tool devolvió a Claude en las delegaciones que reclaman ahorro de entrada | El recibo de `output_to_file` (no se registra su tamaño: se toma 0); la coletilla de ahorro que se añade después de registrar; el mensaje de error de un fallo |
| Neto (`net`) | Bruto − devuelto, evento a evento | Relecturas del mismo fichero (no están en el log; ver `research.md` §5) |
| Coste local / Generado | Tokens reportados por el backend, también en fallos (la GPU los gastó); estimación ÷ 4 solo en delegaciones que salieron bien | La estimación sobre el texto de un error |
| Estimados | Delegaciones que salieron bien sin `usage` del backend | Fallos |

### B. Causa de un fallo de conexión al backend

- **REQ-010: un solo clasificador, total.** Una función pura en `fallos.py`,
  `causa_conexion(suceso, *, loopback)`, recibe lo que pasó (un `int` con el código de una
  respuesta no 2xx, o una excepción cualquiera) y si el **host** es de loopback, y devuelve
  siempre una causa: la tabla cubre **toda** entrada. Las reglas se aplican **en este orden y gana
  la primera** («cadena» = la excepción y sus `__cause__`/`__context__`, recursivamente, sin
  visitar dos veces la misma excepción):

  | # | Condición | Causa |
  |---|---|---|
  | 1 | Código 401 o 403, o `httpx2.HTTPStatusError` cuyo `response.status_code` es 401 o 403 | `credencial` |
  | 2 | Otro código no 2xx, u otro `httpx2.HTTPStatusError` | `http_error` |
  | 3 | La cadena contiene `httpx2.InvalidURL` o `httpx2.UnsupportedProtocol` | `url_invalida` |
  | 4 | La cadena contiene `socket.gaierror` | `dns` |
  | 5 | La cadena contiene `ConnectionRefusedError` | `rechazada` |
  | 6 | La cadena contiene un `OSError` con errno `ENETUNREACH`, `EHOSTUNREACH`, 10051 o 10065 | `sin_ruta` |
  | 7 | `httpx2.ConnectTimeout` y host de loopback | `rechazada` |
  | 8 | `httpx2.ConnectTimeout` | `timeout_conexion` |
  | 9 | Otra `httpx2.TimeoutException` (lectura, escritura, pool) | `sin_respuesta` |
  | 10 | `ValueError` (2xx con cuerpo que no es JSON o no tiene la forma esperada; ver REQ-012) | `respuesta_invalida` |
  | 11 | Cualquier otra `httpx2.HTTPError` | `transporte` |
  | 12 | Cualquier otra excepción | `desconocida` |

  Alcance de cada regla: las reglas 3 a 6 buscan en **toda la cadena**; las reglas 1, 2 y 7 a 12
  miran **solo la excepción de arriba** (`isinstance` sobre el `suceso`). Así, una excepción
  propia que envuelva un `ConnectTimeout` cae en la 12, y eso es determinista. La función clasifica
  fallos: un `int` 2xx no es un fallo y lanza `ValueError` (error de programación de quien llama);
  fuera de eso, toda excepción y todo código no 2xx tienen causa. Las excepciones de prueba se
  construyen como las crea el socket, con errno y mensaje (`OSError(errno.ENETUNREACH, "…")`,
  `OSError(errno.ECONNREFUSED, "…")`, que Python convierte en `ConnectionRefusedError`): un
  `OSError(10051)` con un solo argumento deja `errno` en `None` y caería en la regla 11
  (comprobado). `httpx2.InvalidURL` no es un `HTTPError` (comprobado contra el `httpx2` instalado),
  por eso va antes y por nombre. «Host de loopback» es el criterio que ya usa `config._is_loopback_host` sobre
  el host real de `BASE_URL` **sin puerto** (`config._split_host_port(config.BASE_URL)[0]`; no
  `config.backend_host()`, que lleva el puerto y con el que `"127.0.0.1:9292"` da `False`,
  comprobado), y no el override `LOCAL_DELEGATE_BACKEND_ORIGIN`. La regla 7 existe
  porque en Windows un puerto cerrado tarda ~2 s en rechazarse y con un plazo menor llega como
  `ConnectTimeout` (`research.md` §2). El caso de la Mac (el kernel agota la conexión a los ~75 s:
  `ConnectTimeout` con `TimeoutError(ETIMEDOUT)` en la cadena, host remoto) cae en la regla 8.
- **REQ-011: textos únicos por causa.** Cada causa tiene una etiqueta corta (badge) y un detalle;
  los dos los produce `fallos.py` y nadie más los redacta. `fallos.py` no lee configuración: el
  host, el código y el endpoint entran como **parámetros** (`detalle(causa, *, host, status=None,
  endpoint=None, excepcion=None)`), y quien llama pasa `config.backend_host()`.

  | Causa | Etiqueta corta | Detalle |
  |---|---|---|
  | `dns` | no resuelve | no se resuelve el nombre `<host>` (¿VPN o DNS?) |
  | `rechazada` | nadie escucha | `<host>` rechaza la conexión: no hay nada escuchando en ese puerto |
  | `sin_ruta` | sin ruta | no hay ruta de red hacia `<host>` |
  | `timeout_conexion` | no contesta | `<host>` no contesta a la conexión (ruta, cortafuegos o VPN) |
  | `credencial` | sin acceso | `<host>` responde `<N>`: está arriba pero rechaza la credencial |
  | `http_error` | responde con error | `<host>` responde HTTP `<N>` |
  | `sin_respuesta` | no responde a tiempo | `<host>` acepta la conexión pero no responde a tiempo |
  | `respuesta_invalida` | respuesta no válida | `<host>` responde a `<endpoint>`, pero con un cuerpo que no se entiende |
  | `url_invalida` | URL no válida | la URL del backend no es válida (`<TipoDeExcepción>`): revisa LOCAL_DELEGATE_BASE_URL |
  | `transporte` | fallo de red | fallo de red con `<host>` (`<TipoDeExcepción>`) |
  | `desconocida` | fallo inesperado | fallo inesperado al sondear `<host>` (`<TipoDeExcepción>`) |

  La pista de la credencial (dónde falta la clave) no va en el detalle sino en la pista de
  `doctor`, que sabe quién vio el 401 (REQ-016).
- **REQ-012: el sondeo del backend da la causa.** `server.sondear_backend()` sondea `/models` y
  devuelve `available`, `models`, `models_stale`, `causa`, `detalle` y `status_http`. `available`
  es `true` solo con un 2xx cuyo cuerpo es un **objeto con una lista `data`**; si no, el sondeo lo
  convierte en `ValueError` (regla 10). Dentro de `data` se conserva la tolerancia de hoy: una
  entrada que no es un objeto se ignora y un `id` ausente se pinta `"?"`. Cualquier excepción que
  aun así escape se clasifica (regla 12): el sondeo **nunca** lanza. Cambio de comportamiento
  declarado: un 2xx sin `data`, que hoy da `available: true` sin modelos, pasa a
  `respuesta_invalida`.
  `/api/backend` y `/api/status` (bloque `backend`) devuelven, además de lo de hoy, `causa` y
  `detalle` (los dos `null` cuando `available` es `true`). Un 401 da `available: false` y `causa:
  "credencial"`.
- **REQ-013: plazo del sondeo.** Todos los sondeos de estado (`/models`, `/running`,
  `/api/metrics/stats` y `doctor.backend_probe`) usan el mismo plazo: **3 s para conectar**
  (`config.TIMEOUT_SONDA_CONEXION`) y **2 s para leer** (`config.TIMEOUT_SONDA_LECTURA`),
  constantes sin variable de entorno. `/api/backend` **y** `local_status` piden `/running` **solo**
  si `/models` respondió, así que con el backend inalcanzable tardan como mucho un plazo de
  conexión.
- **REQ-014: el badge dice la causa.** Con `available` el badge dice «conectado» (verde). Con una
  causa en la que **alguien contesta** (`credencial`, `http_error`, `respuesta_invalida`,
  `sin_respuesta`), dice la etiqueta corta sola («sin acceso», «responde con error»…) en ámbar,
  sin la palabra «caído». Con cualquier otra causa, «caído · `<etiqueta corta>`» en rojo. El
  `title` del badge es el `detalle` (o la URL base cuando está conectado). Lo que el badge pinta es
  el **estado visible** de REQ-028, no el último sondeo.
- **REQ-015: `local_status` dice la causa, con el criterio del badge.** La línea `Backend:` dice
  `arriba`; `SIN ACCESO: <detalle>` para `credencial`; `RESPONDE CON ERROR: <detalle>` para
  `http_error`, `respuesta_invalida` y `sin_respuesta` (hay alguien contestando, como en el ámbar
  de REQ-014); y `CAÍDO: <detalle>` para el resto. `local_status` usa `sondear_backend()` y no tiene
  histéresis (es una sola consulta).
- **REQ-016: `doctor` dice la causa, quién la vio, y no manda a arrancar lo que no está aquí.**
  `doctor.backend_probe()` y `Context.backend_models` devuelven `fallos.VistaBackend(sano,
  detalle, causa, fuente)`, con `fuente` `"daemon"` (la causa viene del `/api/backend` del daemon)
  o `"directo"` (sondeo propio). El check `service.backend` muestra el `detalle`. Severidad: `OK` si
  está sano; `UNKNOWN` si la causa es `credencial` y la fuente es `directo` (falta la clave en
  **esta** consola); `WARN` en el resto, incluida `credencial` vista por el daemon. La pista
  depende de causa, fuente y origen (`config.backend_origin()`):

  | Causa | Origen local | Origen remoto |
  |---|---|---|
  | `rechazada` | arranca llama-swap (o revisa LOCAL_DELEGATE_BASE_URL) | arranca llama-swap en `<host>` o revisa el puerto |
  | `dns` | revisa el nombre en LOCAL_DELEGATE_BASE_URL | revisa el nombre en LOCAL_DELEGATE_BASE_URL o usa la IP (p. ej. la 100.x de la tailnet) |
  | `sin_ruta`, `timeout_conexion` | revisa LOCAL_DELEGATE_BASE_URL | revisa la red hacia `<host>` (VPN, cortafuegos, Tailscale) |
  | `credencial`, fuente `directo` | exporta LOCAL_DELEGATE_API_KEY en este entorno | igual |
  | `credencial`, fuente `daemon` | la clave del daemon no vale: revisa LOCAL_DELEGATE_API_KEY en su lanzador | igual |
  | `http_error`, `respuesta_invalida`, `url_invalida` | revisa LOCAL_DELEGATE_BASE_URL | igual |
  | `sin_respuesta`, `transporte`, `desconocida`, o daemon antiguo sin `causa` | sin pista específica: «revisa el backend en `<host>`» | igual |

  Con origen remoto **ninguna** pista dice «arranca llama-swap» a secas. La consulta de `doctor`
  al daemon (`daemon.query_backend` desde `checks._default_backend_models`) usa 1 s para conectar
  con el daemon y, para leer, **más** que el techo de un sondeo fallido del daemon
  (`TIMEOUT_SONDA_CONEXION + TIMEOUT_SONDA_LECTURA + 1` = 6 s), para que la causa que ve el
  daemon llegue también en los fallos lentos (VPN, puerto cerrado en Windows). Limitación aceptada:
  no cubre un `/models` bueno seguido de un `/running` colgado (hasta 5 + 5 s) ni un DNS que se
  cuelga; ahí `doctor` agota la consulta y sondea por su cuenta, y sin la clave en la consola da
  `UNKNOWN`, como hoy.
- **REQ-017: el error de una delegación dice la causa.** Cuando `_post_chat` devuelve
  `connect_error`, el texto es `[local-delegate error] no se pudo conectar con el backend:
  <detalle>`, y `ChatResult` lleva la causa en un campo nuevo `fallo_conexion: str | None`. Los
  **tres** caminos que registran una delegación lo pasan a `_log_event`, que escribe la clave
  `fallo_conexion` solo cuando no es `None`: la delegación simple (`_chat`), la troceada y la de
  imagen. `error` sigue valiendo `connect_error` y `error_class` no cambia (compatibilidad del log
  y del enfriamiento).
- **REQ-018: no se ofrece arrancar un backend remoto.** Con `config.backend_origin() == "remote"`,
  un fallo de conexión no pregunta «¿Lo arranco?» ni llama a `autostart.ensure_backend`, tenga
  `LOCAL_DELEGATE_AUTOSTART` el valor que tenga. Con origen local, todo sigue como hoy, y la suite
  lo sigue probando: la URL de los fixtures (`http://test-backend/v1`) es **remota** para
  `config.backend_origin()`, así que todo test que compruebe la pregunta o el autoarranque **fija
  el origen** de forma explícita (`config.BACKEND_ORIGIN_OVERRIDE = "local"` o una URL de
  `127.0.0.1`), y al menos un test comprueba que el autoarranque y la pregunta se siguen
  ejercitando.
- **REQ-019: una delegación se rinde a los 10 s si no puede conectar.** El cliente de las
  delegaciones (`server._get_client`) usa `httpx2.Timeout(config.HTTP_TIMEOUT,
  connect=min(config.TIMEOUT_CONEXION_DELEGACION, config.HTTP_TIMEOUT))`, con
  `TIMEOUT_CONEXION_DELEGACION = 10.0` (constante, sin variable de entorno). Solo cambia el plazo de
  **conexión**: lectura, escritura y pool siguen en `HTTP_TIMEOUT` (180 s por defecto), así que la
  espera de carga de un modelo, que es de lectura, no cambia. Las delegaciones simples, troceadas y
  de imagen comparten ese cliente. Motivo: cada fallo de la Mac bloqueó ~75–95 s
  (`insumos/anomalias-panel.md`, punto 10).

### C. Estados del panel

- **REQ-020: el mensaje de versión solo cuando falta la versión.** `/api/backend/stats` devuelve
  `causa`, `detalle` y `status_http` cuando no hay datos. El panel dice «sin datos (este backend no
  expone /api/metrics/stats: requiere llama-swap ≥ v236)» **solo** con `status_http == 404`;
  «sin datos: `<etiqueta corta>`» con cualquier otra causa.
- **REQ-021: la lista de modelos no cambia con la conexión.** El daemon guarda en memoria la
  última lista buena de `/v1/models` **por `BASE_URL`**: cuando el backend no responde,
  `/api/backend` y `/api/status` devuelven la lista guardada **para esa misma URL** con `status:
  null` en cada modelo y `models_stale: true`; con una URL sin lista guardada, `models: []`. El
  panel toma la lista del sondeo de 2 s (no del de 60 s), la une al catálogo y la ordena así:
  primero por la posición del primer rol del catálogo que lo usa (mecánico, largo, código,
  visión), después los modelos sin rol por id alfabético. Con y sin conexión salen las mismas
  filas en el mismo orden. Las filas se atenúan según el **estado visible** de REQ-028 (atenuadas
  solo cuando es «no disponible»), **no** según `models_stale`, que ya viene `true` desde el primer
  sondeo fallido.
- **REQ-022: el estado de cada modelo distingue cola propia, carga y turno.** El texto de la fila
  sale de esta tabla, **en orden, gana la primera**. Definiciones: «disponible» = el estado
  visible de REQ-028; «en vuelo» = hay alguna llamada de `/api/inflight` a ese modelo (dato
  propio, siempre del último `/api/inflight`); «en espera local» = todas esas llamadas llevan el
  campo `espera_local` (ver abajo); «running», `status` y
  `running_ok` se leen del **sondeo de referencia** de REQ-028 (el último sondeo bueno mientras el
  estado visible conserva «disponible» tras un fallo; el último sondeo en otro caso): «running» =
  su `state` en `/running`, `status` = el de `/v1/models`, `running_ok` = `/running` respondió en
  ese sondeo (campo nuevo de `/api/backend`). Las condiciones se leen **tal cual**: los paréntesis
  de la última columna explican qué queda a esas alturas, no son parte de la condición.

  | # | Condición | Texto | Nota |
  |---|---|---|---|
  | 1 | No disponible y en vuelo | esperando al backend | |
  | 2 | No disponible | desconocido | `title`: «sin conexión con el backend: `<etiqueta corta>`» |
  | 3 | En vuelo y en espera local | en cola local | `title`: «esperando dentro de local-delegate: `<motivo en palabras>`» |
  | 4 | `running_ok` falso y en vuelo | en curso | (backend que no es llama-swap) |
  | 5 | `running_ok` falso | montado si `status == "loaded"`, si no frío | |
  | 6 | running `starting` | cargando | |
  | 7 | running `ready` y en vuelo | procesando | |
  | 8 | running `ready` | montado | |
  | 9 | En vuelo | esperando turno | (alguna llamada ya se envió a llama-swap, y running es `stopping` o el modelo no está en `/running`) |
  | 10 | running `stopping` | descargando | |
  | 11 | Resto | frío | |

  En la fila 9 el `title` no afirma la causa: «llama-swap aún no lo atiende; en /running: `<lista>`»,
  con cada modelo de `/running` y su estado en palabras («gemma4-26b-a4b listo, qwen36-35b-a3b
  cargando»), o «llama-swap aún no lo atiende; /running está vacío».

  **Espera local (`espera_local`).** Toda espera **dentro de local-delegate**, antes de enviar la
  petición a llama-swap, se publica en la entrada en vuelo con el campo `espera_local`, cuyo valor
  es el motivo como texto, y se borra en cuanto la espera termina. Ausente o `null` = la llamada no
  está esperando dentro de local-delegate. La fila 3 («en cola local») cubre **cualquier** motivo, y
  la fila 9 («esperando turno») queda **solo** para lo que ya se envió a llama-swap: el panel no le
  atribuye a llama-swap una espera nuestra.
  - Hoy hay un motivo, `"plaza"`: la llamada espera plaza en el semáforo propio
    (`MAX_CONCURRENT_REQUESTS`). En palabras: «esperando plaza (máximo de llamadas a la vez)».
  - **Punto de extensión.** Otra espera local futura (por ejemplo el turno por grupo `swap` que
    añadirá `daemon-reparte-el-backend`, su REQ-027) solo tiene que escribir `espera_local` con su
    propio motivo mientras dure la espera: no hace falta tocar la tabla ni `estadoModelo`. Un motivo
    que el panel no conoce se pinta tal cual en el `title` («esperando dentro de local-delegate:
    `<motivo>`»); ponerle palabras es opcional.
- **REQ-023: la chip de estado acepta cualquier valor.** Una función pura `chipEstado(status)`
  decide la clase: `loaded` y `unloaded` con su estilo de hoy, cualquier otro texto con un estilo
  neutro, y `null` o ausente sin chip.
- **REQ-024: «Última delegación» cuando nada corre.** El título del panel «En curso» pasa a
  «Última delegación» mientras pinta la última terminada, y vuelve a «En curso» con llamadas vivas.
  Sin ningún evento sigue «En curso» con «Sin delegaciones todavía».
- **REQ-025: el panel Sistema explica el cómputo remoto y la plataforma.** `/api/system` añade
  `platform` (`sys.platform`), `origin` y `host`. Con `origin == "remote"` la sección de procesos
  lleva siempre la nota «El backend corre en `<host>`: su RAM y VRAM se ven en el panel de esa
  máquina», haya o no procesos locales, y sin procesos esa nota es **lo único** que se ve (no
  sale «Ningún proceso del backend detectado»). La nota es prosa: va en Inter (REQ-034). Con
  `origin == "local"` y sin procesos: en una plataforma que no sea `win32` ni `linux`, «La lista de
  procesos no está disponible en `<platform>` todavía»; en `win32` y `linux`, el texto de hoy. Las
  métricas de memoria van aparte: sin RAM ni VRAM y con `platform == "darwin"`, «RAM y VRAM no se
  miden en macOS todavía»; en otra plataforma, el texto de hoy.
- **REQ-026: el sondeo no se solapa ni se congela.** `/api/inflight` y `/api/backend` se piden por
  **separado**, cada uno con su guarda: como mucho una petición de cada uno en vuelo. El siguiente
  sondeo de cada uno se programa 2 s **después de que termine** el anterior (con éxito o con
  error), y una llamada manual (pestaña visible otra vez, «Refrescar») mientras hay uno en vuelo no
  lanza otro. Así, un `/api/backend` lento no congela «En curso».
- **REQ-027: al reconectar se refresca todo.** Cuando el estado visible (REQ-028) pasa de «no
  disponible» a «disponible», el panel pide `/api/status` y `/api/backend/stats` en ese momento,
  sin esperar al ciclo de 60 s.
- **REQ-028: dos sondeos fallidos antes de «caído».** El panel deriva un **estado visible** del
  backend con una función pura (`estadoVisible(prev, bj)`), que es lo que usan el badge (REQ-014),
  las filas de modelos (REQ-022) y el refresco al reconectar (REQ-027):
  - Un sondeo con `available: true` lo deja disponible **al instante**.
  - Un sondeo fallido tras otro bueno **conserva** lo que se pintaba, y el `title` del badge añade
    «último sondeo: `<detalle>`». **Las filas de modelos también lo conservan**: `estadoVisible`
    guarda el último sondeo bueno y lo devuelve como sondeo de referencia, así que cada fila sigue
    con su último estado conocido («montado», «procesando»…) y sin atenuar. El sondeo fallido no
    las toca aunque traiga `models_stale: true`, `status: null` y `running_ok: false`.
  - El **segundo** sondeo fallido seguido lo pasa a no disponible, con la causa del último: el
    badge deja de decir «conectado» (dice «caído · …», o la etiqueta ámbar de REQ-014) y **solo
    entonces** las filas pasan a «desconocido» (o «esperando al backend» las que tienen algo en
    vuelo), atenuadas.
  - Con el panel recién abierto (sin ningún sondeo bueno todavía), el primer fallo pinta
    «comprobando…» en estilo neutro y las filas, sin último estado que conservar, «desconocido»;
    el segundo fallo pinta la causa.

  `local_status` y `doctor` no tienen histéresis: son una sola consulta y dicen lo que ven.

### D. Presentación

- **REQ-030: miles siempre agrupados, sin depender del navegador.** Todo entero que el panel
  formatea con `F` sale con separador de miles a partir de 4 cifras (`8.003`, no `8003`). `F` y
  `F1` se construyen sobre una función propia, `fmtNum(n, decimales)` (punto de miles, coma
  decimal, signo menos), y no sobre `Intl.NumberFormat` con `useGrouping: 'always'`, que un
  navegador sin `Intl.NumberFormat` v3 convierte en `true` y vuelve a pintar `8003` sin avisar. La
  definición de `F` sigue en la sentencia `const CPT = 4, F = …, PAGE = 10;`.
- **REQ-031: decimales con coma.** Todo número con decimales del panel sale con **un** decimal y
  coma, con el mismo formateador (`F1`): tok/s de llama-swap, GiB de RAM/VRAM, % de la tasa de
  error y de las tablas de hooks y clientes, segundos de «En curso».
- **REQ-032: latencia en segundos.** Toda latencia se muestra en segundos con un decimal mediante
  `fmtSeg(ms)`: `116,9 s`, `0,1 s`; por debajo de 50 ms, «< 0,1 s» (nunca «0,0 s»). Se aplica al
  KPI «Latencia media», la columna de la tabla de actividad, la duración de la última delegación y
  el tiempo transcurrido de las que están en curso.
- **REQ-033: plurales sin paréntesis.** «1 estimado / 4 estimados», «1 delegación / 2
  delegaciones», «1 archivo leído / 2 archivos leídos», «1 evento / 2 eventos». No queda ninguno
  de los literales `archivo(s)`, `leído(s)`, `delegación(es)` ni `estimado(s)`.
- **REQ-034: tipografía por rol.** Etiquetas y prosa en Inter; datos (cifras, ids, rutas) y
  estados vacíos en JetBrains Mono. En concreto: (a) todas las cabeceras `thead th` en Inter;
  (b) la chip «DAEMON MCP» con la misma familia que `.mrole` y `.mstatus`; (c) la fila vacía de
  procesos con la misma familia que `.empty`; (d) la nota de la tarjeta de hooks en Inter; (e) la
  primera columna de «Sugerencias de los hooks» y «Quién delegó» en mono; (f) la hoja de Google
  Fonts pide JetBrains Mono 400; (g) `button, input, select, textarea` heredan la familia; (h) la
  nota de cómputo remoto de REQ-025 en Inter.

### E. Documentación

- **REQ-040:** la wiki (`docs/wiki/Savings-and-metrics.md`, `Troubleshooting.md`, `Daemon.md` y
  `Remote-backend.md` donde aplique) describe la regla de contabilidad con el neto y el desglose,
  las causas de conexión con su pista, el plazo de conexión de 10 s, la histéresis del badge y los
  estados nuevos del panel; `CHANGELOG.md` lo recoge en `[Unreleased]`, con una nota visible de
  que no se publica versión hasta mezclar `coste-api-y-cuota` («Restricciones de entrega»). El mock de
  `scripts/dev/capture_dashboard.py` incluye las claves nuevas. No hay release ni captura nueva.

## Restricciones de entrega

- **No se publica ninguna versión hasta que `coste-api-y-cuota` esté mezclado.** Este cambio
  puede mezclarse en `main`, pero sus cifras en tokens de Claude salen de la `tokens_claude` de hoy
  (chars ÷ 4), que es una cifra intermedia: la versión que las publique tiene que llevar ya la
  función de `coste-api-y-cuota`. El `[Unreleased]` del `CHANGELOG.md` lo anota de forma visible
  para quien prepare la siguiente release (REQ-040). No hay guardián en código: la restricción vive
  en esta spec, en la tarea de documentación y en el CHANGELOG.
- La verificación final reinstala en el daemon de esta PC la versión publicada (0.32.0) al
  terminar, para que el panel de uso diario no enseñe la cifra intermedia.

## Contrato con `coste-api-y-cuota`

Este cambio **define** la contabilidad y el desglose; `coste-api-y-cuota` los **consume** y solo
sustituye la función de conversión. Los dos cambios salen en la **misma versión** (ver
«Restricciones de entrega»), así que ninguna release publica la cifra intermedia (tokens de
Claude calculados con chars ÷ 4).

**Campos por evento** (`_accounting` en Python / `acct` en JS):

| Python | JS | Unidad | Definición |
|---|---|---|---|
| `chars_saved_text` | `charsSavedText` | caracteres | `chars_in` de un evento bueno con `source == "path"` y unidad `chars` |
| `bytes_saved_image` | `bytesSavedImage` | **bytes** | `chars_in` de un evento bueno con `source == "path"` y unidad distinta de `chars` (la imagen) |
| `chars_saved_output` | `charsSavedOutput` | caracteres | `chars_out` de un evento bueno con `output_to_file` (el texto escrito al fichero) |
| `chars_returned` | `charsReturned` | caracteres | `chars_out` de un evento bueno que reclama ahorro de entrada (regla) |
| `saved`, `returned`, `net` | igual | tokens de Claude según `tokens_claude` | regla de contabilidad |
| `failed` | `failed` | booleano | `ok` exactamente `false` |
| `tool`, `model`, `source` | igual | texto | copia del evento (`model` = el modelo local que respondió) |
| `unit` | `unit` | texto | unidad de entrada deducida (`chars` o `bytes`) |
| `backend_calls`, `tokens_in`, `tokens_out`, `estimated`, `fallback`, `cause` | `calls`, `tokensIn`, `tokensOut`, `estimated`, `fallback`, `cause` | llamadas / tokens del modelo **local** | sin cambio de significado salvo REQ-002 |

**Totales** en `/api/stats` (al nivel de `tokens_context_saved`): `chars_saved_text`,
`bytes_saved_image`, `chars_saved_output` y `chars_returned` (sumas), `tokens_context_saved`
(Σ `saved`), `tokens_returned` (Σ `returned`) y `tokens_context_net` (Σ `net`); `tokens_net` en
`by_tool`, `by_backend` y `by_client`.

**Función de conversión** (una en cada lenguaje, y nada más convierte a tokens de Claude):
`tokens_claude(cantidad: int, *, tipo: str, evento: dict) -> int` en `server.py` y
`tokensClaude(cantidad, tipo, e)` en el JS del panel. `evento` es la fila cruda del log, para que
la sustituta pueda leer `tool`, la extensión de `path` o el modelo. Regla de hoy, que implementa
este cambio:

| `tipo` | Hoy devuelve |
|---|---|
| `"text"` | `cantidad ÷ 4` |
| `"returned"` | `cantidad ÷ 4` |
| `"output"` | `tokens_out` reportado por el backend si existe; si no, `cantidad ÷ 4` |
| `"image"` | `tokens_in` reportado por el backend si existe; si no, 0 |

La regla de hoy de `"output"` e `"image"` usa tokens del modelo **local**, como ya hacía
`_accounting`; se conserva para que las cifras no cambien en este cambio. Sustituirla es decisión
de `coste-api-y-cuota` (su REQ-020 deja imágenes y salida a fichero fuera de la base de coste).

**Qué queda fijo y qué no.** Las cifras en **caracteres** de este cambio no dependen de la
función y valen igual antes y después de `coste-api-y-cuota`. Las cifras en **tokens**
(`tokens_context_net`, 800 928 en septiembre, el escenario del KPI) valen con la función de hoy;
cuando `coste-api-y-cuota` la sustituya, cambiarán, y ese cambio es el que las documenta. Por eso
el control con datos reales de este cambio se fija **en caracteres y en tokens**.

**Lo que `coste-api-y-cuota` debe citar** (no se edita aquí; queda anotado para su agente): estos
nombres de campo, la firma de `tokens_claude`/`tokensClaude`, y que su test de paridad cubre la
función sustituta con un caso cuyo resultado cambia entre la regla de hoy y la suya.

## Acceptance scenarios

### Scenario: un fallo no infla las cuentas (REQ-002)

- **Given** un evento `{"source":"path","chars_in":4000,"chars_out":144,"ok":false}` sin tokens
- **When** se contabiliza con `_accounting` y con `acct`
- **Then** las dos copias dan `saved = returned = net = 0`, `chars_saved_text = chars_returned =
  0`, `tokens_in = tokens_out = 0`, `estimated = false`, `failed = true` y `calls = 1`

### Scenario: un fallo a mitad de un troceo conserva el coste real (REQ-002)

- **Given** `{"chunks":3,"ok":false,"tokens_in":900,"tokens_out":10,"source":"path","chars_in":4000}`
- **When** se contabiliza
- **Then** `calls = 3`, `tokens_in = 900`, `tokens_out = 10` y `saved = net = 0`

### Scenario: el neto resta lo que volvió al contexto (REQ-001, REQ-003, REQ-007)

- **Given** `{"source":"path","chars_in":4000,"chars_out":400,"ok":true,"tokens_in":1100,"tokens_out":90}`
- **When** se contabiliza
- **Then** `chars_saved_text = 4000`, `chars_returned = 400`, `saved = 1000`, `returned = 100`,
  `net = 900`

### Scenario: la salida a fichero no descuenta el recibo (REQ-001, REQ-007)

- **Given** `{"source":"inline","output_to_file":true,"chars_out":4000,"tokens_out":950,"ok":true,"tokens_in":10}`
- **When** se contabiliza
- **Then** `chars_saved_output = 4000`, `chars_returned = 0`, `saved = 950`, `returned = 0`,
  `net = 950`

### Scenario: una imagen por `path` (REQ-007)

- **Given** `{"tool":"local_describe_image","source":"path","chars_in":250000,"chars_out":800,"ok":true,"tokens_in":1200,"tokens_out":200}`
- **When** se contabiliza
- **Then** `bytes_saved_image = 250000`, `chars_saved_text = 0`, `chars_returned = 800`,
  `saved = 1200`, `returned = 200`, `net = 1000`

### Scenario: el neto puede ser negativo (REQ-001)

- **Given** `{"source":"path","chars_in":400,"chars_out":800,"ok":true,"tokens_in":120,"tokens_out":200}`
- **When** se contabiliza
- **Then** `saved = 100`, `returned = 200`, `net = −100`

### Scenario: la conversión pasa por una sola función (REQ-008)

- **Given** `tokens_claude` (y `tokensClaude`) sustituida por una que devuelve siempre 7
- **When** se contabiliza el evento del escenario «el neto resta»
- **Then** `saved = 7`, `returned = 7`, `net = 0`, y `tokens_in = 1100` (el coste local no pasa
  por ella)

### Scenario: un log sintético como el de la Mac (REQ-002, REQ-003, REQ-004)

- **Given** un log **sintético** con 4 delegaciones buenas con `usage` y 4 fallos `connect_error`
  con `chars_out: 144`, `source: "path"` y sin tokens (el real tuvo 5 fallos; aquí basta con 4)
- **When** se pide `/api/stats`
- **Then** `estimated_events == 0`, `tokens_context_saved` y `tokens_generated_local` solo suman
  las 4 buenas, y `tokens_context_net == tokens_context_saved − tokens_returned`

### Scenario: septiembre de la PC (REQ-001 a REQ-003, REQ-007; paso **manual** de verificación)

- **Given** el `usage-202609.jsonl` de esta PC (mes cerrado). No va al repo como *fixture*: guarda
  rutas de ficheros del usuario. Se corre a mano en la verificación final, con el comando del plan,
  y la salida queda en `verification.md`.
- **When** se agrega con la regla nueva y la `tokens_claude` de hoy
- **Then** en caracteres: texto 3 463 739, imagen 1 489 047 bytes (5 imágenes), salida a fichero
  5 237 (3 eventos), devuelto 289 554; en tokens: bruto 873 270, devuelto 72 342, neto 800 928;
  0 estimados (cifras de `research.md` §3 y de `scratchpad/contrato_chars.py`)

### Scenario: el panel enseña el neto y el bruto (REQ-004)

- **Given** `/api/stats` con `tokens_context_net = 800928`, `tokens_context_saved = 873270`,
  `tokens_returned = 72342`
- **When** se pinta el panel
- **Then** el KPI dice `800.928` y la pista contiene `873.270` y `72.342`

### Scenario: una herramienta con neto negativo no desaparece (REQ-004)

- **Given** eventos de dos herramientas: `a` con neto total 500 y `b` con neto total −100
- **When** se calcula la serie de «Ahorro por herramienta»
- **Then** salen `["a", 500]` y `["b", -100]`; y una herramienta con neto 0 no sale

### Scenario: cada fallo real tiene su causa (REQ-010)

- **Given** la máquina del CI (Ubuntu, Windows y macOS) o esta PC, sin dobles de red y sin `skip`
- **When** se sondea `http://no-existe.invalid:9292/v1/models`, un puerto de `127.0.0.1` recién
  liberado con el plazo de producción, y `http://192.0.2.1:9292/v1/models` con 0,5 s de conexión
- **Then** las causas son `dns`, `rechazada` y `timeout_conexion` o `sin_ruta` (según la red);
  nunca `dns` ni `rechazada` para la tercera. Esperado igual en los tres sistemas.

### Scenario: un puerto cerrado en otra máquina no parece una VPN (REQ-010, REQ-013)

- **Given** una IP propia **no** de loopback (la de la interfaz de salida) y un puerto libre en
  ella, con el plazo de conexión de producción (3 s)
- **When** se sondea
- **Then** la causa es `rechazada` en los tres sistemas (en Windows tarda ~2,1 s; en Linux y macOS
  el rechazo es inmediato). Con un plazo de 1 s, en Windows saldría `timeout_conexion`: es el
  control del plazo.

### Scenario: el caso de la Mac, sin la Mac (REQ-010)

- **Given** un `httpx2.ConnectTimeout` cuya cadena contiene `TimeoutError(errno.ETIMEDOUT)`
- **When** se clasifica con `loopback=False`
- **Then** la causa es `timeout_conexion`; con `loopback=True`, `rechazada`

### Scenario: un 401 es un backend vivo (REQ-010, REQ-012, REQ-014)

- **Given** un backend que responde 401 a `/v1/models`, y también un `httpx2.HTTPStatusError`
  construido con una respuesta 401
- **When** se pide `/api/backend` (dos veces, por REQ-028) y se clasifica la excepción
- **Then** `available: false`, `causa: "credencial"` en los dos casos, y el badge dice «sin
  acceso» en ámbar, sin «caído»

### Scenario: un cuerpo con otra forma no rompe el sondeo (REQ-012)

- **Given** `/v1/models` responde 200 con el cuerpo `[]`
- **When** se llama a `sondear_backend()`
- **Then** no lanza, `available: false` y `causa: "respuesta_invalida"`

### Scenario: la Mac con la VPN (REQ-016, REQ-017, REQ-018, REQ-019)

- **Given** `LOCAL_DELEGATE_BASE_URL` con un host remoto que agota el plazo de conexión
- **When** una tool delega
- **Then** se rinde en ≤ 10 s más un margen, no se pregunta «¿Lo arranco?», no se llama a
  `autostart.ensure_backend`, el texto dice «`<host>` no contesta a la conexión (ruta,
  cortafuegos o VPN)» y la línea del log lleva `"fallo_conexion": "timeout_conexion"` y
  `"error": "connect_error"`
- **And** `doctor` da `WARN` con la pista «revisa la red hacia `<host>`», sin «arranca llama-swap»

### Scenario: `doctor` con daemon que no ve el backend (REQ-016)

- **Given** un daemon cuyo `/api/backend` responde `{"available":false,"causa":"dns","detalle":"no se resuelve el nombre pc.lan (¿VPN o DNS?)"}`
- **When** se ejecuta el check `service.backend`
- **Then** el mensaje contiene ese detalle y la pista es la de `dns` para el origen configurado

### Scenario: el 401 lo ve el daemon (REQ-016)

- **Given** un daemon cuyo `/api/backend` responde `{"available":false,"causa":"credencial",…}`
- **When** se ejecuta el check `service.backend`
- **Then** es `WARN` (no `UNKNOWN`) y la pista manda al lanzador del daemon, no a esta consola

### Scenario: la versión de llama-swap solo se culpa con un 404 (REQ-020)

- **Given** `/api/backend/stats` con `{available:false, causa:"dns", ...}`
- **When** se pinta la tarjeta de métricas de llama-swap
- **Then** dice «sin datos: no resuelve» y no menciona v236; con `status_http: 404` sí lo menciona

### Scenario: la lista de modelos no baila (REQ-021)

- **Given** el backend respondió con `[gemma4-12b, gemma4-26b-a4b, qwen35-2b, qwen36-35b-a3b]` y
  el catálogo asigna mecánico y largo a `gemma4-26b-a4b`, código a `qwen36-35b-a3b` y visión a
  `gemma4-12b`
- **When** el backend deja de responder (dos sondeos)
- **Then** el panel enseña las mismas cuatro filas en este orden: `gemma4-26b-a4b`,
  `qwen36-35b-a3b`, `gemma4-12b`, `qwen35-2b`; atenuadas y con «desconocido»
- **And** si la `BASE_URL` del daemon fuera otra, `models` vendría vacío

### Scenario: cargando, turno y cola propia (REQ-022)

- **Given** una llamada en vuelo a `qwen36-35b-a3b` con plaza y `/running` con
  `[{model:"gemma4-26b-a4b",state:"ready"}]`
- **When** se pinta la fila de `qwen36-35b-a3b`
- **Then** dice «esperando turno» con el `title` «llama-swap aún no lo atiende; en /running:
  gemma4-26b-a4b listo»
- **And** si `/running` pasa a `[{model:"qwen36-35b-a3b",state:"starting"}]`, dice «cargando»,
  aunque `/v1/models` diga `loaded`
- **And** si la llamada lleva `espera_local: "plaza"` (o cualquier otro motivo, p. ej.
  `"turno_grupo"`), dice «en cola local», esté como esté
  `/running`

### Scenario: nada corre (REQ-024)

- **Given** ninguna llamada viva y una última delegación terminada hace 8 s
- **When** se pinta el panel
- **Then** el título dice «Última delegación», no «En curso»

### Scenario: Sistema en la Mac con cómputo remoto (REQ-025)

- **Given** `/api/system` con `platform: "darwin"`, `origin: "remote"`, `host: "100.64.0.2:9292"`,
  sin RAM ni procesos
- **When** se pinta la tarjeta
- **Then** dice «RAM y VRAM no se miden en macOS todavía» y «El backend corre en
  100.64.0.2:9292…», en Inter, y no dice «Ningún proceso del backend detectado»

### Scenario: el sondeo no se apila ni congela «En curso» (REQ-026)

- **Given** un `/api/backend` que no responde nunca y un `/api/inflight` que responde al instante
- **When** se llama al sondeo tres veces seguidas
- **Then** hay como mucho una petición de cada endpoint en vuelo, y «En curso» se pinta igual

### Scenario: dos fallos antes de «caído» (REQ-027, REQ-028)

- **Given** la secuencia de sondeos bueno, fallido, fallido, bueno
- **When** se deriva el estado visible tras cada uno
- **Then** se ve conectado, conectado (con «último sondeo: …» en el `title`), caído, conectado, y
  en el último paso se piden `/api/status` y `/api/backend/stats`
- **And** con el panel recién abierto y un primer sondeo fallido se ve «comprobando…»

### Scenario: las filas aguantan el primer fallo (REQ-022, REQ-028)

- **Given** un sondeo bueno con `gemma4-26b-a4b` `loaded` y `ready` en `/running`, sin nada en
  vuelo, y después un sondeo fallido (`models_stale: true`, `status: null`, `running_ok: false`)
- **When** se pinta la fila de `gemma4-26b-a4b` tras cada sondeo
- **Then** tras el bueno y tras el primer fallo dice «montado», sin atenuar, y el badge sigue
  «conectado»
- **And** tras un segundo fallo seguido dice «desconocido», atenuada, y el badge dice «caído · …»

### Scenario: `local_status` no llama caído a quien contesta (REQ-015)

- **Given** un backend que responde 500 a `/v1/models`
- **When** se llama a `local_status`
- **Then** la línea `Backend:` empieza por `RESPONDE CON ERROR:` y no contiene `CAÍDO`

### Scenario: números y latencia (REQ-030 a REQ-033)

- **Given** 8003 tokens, una latencia media de 116 948 ms, otra de 30 ms y 1 estimado, en un
  navegador cuyo `Intl.NumberFormat` ignora `useGrouping: 'always'`
- **When** se pinta el panel
- **Then** se lee `8.003`, `116,9 s`, `< 0,1 s` y «1 estimado»

### Scenario: una sola familia por rol (REQ-034)

- **Given** el panel con las tarjetas de hooks, clientes, actividad y procesos con datos
- **When** se mide `getComputedStyle().fontFamily`
- **Then** todas las `thead th` comparten familia (Inter); `.selfchip` comparte la de `.mrole`; la
  fila vacía de procesos, la de `.empty`; la nota de hooks es Inter; la primera columna de
  «Sugerencias de los hooks» y de «Quién delegó» es mono; el botón «Refrescar» tiene la familia del
  `body`; y el `href` de Google Fonts contiene `JetBrains+Mono:wght@400`. `getComputedStyle()`
  devuelve la familia declarada aunque falte la cara, por eso (f) se comprueba por la URL.

## Edge cases and failure behavior

- **Evento sin `ok`** (no debería existir, el log lo escribe siempre): cuenta como bueno en las dos
  copias (`failed` exige `ok === false`). Evento con `ok: null` u `ok: 0`: también bueno, y no
  suma a errores (REQ-006).
- **Fallo con tokens reales**: sus tokens cuentan en coste y generado; nunca en ahorro (REQ-002).
- **Neto negativo** por evento o en total: se enseña tal cual, con signo, en el KPI y en los
  gráficos (REQ-004).
- **Texto por `path` con `0 < chars_in < 4`**: bruto 0 y devuelto `chars_out ÷ 4`, así que el neto
  es negativo (único cambio frente a la primera regla; no hay ninguno en los logs reales).
- **Imagen por `path`**: el bruto es el token real de entrada del modelo local (regla de hoy de
  `tokens_claude`) y el devuelto es la descripción. Sin `tokens_in` reportado, ni bruto ni
  devuelto (no reclama ahorro).
- **`output_to_file` con `source=path`**: bruto = entrada + salida escrita; devuelto 0.
- **Logs históricos**: se recalculan solos, porque las cuentas se hacen al leer el log. Las cifras
  de meses pasados **bajan** (agosto, −32 %); el CHANGELOG lo avisa.
- **Backend que no es llama-swap** (`/running` da 404): `running_ok: false` y se usan las filas 4 y
  5 de la tabla de REQ-022; la tarjeta de métricas dice el texto del 404.
- **Respaldo**: la entrada en vuelo lleva el modelo **pedido**; si responde un respaldo, la fila del
  pedido puede decir «esperando turno» mientras trabaja otro modelo. Limitación conocida, fuera de
  alcance.
- **Túnel en loopback hacia un backend remoto** (`LOCAL_DELEGATE_BACKEND_ORIGIN=remote`): el
  clasificador usa el host real (loopback) y la pista y la pregunta usan el origen declarado
  (remoto), así que no se ofrece arrancar nada.
- **Daemon que arranca con el backend caído**: no hay lista buena que conservar; se ve solo el
  catálogo hasta la primera respuesta (anotado en `research.md` §8).
- **DNS que se cuelga**: `getaddrinfo` no respeta el plazo de `httpx2`, así que el sondeo puede
  tardar más; REQ-026 evita que se apilen y que congele «En curso». `doctor` puede agotar su
  consulta al daemon y sondear por su cuenta (limitación de REQ-016).
- **`/v1/models` con un 2xx sin `data`**: hoy da «disponible» sin modelos; pasa a
  `respuesta_invalida`. Las entradas sueltas que no son objetos, o sin `id`, se toleran como hoy
  (REQ-012).
- **Primer fallo tras un sondeo bueno**: badge y filas conservan el último estado conocido; nada
  pasa a «desconocido» hasta el segundo fallo seguido (REQ-028).
- **Daemon antiguo** (sin `causa` en `/api/backend`) preguntado por un `doctor` nuevo: se usa el
  texto de hoy y la pista genérica de la última fila de REQ-016.
- **`LOCAL_DELEGATE_TIMEOUT` menor que 10 s**: el plazo de conexión de las delegaciones es el
  menor de los dos (REQ-019).
- **Pestaña oculta**: el sondeo no corre (como hoy); al volver, uno solo de cada endpoint (REQ-026).

## Non-functional requirements

- **Privacidad**: `detalle` y `fallo_conexion` llevan host y causa, nunca credenciales ni
  cabeceras; `backend_host()` ya quita usuario y contraseña de la URL.
- **Compatibilidad del log**: solo se **añade** `fallo_conexion`; ninguna clave cambia de
  significado. `error`, `error_class` y el enfriamiento no cambian. La entrada en vuelo
  (`inflight.json`, no es el log) añade `espera_local`.
- **Compatibilidad de la API**: `/api/stats`, `/api/backend`, `/api/backend/stats`, `/api/status`,
  `/api/system` y `/api/inflight` solo añaden claves; `tokens_context_saved` conserva su nombre y
  su significado de bruto. `tokens_context_net` cambiará de densidad con `coste-api-y-cuota`, en
  la misma versión (contrato).
- **Rendimiento**: con el backend inalcanzable, `/api/backend` y `local_status` tardan como mucho
  ~3 s; el siguiente sondeo del panel no sale hasta 2 s después; una delegación que no puede
  conectar se rinde en ≤ 10 s.
- **Accesibilidad**: el color del badge no es la única señal: el texto dice la causa.
- **Sin dependencias nuevas** ni variables de entorno nuevas (los tres plazos nuevos son
  constantes de `config.py`).

## Non-goals

- Coste a precio de API, % de cuota y la densidad real de tokens de Claude: cambio
  `coste-api-y-cuota`, que sustituye `tokens_claude` y usa el desglose de aquí.
- La coletilla de ahorro que devuelve cada tool (`_savings_feedback`, `server.py:1185-1195`, y el
  mensaje de `server.py:367`) sigue en **bruto** con chars ÷ 4: la cambia `coste-api-y-cuota`
  (su REQ-011). No es un olvido.
- Descontar relecturas del neto.
- Atribuir la fila en vuelo al modelo de respaldo que de verdad responde.
- Medir RAM y procesos en macOS (solo se corrige el texto).
- Desglosar la tasa de error por causa; cambiar la latencia media para excluir fallos.
- Persistir en disco la última lista buena de modelos.
- La configuración de grupos de llama-swap.
- Regenerar la captura del README y publicar versión.

## Traceability

| Requisito | Tarea | Verificación |
|---|---|---|
| REQ-001, REQ-002, REQ-003, REQ-005, REQ-006, REQ-007, REQ-008 | T1 | Tests de `_accounting` y de `tokens_claude`; paridad con la lista de casos y la guarda de REQ-001; `/api/stats` (incluido `ok: null`); `local_status`; septiembre a mano (T7) |
| REQ-004 | T1 (datos y `agg`), T5 (KPI en navegador) | Test de node de `agg` con negativos; Playwright del KPI neto |
| REQ-010, REQ-011 | T2 | Tests puros con excepciones construidas (incluidos `HTTPStatusError(401)`, `InvalidURL` y el caso de la Mac) y tests de red real en los tres sistemas |
| REQ-012 (sondeo), REQ-013, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019; REQ-021 y REQ-022 (parte servidor) | T3 | Tests de sondeo, lista por URL, `local_status`, `doctor`/`checks`, `_post_chat` en los tres caminos, plazo de conexión, `espera_local`; `doctor` contra el daemon (T7) |
| REQ-012 (endpoints), REQ-014, REQ-020 a REQ-028 (panel), REQ-034 (h) | T4 | Tests de API y funciones JS con node; Playwright de la nota remota; navegador contra el daemon (T7) |
| REQ-030 a REQ-033, REQ-034 (a)–(g) | T5 | Tests de node (formato) y Playwright (tipografía) |
| REQ-040, Restricciones de entrega | T6 | `test_wiki.py`, `test_captura.py`, lectura; la nota del `[Unreleased]` |
| Todos | T7 | Suite completa, ruff, verificación contra el backend y el daemon reales |
