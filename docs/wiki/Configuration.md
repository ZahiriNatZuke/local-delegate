# Configuration

Todo se configura por variables de entorno (en el bloque `env` de tu config MCP, o en el shell).
Nada está hardcodeado.

## Endpoint

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_BASE_URL` | `http://127.0.0.1:9292/v1` | Endpoint OpenAI-compatible |
| `LOCAL_DELEGATE_API_KEY` | *(vacío)* | Bearer token, si el endpoint lo exige |
| `LOCAL_DELEGATE_BACKEND_ORIGIN` | `auto` | `local`/`remote` fuerzan el origen del cómputo; `auto` lo deduce del host de `BASE_URL` (loopback = local). Decláralo si llegas al backend por un **túnel** (`ssh -L 9292:…`, port-forward de Tailscale): el endpoint se ve en `127.0.0.1` y el dashboard reportaría cómputo local para inferencia que salió de la máquina |
| `LOCAL_DELEGATE_TIMEOUT` | `180` | Timeout HTTP (segundos) |
| `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS` | `2` | Máximo de llamadas al backend simultáneas por proceso; en el daemon se comparte entre clientes |

Para una Mac que usa llama-swap en otra máquina, conserva el MCP en la Mac, fija
`LOCAL_DELEGATE_AUTOSTART=0` y carga `LOCAL_DELEGATE_API_KEY` desde Keychain. Ver
[Backend remoto Mac → PC](Remote-backend.md).

## Catálogo de modelos (roles)

Los defaults apuntan a un setup de referencia con llama-swap; cámbialos por los ids de tu backend.

Largo, código y visión son los modelos que ganaron la medición de septiembre de 2026 (antes
`llama31-8b`, `qwen25-coder-14b` y `qwen3-vl-8b`). En una GPU de 16 GB, medida con `gemma3-4b` cargado
al lado, la configuración de referencia es: Gemma 4 26B-A4B con `-ncmoe 12 --ctx-size 38400`, Qwen3.6-35B-A3B
con `-ncmoe 20 --ctx-size 16384`, los dos con `--reasoning off`, y Gemma 4 12B con su `--mmproj`,
`--batch-size 2048 --ubatch-size 2048` (sin eso aborta al procesar una imagen). Con menos expertos en
RAM van más rápidos, pero Windows desaloja al modelo pequeño de la VRAM para hacerles sitio.

| Variable | Default | Rol |
|---|---|---|
| `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | clasificar, extraer, resumen corto |
| `LOCAL_DELEGATE_MODEL_LONG` | `gemma4-26b-a4b` | documentos largos |
| `LOCAL_DELEGATE_MODEL_CODE` | `qwen36-35b-a3b` | código |
| `LOCAL_DELEGATE_MODEL_VISION` | `gemma4-12b` | visión (imagen→texto, `local_describe_image`) |
| `LOCAL_DELEGATE_LONG_INPUT_CHARS` | `6000` | umbral mecánico↔largo |
| `LOCAL_DELEGATE_STRUCTURED_SUMMARY` (antes `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`) | `0` | `local_summarize` sigue la estructura de un Markdown (solo modelo largo); experimental, ver [Tools](Tools#resumen-por-secciones-experimental-apagado) |
| `LOCAL_DELEGATE_MAX_CHARS_MECHANICAL` / `_LONG` / `_CODE` / `_FAST` | `20000` / `48000` / `20000` / `12000` | tope de chars de entrada **por rol**: por encima, las tools que reducen (`local_summarize`, `local_lint_summary`, `local_commit_msg`, `local_explain_code`, `local_extract`) hacen map-reduce y las que transforman trocean |
| `LOCAL_DELEGATE_MAX_IMAGE_MB` | `8` | tope de tamaño de imagen para `local_describe_image` |
| `LOCAL_DELEGATE_DUMP_CHUNK_NOTES` | *(vacío: apagado)* | carpeta **local** donde cada operación troceada (map-reduce) deja un JSON con la salida de cada paso (map, reagrupado, reduce). Solo para medir: no va al log de uso ni al panel y nunca sale de la máquina. El log de uso ya guarda los pasos **sin texto** (campo `steps`). Lo lee el daemon al arrancar |
| `LOCAL_DELEGATE_CHUNK_CHARS` | `3500` | tamaño de trozo al partir documentos largos (`local_translate`, `local_delegate`) |
| `LOCAL_DELEGATE_CHUNK_MAX_TOKENS` | `2048` | techo de `max_tokens` por trozo |
| `LOCAL_DELEGATE_CHUNK_MIN_CHARS` | `400` | trozo mínimo: por debajo ya no se vuelve a partir aunque el modelo trunque |
| `LOCAL_DELEGATE_COMMIT_LANGUAGE` | *(vacío = el idioma vigente del producto)* | Idioma del mensaje de `local_commit_msg`, entero (primera línea y cuerpo): un código (`es`, `en`, `fr`, `pt`, `de`, `it`, también `es-CU`) o un nombre (`catalán`); lo que no reconoce se usa tal cual. Vacío (desde la 0.36.0): el idioma vigente del producto (`LOCAL_DELEGATE_LANG`, la preferencia o el sistema). `diff`: la regla de antes, el idioma predominante de los textos del diff. No le afecta `LOCAL_DELEGATE_OUTPUT_LANGUAGE`. La orden va solo en la llamada que redacta el mensaje, no en las notas intermedias del map-reduce |
| `LOCAL_DELEGATE_OUTPUT_LANGUAGE` | *(vacío = el idioma vigente)* | Idioma en que `local_summarize`, `local_lint_summary`, `local_explain_code` y `local_describe_image` piden responder al modelo, para idiomas fuera de `es`/`en` (`fr`, `pt`, `de`, `it` o texto libre, como `português`). Texto de 1 a 40 caracteres, sin saltos de línea ni caracteres de control; uno no válido se ignora y `doctor` y `local_status` avisan. La orden va en cada paso del troceado. No cambia los textos de interfaz (recibos, errores, `local_status`, hooks, panel), que siguen a `LOCAL_DELEGATE_LANG`, ni `local_commit_msg`, `local_translate` ni las demás tools. `doctor` y `local_status` muestran el valor efectivo y su origen |

> El chunking existe porque traducir/reescribir produce tanta salida como entrada: con una sola
> llamada un documento de 20 000+ chars choca contra `max_tokens` y vuelve cortado. `CHUNK_CHARS`
> se elige para que la salida de un trozo quepa holgada bajo `CHUNK_MAX_TOKENS` (3500 chars ≈
> 875-1200 tokens contra un techo de 2048). Súbelo solo si tu modelo tolera respuestas más largas.

> `local_delegate` (tool genérica) valida su parámetro `model` contra el conjunto de estos 4 ids
> de texto. `MODEL_VISION` queda fuera a propósito: ese rol no arma payload texto→texto.
> Si dos roles apuntan al mismo id, el catálogo se deduplica sin problema, y **cada rol conserva su
> tope de entrada**: con `LONG` y `CODE` en el mismo modelo, un resumen largo sigue usando los 48 000
> chars del rol largo. Antes el tope se guardaba por nombre de modelo y el último rol pisaba al otro.

## Respaldo entre modelos

Cuando el modelo de un rol falla por culpa del propio modelo, la delegación puede saltar a otro. Las
cadenas se declaran **por rol**, no por nombre de modelo, así que siguen valiendo si cambias los
modelos por defecto. `local_status` muestra cómo quedan resueltas y `local-delegate doctor` avisa si
una variable nombra algo que no existe.

| Variable | Default | Qué hace |
|---|---|---|
| `LOCAL_DELEGATE_FALLBACK` | `1` | `0` lo apaga |
| `LOCAL_DELEGATE_FALLBACK_MAX_HOPS` | `2` | saltos máximos por llamada |
| `LOCAL_DELEGATE_FALLBACK_CODE` | `loaded,long` | cadena del rol de código |
| `LOCAL_DELEGATE_FALLBACK_LONG` | `loaded,code` | cadena del rol largo |
| `LOCAL_DELEGATE_FALLBACK_MECHANICAL` | `loaded,long` | cadena del rol mecánico |

> **Cómo se escribe una cadena:** roles (`mechanical`, `long`, `code`), el paso `loaded` o ids del
> catálogo, separados por comas y en orden. Lo repetido y el propio modelo del rol se quitan solos;
> lo que no sea ni rol, ni `loaded`, ni modelo del catálogo se ignora. **`none` desactiva** el
> respaldo de ese rol: una variable vacía también, pero en Windows fijarla a vacío la borra y el rol
> volvería a su cadena por defecto. Visión no tiene respaldo. **Ninguna cadena por defecto lleva al
> modelo mecánico** desde código o largo.
>
> **`loaded`** son los modelos que **ya están cargados** y tienen una celda aprobada de la
> [afinidad](Tools.md#afinidad-usar-el-modelo-que-ya-está-cargado) para esa tool, distintos del que
> falló. Se resuelve en el momento del salto y nunca carga nada; si no hay ninguno, el paso se salta
> sin gastar salto. Con las celdas de hoy solo tiene miembros para el rol mecánico (en
> `local_translate`, `local_lint_summary` y `local_delegate`); para código y largo las cadenas
> efectivas son `code → long` y `long → code`. `residente` y `resident` se siguen aceptando como
> sinónimos obsoletos de `loaded`, y `doctor` pide renombrarlos.

**Cuándo salta, y cuándo no.** Solo los fallos **del modelo** (un 5xx, una respuesta rota) pasan al
siguiente de la cadena, y cada salto exige que el anterior fallara también por el modelo. Un modelo
que **no se pudo cargar** (falta de memoria, error de carga) salta **solo a `loaded`** y sin
segundo salto: saltar a otro modelo grande encadenaría swaps y OOM. **Si no hay nada en `loaded`, no
salta** y vuelve el error de siempre: antes saltaba al modelo mecánico, que sin residente había que
cargar (consecuencia aceptada). La excepción es la afinidad: si el alternativo que eligió el daemon
falla por capacidad, se prueba el modelo del rol y luego su cadena. No saltan un 4xx (incluido el
desborde de contexto), un backend caído, un timeout de lectura con el modelo ya cargado ni un
razonamiento que agotó `max_tokens`: vuelve el error de siempre. El salto **suelta su plaza de
concurrencia**, pide turno para el modelo nuevo y vuelve a pedir plaza (el tope de
`MAX_CONCURRENT_REQUESTS` se mantiene), y `local_delegate` con `model` explícito no salta nunca.

**Un candidato que no admite la entrada se salta sin llamarlo**: su tope (`LOCAL_DELEGATE_MAX_CHARS_*`
del rol que lo usa) tiene que cubrir lo que se va a enviar. Por eso, con los topes por defecto, **en un
resumen por partes de un documento largo el respaldo no entra nunca**: los trozos miden
0,8 × 48 000 = 38 400 caracteres y ningún otro rol admite más de 20 000. Un documento que cabe en
una sola llamada sí puede saltar, si mide 20 000 caracteres o menos.

La respuesta dice qué modelo respondió, en lugar de cuál y por qué, detrás del contenido; en
`local_extract` va en `_local_delegate.fallback` y en `local_boilerplate` en el recibo, nunca en el
fichero. En un documento por trozos, el modelo cambia como mucho una vez: desde el trozo que saltó,
el resto va directo al respaldo. Si fallan también los respaldos, vuelve el error del modelo pedido
con una línea que lista lo que se probó.

## Enfriamiento por modelo

Un modelo que falla varias veces seguidas deja de recibir peticiones durante un rato, y vuelve solo
cuando vence. El estado lo comparten el daemon y los procesos stdio de la máquina
(`cooldown.json`, junto al log de uso) y sobrevive a un reinicio. Si ese fichero no se puede leer,
se sigue como si no hubiera enfriamiento: nunca bloquea ni hace fallar una delegación.
`local_status` lista los modelos enfriados, con los segundos que les quedan y cuántas veces seguidas
han vuelto a entrar sin un éxito de por medio.

Hasta la 0.34.0 el fichero se llamaba `enfriamiento.json`. El daemon arranca desde él si aún no
hay `cooldown.json` (si están los dos, manda el nuevo) y, de la 0.35.0 a la 0.37.x, lo sigue
escribiendo con sus claves viejas para los hooks de una versión anterior. Esa doble escritura se
retira en la 0.38.0.

Cada vez que un modelo **entra** en enfriamiento, **vuelve a entrar** o **se recupera**, se añade
una línea a `cooldown-events.jsonl` (antes `enfriamiento-eventos.jsonl`, que se sigue leyendo),
junto al log de uso: modelo, hora, clase del fallo, espera y reentradas, nunca prompts ni rutas.
`cooldown.json` solo guarda el presente; este
registro es lo que permite contar después cuántos episodios hubo y cómo acabaron. Para saber si los
números de abajo convienen, `uv run python scripts/measure_cooldown.py --since AAAA-MM-DD` lo
cruza con el log de uso y responde «cambiar», «se quedan» o «no concluyente» (con menos de 5
episodios y 10 fallos que cuenten no hay datos para decidir).

| Variable | Default | Qué hace |
|---|---|---|
| `LOCAL_DELEGATE_COOLDOWN` | `1` | `0` lo apaga |
| `LOCAL_DELEGATE_COOLDOWN_FAILURES` | `3` | fallos seguidos que enfrían el modelo |
| `LOCAL_DELEGATE_COOLDOWN_S` | `120` | espera de la primera vez, en segundos |
| `LOCAL_DELEGATE_COOLDOWN_MAX_S` | `900` | tope de la espera: tras vencer, cada fallo la dobla hasta aquí |

> **Qué cuenta:** solo los fallos del modelo (un 5xx que no es de carga, una respuesta rota) y un
> timeout con el modelo **ya cargado**. No cuentan los errores de conexión, los 4xx, un modelo que no
> se pudo cargar ni un razonamiento que agotó `max_tokens`; tampoco ponen el contador a cero. Un éxito
> sí. Los números no están medidos todavía: son configurables a propósito.
>
> El daemon lee estas variables al arrancar: para cambiarlas hay que reiniciarlo.

## Turno, afinidad y lentitud

Con un llama-swap **local** y su `config.yaml` legible (`LLAMASWAP_CONFIG` y el extra
`[llamaswap]`), el daemon reparte el backend por turno entre los modelos que chocan, aprovecha un
modelo ya cargado cuando hay una celda aprobada para la tool y marca las llamadas lentas. El detalle
está en [Architecture](Architecture.md#turno-afinidad-y-lentitud); aquí, lo que se ajusta.

| Variable | Default | Qué hace |
|---|---|---|
| `LOCAL_DELEGATE_TURN_MAX_S` | `600` | red de seguridad del turno: la primera de la cola se concede **forzada** si lleva estos segundos esperando **y** el daemon lleva otros tantos sin que empiece ni termine ninguna llamada al backend (el reloj se pone a cero con cada llamada que empieza o termina, y no corre mientras hay alguna en vuelo). Su evento lleva `turn: "forced"` |
| `LOCAL_DELEGATE_AFFINITY_MARGIN_S` | `5` | afinidad: un modelo ya cargado solo cuenta como «cargado con margen» si le quedan al menos estos segundos de TTL (o tiene TTL 0, o una petición en vuelo) |
| `LOCAL_DELEGATE_SLOW_THRESHOLD` | `0.5` | una llamada es `slow` si genera a menos de esta fracción de la velocidad normal de su modelo (`pace_rel` < umbral) |
| `LLAMASWAP_CONFIG` | *(vacío)* | ruta del `config.yaml` de llama-swap. Sin ella no hay turno ni afinidad, y el daemon se comporta como antes |
| `LLAMASWAP_WATCH_CONFIG` | `0` | con el auto-arranque, `1` añade `-watch-config` al llama-swap que lanza el daemon, para que `llamaswap residency` vea la recarga |

> **Sin turno** (sin `LLAMASWAP_CONFIG`, sin PyYAML, YAML ilegible, router `matrix`, las dos
> sintaxis de grupos a la vez, una config que `load.go` rechazaría o un backend que no es local) el
> daemon va como siempre, y `local_status` y `doctor` dicen el motivo («Turno: no (…)»).
>
> La «velocidad normal» de un modelo es la mediana de `tok_s` de sus últimos 50 eventos correctos con
> 8 tokens de salida o más; hacen falta 10 para que haya referencia. Se siembra con el log de uso del
> mes en curso y del anterior la primera vez que hace falta. Estas variables, como las demás, se leen
> al arrancar.

## Daemon y web de métricas

`local-delegate serve` usa el host/puerto web para servir MCP en `/mcp` y dashboard en `/`.
En modo `stdio`, las mismas variables controlan únicamente la web embebida heredada.

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_WEB` | `1` | `0` desactiva la web embebida del modo `stdio` |
| `LOCAL_DELEGATE_WEB_HOST` | `127.0.0.1` | Host de web/daemon |
| `LOCAL_DELEGATE_WEB_PORT` | `9393` | Puerto único de web/daemon |
| `LOCAL_DELEGATE_WEB_FONTS` | `1` | Tipografía de marca desde Google Fonts. `0` la desactiva y deja la página con **cero peticiones a terceros** (cae al stack de fuentes del sistema) |
| `LOCAL_DELEGATE_WEB_TOKEN` | *(vacío)* | Token que exige **todo** el puerto del daemon: endpoint MCP, dashboard y `/api/*`. Vacío = sin autenticación (el comportamiento de siempre). Ponlo si el puerto está detrás de un proxy o publicado. Ver [Daemon](Daemon.md#autenticación-del-puerto) |
| `LOCAL_DELEGATE_WEB_SESSION_DAYS` | `365` | Cuánto dura la sesión del navegador tras entrar una vez con el token, renovándose en cada visita. Solo afecta al navegador: los clientes MCP y el CLI mandan el token en cada llamada. `0` desactiva la sesión y vuelve a pedir credenciales en cada petición. Ver [Daemon](Daemon.md#la-sesión-del-navegador) |

> Chart.js se sirve desde el propio paquete (`/vendor/chart.umd.min.js`), no desde un CDN: el
> panel funciona en una máquina sin salida a internet y no anuncia a nadie que estás mirando tus
> métricas. La tipografía es el único recurso externo que queda, y es puramente cosmético.

## Log de uso

Por defecto el log rota por mes (`usage-YYYYMM.jsonl`, mes UTC) dentro de `LOG_DIR`. Si
fijas `LOCAL_DELEGATE_LOG`, ese archivo se usa tal cual y la rotación se desactiva
(compatibilidad con instalaciones que ya apuntaban a una ruta fija).

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_LOG_DIR` | *(dir de datos de usuario)* | Directorio donde se escriben los `usage-YYYYMM.jsonl` rotados. Por defecto `platformdirs.user_data_dir("local-delegate")` (p. ej. `%LOCALAPPDATA%\local-delegate` en Windows) |
| `LOCAL_DELEGATE_LOG` | *(vacío = rotación activa)* | Si se fija, ruta de un `usage.jsonl` explícito sin rotar. El dashboard igual lo lee como fuente adicional aunque uses `LOG_DIR` para el resto |
| `LOCAL_DELEGATE_FEEDBACK` | `1` | `0` apaga la línea "leído server-side: N chars ≈ M tokens de Claude" que se anexa al resultado cuando `source=path`. En `local_extract` no se anexa al texto sino que viaja dentro de `_local_delegate` (ver abajo): pegarla rompería el JSON. En `local_describe_image` dice solo los bytes |

## Coste equivalente

El equivalente a precio de API y el bloque de cuota (ver
[Savings & metrics](Savings-and-metrics.md#coste-equivalente-a-precio-de-api)) tienen una sola
variable:

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_COST_FALLBACK` (antes `LOCAL_DELEGATE_COSTE_RESPALDO`) | *(vacío = `claude-opus-5-5` en subagente)* | Con qué modelo e hilo se valora una delegación a la que no se le pudo atribuir modelo: `modelo` o `modelo:main\|subagent` (con solo `modelo`, el hilo es `subagent`). Gana al valor declarado. Un valor que no se entiende, o un modelo que no está en la tabla de precios, no rompe nada: se usa el declarado y el panel lo dice. El rótulo de la barra de cobertura nombra siempre el respaldo en uso |

El **plazo** con que se rellenan las delegaciones a posteriori no es una variable de
local-delegate: es `cleanupPeriodDays` de `~/.claude/settings.json`, el plazo al que Claude Code
borra los transcripts (30 días si no está puesto). `local-delegate recompute-cost` lo lee y lo
guarda en `cost-aggregates.json`, y el panel y `doctor` usan ese valor guardado: el daemon nunca
abre `~/.claude`. Tampoco hay variable para `N`: sale del relleno, de la mediana de su grupo o del
valor declarado de su hilo, en ese orden.

## Parámetros del backend por rol

Cada petición al backend lleva solo lo que arma la tool: `model`, `messages`, `max_tokens`,
`temperature`, `stream` y, en `local_extract`, `response_format`. Para ajustar el muestreo o
encender el razonamiento sin tocar código hay **parámetros por rol** (`mechanical`, `long`, `code`,
`vision`), sacados de una lista cerrada y validados por tipo y rango. Las tools MCP no ganan ningún
argumento: el modelo que delega no puede fijar nada de esto.

### El fichero y el subcomando

Se guardan en `backend-params.json`, dentro de `LOCAL_DELEGATE_LOG_DIR` (el mismo directorio de los
`usage-YYYYMM.jsonl`), con este esquema:

```json
{"version": 1, "roles": {"code": {"top_k": 20, "temperature": 0.3}}}
```

Se edita con `local-delegate backend-params`, no a mano:

```bash
local-delegate backend-params show            # ruta del fichero y, por rol, valor, origen y avisos
local-delegate backend-params show --json     # lo mismo en JSON
local-delegate backend-params set code top_k 20
local-delegate backend-params unset code top_k
local-delegate backend-params reset code      # vacía el rol; sin rol, vacía todos
```

- `set <rol> <clave> <valor>` valida el rol, la clave, el tipo y el rango **antes** de escribir.
  Si algo no vale, sale con código **2**, dice el motivo (rol y clave, nunca el valor) y no toca el
  fichero. Si todo va bien, sale con **0** y confirma `<rol>.<clave> guardado en <ruta>`.
  `enable_thinking` acepta `on`/`off`/`true`/`false`.
- `unset <rol> <clave>` quita una clave; una clave que no está no es error.
- `reset [<rol>]` vacía un rol entero, o todos, **sin preguntar**: también se lleva
  `enable_thinking` y el presupuesto de razonamiento.
- `show` imprime `Fichero: <ruta>` y luego solo los roles con valores o avisos, una línea por clave
  con `clave = valor  (fichero|variable)`. Sin nada configurado dice «sin parámetros».
  `show --json` da `{"file": …, "roles": [{"role", "params": [{"key", "value", "source"}],
  "warnings": [{"code", "key"}]}]}`, con los cuatro roles siempre.
- La escritura es atómica (fichero temporal en el mismo directorio y `os.replace`) bajo el cerrojo
  `backend-params.json.lock`: una escritura que falla a medias deja el fichero anterior como
  estaba, y dos `set` a la vez no se pisan.

Al leerlo, el producto nunca falla por el fichero:

- ausente, vacío o con `{"version": 1, "roles": {}}`: sin parámetros;
- JSON ilegible, `version` distinta de 1 o más de 64 KB: se ignora **entero**, con aviso. `set` no
  lo sobrescribe (así no se pierde a ciegas una edición a mano): arréglalo o bórralo antes;
- un rol desconocido se quita con aviso;
- una clave no permitida, de tipo equivocado o fuera de rango se quita **sola**, con un aviso que
  nombra el rol y la clave pero **nunca el valor**; el resto del rol se aplica.

`doctor` muestra en su cabecera, debajo de las líneas de idioma, la ruta del fichero, los
parámetros de cada rol (los que vienen de la variable, con la marca `(variable)`) y sus avisos.
`local_status`, debajo de la línea de `vision`, muestra `Parámetros por rol: <ruta>` y una línea
por rol con parámetros (`  <rol>: clave=valor (fichero|variable), …`, los booleanos como
`on`/`off`), con sus avisos debajo. Sin nada configurado, ninguno de los dos añade líneas.

### Override puntual: `LOCAL_DELEGATE_BACKEND_PARAMS`

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_BACKEND_PARAMS` | *(vacío)* | Override puntual del fichero, clave a clave, con el formato `rol.clave=valor;…` (p. ej. `code.top_k=20;mechanical.temperature=0.5`). Hasta 2048 caracteres; más larga se ignora entera, con aviso |

La gramática:

- se separa por `;` y se descartan los trozos vacíos (un `;` final o `;;` no avisan);
- se quitan los espacios alrededor de cada trozo, de la clave y del valor;
- se parte por el **primer** `=` y, a la izquierda, por el **primer** `.`;
- un trozo sin `=`, con un segundo `=` o sin `.` está mal formado: se quita solo ese, con aviso;
- si una clave se repite en el mismo rol, gana la última, con aviso;
- los valores siguen las reglas de `set` (un número que da infinito, como `1e400`, se rechaza).

### Claves permitidas

Solo estas 21 claves. Los rangos son los de llama.cpp b10909, pero **más estrictos**: se rechaza lo
que el servidor recortaría en silencio. Ningún número puede ser `NaN` ni `±Infinity`, y un booleano
JSON no cuenta como número.

| Grupo | Clave | Tipo | Rango aceptado | Destino en el cuerpo |
| --- | --- | --- | --- | --- |
| muestreo | `temperature` | float | ≥ 0 | raíz |
| muestreo | `top_k` | int | ≥ 0 (0 = apagado) | raíz |
| muestreo | `top_p` | float | 0–1 | raíz |
| muestreo | `min_p` | float | 0–1 | raíz |
| muestreo | `typical_p` | float | 0–1 | raíz |
| muestreo | `repeat_penalty` | float | finito | raíz |
| muestreo | `repeat_last_n` | int | 0–2³¹−1 | raíz |
| muestreo | `presence_penalty` | float | finito | raíz |
| muestreo | `frequency_penalty` | float | finito | raíz |
| muestreo | `dry_multiplier` | float | finito | raíz |
| muestreo | `dry_base` | float | ≥ 1 | raíz |
| muestreo | `dry_allowed_length` | int | 0–2³¹−1 | raíz |
| muestreo | `dry_penalty_last_n` | int | 0–2³¹−1 | raíz |
| muestreo | `xtc_probability` | float | 0–1 | raíz |
| muestreo | `xtc_threshold` | float | 0–1 | raíz |
| muestreo | `mirostat` | int | 0, 1 o 2 | raíz |
| muestreo | `mirostat_tau` | float | finito | raíz |
| muestreo | `mirostat_eta` | float | finito | raíz |
| razonamiento | `enable_thinking` | bool (`set` y la variable aceptan `on`/`off`/`true`/`false`) | — | `chat_template_kwargs.enable_thinking` |
| razonamiento | `reasoning_budget_tokens` | int | **1–8192** | raíz (más la suma al tope) |
| razonamiento | `reasoning_effort` | enum | `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | raíz |

El techo de 8192 del presupuesto es una elección conservadora, no un límite técnico: coincide con el
contexto del modelo más pequeño del catálogo (`gemma3-4b`, `--ctx-size 8192`), y en las pruebas en
vivo bastaron entre 100 y 700 tokens. El mínimo es 1 porque un presupuesto de 0 cierra el
razonamiento en el acto.

### Claves reservadas

Ninguna de estas se puede configurar, ni por fichero, ni por variable, ni con `set`. El cuerpo nunca
lleva una clave reservada que no haya puesto el producto.

| Grupo | Claves |
| --- | --- |
| contrato de la tool | `model`, `messages`, `stream`, `stream_options`, `max_tokens`, `max_completion_tokens`, `n_predict`, `response_format`, `json_schema`, `grammar`, `tools`, `tool_choice`, `functions`, `function_call`, `n`, `n_cmpl`, `stop`, `logprobs`, `n_probs`, `response_fields` |
| servidor | `cache_prompt`, `id_slot`, `n_keep`, `samplers`, `seed` |
| razonamiento en crudo | `chat_template_kwargs`, `reasoning_format` |

Tampoco se aceptan, por ahora, las claves aplazadas: `dry_sequence_breakers`, `top_n_sigma`,
`dynatemp_range`, `dynatemp_exponent`, `min_keep`, `adaptive_target`, `adaptive_decay`,
`reasoning_budget_message` y `reasoning_control`. Para ajustar modelo a modelo, en vez de rol a rol,
está `filters.setParams` de llama-swap.

### Precedencia y fusión

Para cada rol y cada clave, el valor efectivo sale de, en este orden:
**`LOCAL_DELEGATE_BACKEND_PARAMS` > `backend-params.json` > valor propio de la tool**. La variable
pisa clave a clave: una clave que solo está en el fichero se mantiene. Hoy la tool solo tiene valor
propio para `temperature` (`local_classify` y `local_extract` 0, `local_boilerplate` 0,1 y las demás
0,2): configurada en un rol, la temperatura pisa la de **todas** las tools que corren con ese rol.

El cuerpo de cada llamada al backend se arma en tres capas, de abajo arriba:

1. **Base de la tool**: su `temperature` y su `max_tokens`.
2. **Parámetros del rol**: van encima y pueden pisar `temperature`. El presupuesto de razonamiento
   **se suma** al `max_tokens` de la tool, nunca lo sustituye.
3. **Claves de contrato** (`model`, `messages`, `stream`, `response_format` y las demás reservadas
   que ponga el producto): van encima de todo y nunca se pisan.

Los parámetros se resuelven **una vez por operación**, con el rol de origen, y viajan iguales a
todas sus llamadas: cada trozo, cada paso de map/reduce, la reducción, los reintentos y el
**respaldo**. Si la afinidad o el respaldo mandan la operación a otro modelo, sigue llevando los
parámetros de su rol de origen, no los del rol de ese modelo.

Dos casos aparte:

- `local_delegate` con `model=…` explícito no lleva **ningún** parámetro de rol; sin modelo
  explícito usa los de `mechanical`.
- Si el backend rechaza una llamada con parámetros (HTTP 400), se reintenta **una vez** sin ellos
  (con la `temperature` y el `max_tokens` de la tool, sin presupuesto, y con `response_format` si lo
  había), antes del reintento sin schema de `LOCAL_DELEGATE_JSON_SCHEMA=auto`. Si así funciona, el
  resto de la operación va sin parámetros y el log lo marca con `backend_params_rejected`. Si
  también falla sin ellos, la culpa no era de los parámetros: no se marca nada y se sigue el flujo
  de siempre, con los parámetros. Esa prueba se hace una sola vez por operación.

### Qué rol usa cada tool

| Tool | Rol |
| --- | --- |
| `local_classify` | `mechanical` |
| `local_summarize`, `local_extract`, `local_lint_summary`, `local_translate` | `mechanical` o `long`, **según el tamaño de la entrada**: por encima de `LOCAL_DELEGATE_LONG_INPUT_CHARS` (6000), `long` |
| `local_commit_msg`, `local_explain_code`, `local_boilerplate` | `code` |
| `local_describe_image` | `vision` |
| `local_delegate` | `mechanical` (sin modelo explícito; con él, ninguno) |

Ojo con las cuatro que cambian de rol: un `local_summarize` corto usa los parámetros de
`mechanical` y uno largo los de `long`. Si quieres el mismo ajuste en las dos, ponlo en los dos
roles.

### Razonamiento

El razonamiento se enciende con `enable_thinking` **y** un `reasoning_budget_tokens` en el mismo
rol. Primero el presupuesto, luego el interruptor:

```bash
local-delegate backend-params set code reasoning_budget_tokens 512
local-delegate backend-params set code enable_thinking on
```

- `set <rol> enable_thinking on` sin presupuesto se rechaza (código 2). También se rechaza
  `unset <rol> reasoning_budget_tokens` mientras `enable_thinking` siga encendido en el fichero
  (antes, `unset <rol> enable_thinking`). `reset` sí vacía el rol entero sin exigir nada.
- Si la combinación sin presupuesto llega por un fichero editado a mano o por la variable,
  `enable_thinking` se ignora en ese rol, con aviso.
- Con el razonamiento encendido, cada llamada lleva `chat_template_kwargs: {"enable_thinking": true}`,
  `reasoning_budget_tokens` y `max_tokens = tope de la tool + presupuesto`. Así el razonamiento no
  se come la respuesta: el presupuesto **se suma** al tope.
- `enable_thinking off` manda `chat_template_kwargs: {"enable_thinking": false}` y no toca
  `max_tokens`.

**`reasoning_effort` solo no enciende el razonamiento.** Va en la raíz del cuerpo y llama.cpp lo
pasa a la plantilla como variable, pero con los modelos de referencia, servidos con
`--reasoning off`, no vence a ese flag: lo que lo vence es `enable_thinking: true`. Úsalo solo
junto con `enable_thinking` y presupuesto.

*Medido el 2026-10-20:* con `gemma4-26b-a4b`, presupuesto de 256 tokens y dos casos del corpus,
`off` no razonó y `low` y `high` razonaron casi lo mismo (937 y 937 caracteres en un caso, 812 y
809 en el otro): no hubo diferencia medible entre niveles. No cuentes con que `low` y `high` den
resultados distintos; lo que enciende y acota el razonamiento es `enable_thinking` con su presupuesto.

**El razonamiento tiene que caber en el contexto del modelo.** Antes de cada llamada con el
razonamiento encendido se estima si cabe:

```text
ceil((caracteres del sistema + caracteres de la entrada) × 2 / 4) + max_tokens de la tool + presupuesto ≤ n_ctx
```

Se cuenta a 2 caracteres por token, no a 4, porque en código y en español la densidad llega al
doble. Si no cabe, **esa llamada** va sin razonamiento (`enable_thinking: false` y el `max_tokens`
de la tool, sin presupuesto), con el resto de parámetros del rol, y el log marca
`reasoning_skipped: "context"`. La entrada no se recorta. El `n_ctx` de cada modelo se lee de
`--ctx-size`/`-c` en la config de llama-swap; si no se puede (sin el extra `[llamaswap]`, sin config
o sin el modelo en ella), se usa un estimado de **8192** y `doctor` y `local_status` lo avisan. El rol
`vision` queda fuera de la comprobación: su entrada es una imagen. `set` avisa, sin rechazar, si el
tope de entrada del rol (`LOCAL_DELEGATE_MAX_CHARS_<ROL>`) en tokens más
`LOCAL_DELEGATE_CHUNK_MAX_TOKENS` más el presupuesto pasa del contexto del modelo del rol; `show`,
`doctor` y `local_status` repiten el aviso.

**Qwen y el razonamiento sin etiquetas.** Con Qwen, el razonamiento que pasa del presupuesto puede
colarse en la respuesta sin etiquetas `<think>`: el producto no lo puede quitar ni contar, así que
`reasoning_chars` del log no lo incluye. Solo cuenta lo que llega en `reasoning_content` o entre
etiquetas `<think>`. Con un presupuesto pequeño pasa además que la respuesta se corta: en la prueba
en vivo, Qwen3.6 en el rol `code` con 256 tokens gastó el presupuesto, siguió razonando dentro de la
respuesta y llegó a `max_tokens` (`finish_reason: length`). Si das al rol `code` un presupuesto
bajo, comprueba en el log que sus eventos no salen con `truncated_out: true`; si salen, súbelo.

### Dónde se aplica y cuándo cambia

- **El fichero no exige reiniciar nada**: se relee al empezar cada operación (con una caché que se
  invalida cuando el fichero cambia), así que un `set` vale desde la llamada siguiente del daemon.
- **La variable sí exige reiniciar el daemon**: el daemon ve el entorno con el que arrancó.
  `backend-params show` y `doctor` leen la variable de **tu** shell, que puede no ser la del daemon;
  `doctor` lo avisa cuando la encuentra definida.
- **La configuración es de cada máquina que delega**, no del backend: una Mac que delega en la GPU
  de la PC usa su propio `backend-params.json`. En una máquina sin la config de llama-swap, como la
  Mac, el contexto de cada modelo es el estimado de 8192, así que los roles cuyo modelo tiene más
  contexto se saltarán el razonamiento antes de lo necesario.

### Antes de dar por bueno un cambio

Un cambio de temperatura (o de cualquier parámetro de muestreo o de razonamiento) se mide con el
benchmark de afinidad (`local-delegate benchmark` sobre el corpus
`benchmarks/afinidad-2026-10/cases.json`, ver [Backend versions](Backend-versions.md)) **antes** de darlo por bueno: a ojo no se ve si un
resumen mejoró o empeoró. El benchmark no aplica `backend-params.json` ni la variable, pero apunta en
los metadatos de la corrida qué claves había activas en cada rol; para medir razonamiento usa sus
opciones `--reasoning-effort` y `--reasoning-budget`.

## `local_extract` — JSON con schema

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_JSON_SCHEMA` | `auto` | `auto` pide `response_format` con schema y cae a modo libre si el backend responde 400; `on` lo exige (propaga el error); `off` nunca lo pide |

Desde la migración al SDK `mcp` 2.x, `local_extract` devuelve **un objeto validado**, no una cadena
con JSON dentro: quien llama ya no tiene que parsearlo. Las claves son exactamente las pedidas; lo
que no es dato viaja bajo la clave reservada `_local_delegate` para no ensuciar el resto:

```jsonc
// normal
{ "host": "127.0.0.1", "port": "9393" }

// salida truncada en un trozo (`max_tokens`): puede faltar algún campo
{ "host": "127.0.0.1", "_local_delegate": { "truncated": true, "warning": "…" } }

// leída de un `path`: el dato de ahorro va aquí, NO pegado al texto (rompería el JSON)
{ "host": "127.0.0.1", "_local_delegate": { "read_server_side": { "chars": 2848, "approx_tokens": 712 } } }

// respondió un modelo de respaldo
{ "host": "127.0.0.1", "_local_delegate": { "fallback": { "answered_by": "…", "instead_of": "…", "reason": "http_500", "class": "model" } } }

// el modelo no devolvió JSON, o el backend falló
{ "_local_delegate": { "error": "response is not parseable as JSON", "raw": "…" } }
```

**Contrato desde la 0.36.0 (REQ-010, cambio incompatible).** Las subclaves y los marcadores pasan a
inglés y **no dependen del idioma** (`LOCAL_DELEGATE_LANG`); el texto que va dentro (`warning`,
`error` y lo que sigue a un marcador) sí sale en el idioma del proceso servidor. Se emite solo la
forma nueva:

| Hasta la 0.35 | Desde la 0.36.0 |
|---|---|
| `truncado` | `truncated` |
| `aviso` | `warning` |
| `leido_server_side.{chars, tokens_aprox}` | `read_server_side.{chars, approx_tokens}` |
| `respaldo.{respondio, en_lugar_de, motivo, clase}` | `fallback.{answered_by, instead_of, reason, class}` |
| `crudo` | `raw` |
| `[local-delegate aviso: …]` | `[local-delegate warning: …]` |
| `[local-delegate respaldo: …]` | `[local-delegate fallback: …]` |
| `[local-delegate: entrada truncada — …]` | `[local-delegate: input truncated — …]` |
| `[local-delegate error]` | sin cambio |

`truncated`/`warning` significan desde la 0.36.0 **«salida truncada en un trozo»**: `local_extract`
lee la entrada entera y la trocea si no cabe, y las dos claves dicen que alguna llamada acabó por
`max_tokens`, así que puede faltar algún campo. El motivo `reason` de un salto por enfriamiento es el
valor de máquina `cooldown` (antes, «en enfriamiento»).

> El tercer caso es el que corrige la 0.13.1. Hasta la 0.13.0, la línea de ahorro se anexaba al
> texto también en esta tool, y como aquí el resultado **se parsea**, convertía un JSON perfecto en
> uno imparseable: `local_extract(path=…)` devolvía siempre `_local_delegate.error`, justo en el modo
> que ahorra contexto. Ningún test lo vio porque todos usaban `text=`.

## Seguridad — raíces permitidas

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_ALLOWED_DIRS` | *(vacío = sin restricción)* | Lista de directorios raíz separados por `;`. Cualquier `path` fuera de todos ellos se rechaza con un error que lista las raíces permitidas |

## Hooks de lectura (opt-in, solo Claude Code)

Los hooks son un mecanismo **exclusivo de Claude Code**: en Claude Desktop no existen, así que
nada de esta sección le aplica. Se instalan con `install --enable-read-hook`, que registra los
dos: el de la tool `Read` y el de `Bash|PowerShell`. Van juntos a propósito — son una regla sola
sobre dos caminos, y cerrar `Read` dejando `cat informe.md` abierto no cambia la conducta, la
muda de sitio.

| Variable | Default | Descripción |
|---|---|---|
| `LD_HOOK_READ_ENABLED` | `0` | Enciende el hook de lectura. `install --enable-read-hook` lo pasa como argumento, así que no hace falta ponerla a mano |
| `LD_HOOK_READ_SUGGEST_KB` | `8` | A partir de aquí se avisa. Bajó de 32 a 8 tras medir: 24 de 24 lecturas calladas por tamaño eran documentación |
| `LD_HOOK_READ_STRONG_KB` | `100` | A partir de aquí el aviso es «recomendación fuerte» |
| `LD_HOOK_READ_BLOCK` (antes `LD_HOOK_READ_BLOQUEAR`) | `0` | **Rechaza** la lectura en vez de sugerir. Ver abajo |
| `LD_HOOK_ENABLED` | `1` | Interruptor del experimento: `0` apaga hooks **y** telemetría, para la rama baseline de un A/B. Solo puede apagar |
| `LD_HOOK_TELEMETRY_LOG` | *(vacío = sin telemetría)* | Fichero JSONL donde los hooks registran lo que deciden |

### El bloqueo

Con `LD_HOOK_READ_BLOCK=1`, una lectura **completa** de un `.md` o un `.txt` por encima del
umbral se rechaza con un mensaje que nombra la tool que sirve, el `path` para llamarla y la salida
de emergencia: leer por franjas con `offset`/`limit`, que nunca se bloquean. Lo mismo con los
volcados de shell (`cat`, `type`, `more`, `Get-Content`, `gc`, `rtk read`, `head`) sobre una única
ruta; con una tubería, una redirección, comandos encadenados o un flag que ya acota, no se bloquea.

Nace apagado. Estas son las formas de que no bloquee:

- **Apagarlo al momento: crea el fichero `~/.claude/local-delegate-block-off`** (vacío
  vale; antes `local-delegate-bloqueo-apagado`, que sigue apagando con aviso). Gana a la variable
  y el hook lo mira en cada lectura, así que no hace falta cerrar ni reiniciar nada; bórralo para
  volver a encenderlo. En PowerShell:
  `New-Item "$HOME\.claude\local-delegate-block-off" -ItemType File`. Con
  `LD_HOOK_READ_SWITCH_FILE` (antes `LD_HOOK_READ_INTERRUPTOR`) se puede poner en otra ruta.
- `LD_HOOK_READ_BLOCK=0`. Ojo: una sesión ya abierta sigue con el valor con el que arrancó,
  porque hereda el entorno del lanzador. Por eso existe el fichero.
- Que el backend local no responda. El hook lo sondea él mismo (300 ms, cacheado un minuto) en vez
  de fiarse de las delegaciones anteriores, que sería un círculo cerrado: sin delegaciones no hay
  marca fresca, sin marca fresca no se bloquea, y sin bloqueo no hay delegaciones.
- Que el modelo que haría el resumen esté **en enfriamiento**: el hook lee el mismo
  `cooldown.json` que el servidor (o `enfriamiento.json`, si el daemon es de una versión anterior)
  y, si ese modelo está parado, deja pasar la lectura. Mira el
  modelo por defecto del rol, o `LOCAL_DELEGATE_MODEL_LONG`/`_MECHANICAL` si el cliente las tiene.
- `LD_HOOK_ENABLED=0`.

Cada evento de la telemetría lleva `block` (`on`, `off_file` u `off_variable`), para que una
medición sepa en qué estado estaba la regla. Hasta la versión anterior la clave se llamaba `bloqueo`
(`encendido`, `apagado_fichero`, `apagado_variable`), y el motivo de cada decisión, `motivo` (hoy
`reason`); el panel y los scripts de medición leen los dos formatos, también mezclados en el mismo
fichero. Si un hook leyó un nombre viejo (una variable o el interruptor), su evento lo dice en
`deprecated_names`, y `doctor` lo avisa mirando los últimos 7 días del fichero.

**Las lecturas por otros MCP se cuentan, no se bloquean.** `--enable-read-hook` registra el mismo
hook para las tools de lectura de otros servidores MCP (`mcp__*__read_*` y
`mcp__*__get_file_contents`). Por ese camino solo deja un evento con `route: mcp`: sin contarlas,
una subida de las delegaciones no distinguiría «se delegó» de «se leyó por otro sitio».

`.json`, `.csv`, `.log` y `.yaml` **se avisan pero no se bloquean**: ahí se busca un valor exacto
—un `package.json`, la línea del error— y un resumen no sustituye a la lectura. El código no dice
nada, ni antes ni ahora.

## Nombres viejos de variables (alias con aviso)

Cuatro variables cambiaron de nombre al pasar a inglés en la 0.35.0. El nombre viejo **sigue
funcionando** igual durante la 0.35.x, la 0.36.x y la 0.37.x, y se retira en la **0.38.0**.
Si están las dos, gana la nueva. `doctor` avisa del nombre viejo (check «nombres obsoletos») si lo
ve en la shell o en el bloque `env` de `~/.claude/settings.json`, y `local_status` dice los que
haya leído el daemon o el servidor por stdio.

| Nombre nuevo | Nombre viejo |
|---|---|
| `LD_HOOK_READ_BLOCK` | `LD_HOOK_READ_BLOQUEAR` |
| `LD_HOOK_READ_SWITCH_FILE` | `LD_HOOK_READ_INTERRUPTOR` |
| `LOCAL_DELEGATE_STRUCTURED_SUMMARY` | `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` |
| `LOCAL_DELEGATE_COST_FALLBACK` | `LOCAL_DELEGATE_COSTE_RESPALDO` |

Lo mismo vale para el subcomando `recompute-cost` (antes `recalcular-coste`) y su opción
`--reset-calibration` (antes `--reiniciar-calibracion`): los nombres viejos siguen aceptándose,
ocultos en la ayuda y con un aviso en `stderr`.

Y para el fichero que apaga el bloqueo: `~/.claude/local-delegate-block-off` (antes
`local-delegate-bloqueo-apagado`). El viejo sigue apagando durante el mismo plazo; `doctor` avisa
si existe, y también si la telemetría de los hooks dice que lo leyeron.

### Nombres en disco que cambiaron

Los hooks y el daemon comparten ficheros en el temporal del usuario. Desde esta versión se escriben
con el nombre nuevo, y el daemon sigue leyendo el viejo, por si queda instalado un hook de una
versión anterior:

| Nombre nuevo | Nombre viejo | Qué es |
|---|---|---|
| `local-delegate-blocks.jsonl` | `local-delegate-bloqueos.jsonl` | notas de cada bloqueo, para cruzarlo con la delegación |
| `local-delegate-calls/` | `local-delegate-llamadas/` | notas del hook de atribución |
| `local-delegate-health-<huella>.json` | `local-delegate-salud-<huella>.json` | caché de un minuto de «el backend responde» |
| hook `record_call.py` | hook `anotar_llamada.py` | `install`/`update` retiran el viejo (copia y registro) |

## Auto-arranque de llama-swap (opt-in)

Solo se usa si `LOCAL_DELEGATE_AUTOSTART=1`. Específico de llama-swap.

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_AUTOSTART` | `0` | `1` intenta arrancar llama-swap si el endpoint no responde |
| `LLAMASWAP_EXE` | *(busca `llama-swap` en PATH)* | Ruta al ejecutable |
| `LLAMASWAP_CONFIG` | *(vacío)* | Ruta al `config.yaml` de llama-swap. Fuera del auto-arranque también la usan el turno y la afinidad (ver [arriba](#turno-afinidad-y-lentitud)) y `llamaswap residency` |
| `LLAMASWAP_LISTEN` | `127.0.0.1:9292` | host:puerto de llama-swap |
| `LLAMASWAP_WATCH_CONFIG` | `0` | `1` añade `-watch-config` cuando hay `LLAMASWAP_CONFIG` |
