# Research: Parámetros extra por petición al backend (reasoning effort y extra body)

Fecha: 2026-10-20. Base: `main` en `f2dd267` (0.36.1). Solo lectura; nada implementado.

## Resumen

- **Hay un solo embudo para todas las tools**: `server._call_model` arma `request_body = {"model": model, **payload}` (`src/local_delegate/server.py:2028`) y lo manda por `_post_chat` (`server.py:1339`). Por ahí pasan las 11 tools, los trozos de map/reduce, la visión, el respaldo entre modelos y el reintento sin esquema. Inyectar ahí cubre todo sin tocar cada tool.
- **El producto pone 6 claves**: `model`, `messages`, `max_tokens`, `temperature`, `stream` y, a veces, `response_format` (`server.py:2337-2347`). El benchmark, que es otro camino aparte, añade `seed` y `chat_template_kwargs` (`benchmark.py:1065-1079`). Ningún otro camino (doctor, sondas, panel) manda `chat/completions`: solo hacen `GET /v1/models`.
- **Trampa del reintento**: un 400 provocado por el extra en `local_extract` dispara el reintento «sin esquema» (`server.py:2032-2038`). El fallo se atribuiría al esquema y se repetiría con el mismo extra.
- **El backend real tiene el razonamiento apagado**: los cinco modelos arrancan con `--jinja --reasoning off` (`D:\Projects\llms\llama-swap\config.yaml:21,28,35,43,52`). llama.cpp acepta `reasoning_effort` a secas («`none`» lo apaga; cualquier otro valor llega a la plantilla) y `chat_template_kwargs`. El binario b10909 contiene esas cadenas. Nadie ha comprobado si un valor por petición vence a `--reasoning off`.
- **Ya existe un patrón de validación que encaja**: `config.output_language()` devuelve `(value, problem, raw)`, ignora el valor no válido y avisa en la cabecera de `doctor` y en `local_status` con textos del catálogo (`config.py:448-463`, `i18n.py:124-165`, `doctor.py:61-64`, `server.py:5649-5652`). Si la variable se lee con `_read`/`_env`, la suite la aísla sola (`config.py:37-40,579`; `tests/test_environment_isolation.py:155`).
- **El fork falla en lo que importa**: no valida el esfuerzo, ignora en silencio un JSON roto (el comentario promete un aviso que no existe) y solo protege las claves presentes en ese momento, así que puede meter `response_format`, `tools`, `n_predict`, `grammar`… No trae ni un test y lee `os.environ` directo, saltándose la puerta que la suite vigila.
- **La documentación está solo en español**: wiki `docs/wiki/Configuration.md` (tabla de variables), tabla de `README.md` (~l. 196-221) y `CHANGELOG.md` `[Unreleased]`. Ningún test obliga a documentar una variable nueva. Si se añade un *check* a `doctor`, hay que tocar el recuento de 25 (`tests/test_checks.py:93`) y la tabla del wiki (`tests/test_wiki.py:219,241`).
- **Alternativa ya disponible sin código**: llama-swap tiene `filters.setParams`/`stripParams` por modelo, que fijan parámetros del cuerpo modelo a modelo. Esto afecta a si el extra debe ser global o por modelo.

## Caminos de petición

| Camino | fichero:línea | Claves que pone |
| --- | --- | --- |
| Construcción común de toda tool (`_run_chat`) | `server.py:2337-2347` | `messages` (system + user), `max_tokens`, `temperature`, `stream: false`, `response_format` (solo si se pide) |
| Embudo de envío (`_call_model`) | `server.py:2028` | añade `model` (va **primero**: un `**payload` con `model` lo pisaría) |
| Reintento sin esquema (`JSON_SCHEMA=auto`) | `server.py:2032-2038` | quita `response_format` y reenvía el mismo `request_body` si la respuesta fue `http_400` |
| POST real y reintento si el backend está caído | `server.py:1330-1339`, `1364-1400` | envía `request_body` tal cual; segundo intento tras arrancar el backend |
| Respaldo entre modelos (`_with_fallback`/`_attempt`) | `server.py:2044-2058`, `2148-2210` | mismo `payload` contra otro modelo: el extra viajaría también al respaldo |
| Varios trozos (`_CurrentModel.call`, map/reduce, troceado) | `server.py:2395-2419`, `3264-3272`, `3009-3011` | pasan por `_run_chat`; `max_tokens` propio por paso |
| `local_extract` con esquema | `server.py:4479-4481`, `4514`, `4536`, `3534` | `response_format` = `json_object` + `schema` |
| Visión (`local_describe_image`) | `server.py:5143` → `_run_chat` | `messages[1].content` es una lista con `image_url` (data URI en base64) |
| Benchmark (camino aparte, cliente propio) | `benchmark.py:1065-1079`, `1113`, `1270` | `model`, `messages`, `max_tokens`, `temperature`, `seed`, `stream`, `response_format` (del caso), `chat_template_kwargs` (del esfuerzo) |
| Sondas de estado / doctor / panel | `server.py:5315-5374`, `probes.py:265-310`, `llamaswap_api.py:370` | solo `GET /v1/models` y similares; no envían cuerpo de chat |
| CLI `cli.py:930` | `cli.py:930` | POST al **daemon** (`/api/llamaswap/watch`), no al backend: fuera de alcance |

Claves candidatas a reservadas, porque el producto las controla o porque llama.cpp las trata como equivalentes:
`model`, `messages`, `stream`, `stream_options`, `max_tokens`, `max_completion_tokens`, `n_predict` (alias de llama.cpp), `temperature`, `response_format`, `json_schema` y `grammar` (llama.cpp los acepta en la raíz y equivalen a un esquema), `tools`, `tool_choice`, `functions`, `function_call`, `n`.

## Configuración y validación

- **Puerta única**: `_read` (`config.py:37-40`) apunta el nombre en `_READ_VARIABLES`. De ahí sale `ENVIRONMENT_VARIABLES` (`config.py:579`), que `tests/conftest.py:35-39` borra del entorno en cada test. La guarda `test_config_only_reads_the_environment_through_the_registered_door` (`tests/test_environment_isolation.py:155-189`) falla si `config.py` toca `os.environ` fuera de `_read`.
- **Ayudantes**: `_env`, `_env_int`, `_env_flag`, `_env_float` (`config.py:43-66`). Los numéricos caen al valor por defecto **sin avisar**. `JSON_SCHEMA_MODE` hace lo mismo (`config.py:497-498`).
- **Patrón con aviso (el que conviene copiar)**: `OutputLanguage(value, problem, raw)` + `output_language()` (`config.py:448-463`). Se lee **al llamar**, no al importar, para que `monkeypatch.setenv` funcione sin recargar. Para que entre en el inventario hay un bucle que lo lee al importar (`config.py:466-476`). El código de problema se traduce en `i18n._OUTPUT_LANGUAGE_WARNINGS` (`i18n.py:124-128`) y `response_language_lines()` (`i18n.py:153-165`). Ese aviso sale en la cabecera de `doctor` (`doctor.py:61-64`, «no cambia el total de 25») y en `local_status` (`server.py:5649-5652`).
- **Catálogo**: `src/local_delegate/resources/i18n/{es,en}/*.json` (`common.json`, `doctor.json`, `mcp.json`…). Ejemplo: `common.output_language.warning.*` en `es/common.json:10-11`. Guardas: `tests/test_i18n_parity.py:97` (paridad es/en), `:103` (cada clave en su fichero de superficie) y `:136` (toda clave literal usada existe).
- **Alcance de `doctor`**: corre en la shell del usuario, no ve el entorno del daemon. `local_status` es el único que ve el del proceso servidor (`server.py:5660-5664`, comentario de REQ-003). Un aviso solo en `doctor` puede mentir si la variable está en el daemon y no en la shell, o al revés.
- **Checks de `doctor` con aviso**: el modelo más cercano es `_probe_fallback` (`checks.py:1785-1830`, check `config.fallback` en `checks.py:2118`). Añadir un check nuevo obliga a tocar `test_checks.py:93` (25 ids exactos), los recuentos en palabras (`test_checks.py:1208-1216`), `test_doctor.py:266` y la tabla del wiki (`test_wiki.py:219,241`).

## Backend: qué acepta

- **llama.cpp `llama-server`** (README de `tools/server` en `master`, consultado el 2026-10-20, https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md):
  - `reasoning_effort` (cuerpo de `/v1/chat/completions`): «If `none`, reasoning/thinking is disabled. Otherwise, the value is made available to the jinja template.»
  - `chat_template_kwargs`: parámetros extra para la plantilla, p. ej. `{"enable_thinking": false}`.
  - `reasoning_format` por petición. En CLI: `--reasoning on|off|auto`, `--reasoning-budget N`, `--reasoning-effort LEVEL`, `--chat-template-kwargs`.
  - El README **no dice** si un valor por petición vence a `--reasoning off` del arranque.
- **Binario instalado (b10909)**: `D:\Projects\llms\llamacpp-b10909\llama-server-impl.dll` contiene `reasoning_effort`, `chat_template_kwargs`, `enable_thinking`, `reasoning_format`, `thinking_budget_tokens` y `reasoning_budget_*` (búsqueda de cadenas, 2026-10-20). Que la clave esté en el binario no prueba que se aplique: hay que verificarlo en vivo.
- **Lo que ya sabe el benchmark** (`benchmark.py:1004-1016`): `off` → `chat_template_kwargs: {"enable_thinking": false}` (plantillas de Qwen3 y afines, verificado en b9925); el resto → `chat_template_kwargs: {"reasoning_effort": …}` (variable de la plantilla de gpt-oss). Hubo un fallo en julio por medir con `low` creyendo que era neutro.
- **llama-swap** (`docs/config.example.yaml` en `main`, consultado el 2026-10-20, https://github.com/mostlygeek/llama-swap/blob/main/docs/config.example.yaml): reescribe el cuerpo solo con `filters.stripParams`, `filters.setParams` (por modelo; `model` está protegido; una clave terminada en `?` solo se pone si la petición no la trae) y `setParamsByID`. Lo demás pasa tal cual. La config real no usa filtros.
- **Config real** (`D:\Projects\llms\llama-swap\config.yaml:17-56`): `gemma3-4b`, `qwen35-2b`, `gemma4-26b-a4b`, `qwen36-35b-a3b` y `gemma4-12b`, todos con `--jinja --reasoning off`. Los que razonan son Qwen3.5/3.6 (`enable_thinking`) y Gemma 4 (pensamiento opcional). Gemma 3 no razona. Con la config de hoy, `LOCAL_DELEGATE_REASONING_EFFORT` solo tendría efecto si la petición vence al `--reasoning off` (por verificar). Su uso real sería **apagar** el razonamiento en backends que lo traen encendido, como pedía el fork.
- **Claves desconocidas**: llama.cpp suele ignorarlas sin error. Una errata en el extra no daría 400, sino que no haría nada. Por eso la validación local es la única señal.

## El fork: qué hizo y qué falla

Fuente: PR cerrado https://github.com/ZahiriNatZuke/local-delegate/pull/1 (rama `magic-zagan:feat/reasoning-effort-and-extra-body`; el fork no se toca desde 2026-07-18). Toca `config.py` (+23) y `server.py` (+22), además de README, panel, `pyproject` y CI, que quedan fuera de alcance.

Qué hizo: `REASONING_EFFORT = os.environ.get(...).strip()` y `EXTRA_BODY = json.loads(...)` si es un dict, ambos leídos al importar. En `_chat`, `payload["reasoning_effort"] = …` y luego un bucle `for k, v in EXTRA_BODY.items(): if k not in payload: payload[k] = v`.

Fallos y huecos:
1. **Sin validar el esfuerzo**: manda cualquier texto. Lista siete valores (`none`…`max`) que no comprueba.
2. **JSON roto o que no es objeto: se ignora en silencio**. El comentario dice «se ignora con warning», pero no hay aviso, ni en `doctor` ni en `local_status`.
3. **Protección por presencia, no por lista**: solo respeta las claves que ya están en el `payload`. Sin `response_format` (todas las tools menos `extract`), el extra puede meter `response_format`, `json_schema`, `grammar`, `tools`, `n_predict`, `stop`… y cambiar el contrato de salida en silencio.
4. **Precedencia implícita**: `reasoning_effort` del extra queda tapado por la variable dedicada porque se escribe antes, sin avisar del conflicto.
5. **Se salta la puerta `_read`**: hoy rompería `test_config_only_reads_the_environment_through_the_registered_door` y la variable no se aislaría en la suite.
6. **Cero tests** y sin wiki ni CHANGELOG.
7. **Se aplica en `_chat`, no en el embudo**: con la arquitectura actual, que tiene respaldo, troceado y reintento sin esquema, ese sitio ya no existe. El código actual está en `_run_chat`/`_call_model`.
8. Mezclado con cosas ajenas: instrucción de idioma en chino en el system prompt, renombrado de `APP_NAME`, panel.

## Documentación y tests de guardia

- **Wiki**: `docs/wiki/Configuration.md`, que tiene secciones por tema. Lo natural es una sección nueva («Parámetros extra al backend») o añadirla junto a `## local_extract — JSON con schema` (l. 221-225), con la lista de reservadas y la advertencia de que no se loguea. Si sale un aviso en `doctor`, también `docs/wiki/Troubleshooting.md`.
- **README**: la tabla de variables (`README.md:196-221`).
- **CHANGELOG**: `## [Unreleased]` (`CHANGELOG.md:7`). Regla de release: tres sitios (CHANGELOG, README, wiki).
- **Idioma de la doc**: README, wiki y CHANGELOG están solo en español. El «es/en» del brief se cumple con los textos del catálogo i18n (avisos de `doctor`/`local_status`), no con la doc.
- **Guardas que se disparan solas**: aislamiento del entorno y puerta única (`tests/test_environment_isolation.py:21,47,155`), paridad e integridad del catálogo (`tests/test_i18n_parity.py:97,103,136`), y recuento de checks y tabla del wiki **solo si** se añade un check (`tests/test_checks.py:93`, `tests/test_wiki.py:219,241`).
- **Lo que no vigila ningún test**: que una variable nueva salga en el wiki o en el README. Eso queda para la revisión.
- **Tests existentes reutilizables como modelo**: `tests/test_benchmark.py:336-343` (forma de `chat_template_kwargs` según el esfuerzo) y `tests/test_core.py:23-29` (valor de entorno inválido → valor por defecto).

## Riesgos

1. **Logueo de datos sensibles**: hoy **no** se loguea el cuerpo de la petición. `_log_event` (`server.py:726-760`) recibe campos sueltos (modelo, tamaños, tokens, error) y no el `payload`. Los errores guardan `http_<status>` y como mucho 300 caracteres de la **respuesta** (`server.py:1348`). El registro del benchmark tampoco guarda el `payload` (`benchmark.py:1280-1310`). El riesgo nuevo está en los avisos: el texto de `doctor`/`local_status` no debe repetir el valor del extra (ni el crudo ni sus valores), solo los nombres de clave y el motivo.
2. **El reintento sin esquema confunde la causa**: un 400 provocado por el extra en `local_extract` con `JSON_SCHEMA=auto` se toma por «el backend no soporta esquema». Se reintenta sin `response_format` y con el mismo extra, y queda `json_schema: "fallback"` o `"error"` en el log (`server.py:2031-2040`). Es poco probable, porque llama.cpp ignora las claves desconocidas, pero un tipo inválido en una clave conocida (p. ej. `top_k: "x"`) sí da 400. Clase `REQUEST` (`failures.py:159-162`): no enfría el modelo, pero la tool falla.
3. **El respaldo recibe el mismo extra**: los parámetros de una plantilla (p. ej. `chat_template_kwargs.enable_thinking` para Qwen) viajan también al respaldo de Gemma. Suele ser inocuo, porque la plantilla ignora variables que no usa, pero un extra global es por naturaleza para todos los modelos y roles. Para afinar modelo a modelo existe `setParams` de llama-swap.
4. **Turno, afinidad y daemon**: el extra no interviene en el turno ni en la afinidad, que miran el modelo, no el cuerpo. Pero la variable vale para **el proceso que delega**: el daemon (`serve`, tarea programada) toma el entorno al arrancar, así que cambiarla exige reiniciarlo (y eso tira el MCP de la sesión: hay que pedir `/mcp`). `doctor` mira la shell y puede no coincidir con el daemon (ver §Configuración).
5. **La Mac**: delega con su propio proceso MCP contra el backend de la PC, porque su `/mcp` por tailnet da 421. Toma su propio entorno, no el de la PC. El `--reasoning off` de la PC le afecta igual. Hay que documentar que la variable se pone en cada máquina que delega.
6. **Cuerpo muy grande o anidado**: un extra enorme viaja en cada trozo de cada operación. Conviene un tope de tamaño (como los 40 caracteres de `OUTPUT_LANGUAGE`, aquí unos pocos KB).
7. **`--reasoning off` frente a la petición**: si llama.cpp no deja que la petición venza al arranque, la variable de esfuerzo no hará nada con la config de esta PC. Hay que verificarlo en vivo antes de documentar ejemplos.
8. **Fidelidad del benchmark**: el benchmark reproduce «la petición de producción» (`benchmark.py:1046`). Si producción manda un extra y el benchmark no, las mediciones dejan de representar producción sin que se note.

## Recomendación para la spec

- **Dónde inyectar**: en un único punto común a todos los caminos, `_call_model` (`server.py:2028`) o `_run_chat` (`server.py:2337`), de modo que lo recojan el respaldo, el troceado y el reintento sin esquema. Orden: `{**extra_validado, **payload_del_producto, "model": model}`, para que el producto siempre gane, además de la lista de reservadas.
- **Claves reservadas** (lista fija en código, no «lo que esté presente»): `model`, `messages`, `stream`, `stream_options`, `max_tokens`, `max_completion_tokens`, `n_predict`, `temperature`, `response_format`, `json_schema`, `grammar`, `tools`, `tool_choice`, `functions`, `function_call`, `n`. Si el extra trae alguna, **se descartan esas claves**, se usa el resto y se avisa con los nombres. Alternativa a decidir: ignorar el extra entero.
- **`LOCAL_DELEGATE_EXTRA_BODY`**: JSON que debe ser **objeto**, con tope de tamaño (p. ej. 4096 caracteres) y sin `NaN`/`Infinity`. Si el JSON es inválido, no es objeto o pasa del tope, se ignora entero y se avisa. Se lee por `_read`/`_env` con el patrón `(value, problem, raw)` de `output_language`.
- **`LOCAL_DELEGATE_REASONING_EFFORT`**: se valida contra una lista cerrada. La propuesta es `none`, `minimal`, `low`, `medium`, `high`, `xhigh` (los de OpenAI, que llama.cpp pasa a la plantilla). Un valor fuera de la lista se ignora y se avisa. Se manda como `reasoning_effort` en la raíz, que es lo que documenta llama.cpp; `none` lo apaga.
- **Precedencia**: la variable dedicada vence a `reasoning_effort` dentro del extra, con aviso de conflicto. `chat_template_kwargs` del extra pasa tal cual, sin fusión profunda.
- **Benchmark**: **no** debe leer estas variables. Ya tiene su `--reasoning-effort` (`benchmark.py:1417-1422`, valores en `:993`) y sus medidas tienen que ser reproducibles e identificables (`benchmark.py:1288-1289`). A lo sumo, que registre en los metadatos de la corrida si el entorno de producción tenía extra, para detectar la deriva del riesgo 8. Es reutilizable el conocimiento de `reasoning_kwargs` (`off` ≠ `low`), no el código.
- **Doctor y estado**: sin check nuevo, para no tocar el recuento de 25. Mejor una línea de aviso en la cabecera de `doctor` y en `local_status`, como `OUTPUT_LANGUAGE`, y que `local_status` muestre qué claves extra van activas (solo nombres, nunca valores) y el esfuerzo efectivo.
- **Mensajes i18n (es/en)**, propuesta en `common.json` y `mcp.json`/`doctor.json`: `…extra_body.warning.invalid_json`, `…not_object`, `…too_long`, `…reserved_keys` (con `{keys}`), `…reasoning_effort.warning.invalid` (con `{allowed}`), `…reasoning_effort.warning.overrides_extra`, y la línea de estado (`mcp.status.backend_params.line` con `{effort}` y `{keys}`). Ninguno lleva valores del extra.
- **Tests mínimos**: parseo y validación (JSON roto, lista, demasiado grande, reservadas, esfuerzo inválido); que el cuerpo enviado contiene el extra en **todos** los caminos (una tool sencilla, `extract` con esquema y su reintento, un trozo de map/reduce, visión y respaldo); que el producto gana; que el aviso no contiene valores; y que el benchmark no cambia.

## Preguntas abiertas para el usuario

1. Si el extra trae una clave reservada, ¿se descarta **solo esa clave** y se avisa, o se ignora **el extra entero**?
2. ¿Basta un extra **global** (todos los roles y modelos, respaldo incluido), dejando el ajuste por modelo a `setParams` de llama-swap? ¿O hace falta ya alguna variante por rol (`LOCAL_DELEGATE_EXTRA_BODY_<ROL>`), que el brief deja fuera salvo que sea imprescindible?
3. ¿`temperature` es reservada (hoy la fija cada tool y hay mediciones que dependen de ella) o se permite pisarla desde el extra?
4. Con la config de esta PC (`--reasoning off` en todo), ¿quieres que la verificación en vivo pruebe si la petición vence al arranque, para documentar ejemplos ciertos? ¿O la variable se documenta solo para backends con razonamiento encendido?

## Segunda ronda (2026-10-20)

Base: `main` en `f2dd267`. Solo lectura del repo y de `D:\Projects\llms\`; nada implementado. Fuente de llama.cpp: tag `b10909` descargado con `gh api` (`tools/server/{README.md,server-common.cpp,server-schema.cpp,server-schema.h,server-context.cpp}`, `common/{chat.cpp,arg.cpp}`). Responde a las decisiones del usuario del brief (por rol, lista cerrada, fichero + comando, verificación en vivo) y al punto del panel (decisión 7).

### Resumen de la segunda ronda

- **`reasoning_effort` NO vence a `--reasoning off`** con nuestras plantillas (Qwen3.6 y Gemma 4): verificado en vivo y explicado por la fuente. Lo que sí lo vence es **`chat_template_kwargs: {"enable_thinking": true}`**. No hace falta tocar llama-swap.
- **El razonamiento se come `max_tokens`**: con 700 tokens, Qwen3.6 los gastó todos pensando y devolvió `content` vacío (`finish_reason: length`), que el producto ya clasifica como fallo de `CONFIGURATION` (`failures.py:191`). `local_classify` usa `max_tokens=16` (`server.py:4412`): encender el razonamiento en `mechanical` sin tocar el tope la rompe.
- **`reasoning_budget_tokens` por petición funciona**, pero en Qwen el modelo siguió «pensando» dentro de `content` al cortarse el presupuesto (1264 caracteres de razonamiento filtrados a la respuesta). En Gemma cortó limpio.
- **llama.cpp no da tokens de razonamiento en `usage`** (solo `prompt_tokens`, `completion_tokens` y `prompt_tokens_details.cached_tokens`). La única señal de que razonó es `message.reasoning_content` no vacío.
- **El benchmark mide «esfuerzo» sin efecto**: `reasoning_kwargs` manda `chat_template_kwargs: {"reasoning_effort": …}` para todo lo que no es `off` (`benchmark.py:1014-1016`). Es el mismo camino que `reasoning_effort` en la raíz y, con `--reasoning off`, no cambia nada en Qwen3.6 ni en Gemma 4.
- **No existe hoy un subcomando para `language.json`**: lo escriben `install`/`update` (`install.py:1075-1131`) y se cachea por proceso (`i18n.py:33-36`), así que cambiarlo exige reiniciar el daemon. El modelo bueno para «fichero + comando» es `test-windows.json` (`test_windows.py`, `cli.py:460-476`): se lee en cada uso, con escritura atómica bajo `FileLock`.
- **El respaldo pierde el rol**: tras un salto, `_CurrentModel` pone `self.role = None` (`server.py:2427`) y los trozos siguientes van sin rol. Los parámetros por rol hay que resolverlos **una vez por operación** y llevarlos aparte.
- **El log ya tiene un evento por operación** (no por trozo ni por salto) y `/api/events` sirve las filas tal cual (`web/metrics.py:517-541`): un campo nuevo llega al panel sin tocar el endpoint.

### 1. Catálogo verificado de parámetros por petición (llama-server b10909)

Cómo entra un parámetro por `/v1/chat/completions`: `oaicompat_chat_params_parse` trata a mano `reasoning_format`, `chat_template_kwargs`, `reasoning_effort` y el presupuesto (`server-common.cpp:1295-1378`). Después copia **todas** las demás claves del cuerpo a los parámetros de llama.cpp, con el comentario «This allows user to use llama.cpp-specific params like "mirostat", ... via OAI endpoint» (`server-common.cpp:1391-1398`). Allí las lee el esquema de campos de `server-schema.cpp`.

Límites: `set_limits` **recorta** al rango sin error y `set_hard_limits` **lanza** un error, que llega como 400 (`server-schema.h:50-64`, `server-schema.cpp:591-601`). Un tipo JSON erróneo (`"top_k": "x"`) también lanza al hacer `get<T>()`. Las claves desconocidas no dan error. Los valores por defecto son los del README del tag (l. 511-591), porque la config de llama-swap no fija ningún parámetro de muestreo (`config.yaml:17-56`). El producto manda siempre `temperature`, así que el 0,8 del servidor no aplica nunca.

| Nombre | Tipo | Rango o valores | Defecto | ¿Por petición? | Fuente (b10909) |
| --- | --- | --- | --- | --- | --- |
| `temperature` | float | ≥ 0 (recorta) | 0,8 | sí | `server-schema.cpp:116`; README l. 511 |
| `top_k` | int | ≥ 0 (recorta; 0 = apagado) | 40 | sí | `server-schema.cpp:89`; README l. 517 |
| `top_p` | float | 0–1 (recorta) | 0,95 | sí | `server-schema.cpp:93`; README l. 519 |
| `min_p` | float | 0–1 (recorta) | 0,05 | sí | `server-schema.cpp:97`; README l. 521 |
| `typical_p` | float | 0–1 (recorta; 1 = apagado) | 1,0 | sí | `server-schema.cpp:112`; README l. 539 |
| `repeat_penalty` | float | sin límite (1 = apagado) | 1,1 | sí | `server-schema.cpp:130`; README l. 541 |
| `repeat_last_n` | int | **0–2³¹ (error fuera)**; `-1` da 400 en esta versión | 64 | sí | `server-schema.cpp:126` |
| `presence_penalty` | float | sin límite (0 = apagado) | 0 | sí | `server-schema.cpp:136`; README l. 545 |
| `frequency_penalty` | float | sin límite (0 = apagado) | 0 | sí | `server-schema.cpp:133`; README l. 547 |
| `dry_multiplier` | float | sin límite (0 = apagado) | 0 | sí | `server-schema.cpp:139` |
| `dry_base` | float | < 1 se cambia por el defecto | 1,75 | sí | `server-schema.cpp:142` |
| `dry_allowed_length` | int | **0–2³¹ (error)** | 2 | sí | `server-schema.cpp:149` |
| `dry_penalty_last_n` | int | **0–2³¹ (error)**; `-1` da 400 | 64 | sí | `server-schema.cpp:153` |
| `dry_sequence_breakers` | array de strings | no vacío (error si vacío) | `["\n", ":", "\"", "*"]` | sí | `server-schema.cpp:242-249` |
| `xtc_probability` | float | 0–1 (recorta) | 0 | sí | `server-schema.cpp:104` |
| `xtc_threshold` | float | 0–1 (recorta; > 0,5 lo apaga) | 0,1 | sí | `server-schema.cpp:108`; README l. 561 |
| `mirostat` | int | 0, 1, 2 (recorta) | 0 | sí | `server-schema.cpp:157` |
| `mirostat_tau` | float | sin límite | 5,0 | sí | `server-schema.cpp:161` |
| `mirostat_eta` | float | sin límite | 0,1 | sí | `server-schema.cpp:164` |
| `top_n_sigma` (no estaba en el brief) | float | < 0 = apagado | -1 | sí | `server-schema.cpp:101`; README l. 130 |
| `dynatemp_range`, `dynatemp_exponent` (no estaban en el brief) | float | sin límite | 0 / 1 | sí | `server-schema.cpp:120,123` |
| `min_keep` (no estaba en el brief) | int | 0–2³¹ (error) | 0 | sí | `server-schema.cpp:183` |
| `adaptive_target`, `adaptive_decay` (no estaban en el brief) | float | ≤ 1 (recorta) / **0–0,99 (error)** | -1 / 0,9 | sí | `server-schema.cpp:167,171` |
| `reasoning_effort` | string | `none` apaga el razonamiento; cualquier otro texto **solo** se pasa a la plantilla como variable (el CLI cita `minimal`, `low`, `medium`, `high`, `xhigh`, `max`) | sin poner | sí, pero **no enciende el razonamiento** | `server-common.cpp:1324-1332`; `common/chat.cpp:934-937`; `arg.cpp:3694-3699` |
| `chat_template_kwargs` | objeto | claves libres; `enable_thinking` tiene que ser booleano (un string da 400) | el del arranque (`--reasoning off` ⇒ `enable_thinking: "false"`) | sí; **se fusiona clave a clave sobre el del arranque y gana** | `server-common.cpp:1307-1322`; `arg.cpp:3683-3685` |
| `enable_thinking` | — | **no existe en la raíz**: solo dentro de `chat_template_kwargs` | — | solo dentro de `chat_template_kwargs` | `server-common.cpp:1315` |
| `reasoning_format` | string | `none`, `auto`, `deepseek`, `deepseek-legacy` (otro valor lanza error) | el del arranque (`auto`) | sí | `server-common.cpp:1295-1297`; `common/chat.cpp:879-893` |
| `reasoning_budget_tokens` (alias `thinking_budget_tokens`) | int | **-1–2³¹ (error)**; -1 = sin tope, 0 = cierra ya | -1 (`--reasoning-budget`) | sí; **solo actúa si la plantilla tiene etiquetas de fin de razonamiento** | `server-common.cpp:1364-1378`; `server-schema.cpp:383` |
| `reasoning_budget_message` | string | texto que se inyecta al cortar | ninguno | sí | `server-common.cpp:1376`; `server-schema.cpp:415` |
| `reasoning_control` | bool | arma el corte en tiempo real por `/v1/chat/completions/control` | false | sí | `server-common.cpp:1377`; README l. 1324 |

Lo que **no existe o cambia de nombre** respecto al brief:
- `enable_thinking` en la raíz no existe: va dentro de `chat_template_kwargs`.
- `typ_p` es el nombre interno; el del cuerpo es `typical_p`. `n_probs` tiene el alias `logprobs`.
- `max_tokens` y `max_completion_tokens` son alias de `n_predict` (`server-schema.cpp:44`), y `n` lo es de `n_cmpl` (`:62`). `grammar` es alias de `json_schema` (`:252-253`). Todos van a la lista de reservadas, que se amplía con `n_predict`, `n_cmpl`, `max_completion_tokens` y `response_fields`.
- No hay `reasoning_tokens` en `usage` (ver §2).

### 2. Prueba en vivo: ¿la petición vence a `--reasoning off`?

Ventana de prueba `w-20261020T124016Z` («backend-extra-params: reasoning por peticion»), abierta a las 12:40:16Z y **cerrada** a las 12:44:01Z. El token se cargó como lo hace el lanzador del daemon (`start-local-delegate-secure.ps1:3,19-25`: secreto DPAPI `remote-api-key.clixml`) dentro de un proceso efímero, sin imprimirlo. Hubo 12 llamadas directas a `http://127.0.0.1:9292/v1/chat/completions` bajo el cerrojo `pesado.sh`, con el prompt «A train leaves at 14:35 and the trip takes 2 h 47 min…», `max_tokens: 700` y `temperature: 0.2`. Las respuestas crudas están en el scratchpad (`bep-live/resp`, `bep-live/resp2`); el guion es `bep-tools/probe.py`.

| Modelo | Variante | `reasoning_content` (chars) | `completion_tokens` | `prompt_tokens` | `finish` | Tiempo |
| --- | --- | --- | --- | --- | --- | --- |
| qwen36-35b-a3b | sin nada | 0 | 6 | 47 | stop | 21,7 s (incluye cargar el modelo) |
| qwen36-35b-a3b | `reasoning_effort: "high"` | 0 | 6 | 47 | stop | 0,3 s |
| qwen36-35b-a3b | `chat_template_kwargs.enable_thinking: true` | **1422** | **700** | 45 | **length** (`content` vacío) | 22,9 s |
| gemma4-26b-a4b | sin nada | 0 | 6 | 48 | stop | 14,5 s (incluye la carga) |
| gemma4-26b-a4b | `reasoning_effort: "high"` | 0 | 6 | 48 | stop | 0,3 s |
| gemma4-26b-a4b | `chat_template_kwargs.enable_thinking: true` | **535** | 261 | 51 | stop | 7,1 s |
| gemma4-26b-a4b | `enable_thinking: true` + `reasoning_budget_tokens: 100` | 225 | 109 | 51 | stop | 2,8 s |
| gemma4-26b-a4b | `reasoning_effort: "high"` + `enable_thinking: true` | 520 | 255 | 51 | stop | 6,2 s |
| gemma4-26b-a4b | `reasoning_effort: "none"` + `enable_thinking: true` | 602 | 283 | 51 | stop | 7,1 s |
| qwen36-35b-a3b | `enable_thinking: true` + `reasoning_budget_tokens: 100` | 281 | 627 | 45 | stop (1264 chars de razonamiento en `content`) | 66,6 s |
| qwen36-35b-a3b | `reasoning_effort: "high"` + `enable_thinking: true` | 781 | 395 | 45 | stop | 8,7 s |
| qwen36-35b-a3b | `reasoning_effort: "none"` + `enable_thinking: true` | 1608 | 700 | 45 | length | 15,3 s |

Lectura:
- **`reasoning_effort` solo no hace nada**. Da el mismo `prompt_tokens`, por lo que la plantilla renderizó el mismo texto, y sale de la caché en 0,3 s. La fuente lo explica: con un valor que no es `none`, solo añade `reasoning_effort` a las variables de la plantilla y no toca `enable_thinking` (`server-common.cpp:1324-1332`). El arranque ya fijó `enable_thinking=false` (`arg.cpp:3683-3685`, `server-context.cpp:1464`). Las plantillas de Qwen3.6 y Gemma 4 no usan esa variable. Sí la usa la de gpt-oss.
- **`chat_template_kwargs.enable_thinking: true` sí vence al arranque**. Las kwargs de la petición se fusionan clave a clave sobre las del arranque (`server-common.cpp:1307-1311`), y la de la petición pone `inputs.enable_thinking = true` (`:1316-1317`). Cambia la plantilla: el `prompt_tokens` pasa de 47 a 45 en Qwen y de 48 a 51 en Gemma.
- **`reasoning_effort: "none"` no apaga lo que encendió `chat_template_kwargs`**. Pone `inputs.enable_thinking=false`, pero la variable `enable_thinking` de las kwargs llega a la plantilla y pisa a la de `inputs`: en `common/chat.cpp:910` se pone primero y en `:915-919` el contexto extra (que son las kwargs, `:1273-1275`) la sobrescribe. Para el producto, dos claves que digan cosas distintas sobre el razonamiento son un conflicto que hay que resolver **antes** de mandar, con una sola clave de producto.
- **Sin tokens de razonamiento en `usage`**: las 12 respuestas traen solo `completion_tokens`, `prompt_tokens`, `total_tokens` y `prompt_tokens_details.cached_tokens`. Los `timings` traen `cache_n`, `predicted_ms`, `predicted_n`, `predicted_per_second`, `predicted_per_token_ms`, `prompt_ms`, `prompt_n`, `prompt_per_second` y `prompt_per_token_ms`. El mensaje trae `reasoning_content` **solo** cuando razonó (la clave falta si no).

Conclusión: **no hace falta tocar llama-swap**. Para encender el razonamiento por petición basta `chat_template_kwargs: {"enable_thinking": true}`; para apagarlo, `false` (o `reasoning_effort: "none"`, si nadie más toca las kwargs). Si algún día se quisiera **imponer** un valor desde el backend sin pasar por el producto, llama-swap tiene `filters.setParams` por modelo (p. ej. `chat_template_kwargs: {enable_thinking: false}`), pero pisaría lo que mande el producto. La variante con `?` final solo lo pone si la petición no lo trae (ver primera ronda). No se recomienda.

### 3. Patrón de fichero + comando

Cómo funciona hoy `language.json`:
- **Ruta**: `config.LOG_DIR / "language.json"`. `LOG_DIR` sale de `LOCAL_DELEGATE_LOG_DIR` o del `user_data_dir` del paquete (`config.py:203-216`). El nombre está en `hook_common.LANGUAGE_PREFERENCE_FILE` (`resources/hooks/hook_common.py:384`).
- **Formato**: `{"lang": "es", "source": "variable|system|fallback"}` (`install.py:1091-1096`).
- **Escritura**: solo `install`/`update`, con `plan_language` → `language_action`, y `write_text` directo sin `.bak` ni cerrojo (`install.py:1075-1131`; `update.py:237`). **No hay subcomando** para cambiarlo a mano: el único camino es `LOCAL_DELEGATE_LANG=xx local-delegate update`.
- **Lectura**: `hook_common.resolve_language` (`hook_common.py:495-531`), con este orden: variable `LOCAL_DELEGATE_LANG` → fichero → idioma del sistema → reserva. Avisa con códigos (`invalid_variable`, `unreadable_preference`, `invalid_preference`) que `i18n` traduce (`i18n.py:84-89,106-121`).
- **Recarga**: `i18n.current()` está en `functools.cache` (`i18n.py:33-36`): **el daemon lo lee una vez y hay que reiniciarlo**, lo que tira el MCP de la sesión. Los hooks lo leen en cada invocación.
- **Cómo se muestra**: en la cabecera de `doctor` (`doctor.py:48-66`, «no cambia el total de 25») y en `local_status` (`server.py:5638-5653`), con los mismos datos de `i18n.language_report()`.

El patrón que conviene copiar es **`test-windows.json`, no `language.json`**: es un fichero en `LOG_DIR` con un subcomando que lo edita y una lectura tolerante en cada uso.
- Módulo único con la regla (`test_windows.py:1-14`).
- `load(log_dir)`, que nunca lanza y cuenta lo que no entiende (`test_windows.py:243`).
- Escritura atómica con `mkstemp` + `os.replace` (`:268-278`) bajo `FileLock` (`:288-322`).
- Subcomando anidado (`cli.py:460-476`), registrado en `build_parser` (`cli.py:1389`).
- El panel y `local_status` lo leen sin reiniciar (`web/metrics.py:557-560`).

Propuesta:
- **Fichero**: `LOG_DIR/backend-params.json`, en el mismo directorio de datos, aislado ya en la suite por `isolate_runtime_logs` (`tests/conftest.py:50-59`). Esquema:
  ```json
  {
    "version": 1,
    "roles": {
      "code":       {"thinking": "on", "reasoning_budget_tokens": 512, "temperature": 0.3},
      "mechanical": {"top_k": 20, "min_p": 0.05},
      "long":       {},
      "vision":     {"thinking": "off"}
    }
  }
  ```
  Las claves son **del producto**, en una lista cerrada que se traduce al cuerpo al enviar. `thinking: on|off` → `chat_template_kwargs.enable_thinking` (la única que vence a `--reasoning off`, §2). `reasoning_effort` → raíz (solo para plantillas que lo leen, como gpt-oss). `reasoning_budget_tokens` → raíz. El usuario no escribe `chat_template_kwargs` a mano: así no hay conflicto `reasoning_effort: none` contra `enable_thinking: true` (§2) ni variables de plantilla arbitrarias.
- **Módulo**: `src/local_delegate/backend_params.py` como única copia de la regla (catálogo de claves con tipo y rango, `load`, `validate`, `effective(role)`, `to_body(params)`), y su uso desde `server.py`, `doctor.py`, `cli.py` y el benchmark (§1 de la primera ronda: que el benchmark lo **registre**, no que lo aplique).
- **Subcomando** `local-delegate backend-params`:
  - `show [--json]`: efectivo por rol, con origen (fichero/variable) y avisos.
  - `set <role> <key> <value>`: valida tipo y rango antes de escribir; un valor fuera de rango es un error con código ≠ 0 y no se escribe.
  - `unset <role> <key>`.
  - `reset [<role>]`.

  Encaja como `_add_backend_params_parser(sub)` junto a `_add_test_window_parser` (`cli.py:460-476`), registrado en `build_parser` (`cli.py:1341-1389`), con un `cmd_backend_params` como `cmd_test_window` (`cli.py:390`). Los textos irían en `resources/i18n/{es,en}/cli.json`.
- **Recarga**: leer en cada operación con caché por `mtime` (como el panel con `test-windows.json`): **sin reiniciar el daemon**. Es la diferencia clave con `language.json`.
- **Muestra**: una línea por rol con los **nombres y valores** (lista cerrada: números, booleanos y enumerados, no hay secretos que ocultar) en la cabecera de `doctor`, sin check nuevo para no tocar el recuento de 25 (`doctor.py:48-66`), y en `local_status` debajo de los roles (`server.py:5526-5534`). `doctor` lee el fichero, que es el mismo para la shell y el daemon; la variable de override (§5) solo la ve bien `local_status`.

### 4. Roles, respaldo y temperatura

**Rol → modelo.**
- `config.models_by_role()` (`config.py:334-340`) con `MODEL_MECHANICAL/LONG/CODE` (`config.py:269-274`) y `MODEL_VISION` aparte (`:277`), fuera de `ALLOWED_MODELS` (`:278`). Los defectos del código (mechanical=gemma3-4b, long=gemma4-26b-a4b, code=qwen36-35b-a3b) no coinciden con lo que enseña `local_status` en esta PC (mechanical→gemma4-26b-a4b, long→qwen36-35b-a3b, code→gemma4-26b-a4b): ahí manda el entorno del daemon.
- Las tools que enrutan por tamaño usan `_role_for_size` (`server.py:3136-3143`): `long` si la entrada pasa de `LONG_INPUT_CHARS`, si no `mechanical`.

**Tool → rol y temperatura.**

| Tool | Rol | Temperatura | Dónde |
| --- | --- | --- | --- |
| `local_summarize` | mechanical/long por tamaño | 0,2 (defecto) | `server.py:4326`; defectos en `_chat` `:2508`, `_chat_chunked` `:2963`, `_chat_map_reduce` `:3182` |
| `local_classify` | mechanical | **0,0** (`max_tokens=16`) | `server.py:4412-4415` |
| `local_extract` | mechanical/long por tamaño | **0,0** (`max_tokens=512`) | `server.py:4473`, `:4503`, `:4527-4530` |
| `local_lint_summary` | mechanical/long por tamaño | 0,2 | `server.py:4726`, `:4768`, `:4789` |
| `local_translate` | mechanical/long por tamaño | 0,2 | `server.py:4970`, `:4979` |
| `local_delegate` | mechanical (también con modelo explícito) | 0,2 | `server.py:4684`, `:4694` |
| `local_boilerplate` | code | **0,1** | `server.py:4609-4612` |
| `local_commit_msg` | code | 0,2 explícita | `server.py:4910`, `:4931-4934` |
| `local_explain_code` | code | 0,2 | `server.py:5081`, `:5097-5099` |
| `local_describe_image` | vision | 0,2 | `server.py:5146-5151` |

Consecuencia: `summarize`, `extract`, `lint_summary` y `translate` **cambian de rol según el tamaño de la entrada**, así que llevarán parámetros distintos según lo largo que sea el documento. Hay que documentarlo.

**Mismo embudo.** Sí: la visión entra por `_chat` → `_run_chat` (`server.py:5146` → `:2545-2558`), y los trozos y la reducción por `_CurrentModel.call` → `_run_chat` (`server.py:2395-2419`). El cuerpo se arma en un solo sitio (`server.py:2337-2347`) y se envía en `_call_model` (`:2028`).

**Qué sabe el respaldo en cada punto.**
- En `_with_fallback.call` se conocen el `role` de origen (parámetro, `server.py:2150`), el modelo pedido y el **modelo real** que va a llamar (`target`, elegido por `op.pick()` con afinidad, `:2197-2209`). El `payload` es **el mismo** objeto para todos los intentos (`:2208-2209`).
- `_OperationTurn` guarda `role_name` durante toda la operación (`server.py:1757-1772`).
- En cambio, `_CurrentModel` **olvida el rol** tras un salto (`self.role = None`, `:2427`) y con `explicit` (`:2387`).
- Al modelo que responde no se le puede asignar un rol sin ambigüedad: en esta PC `mechanical` y `code` resuelven al **mismo** modelo (gemma4-26b-a4b), la afinidad puede elegir un alternativo ya cargado (`:2238-2241`) y el paso `loaded` elige entre miembros (`:2095-2096`, `:2117-2130`).

**Recomendación: viajan los parámetros del rol de origen**, resueltos una vez por operación.
1. El rol expresa **la tarea** (qué tool y con qué contrato de salida: `classify` con 16 tokens, `extract` con esquema), no el modelo. El respaldo responde al mismo contrato.
2. «El rol cuyo modelo responde» no está bien definido (dos roles por modelo, afinidad, `loaded`) y obligaría a una búsqueda inversa con empates.
3. «Ninguno» haría que una misma operación troceada cambiara de muestreo a mitad, porque los trozos posteriores al salto van al respaldo (REQ-006, `server.py:2365-2370`).
4. Las claves de razonamiento son inocuas en modelos que no razonan: `chat_template_kwargs` sobra en plantillas sin `enable_thinking`, y `reasoning_budget_tokens` solo actúa con etiquetas de fin (`server-common.cpp:1372`).

Implementación sugerida: resolver `backend_params.effective(role)` en `_chat`/`_chat_chunked`/`_chat_map_reduce`, guardarlo en `_CurrentModel` (que hoy pierde el rol) y pasarlo a `_run_chat` para fusionarlo en el `payload` (`server.py:2337-2347`) **debajo** de las claves del producto. Con **modelo explícito** (`local_delegate(model=…)`, REQ-005) hoy se pasa `role="mechanical"` (`:4684,4694`): ver «Preguntas abiertas».

**Trampa del tope de salida.** El razonamiento cuenta dentro de `max_tokens` (§2: 700 de 700 en Qwen). Si un rol enciende `thinking`, el producto tiene que **sumar** el presupuesto al tope de la tool (`max_tokens = tope_de_la_tool + reasoning_budget_tokens`) y **exigir** un presupuesto, o una tool corta como `classify` (16 tokens) falla siempre como `CONFIGURATION` (`failures.py:185-201`). Esa clase no salta al respaldo (`server.py:1138`, `:2230`). Además, con Qwen el texto que se pasa del presupuesto aparece en `content` **sin etiquetas** (§2), y `_strip_think` (`server.py:1468-1476`) no lo quita.

### 5. Override por variable de entorno

- **Nombre y formato**: `LOCAL_DELEGATE_BACKEND_PARAMS`, con el mismo vocabulario que el fichero en formato plano `rol.clave=valor;…` (p. ej. `code.thinking=on;code.reasoning_budget_tokens=512;mechanical.temperature=0`). Se propone plano y no JSON porque en Windows las comillas de un JSON en una variable rompen el lanzador y el `env` de los clientes (memoria «el quoting es parte del sistema»). Con lista cerrada y claves planas no hace falta anidar.
- **Lectura**: una función `backend_params_override()` en `config.py` que lea con `_env` **al llamar** (como `output_language`, `config.py:455-464`) y que devuelva `(value, problem, raw)`. Se añade al bucle de lectura al importar (`config.py:466-476`), así entra en `ENVIRONMENT_VARIABLES` (`config.py:579`) y la suite la borra sola (`tests/conftest.py:24-40`). La guarda de la puerta única (`tests/test_environment_isolation.py:155-189`) la cubre sin cambios.
- **Precedencia**: clave a clave, variable > fichero > valor de la tool (la temperatura de la tabla de §4). La variable no puede «borrar» una clave del fichero (para eso, `backend-params unset`). Una clave inválida de la variable se quita sola con aviso y no arrastra a las demás (decisión 2). El aviso da el nombre y el motivo, nunca el valor crudo.
- **Visibilidad**: `local_status` muestra el origen de cada clave (fichero/variable), porque es el único que ve el entorno del daemon (`server.py:5660-5664`). `doctor` muestra el fichero y, si la variable está en **su** shell, lo dice, con la advertencia de que puede no ser la del daemon. La variable exige reiniciar el daemon; el fichero no.

### 6. Panel y log de uso (decisión 7)

**Cómo se escribe hoy el log.**
- Fichero `LOG_DIR/usage-YYYYMM.jsonl` (`server.py:417`). Hay **un evento por operación**, no por trozo ni por salto: `_log_event` (`server.py:726-…`) se llama desde `_chat` (`:2593-2623`) y desde las dos variantes troceadas (`:3059`, `:3474`).
- Los trozos dejan huella en `chunks` (llamadas reales al backend, omitido si es 1, `:821-825`) y en `steps` (`kind`, `chars_out` y `finish_reason` por paso de map/reduce, `:852-863`).
- El respaldo no genera evento propio: queda en `model` (el que respondió), `model_requested`, `fallback_reason` y `fallback_class` (`:878-885`). La afinidad usa `routing: "affinity"` (`web/metrics.py:2909-2910`).
- La lista `attempts` (llamadas reales, con `model` y `timings`, `server.py:1120-1135`) llega a `_log_event`, pero solo se usa para la espera y el ritmo (`:647-704`).
- **Hoy `ChatResult` no guarda nada del razonamiento**: `_post_chat` lee solo `content`, `finish_reason`, `usage` y `timings` (`server.py:1354-1363`). `reasoning_content` solo lo mira el clasificador de fallos (`failures.py:184-201`).

**Cómo detectar si razonó**: por la prueba en vivo (§2), **solo** por `message.reasoning_content` no vacío. `usage` no trae tokens de razonamiento en b10909, y `completion_tokens` incluye los del razonamiento sin separarlos.

**Campos nuevos propuestos** (JSON en inglés, aditivos, omitidos cuando no aplican, como el resto del log):
- `backend_params`: `{"role": "code", "values": {"thinking": "on", "reasoning_budget_tokens": 512, "temperature": 0.3}, "source": {"temperature": "env"}}`. Lleva las claves **de producto** aplicadas (lista cerrada, así que los valores son seguros de guardar) y solo aparece cuando hay alguna. `source` solo lista las que vinieron de la variable.
- `reasoning_chars`: la suma de `len(reasoning_content)` de **todas** las llamadas reales de la operación (como `chars_out_raw`, `server.py:845-851`). Se omite si es 0. «Razonó» = `reasoning_chars > 0`. Se cuentan también los intentos fallidos, porque una respuesta de `CONFIGURATION` por razonar de más es justo la que hay que ver.
- Opcional: `reasoning_chars` dentro de cada `steps[]`, para saber qué paso de map/reduce razonó.

Para eso, `ChatResult` y `Attempt` ganan `reasoning_chars: int | None`, que se rellena en `_post_chat` (`server.py:1354-1363`) y en `_body_failure`. Nunca se guarda el texto del razonamiento: el log no guarda contenido (`server.py:845-851`, `:894-896`).

**Cómo pinta hoy el panel.**
- El JS va **dentro** de `web/metrics.py` (HTML y JS en un string).
- `/api/events` (`web/metrics.py:517-541`) sirve las filas tal cual («las filas son datos del log y se sirven tal cual»): **no hace falta tocar el endpoint**.
- La lista es `drawActivity` (`web/metrics.py:3095-3131`), con las columnas `time, tool, model, input, compute, chars, latency, ok` y marcas `chunkchip` (llamadas), `fbchip` (salto) y `slowchip`, cada una con su `title`.
- **No existe diálogo de detalle por fila**: los dos `<dialog>` que hay son ayuda (`helpDlg`, `:1758`) e información por grupos (`infoDlg`, `:1776`, `INFO_GROUPS` `:3210-3215`).
- El espejo JS de `_accounting` (`acct`, `:2873-2910`) y su prueba de paridad en `test_metrics.py` **no se tocan** si los campos nuevos no cambian la contabilidad.

**Propuesta de panel** (dashboard: sin prosa; el detalle, en un diálogo):
- En la fila, una marca nueva `reasonchip` junto al modelo cuando `reasoning_chars > 0`, con `title` del catálogo (p. ej. `panel.activity.reasoning_title`) y otra `paramschip` cuando hay `backend_params`.
- Un diálogo **nuevo** de detalle de la llamada, que se abre al pulsar la fila (o un grupo `event` en `infoDlg`), con una tabla de clave → valor: rol, parámetros aplicados con su origen, `reasoning_chars`, `steps` y el respaldo. Es trabajo nuevo de UI, con capturas en claro y oscuro (memoria «el panel es un dashboard»).

**Tests de guardia que se tocarían.**
- `tests/test_dashboard_states.py:787-834` (`drawActivity` con node: un caso con razonamiento y su control sin él, como el de `fbchip`).
- `tests/test_metrics.py:1570` (cadenas del HTML).
- `tests/test_i18n_parity.py:97,103,136` (claves `panel.activity.*` nuevas en `es/panel.json` y `en/panel.json`).
- `tests/test_dashboard_js.py:583` (las URLs pedidas no cambian: sirve de control).
- Tests nuevos de `_log_event`: campo omitido si es 0, suma sobre `attempts` y nunca el texto, siguiendo el modelo de `tests/test_lossless_summary_output.py`, que cubre `chars_out_raw`.
- Documentación: `docs/wiki/Savings-and-metrics.md:33`, donde están los campos del log. Ningún test obliga a ponerlos.

### Recomendación actualizada para la spec

Sustituye a la de la primera ronda donde choquen. Las dos variables globales (`LOCAL_DELEGATE_REASONING_EFFORT` y `LOCAL_DELEGATE_EXTRA_BODY`) **se retiran del diseño**.

1. **Lista cerrada de claves de producto por rol** (`mechanical`, `long`, `code`, `vision`):
   - **Muestreo**: `temperature`, `top_k`, `top_p`, `min_p`, `typical_p`, `repeat_penalty`, `repeat_last_n` (≥ 0), `presence_penalty`, `frequency_penalty`, `dry_multiplier`, `dry_base`, `dry_allowed_length`, `dry_penalty_last_n` (≥ 0), `xtc_probability`, `xtc_threshold`, `mirostat` (0/1/2), `mirostat_tau` y `mirostat_eta`. Se validan con los rangos de la tabla de §1, **más estrictos** que llama.cpp: se rechaza lo que el servidor recortaría en silencio.
   - **Razonamiento**: `thinking` (`on`/`off` → `chat_template_kwargs.enable_thinking`), `reasoning_budget_tokens` (≥ 0; **obligatorio si `thinking=on`**) y `reasoning_effort` (enum `minimal|low|medium|high|xhigh|max`, documentado como «solo plantillas que lo leen; no enciende el razonamiento»).
   - Fuera de la primera versión: `dry_sequence_breakers`, `top_n_sigma`, `dynatemp_*`, `min_keep`, `adaptive_*`, `reasoning_budget_message` y `reasoning_control`.
   - **No configurables**: `reasoning_format` (el producto depende de que el razonamiento salga aparte, en `reasoning_content`) y `chat_template_kwargs` en crudo.
   - Reservadas, además de las del brief: `n_predict`, `max_completion_tokens`, `n_cmpl` y `response_fields`.
2. **Fichero `LOG_DIR/backend-params.json`** con el esquema de §3, módulo único `backend_params.py`, subcomando `backend-params show|set|unset|reset` siguiendo el patrón de `test-windows`. Se lee en cada operación con caché por `mtime`: sin reiniciar el daemon.
3. **Override `LOCAL_DELEGATE_BACKEND_PARAMS`** en formato plano `rol.clave=valor;…`, leído por `_env` al llamar. Precedencia clave a clave: variable > fichero > tool.
4. **Se aplican los del rol de origen**, resueltos una vez por operación y llevados por `_CurrentModel` (que hoy pierde el rol tras un salto). Se fusionan en `_run_chat` **debajo** de las claves del producto.
5. **Temperatura**: sin configurar, la de cada tool. Configurada en un rol, pisa la de todas las tools de ese rol (decisión 3). Se mide con el benchmark de afinidad antes de darla por buena.
6. **Con `thinking=on`**, el producto suma `reasoning_budget_tokens` al `max_tokens` de cada llamada. Se documenta que en Qwen el exceso se filtra a la respuesta.
7. **Log**: `backend_params` y `reasoning_chars` (suma sobre las llamadas reales; también por `steps`). Para eso, `ChatResult` y `Attempt` ganan `reasoning_chars`.
8. **Panel**: marcas `reasonchip`/`paramschip` en `drawActivity` y un diálogo nuevo de detalle por fila. Sin tocar `/api/events` ni `acct`.
9. **`doctor` y `local_status`**: líneas de cabecera, sin check nuevo (el recuento sigue en 25), con nombres y valores por rol y el origen.
10. **Benchmark**: no aplica el fichero; registra en los metadatos si había parámetros activos. Aparte, hay que **corregir o documentar** que su `--reasoning-effort` distinto de `off` no tiene efecto con `--reasoning off` en Qwen3.6/Gemma 4 (`benchmark.py:1014-1016`).

### Preguntas abiertas

1. **Modelo explícito** (`local_delegate(model=…)`): ¿se le aplican los parámetros del rol `mechanical` (lo que pasa hoy con `role`), los del rol cuyo modelo coincide (ambiguo si hay dos), o **ninguno** (coherente con REQ-005: lo explícito no se toca)? Propuesta: ninguno.
2. **`thinking=on` sin presupuesto**: ¿se rechaza la configuración (propuesta) o se pone un presupuesto por defecto (p. ej. 512) y se avisa?
3. **El fallo del benchmark** (`reasoning_effort` sin efecto): ¿se arregla dentro de este cambio (que `--reasoning-effort on|<nivel>` mande `enable_thinking: true`) o va al backlog como hallazgo aparte? Si alguna medición pasada se apoyó en él, impacta en el trabajo en curso.
