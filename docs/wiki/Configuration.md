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
`llama31-8b`, `qwen25-coder-14b` y `qwen3-vl-8b`). En una GPU de 16 GB, con `gemma3-4b` residente al
lado, la configuración de referencia es: Gemma 4 26B-A4B con `-ncmoe 12 --ctx-size 38400`, Qwen3.6-35B-A3B
con `-ncmoe 20 --ctx-size 16384`, los dos con `--reasoning off`, y Gemma 4 12B con su `--mmproj`,
`--batch-size 2048 --ubatch-size 2048` (sin eso aborta al procesar una imagen). Con menos expertos en
RAM van más rápidos, pero Windows desaloja al residente de la VRAM para hacerles sitio.

| Variable | Default | Rol |
|---|---|---|
| `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | clasificar, extraer, resumen corto |
| `LOCAL_DELEGATE_MODEL_LONG` | `gemma4-26b-a4b` | documentos largos |
| `LOCAL_DELEGATE_MODEL_CODE` | `qwen36-35b-a3b` | código |
| `LOCAL_DELEGATE_MODEL_VISION` | `gemma4-12b` | visión (imagen→texto, `local_describe_image`) |
| `LOCAL_DELEGATE_LONG_INPUT_CHARS` | `6000` | umbral mecánico↔largo |
| `LOCAL_DELEGATE_MAX_CHARS_MECHANICAL` / `_LONG` / `_CODE` / `_FAST` | `20000` / `48000` / `20000` / `12000` | tope de chars de entrada **por rol** |
| `LOCAL_DELEGATE_MAX_IMAGE_MB` | `8` | tope de tamaño de imagen para `local_describe_image` |
| `LOCAL_DELEGATE_CHUNK_CHARS` | `3500` | tamaño de trozo al partir documentos largos (`local_translate`, `local_delegate`) |
| `LOCAL_DELEGATE_CHUNK_MAX_TOKENS` | `2048` | techo de `max_tokens` por trozo |
| `LOCAL_DELEGATE_CHUNK_MIN_CHARS` | `400` | trozo mínimo: por debajo ya no se vuelve a partir aunque el modelo trunque |

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
| `LOCAL_DELEGATE_FALLBACK_CODE` | `residente,long` | cadena del rol de código |
| `LOCAL_DELEGATE_FALLBACK_LONG` | `residente,code` | cadena del rol largo |
| `LOCAL_DELEGATE_FALLBACK_MECHANICAL` | `long` | cadena del rol mecánico |

> **Cómo se escribe una cadena:** roles (`mechanical`, `long`, `code`, `residente`) o ids del
> catálogo, separados por comas y en orden. Lo repetido y el propio modelo del rol se quitan solos;
> lo que no sea ni rol ni modelo del catálogo se ignora. **`none` desactiva** el respaldo de ese rol:
> una variable vacía también, pero en Windows fijarla a vacío la borra y el rol volvería a su cadena
> por defecto. Visión no tiene respaldo.
>
> **El residente** es el modelo del grupo `persistent` de tu `config.yaml` de llama-swap
> (`LLAMASWAP_CONFIG`, necesita el extra `pyyaml`), que ya está en memoria y no obliga a cargar nada.
> Si no se puede leer, es el del rol mecánico.

**Cuándo salta, y cuándo no.** Solo los fallos **del modelo** (un 5xx, una respuesta rota) pasan al
siguiente de la cadena, y cada salto exige que el anterior fallara también por el modelo. Un modelo
que **no se pudo cargar** (falta de memoria, error de carga) salta **solo al residente** y sin
segundo salto: saltar a otro modelo grande encadenaría swaps y OOM. No saltan un 4xx (incluido el
desborde de contexto), un backend caído, un timeout de lectura con el modelo ya cargado ni un
razonamiento que agotó `max_tokens`: vuelve el error de siempre. El salto ocupa la misma plaza de
concurrencia que la llamada original, y `local_delegate` con `model` explícito no salta nunca.

**Un candidato que no admite la entrada se salta sin llamarlo**: su tope (`LOCAL_DELEGATE_MAX_CHARS_*`
del rol que lo usa) tiene que cubrir lo que se va a enviar. Por eso, con los topes por defecto, **en un
resumen por partes de un documento largo el respaldo no entra nunca**: los trozos miden
0,8 × 48 000 = 38 400 caracteres y ningún otro rol admite más de 20 000. Un documento que cabe en
una sola llamada sí puede saltar, si mide 20 000 caracteres o menos.

La respuesta dice qué modelo respondió, en lugar de cuál y por qué, detrás del contenido; en
`local_extract` va en `_local_delegate.respaldo` y en `local_boilerplate` en el recibo, nunca en el
fichero. En un documento por trozos, el modelo cambia como mucho una vez: desde el trozo que saltó,
el resto va directo al respaldo. Si fallan también los respaldos, vuelve el error del modelo pedido
con una línea que lista lo que se probó.

## Enfriamiento por modelo

Un modelo que falla varias veces seguidas deja de recibir peticiones durante un rato, y vuelve solo
cuando vence. El estado lo comparten el daemon y los procesos stdio de la máquina
(`enfriamiento.json`, junto al log de uso) y sobrevive a un reinicio. Si ese fichero no se puede leer,
se sigue como si no hubiera enfriamiento: nunca bloquea ni hace fallar una delegación.
`local_status` lista los modelos enfriados, con los segundos que les quedan y cuántas veces seguidas
han vuelto a entrar sin un éxito de por medio.

Cada vez que un modelo **entra** en enfriamiento, **vuelve a entrar** o **se recupera**, se añade
una línea a `enfriamiento-eventos.jsonl`, junto al log de uso: modelo, hora, clase del fallo,
espera y reentradas, nunca prompts ni rutas. `enfriamiento.json` solo guarda el presente; este
registro es lo que permite contar después cuántos episodios hubo y cómo acabaron. Para saber si los
números de abajo convienen, `uv run python scripts/medir_enfriamiento.py --desde AAAA-MM-DD` lo
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
| `LOCAL_DELEGATE_FEEDBACK` | `1` | `0` apaga la línea "leído server-side: N chars ≈ M tokens" que se anexa al resultado cuando `source=path`. En `local_extract` no se anexa al texto sino que viaja dentro de `_local_delegate` (ver abajo): pegarla rompería el JSON |

## `local_extract` — JSON con schema

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_JSON_SCHEMA` | `auto` | `auto` pide `response_format` con schema y cae a modo libre si el backend responde 400; `on` lo exige (propaga el error); `off` nunca lo pide |

Desde la migración al SDK `mcp` 2.x, `local_extract` devuelve **un objeto validado**, no una cadena
con JSON dentro: quien llama ya no tiene que parsearlo. Las claves son exactamente las pedidas,
salvo dos casos que viajan bajo la clave reservada `_local_delegate` para no ensuciar el resto:

```jsonc
// normal
{ "host": "127.0.0.1", "puerto": "9393" }

// entrada truncada — el aviso iba antes como texto DELANTE del JSON, y había que limpiarlo
{ "host": "127.0.0.1", "_local_delegate": { "truncado": true, "aviso": "entrada truncada — …" } }

// leída de un `path`: el dato de ahorro va aquí, NO pegado al texto (rompería el JSON)
{ "host": "127.0.0.1", "_local_delegate": { "leido_server_side": { "chars": 2848, "tokens_aprox": 712 } } }

// el modelo no devolvió JSON, o el backend falló
{ "_local_delegate": { "error": "respuesta no parseable como JSON", "crudo": "…" } }
```

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
| `LD_HOOK_READ_BLOQUEAR` | `0` | **Rechaza** la lectura en vez de sugerir. Ver abajo |
| `LD_HOOK_ENABLED` | `1` | Interruptor del experimento: `0` apaga hooks **y** telemetría, para la rama baseline de un A/B. Solo puede apagar |
| `LD_HOOK_TELEMETRY_LOG` | *(vacío = sin telemetría)* | Fichero JSONL donde los hooks registran lo que deciden |

### El bloqueo

Con `LD_HOOK_READ_BLOQUEAR=1`, una lectura **completa** de un `.md` o un `.txt` por encima del
umbral se rechaza con un mensaje que nombra la tool que sirve, el `path` para llamarla y la salida
de emergencia: leer por franjas con `offset`/`limit`, que nunca se bloquean. Lo mismo con los
volcados de shell (`cat`, `type`, `more`, `Get-Content`, `gc`, `rtk read`, `head`) sobre una única
ruta; con una tubería, una redirección, comandos encadenados o un flag que ya acota, no se bloquea.

Nace apagado. Estas son las formas de que no bloquee:

- **Apagarlo al momento: crea el fichero `~/.claude/local-delegate-bloqueo-apagado`** (vacío
  vale). Gana a la variable y el hook lo mira en cada lectura, así que no hace falta cerrar ni
  reiniciar nada; bórralo para volver a encenderlo. En PowerShell:
  `New-Item "$HOME\.claude\local-delegate-bloqueo-apagado" -ItemType File`. Con
  `LD_HOOK_READ_INTERRUPTOR` se puede poner en otra ruta.
- `LD_HOOK_READ_BLOQUEAR=0`. Ojo: una sesión ya abierta sigue con el valor con el que arrancó,
  porque hereda el entorno del lanzador. Por eso existe el fichero.
- Que el backend local no responda. El hook lo sondea él mismo (300 ms, cacheado un minuto) en vez
  de fiarse de las delegaciones anteriores, que sería un círculo cerrado: sin delegaciones no hay
  marca fresca, sin marca fresca no se bloquea, y sin bloqueo no hay delegaciones.
- Que el modelo que haría el resumen esté **en enfriamiento**: el hook lee el mismo
  `enfriamiento.json` que el servidor y, si ese modelo está parado, deja pasar la lectura. Mira el
  modelo por defecto del rol, o `LOCAL_DELEGATE_MODEL_LONG`/`_MECHANICAL` si el cliente las tiene.
- `LD_HOOK_ENABLED=0`.

Cada evento de la telemetría lleva `bloqueo` (`encendido`, `apagado_fichero` o
`apagado_variable`), para que una medición sepa en qué estado estaba la regla.

**Las lecturas por otros MCP se cuentan, no se bloquean.** `--enable-read-hook` registra el mismo
hook para las tools de lectura de otros servidores MCP (`mcp__*__read_*` y
`mcp__*__get_file_contents`). Por ese camino solo deja un evento con `camino: mcp`: sin contarlas,
una subida de las delegaciones no distinguiría «se delegó» de «se leyó por otro sitio».

`.json`, `.csv`, `.log` y `.yaml` **se avisan pero no se bloquean**: ahí se busca un valor exacto
—un `package.json`, la línea del error— y un resumen no sustituye a la lectura. El código no dice
nada, ni antes ni ahora.

## Auto-arranque de llama-swap (opt-in)

Solo se usa si `LOCAL_DELEGATE_AUTOSTART=1`. Específico de llama-swap.

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_AUTOSTART` | `0` | `1` intenta arrancar llama-swap si el endpoint no responde |
| `LLAMASWAP_EXE` | *(busca `llama-swap` en PATH)* | Ruta al ejecutable |
| `LLAMASWAP_CONFIG` | *(vacío)* | Ruta al `config.yaml` de llama-swap |
| `LLAMASWAP_LISTEN` | `127.0.0.1:9292` | host:puerto de llama-swap |
| `LLAMASWAP_WATCH_CONFIG` | `0` | `1` añade `-watch-config` cuando hay `LLAMASWAP_CONFIG` |
