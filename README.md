<!-- mcp-name: io.github.ZahiriNatZuke/local-delegate -->

# local-delegate

**Delega tareas mecánicas texto→texto a un LLM local para conservar la cuota de tu suscripción de Claude.**
Un servidor MCP (`stdio` o daemon HTTP compartido) que es cliente **genérico** de cualquier
endpoint OpenAI-compatible — llama-swap, Ollama, LM Studio, vLLM.

[![PyPI](https://img.shields.io/pypi/v/local-delegate-mcp.svg)](https://pypi.org/project/local-delegate-mcp/)
[![CI](https://github.com/ZahiriNatZuke/local-delegate/actions/workflows/ci.yml/badge.svg)](https://github.com/ZahiriNatZuke/local-delegate/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

**[zahirinatzuke.github.io/local-delegate](https://zahirinatzuke.github.io/local-delegate/)** — qué
hace y por qué, en una página (es/en). Su fuente está en [`site/`](./site).

## Demo

<!-- URL absoluta a raw.githubusercontent.com para que la imagen también se renderice en
     PyPI (los links relativos solo se resuelven dentro de GitHub). -->
![Dashboard de ahorro de local-delegate](https://raw.githubusercontent.com/ZahiriNatZuke/local-delegate/main/docs/assets/dashboard.png)

*Dashboard embebido (datos de ejemplo): estado del backend local (modelos montados, delegación en curso con su progreso por trozos, tools MCP), RAM/VRAM del sistema con consumo por proceso, tokens de contexto conservados, ahorro por herramienta y modelo, dónde corrió el cómputo —esta máquina o un backend remoto— y actividad reciente paginada en tu hora local. Se sirve en `http://127.0.0.1:9393`.*

## ¿Por qué?

Cuando Claude tiene que resumir un log enorme, clasificar, extraer campos o generar boilerplate,
gasta cuota de tu suscripción en trabajo **mecánico**. `local-delegate` expone esas tareas como
tools MCP que corren en un LLM **local**: pasas `path` en vez de `text` y el archivo se lee
**del lado del servidor**, así el contenido grande **nunca entra al contexto de Claude**. Solo
vuelve el resultado corto: el documento no ocupa tu ventana de contexto ni lo procesa Claude.

## Instalación rápida

Con [`uv`](https://docs.astral.sh/uv/) no hay nada que instalar: `uvx` baja y ejecuta el paquete aislado.

Añádelo a tu config de MCP (Claude Desktop / Claude Code) en modo compatible `stdio`:

```json
{
  "mcpServers": {
    "local-delegate": {
      "command": "uvx",
      "args": ["local-delegate-mcp"]
    }
  }
}
```

Ver plantillas completas en [`examples/`](./examples).

O deja que el paquete lo configure todo por ti —entrada MCP, hooks, skill y la regla de
delegación en tu `CLAUDE.md`/`AGENTS.md` global— con un solo comando:

```bash
uv tool install local-delegate-mcp          # deja `local-delegate` en el PATH
local-delegate install --dry-run            # muestra exactamente qué tocaría
local-delegate install                      # aplica
```

También sirve `uvx local-delegate-mcp install` para probarlo sin instalar nada, pero ten en cuenta
que **`uvx` no deja el comando disponible**: monta un entorno efímero y lo borra al terminar, así
que después `local-delegate doctor` responderá «command not found». El propio `install` te lo avisa
si detecta ese caso.

Es idempotente, deja `.bak` de lo que edita (la primera vez que lo toca; después no lo pisa), no
toca configuración ajena y se revierte con `local-delegate uninstall`. Desde la 0.44.0 escribe de
forma atómica, reaplica su cambio si Claude Code guarda el fichero a la vez, y si un fichero no está
en UTF-8 (cp1252, UTF-16) la acción falla sin tocarlo. Detalle y opciones en [Instalación de la integración](./docs/wiki/Integration-install.md).

¿Autocompletado con Tab de subcomandos, opciones y valores? `local-delegate install
--shell-completion` lo deja cargado en el perfil de PowerShell, zsh o bash (opt-in, reversible con
`uninstall --shell-completion`), y `local-delegate completion powershell|zsh|bash` imprime el script
por si prefieres cargarlo tú. Ver [Autocompletado del shell](./docs/wiki/Integration-install.md#autocompletado-del-shell).

Si usas **varias sesiones o varios clientes** en la misma máquina, se recomienda un solo daemon:

```powershell
uvx local-delegate-mcp serve
```

El daemon sirve MCP en `http://127.0.0.1:9393/mcp` y el dashboard en
`http://127.0.0.1:9393/`. Codex, Claude Code, opencode y cualquier cliente compatible con Streamable HTTP
pueden compartir esa URL sin levantar procesos MCP duplicados. Con un llama-swap local, el extra
`[llamaswap]` y `LLAMASWAP_CONFIG` apuntando a su `config.yaml`, el daemon además **reparte el backend por turno**:
dos delegaciones cuyos modelos se desalojarían entre sí no se pisan, y la segunda espera (el panel
lo enseña como espera local). Guía completa: [Daemon compartido](./docs/wiki/Daemon.md).

Una delegación puede sumar espera de turno e inferencia, y algunos clientes cortan antes: **Codex
corta toda llamada a una tool MCP a los 60 s** (`tool_timeout_sec` en `[mcp_servers.local-delegate]`
de `config.toml` lo sube, y hay que reponerlo tras cada `install`/`update`, que reescriben ese
bloque) y Claude Code corta una llamada HTTP **tras 5 min sin respuesta** (la variable
`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`, en ms, lo sube y sobrevive a `install`). Detalle en
[Instalación de la integración](./docs/wiki/Integration-install.md#plazos-de-los-clientes-mcp).

Para usar la GPU de otra máquina manteniendo los paths locales del cliente, usa un MCP local que
apunte al backend remoto: [guía Mac → PC](./docs/wiki/Remote-backend.md) y
[recipe técnica completa](./docs/recipes/remote-backend.md).

> **No fijes una versión vieja «por estabilidad».** Un pin (`==X.Y.Z`) congela también los rangos de
> dependencias que declaraba aquel wheel, y eso envejece mal: las versiones anteriores a la 0.12.2
> pedían `mcp` **sin techo**, así que hoy resuelven al SDK 2.x y **mueren en el import**. Si necesitas
> fijar, fija la **actual**, y súbela cuando salga una nueva.

En Windows, si lo registras como tarea al iniciar sesión, ejecuta el `pythonw.exe` del entorno
donde instalaste el paquete con `-m local_delegate serve --log-level warning`. `pythonw` no crea
consola ni botón en la barra de tareas. La tarea pertenece al usuario de **Windows**, no a Codex
ni a Claude: cualquier cliente local comparte el mismo daemon. El dashboard identifica ese único
proceso con la insignia `DAEMON MCP`; las sesiones conectadas son clientes HTTP, no procesos MCP
adicionales.

**Al actualizar en Windows, para el daemon antes de `uv tool install --force`.** Con el daemon
corriendo, la reinstalación puede fallar a mitad (tiene abiertos ficheros del entorno) y dejarlo
roto; `schtasks /End` no basta porque el lanzador está desacoplado, así que para el proceso
`pythonw` del daemon, instala y vuelve a lanzarlo. Después, `local-delegate update` repone hooks,
skill y el bloque de `CLAUDE.md`/`AGENTS.md` si quedaron desfasados.

Si instalaste con una versión fija (`uv tool install "local-delegate-mcp==X.Y.Z"`), `uv tool
upgrade` dice «Nothing to upgrade» y no sube nada: reinstala con
`uv tool install "local-delegate-mcp[llamaswap]@latest"` (con tus extras). Desde la 0.45.1,
`local-delegate update` y `doctor` lo detectan y dan ese comando.

> **La 0.36.0 habla en español o en inglés y sigue al idioma del sistema.** Con el sistema en
> inglés pasarás a ver inglés: para quedarte en español, `LOCAL_DELEGATE_LANG=es local-delegate
> install` (o `update`). Las claves de `_local_delegate` y los marcadores de las tools pasan a
> inglés (cambio incompatible); la tabla está en el [CHANGELOG](./CHANGELOG.md) y en
> [Idioma](./docs/wiki/Language.md).

> **La 0.35.0 renombra comandos, variables, la skill y ficheros de datos a inglés.** Los nombres
> viejos funcionaron con aviso desde la 0.35.0 y **en la 0.38.0 se retiraron**: ya no
> tienen efecto. `local-delegate doctor` nombra los que sigan puestos (hasta la 0.40.x) y
> `local-delegate update` migra los que puede. Volver a una versión anterior no está soportado. La
> tabla completa está en el [CHANGELOG](./CHANGELOG.md).

## Requisitos

**Python 3.11+** — con `uvx` no tienes que instalarlo tú, lo resuelve él; solo importa si instalas
con `pip` en un entorno propio.

Y un **endpoint OpenAI-compatible** ya corriendo, accesible en `LOCAL_DELEGATE_BASE_URL`
(default `http://127.0.0.1:9292/v1`). Cualquiera sirve:

- **llama-swap** — ver [recipe con GPU Blackwell](./docs/recipes/llama-swap-blackwell.md).
- **Ollama** — `http://127.0.0.1:11434/v1`.
- **LM Studio**, **vLLM**, o cualquier servidor que hable la API de OpenAI.

El paquete **no arranca** ningún backend por defecto (`LOCAL_DELEGATE_AUTOSTART=0`). El
auto-arranque de llama-swap es opt-in (ver tabla de configuración).

¿Qué versiones de `llama-server`/`llama-swap` usar y cómo disponer el workspace? Ver
[Versiones del backend y workspace de referencia](./docs/wiki/Backend-versions.md) (sugerencia
probada, no requisito). `local-delegate doctor` compara tu instalación contra esas versiones y, de
paso, comprueba el resto del andamiaje —hooks, skill, memoria, entradas MCP y el daemon— sin
escribir nada ([qué mira cada check](./docs/wiki/Integration-install.md#comprobar-la-instalación-local-delegate-doctor)).

## Tools

Pasar `path` (en vez de `text`) hace que el MCP lea el archivo server-side: el contenido no entra
al contexto de Claude, y de ahí sale el ahorro.

| Tool | Qué hace | Rol de modelo (default) |
|---|---|---|
| `local_summarize` | Resume texto o archivo; `focus` opcional para decir qué conservar (p. ej. «cifras de configuración») | mecánico / largo (auto) |
| `local_classify` | Devuelve UNA etiqueta de una lista | mecánico |
| `local_extract` | Extrae campos → **objeto validado**, no una cadena que haya que parsear | mecánico / largo (auto) |
| `local_boilerplate` | Genera código desde una spec y lo **escribe en `target`**; devuelve solo un recibo | código |
| `local_delegate` | Escape genérico texto→texto | mecánico (o el que pases) |
| `local_lint_summary` | Resume logs de lint/tests/CI | mecánico / largo (auto) |
| `local_commit_msg` | Mensaje de commit desde un diff | código |
| `local_translate` | Traduce texto o archivo | mecánico / largo (auto) |
| `local_explain_code` | Explica código en prosa | código |
| `local_describe_image` | Describe una imagen o responde una pregunta sobre ella (imagen→texto) | visión |
| `local_status` | Diagnóstico de solo lectura: backend, catálogo, log, VRAM, RAM de sistema | — (no llama al backend de chat) |

Los modelos locales **no** usan tool-calling: el server arma el prompt + guardrails, hace POST al
endpoint y devuelve **solo texto**.

**Documentos largos.** `local_translate` (y `local_delegate` con entradas largas) parten el texto
por límites naturales —headers Markdown, párrafos, líneas— y procesan **un trozo por llamada**
respetando el techo de `max_tokens`, concatenando las salidas en orden y conservando el formato en
las costuras. Un documento de 20 000+ caracteres vuelve completo en vez de cortado a mitad. El log
registra `chunks: N` y el dashboard muestra el progreso (`trozo 3/7`) mientras corre. Desde la
0.43.0, «En curso» dice también la fase: «Combinando 3 trozos…» mientras se juntan los parciales y
«Reintentando trozo n/total» cuando un trozo cortado se vuelve a partir; y la actividad separa
trozos de llamadas al backend (`3 +1`: tres trozos y una combinación).

**Llamadas largas y colas.** Desde la 0.45.0 cada llamada viva manda progreso MCP cada 20 s con su
fase («esperando turno, puesto N», «procesando el trozo k/N»), así que Claude Code ya no corta a los
300 s una delegación que espera en la cola. El daemon pone a cada llamada un plazo propio
(`LOCAL_DELEGATE_CALL_MAX_S`, 1800 s) y, si la cola lleva 900 s sin avanzar, falla en el acto con
«cola saturada» en vez de colgar al cliente. Las delegaciones abortadas quedan en el log como
errores, «En curso» separa «Procesando (n)» de «En cola (m)», y cada entrada del log dice desde qué
máquina vino (`host`) y cuánto esperó en cada fase (`concurrency`). Desde la 0.46.0 una
delegación troceada larga cede el turno entre trozos a la que choca con ella
(`LOCAL_DELEGATE_TURN_YIELD_S`, 120 s), «En curso» agrupa en «Esperando al backend» la llamada que
espera a que llama-swap cambie de modelo, y un `read_timeout` nombra el modelo que lo bloqueaba.

**Resúmenes de documentos enormes.** `local_summarize` y `local_lint_summary` hacen **map-reduce**
cuando la entrada no cabe en el modelo: resumen cada parte y luego resumen los resúmenes, por
niveles si hace falta. Antes truncaban —de un log de CI enorme se resumía el principio y el resto
se descartaba en silencio, que es justo donde suelen estar los errores— y ahora se lee entero. Si
algún trozo se corta por `max_tokens`, el resultado lo avisa y el log registra `finish_reason:
length`. Desde la 0.43.0 un parcial cortado ya no se da por bueno: se descarta, se parte el trozo
(o el grupo del reagrupado) y se reintenta, hasta dos niveles; si aun así queda alguno cortado, el
aviso dice qué trozo y sus líneas.
Desde la 0.36.1, con un log que no cabe en una llamada, `local_lint_summary` da entrada solo a los
diez ficheros más nombrados (y dice cuántos más hay), y las cifras del resumen final las pone el
programa, no el modelo.
Desde la 0.36.0 también `local_commit_msg`, `local_explain_code` (por `def`/`class` de primer
nivel, con el inventario de nombres en el paso final) y `local_extract` (un objeto parcial por
trozo y un paso final con schema que los combina) leen la entrada entera. Desde la 0.44.2, si tras
trocear algún campo de `local_extract` queda `null` en todos los trozos, `_local_delegate.chunked`
lo dice (`pieces`, `null_fields`, `notice`): ese `null` significa «no visto», no «no existe».

## Configuración

Todo por variables de entorno; nada hardcodeado. Los ids de modelo default son solo eso —
cámbialos por los de tu backend.

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_BASE_URL` | `http://127.0.0.1:9292/v1` | Endpoint OpenAI-compatible |
| `LOCAL_DELEGATE_API_KEY` | *(vacío)* | Bearer token, si tu endpoint lo exige |
| `LOCAL_DELEGATE_BACKEND_ORIGIN` | `auto` | `local`/`remote` fuerzan el origen del cómputo; `auto` lo deduce del host. Ponlo si llegas al backend por un **túnel** (`ssh -L`, port-forward): en loopback se vería como local |
| `LOCAL_DELEGATE_TIMEOUT` | `180` | Timeout HTTP (segundos) |
| `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS` | `2` | Backpressure máximo por proceso; compartido por todos los clientes del daemon |
| `LOCAL_DELEGATE_ASK` | `1` | Preguntar al usuario (vía `elicitation`) en vez de fallar seco: backend caído, modelo fuera del catálogo, `output_format` vacío. `0` lo desactiva |
| `LOCAL_DELEGATE_ASK_TIMEOUT` | `30` | Segundos de espera por una respuesta; agotados, la tool sigue como si no hubiera preguntado |
| `LOCAL_DELEGATE_LOG_DIR` | *(dir de datos de usuario)* | Directorio de los `usage-YYYYMM.jsonl` rotados por mes y del `clients.jsonl` |
| `LOCAL_DELEGATE_LOG` | *(vacío = rotación activa)* | Si se fija, ruta de un `usage.jsonl` explícito sin rotar (compatibilidad) |
| `LOCAL_DELEGATE_MACHINE_NAME` | *(nombre corto del equipo)* | Nombre de esta máquina en el log de uso (`host`) y en la cabecera `X-Local-Delegate-Host` que va al backend; útil si dos equipos se llaman igual |
| `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | Modelo para clasificar/extraer/resumen corto |
| `LOCAL_DELEGATE_MODEL_LONG` | `gemma4-26b-a4b` | Modelo para documentos largos |
| `LOCAL_DELEGATE_MODEL_CODE` | `qwen36-35b-a3b` | Modelo para código |
| `LOCAL_DELEGATE_MODEL_VISION` | `gemma4-12b` | Modelo de visión para `local_describe_image` |
| `LOCAL_DELEGATE_MAX_IMAGE_MB` | `8` | Tope de tamaño de imagen para `local_describe_image` |
| `LOCAL_DELEGATE_DUMP_CHUNK_NOTES` | *(vacío: apagado)* | Carpeta local donde cada operación troceada deja la salida de cada paso; solo para medir, nunca sale de la máquina |
| `LOCAL_DELEGATE_LONG_INPUT_CHARS` | `6000` | Umbral mecánico↔largo |
| `LOCAL_DELEGATE_CHUNK_CHARS` | `3500` | Tamaño de trozo al partir documentos largos (`local_translate`, `local_delegate`) |
| `LOCAL_DELEGATE_CHUNK_MAX_TOKENS` | `2048` | Techo de `max_tokens` por trozo |
| `LOCAL_DELEGATE_CHUNK_MIN_CHARS` | `400` | Trozo mínimo: por debajo ya no se vuelve a partir |
| `LOCAL_DELEGATE_JSON_SCHEMA` | `auto` | `response_format` con schema en `local_extract`: `auto`/`on`/`off` |
| `LOCAL_DELEGATE_FEEDBACK` | `1` | Línea de ahorro anexada al resultado cuando `source=path` (`0` la apaga). En `local_extract` no se anexa al texto —rompería el JSON—: va dentro de `_local_delegate` |
| `LOCAL_DELEGATE_ALLOWED_DIRS` | *(vacío = sin restricción)* | Raíces permitidas para `path`, separadas por `;` |
| `LOCAL_DELEGATE_WEB` | `1` | Web embebida del modo `stdio` (`0` para desactivarla). Desde la 0.42.0 pide el token de `LOCAL_DELEGATE_WEB_TOKEN` si está puesto, igual que el daemon |
| `LOCAL_DELEGATE_WEB_HOST` / `_PORT` | `127.0.0.1` / `9393` | Host/puerto de la web o del daemon. Vacía cuenta como no puesta |
| `LOCAL_DELEGATE_WEB_ALLOWED_HOSTS` | *(vacío)* | Nombres extra que el puerto admite en la cabecera `Host`, separados por comas (p. ej. el de `tailscale serve`). Por defecto solo loopback y `WEB_HOST`, contra el DNS rebinding (desde la 0.42.0: sin ella, entrar por otro nombre da 421); `*` desactiva la comprobación |
| `LOCAL_DELEGATE_WEB_FONTS` | `1` | Tipografía de marca desde Google Fonts (`0` = cero peticiones a terceros) |
| `LOCAL_DELEGATE_AUTOSTART` | `0` | Auto-arranque de llama-swap (opt-in) |
| `LLAMASWAP_EXE` / `LLAMASWAP_CONFIG` / `LLAMASWAP_LISTEN` | — | Solo si `AUTOSTART=1`; `LLAMASWAP_CONFIG` además activa el turno y la afinidad del daemon (con el extra `[llamaswap]`). `LLAMASWAP_EXE` tiene que ser una ruta **absoluta** a un fichero que exista (si no, avisa y no arranca); sin ella, `llama-swap` se busca solo en las carpetas absolutas del `PATH`, nunca en la carpeta actual (desde la 0.44.0) |
| `LLAMASWAP_WATCH_CONFIG` | `0` | `1` añade `-watch-config` al backend autoarrancado |
| `LOCAL_DELEGATE_FALLBACK` | `1` | Respaldo entre modelos: si el modelo de un rol falla por su culpa, responde el siguiente de su cadena (`_MAX_HOPS`=2; cadenas con `_<ROL>`, ver la wiki). `0` lo apaga |
| `LOCAL_DELEGATE_COOLDOWN` | `1` | Enfriamiento por modelo: 3 fallos seguidos (`_FAILURES`) lo paran 120 s (`_S`), doblando hasta 900 s (`_MAX_S`). `0` lo apaga |
| `LOCAL_DELEGATE_BACKEND_BREAKER` | `1` | Corte por backend inalcanzable: 3 fallos de conexión seguidos (`_FAILURES`) hacen que las `local_*` respondan al momento «backend inalcanzable, hazlo tú» durante 60 s (`_S`), doblando hasta 600 s (`_MAX_S`), sin contar como delegación; al vencer, la siguiente llamada prueba. `0` lo apaga |
| `LOCAL_DELEGATE_COST_FALLBACK` | *(vacío = `claude-opus-5-5` en subagente)* | Con qué modelo e hilo se valora una delegación sin modelo atribuido: `modelo` o `modelo:main\|subagent`. Un valor inválido no rompe nada: el panel usa el declarado y lo dice |
| `LOCAL_DELEGATE_COMMIT_LANGUAGE` | *(vacío = el idioma vigente)* | Idioma del mensaje de `local_commit_msg`: `es`, `en`, `fr`, `pt`, `de`, `it` o un nombre libre. Vacío: el idioma vigente del producto; `diff`: el idioma predominante de los textos del diff |
| `LOCAL_DELEGATE_OUTPUT_LANGUAGE` | *(vacío = el idioma vigente)* | Idioma en que las tools de texto libre (`local_summarize`, `local_lint_summary`, `local_explain_code`, `local_describe_image`) piden responder al modelo: `fr`, `pt`, `português`… No cambia la interfaz ni `local_commit_msg` |
| `LOCAL_DELEGATE_TURN_MAX_S` | `600` | Turno del daemon entre modelos que chocan en llama-swap: si la primera de la cola lleva estos segundos esperando **y** el daemon lleva otros tantos sin que empiece ni termine ninguna llamada al backend, se le concede el turno igual (`turn: "forced"` en el log) |
| `LOCAL_DELEGATE_TURN_YIELD_S` | `120` | Cesión del turno entre trozos: si la primera de la cola lleva estos segundos esperando un modelo que choca con el de una operación que tiene el turno desde hace otro tanto, esa operación lo suelta antes de su siguiente trozo y vuelve al final de la cola (`turn_yields` en el log). Coste: como mucho una pareja de cargas de modelo cada este tiempo cuando dos operaciones largas chocan. `0` lo desactiva |
| `LOCAL_DELEGATE_CALL_MAX_S` | `1800` | Plazo propio del daemon para una llamada, cola incluida: al pasarlo se cancela y queda en el log como fallo (`cancel_reason: "deadline"`). `0` lo desactiva |
| `LOCAL_DELEGATE_PROGRESS_INTERVAL_S` | `20` | Cada cuántos segundos una llamada viva manda `notifications/progress` con su fase (puesto en la cola, plaza, trozo k/N), para que el cliente no la corte por inactividad (Claude Code: 300 s). `0` lo desactiva |
| `LOCAL_DELEGATE_QUEUE_MAX_WAIT_S` | `900` | Máximo de segundos que quien espera turno o plaza aguanta **sin que la cola avance** (una cola lenta que avanza no corta a nadie): al pasarlo la llamada falla en el acto con «cola saturada» (`error: "queue_saturated"`). `0` lo desactiva |
| `LOCAL_DELEGATE_SLOW_THRESHOLD` | `0.5` | Una llamada es «lenta» (`slow` en el log, «lento ×0,37» en el panel) si genera a menos de esta fracción de la velocidad normal de su modelo |
| `LOCAL_DELEGATE_AFFINITY_MARGIN_S` | `5` | Afinidad: un modelo ya cargado solo se aprovecha si le quedan al menos estos segundos de TTL |
| `LOCAL_DELEGATE_BACKEND_PARAMS` | *(vacío)* | Override puntual, clave a clave, de los parámetros por rol de `backend-params.json` (muestreo y razonamiento): `rol.clave=valor;…`, p. ej. `code.top_k=20`. Exige reiniciar el daemon; el fichero no |

Los **parámetros por rol** que viajan en cada petición al backend (`top_k`, `temperature`,
`enable_thinking` con su presupuesto…) se guardan en `backend-params.json` y se editan con
`local-delegate backend-params show|set|unset|reset`; la lista cerrada de claves, la precedencia y
el razonamiento están en la [wiki](docs/wiki/Configuration.md#parámetros-del-backend-por-rol).

## La métrica de ahorro

El MCP registra cada llamada en un log rotado por mes y sirve un **dashboard** en
`http://127.0.0.1:9393`, con selector de rango y visibilidad de delegaciones en curso.
El *contexto conservado* = la entrada leída server-side (llamadas con `source=path` que salieron
bien) menos lo que la tool te devolvió, contada **una vez por delegación** aunque el MCP la trocee.
Se mide en caracteres y se pasa a **tokens de Claude** con una tabla de densidad medida por familia
de tokenizador y tipo de contenido (prosa, código, log, datos estructurados, diff): un `.md` no
cuenta lo mismo que un `.json`, y Haiku 4.5 no cuenta como Opus 5.5. Las imágenes salen de esa
cifra —sin sus dimensiones no hay forma de saber cuántos tokens le costarían a Claude— y se enseñan
aparte. Enfrente, el *coste local* = los tokens que consumió de verdad tu GPU **sumando todas** las
llamadas: una delegación troceada repite el prompt de sistema en cada trozo, y esa diferencia es lo
que costó trocear. Ahí se usa el token real que reporta el backend; `chars ÷ 4` es solo el respaldo
del modelo **local** cuando no lo da. Detalle en la [wiki](./docs/wiki/Savings-and-metrics.md).

El panel enseña además un **equivalente estimado a precio de API**: lo que costaría ese mismo
contexto leído por Claude a precio de lista, entre una cota baja y una estimación que cuenta las
peticiones en las que ese contenido se habría vuelto a leer de la caché. **No es dinero que hayas
ahorrado**: tu suscripción es de tarifa plana. Es una estimación con supuestos a la vista (con qué
modelo se atribuye cada delegación, cuántas peticiones siguieron, qué densidad se usó) y no
descuenta las relecturas del mismo fichero. Junto a ella, un bloque de **cuota** que sale «sin
calibrar» hasta que hay al menos tres medidas del statusline de ventanas distintas, y nunca enseña
un porcentaje sin esa calibración. Para atribuir el histórico y alimentar esos dos bloques, lanza
de vez en cuando `local-delegate recompute-cost` (lee tus transcripts en local y escribe solo
agregados); `doctor` avisa si hay delegaciones a punto de quedarse sin transcript.

Las **pruebas no cuentan**: las delegaciones del cliente `mcp` de los scripts, las de bancos y
las que caen en una **ventana de prueba** se apartan del panel y de `local_status`. Antes de probar
en vivo contra el MCP o el daemon, marca el intervalo y guarda el id que imprime:

```bash
local-delegate test-window start --label "prueba del lunes"   # imprime el id
local-delegate test-window stop <id>
local-delegate test-window list                               # ventanas y filas en cada una
```

El botón **Pruebas** de la barra del panel las vuelve a enseñar; su ⓘ dice cuántas quedaron fuera.

El panel sale en español o en inglés según el idioma de tu navegador, y el selector `ES`/`EN` de su
cabecera lo cambia (se recuerda en ese navegador). Ver
[Savings & metrics](docs/wiki/Savings-and-metrics.md#idioma).

Los rangos, los días del gráfico y las horas de la tabla usan **tu zona horaria** (el log se
escribe en UTC, que es un instante sin ambigüedad; la conversión es de presentación). El
dashboard también separa **dónde corrió el cómputo**: `local` si el backend escucha en loopback,
`remote` si la inferencia se fue a otra máquina —por ejemplo esta Mac usando la GPU de la PC—.
Los eventos anteriores a la v0.11.0 no traen el campo y aparecen como `n/d`.

## Alcance / no-objetivos

`local-delegate` es deliberadamente **texto/imagen→texto**: arma el prompt (o el payload
multimodal), hace POST a `/chat/completions` y devuelve solo texto. Cosas que **no** hace
a propósito:

- **Tool-calling local.** Los modelos locales no invocan herramientas ni ejecutan código;
  eso lo sigue haciendo Claude. Añadirlo convertiría este paquete en un orquestador
  paralelo, que no es el objetivo.
- **Generación o edición de imágenes.** `local_describe_image` es solo imagen→texto
  (describir, leer texto visible, responder una pregunta puntual); nada de generar ni
  editar imágenes.
- **Audio.** Para transcripción usa el companion
  [`whisper-transcribe-mcp`](https://github.com/ZahiriNatZuke/whisper-transcribe-mcp) en
  vez de intentar meter audio aquí.
- **Sustituir la suscripción.** El objetivo es conservar cuota delegando pasos mecánicos
  acotados, no enrutar todo el trabajo a modelos locales.

## Integración con el cliente: hooks, skill y memoria

`local-delegate install` deja lista la integración completa en tu HOME:

| Componente | Dónde | Qué hace |
|---|---|---|
| Entrada MCP | config de Claude Code / `~/.codex/config.toml` / `~/.config/opencode/opencode.json[c]` | registra el servidor (stdio con `uvx` o HTTP contra el daemon) |
| Hooks | plugin de Claude Code `local-delegate@local-delegate` (o `~/.claude/hooks/local-delegate/` + `settings.json`) | sugieren delegar; los de lectura además pueden **rechazar** una lectura completa de documentación, si se enciende; uno anota qué agente pidió cada delegación |
| Skill | `~/.claude/skills/local-delegation/` y `~/.config/opencode/skill/local-delegation/` | regla de oro y catálogo de tools |
| Memoria | bloque gestionado en `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` y `~/.config/opencode/AGENTS.md` | la regla en una nota corta siempre cargada |

Por defecto se configuran **solo los clientes que tengas instalados**; se elige a mano con
`--clients claude|codex|opencode`. Los **hooks** son solo de Claude Code: opencode extiende con
plugins en TypeScript, que es otra superficie, y Claude Desktop no tiene hooks en absoluto. Cada
pieza se puede excluir (`--no-hooks`, `--no-skill`, `--no-memory`, `--no-mcp`).

Todo sale en **español o en inglés**. `install` y `update` guardan el idioma de la sesión en
que corren (`LOCAL_DELEGATE_LANG=es|en`, o el del sistema) en `language.json`, para que el
daemon y los hooks lo usen también, y escriben la skill, el bloque de memoria y el catálogo de
los subagentes en ese idioma. Precedencia y cómo volver a seguir al sistema:
[Idioma](./docs/wiki/Language.md).

Actúan solos tres hooks: `UserPromptSubmit` (intenciones mecánicas), `SubagentStart` (le recuerda
a cada subagente cargar las tools `local_*` y leer por rangos) y `record_call.py`
(`PreToolUse` sobre las tools de local-delegate), que no avisa ni bloquea: anota qué agente pidió
cada delegación y con qué esfuerzo, para atribuir el coste equivalente a su modelo. Los dos de
lectura —`PreToolUse`/`Read` y `PreToolUse`/`Bash|PowerShell`— quedan apagados salvo
`--enable-read-hook`, que los enciende juntos (`--disable-read-hook` o `uninstall` los apagan). Van juntos
porque son una regla sola sobre dos caminos: cerrar la tool `Read` y dejar `cat informe.md`
abierto no cambia la conducta, la muda de sitio. Con una imagen grande que acepta
`local_describe_image` (`.png`, `.jpg`, `.gif`, `.webp`) el aviso recomienda esa tool con `path`,
no una lectura por rangos; `.svg`, `.bmp`, `.ico`, las imágenes pequeñas, los `.pdf` y los
`.ipynb` pasan en silencio.

Esos dos avisan; **rechazar** una lectura es otra cosa y viene aparte y apagada
(`LD_HOOK_READ_BLOCK`). Solo alcanza a la lectura completa de un `.md` o un `.txt` grande, con
el backend local respondiendo, y el mensaje del rechazo nombra la tool que sirve y la salida de
emergencia: leer por franjas nunca se bloquea. El motivo de que exista es que está medido —cuatro
veces— que sugerir no cambia la conducta.
Ver [Instalación de la integración](./docs/wiki/Integration-install.md) y
[`docs/recipes/claude-code-hooks.md`](./docs/recipes/claude-code-hooks.md).

### Plugin de Claude Code, comandos del mod y Claude Desktop

Desde la 0.40, con Claude Code 2.1.292 o posterior instalado con `uv tool`, `install` entrega los
hooks como un **plugin** (`local-delegate@local-delegate`) en vez de escribirlos en
`settings.json`, y migra sola una instalación anterior conservando el bloqueo de lectura. Si no se
cumplen las condiciones, sigue con `settings.json` y dice por qué; `--claude-delivery settings`
vuelve atrás a mano y `update` lo respeta. El MCP **no** va dentro del plugin.

El plugin trae además un **mod**, que corre dentro de Claude Code sin gastar turnos del modelo:

- `/local-summarize <ruta>`, `/local-commit` (propone el mensaje desde `git diff --cached`; solo
  lo muestra) y `/local-lint <fichero|comando>` llaman a la tool local directamente.
- Deja fijas `local_summarize`, `local_extract`, `local_lint_summary` y `local_commit_msg`, para
  que el modelo no tenga que buscarlas con ToolSearch.
- Pone sobre el prompt una banda con el estado de local-delegate en la sesión: en la terminal,
  una barra de una fila con fondo y una etiqueta de estado (` ● LISTO `, ` ◐ DELEGANDO `,
  ` ○ CAÍDO `), el modelo, la tool en curso con su trozo (`7/9`) y lo que lleva (`3 min 16 s`), las delegaciones y el ahorro de la
  sesión y el modo de lectura (opción `status_style`: `bar` o `line`, una raya sobre una línea);
  en Claude Desktop, una sola línea de texto en dos tonos, sin píldora ni enlace. Desde la 0.45.0,
  con varias delegaciones a la vez nombra primero la que procesa el backend y, si todas esperan, la
  más antigua con su espera (`en cola · 4 min 0 s`). Una delegación que espera a que llama-swap
  cambie de modelo dice ` ◐ ESPERANDO BACKEND ` con el modelo que pidió, no el cargado. Se
  refresca sola cada segundo mientras hay una delegación en curso. La cuota de Claude no va
  aquí: es de la status line.
- Desde la 0.41, el **mod de lectura** (encendido por defecto, opción `read_mod_enabled`) resume
  con `local_summarize` la prosa grande que se lee entera y entrega el resumen como resultado de
  la propia tool; con diálogo pregunta antes. Tras un resumen, escribir en ese fichero se rechaza
  hasta leerlo de verdad. Mientras actúa, los hooks de lectura de la sesión se apartan. Para
  decidir qué lee cada llamada le pregunta al daemon, sin arrancar procesos (la sobrecarga medida
  por llamada `Bash` queda dentro del ruido). Sin valor guardado cuenta como encendido; si lo
  apagaste en la 0.40.0, se vuelve a encender en el menú de configuración del plugin. Desde la
  0.44.2 una lectura por rango pasa siempre literal en un subagente (sin gastar el margen del
  80 % del hilo principal), en un fichero corto (200 líneas o menos y menos de 32 KB) y cuando el
  rango empieza después de la última línea.
- Tras actualizar, abre una sesión nueva de Claude Code: los mods se cargan al empezar la sesión.

En Windows, `install --desktop` añade el chat de **Claude Desktop**: escribe una entrada que lanza
`local-delegate desktop-bridge`, un puente stdio hacia el daemon que lee el token él mismo, porque
Desktop no pasa su entorno a los MCP. Para bajar a la 0.39, `uninstall` antes. Todo el detalle en
[Entrega por plugin de Claude Code](./docs/wiki/Claude-plugin.md).

## Groups de llama-swap (opcional)

Con `pip install "local-delegate-mcp[llamaswap]"` quedan disponibles los CLIs para gestionar
**groups** de llama-swap (un pool que se turna y, solo si lo pides, un modelo que se queda
cargado) con guardrail de VRAM **y RAM de sistema** incorporado (`--ram-gb` es opcional: `llama-server`
mapea el GGUF también en RAM aunque el cómputo sea 100% GPU, así que un catálogo que cabe en
VRAM puede igual agotar la RAM en máquinas con menos de 32 GB):

```bash
local-delegate check-llamaswap --config config.yaml --vram-gb 16 --ram-gb 32
local-delegate init-llamaswap --config config.yaml --swap gemma3-4b,gemma4-26b-a4b,qwen36-35b-a3b --vram-gb 16 --ram-gb 32
local-delegate llamaswap residency            # qué se queda cargado y con qué TTL; no escribe
local-delegate llamaswap residency --none --ttl gemma3-4b=120   # volver a «ningún residente»
```

**Lo recomendado es ningún residente**: con el turno del daemon, los modelos que chocan se
reparten el backend sin pelearse, y un modelo ya cargado se aprovecha cuando hay una celda
aprobada para esa tool (ver [Tools](./docs/wiki/Tools.md)). La **residencia es opt-in**:
`init-llamaswap --resident ID` o `llamaswap residency --pin ID` dejan ese modelo en un grupo
`persistent` con `ttl: 0`, y **retiene su VRAM de forma permanente** (`--pin` pide la VRAM medida de
cada modelo con `--vram-model ID=GiB` y se niega si no cabe junto al peor caso del resto). `--ttl-resident` vale 0 por defecto: con `persistent` y un TTL
mayor que 0 el modelo se descarga igual y no hay residencia de verdad.

El paquete **nunca** toca tu `config.yaml` por su cuenta — estos comandos solo corren si vos
los invocás. `init-llamaswap` corre el/los guardrail(es) antes de escribir (no escribe nada si
no cabe en VRAM o, si pasaste `--ram-gb`, en RAM) y nunca sobreescribe sin `--force` (dejando
una copia `<config>.<AAAAMMDD-HHMMSS>.bak`). `llamaswap residency` edita solo las líneas que
cambian, deja la misma copia con fecha, no escribe con delegaciones en curso (salvo `--now`) y
dice qué hizo llama-swap con la recarga. Detalle completo, semántica de `groups` verificada contra el código de llama-swap, y
ritual de aplicación en [`docs/recipes/llama-swap-groups.md`](./docs/recipes/llama-swap-groups.md).

## Enlaces

- [Wiki](./docs/wiki/Home.md) · [Recipes](./docs/recipes)
- [CONTRIBUTING](./CONTRIBUTING.md) · [CODE OF CONDUCT](./CODE_OF_CONDUCT.md) · [CHANGELOG](./CHANGELOG.md)
- [Licencia MIT](./LICENSE)
