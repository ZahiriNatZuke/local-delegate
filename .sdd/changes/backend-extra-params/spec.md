# Especificación: parámetros por rol en las peticiones al backend

## Contexto

Las tools `local_*` mandan al backend (llama-swap / llama.cpp b10909) solo las claves que arma el
producto: `model`, `messages`, `max_tokens`, `temperature`, `stream` y, en `local_extract`,
`response_format`. Hoy no hay forma de ajustar el muestreo ni de encender el razonamiento sin tocar
código.

Este cambio añade parámetros **por rol** (`mechanical`, `long`, `code`, `vision`):
- salen de una **lista cerrada** y se validan;
- se guardan en un fichero que edita un subcomando, con override puntual por variable de entorno;
- se ven en `doctor`, `local_status`, el log de uso y el panel.

Mandan las decisiones del usuario del [brief](brief.md) (§«Decisiones del usuario», 1–11). La base
técnica, con `fichero:línea`, está en [research.md](research.md), sobre todo en su «Segunda ronda» y
en la «Recomendación actualizada». La revisión del gate está en [review.md](review.md). Las
variables globales del alcance inicial (`LOCAL_DELEGATE_REASONING_EFFORT` y
`LOCAL_DELEGATE_EXTRA_BODY`) se retiran del diseño.

La decisión 6 ya tiene respuesta, y es **negativa**. La prueba en vivo de research §2 mostró que
`reasoning_effort` por petición **no** vence a `--reasoning off` con las plantillas de Qwen3.6 y
Gemma 4, y que `chat_template_kwargs.enable_thinking: true` **sí** lo vence. Por eso la spec enciende
el razonamiento con `enable_thinking` y la verificación en vivo comprueba esa vía.

**Vocabulario.**
- **Clave de producto**: el nombre que escribe el usuario (fichero, variable o subcomando).
- **Cuerpo**: el JSON que se manda a `/v1/chat/completions`.
- **Operación**: una invocación de tool. Puede hacer varias **llamadas reales** al backend (trozos,
  pasos de map/reduce, reintentos, respaldo) y deja un solo evento en el log.

## Requisitos

### Fichero y módulo

- **REQ-001 — Fichero por rol.**
  - La configuración debe vivir en `LOG_DIR/backend-params.json`, con el esquema
    `{"version": 1, "roles": {"<role>": {"<key>": <value>, …}}}`. Los roles válidos son
    `mechanical`, `long`, `code` y `vision`.
  - La regla debe tener una sola copia, en `src/local_delegate/backend_params.py`: catálogo, `load`,
    `validate`, `effective(role)` y `to_body`.
  - La lectura nunca debe lanzar.
  - Equivalen a «sin parámetros»: un fichero ausente, uno vacío o uno con solo
    `{"version": 1, "roles": {}}`.
  - Se ignora entero, con aviso: un JSON ilegible, una `version` distinta de 1 o un fichero de más
    de 64 KB.
  - Un rol desconocido se quita, con aviso.

  *Aceptación*: tests unitarios de `load` con el fichero ausente, vacío, con JSON roto, con
  `version: 2`, con más de 64 KB y con el rol `foo`. Ninguno lanza, y cada uno devuelve el código de
  problema esperado.
- **REQ-002 — Escritura atómica bajo cerrojo.** Toda escritura del fichero debe usar `mkstemp` en
  el mismo directorio más `os.replace`, bajo `FileLock`, con el patrón de `test_windows.py:268-322`.
  Una escritura que falla a medias debe dejar intacto el fichero anterior.
  *Aceptación*:
  - un test que simula un fallo de `os.replace` y comprueba que el fichero original no cambia y que
    no quedan temporales;
  - otro test con dos `set` concurrentes, en hilos o en procesos, que comprueba que el fichero final
    es JSON válido y contiene las dos claves.

### Subcomando

- **REQ-003 — `local-delegate backend-params show|set|unset|reset`.**
  - `show [--json]` debe listar, por rol, las claves efectivas con su valor, su origen (`file` o
    `env`) y los avisos.
  - `set <role> <key> <value>` debe validar el rol, la clave, el tipo y el rango **antes** de
    escribir. Si algo no vale, termina con código ≠ 0, imprime el motivo sin el valor y no toca el
    fichero.
  - `set` puede **avisar** sin rechazar: es el caso de REQ-023.
  - `unset <role> <key>` quita una clave, y `reset [<role>]` vacía un rol o todos.
  - El parser se registra en `build_parser` como `_add_backend_params_parser`, junto a
    `_add_test_window_parser` (`cli.py:460-476`, `:1389`).
  - Los textos van en `resources/i18n/{es,en}/cli.json`, incluida la ayuda de `--help`.

  *Aceptación*: tests de CLI para cada verbo, que comprueben el código de salida, el contenido del
  fichero tras cada verbo y el JSON de `show --json`. Tras un `set` inválido, los bytes y el `mtime`
  del fichero no cambian.

### Lista cerrada, tipos y rangos

- **REQ-004 — Claves permitidas, con tipo y rango.** Solo se aceptan estas claves de producto.
  - Los rangos son los de la tabla verificada de b10909 (research §1), pero **más estrictos**: se
    rechaza lo que el servidor recortaría en silencio.
  - Ningún número puede ser `NaN` ni `±Infinity`.
  - Un booleano JSON no cuenta como número.

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
  | razonamiento | `reasoning_budget_tokens` | int | **1–8192** | raíz (más la suma al tope, REQ-011) |
  | razonamiento | `reasoning_effort` | enum | `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | raíz (REQ-011) |

  **Por qué el techo del presupuesto es 8192.** Es una **elección conservadora**, no un límite
  técnico:
  - coincide con el contexto del modelo más pequeño del catálogo (`gemma3-4b`, `--ctx-size 8192`);
  - en la prueba en vivo de research §2 bastaron entre 100 y 700 tokens.

  Un modelo con más contexto podría admitir algo más; por ejemplo, `qwen36-35b-a3b` tiene 16 384.
  Lo que no quepa en una llamada concreta lo cubren la comprobación de REQ-023 y el aviso de `set`.

  El mínimo es 1 porque un presupuesto de 0 cierra el razonamiento en el acto y no es un
  «presupuesto efectivo» (decisión 9).

  *Aceptación*:
  - un test parametrizado con, por cada clave, un valor válido, uno de tipo equivocado y uno fuera de
    rango por cada límite (incluidos `NaN`, `inf`, `true`, el presupuesto `0` y `8193`, y
    `reasoning_effort: none`);
  - otro test que comprueba que el catálogo del código tiene exactamente estas 21 claves.
- **REQ-005 — Claves reservadas.** Ninguna de estas claves puede configurarse, ni por fichero, ni
  por variable, ni por `set`:
  - contrato de la tool: `model`, `messages`, `stream`, `stream_options`, `max_tokens`,
    `max_completion_tokens`, `n_predict`, `response_format`, `json_schema`, `grammar`, `tools`,
    `tool_choice`, `functions`, `function_call`, `n`, `n_cmpl`, `stop`, `logprobs`, `n_probs`,
    `response_fields`;
  - servidor: `cache_prompt`, `id_slot`, `n_keep`, `samplers`, `seed`;
  - razonamiento en crudo: `chat_template_kwargs` y `reasoning_format`.

  Las claves aplazadas (ver «Fuera de alcance») tampoco se aceptan. El cuerpo nunca debe llevar una
  clave reservada que no haya puesto el producto.
  *Aceptación*: un test parametrizado con cada clave reservada por las tres vías. Con `set`, sale
  con código ≠ 0. Por fichero o por variable, la clave no llega al cuerpo capturado y aparece un
  aviso.
- **REQ-006 — Una clave no permitida se quita sola.** Si el fichero o la variable traen una clave
  desconocida o reservada, solo se quita esa clave y las demás del rol se aplican. El aviso da el
  rol, el nombre de la clave y el motivo, **nunca el valor**.
  *Aceptación*: dos tests.
  - Fichero: `{"code": {"top_k": 20, "foo": "SENTINEL-7Q"}}`.
  - Variable: `code.foo=SENTINEL-7Q;code.top_k=SENTINEL-8R;code.min_p=0.1`.

  En los dos, el cuerpo lleva solo las claves válidas y ninguno de los dos centinelas aparece en el
  aviso, en `show`, en `doctor`, en `local_status` ni en el log de uso.
- **REQ-007 — Valores fuera de rango o de tipo equivocado.** Por `set`, se rechazan (REQ-003). Por
  fichero o por variable, la clave se quita con un aviso sin valor y el resto del rol se aplica.
  *Aceptación*: un test con `{"mechanical": {"top_p": 1.5, "min_p": 0.1}}` y otro con
  `mechanical.top_k=x` en la variable. En los dos, el cuerpo lleva solo la clave válida y el aviso
  nombra la clave y el motivo, sin el valor.

### Resolución y aplicación

- **REQ-008 — Variable de override y precedencia clave a clave.**
  - **Precedencia**: para cada rol y cada clave, el valor efectivo sale de
    `LOCAL_DELEGATE_BACKEND_PARAMS` > fichero > valor propio de la tool. Hoy la tool solo tiene
    valor propio para `temperature`.
  - **Lectura**: la variable se lee con `_env` **al llamar**, con el patrón `(value, problem, raw)`
    de `output_language` (`config.py:448-462`). El lector vive en `config.py` y se añade al bucle
    `for _reader in (...)` que lo invoca al importar (`config.py:465-476`), para que entre en
    `ENVIRONMENT_VARIABLES` (`config.py:579`).
  - **Avisos**: de `raw` solo se usan el rol y la clave de cada trozo, **nunca** el texto que va
    detrás de `=`.
  - **Tope**: 2048 caracteres. Si la variable lo pasa, se ignora entera y se avisa.
  - **Gramática del formato plano `role.key=value;…`**:
    - se separa por `;` y se descartan los trozos vacíos (un `;` final o `;;` no avisa);
    - se quitan los espacios alrededor de cada trozo, de la clave y del valor;
    - se separa por el **primer** `=` y, en la parte izquierda, por el **primer** `.`;
    - un trozo sin `=`, con un segundo `=` o sin `.` está mal formado: se quita sin arrastrar a los
      demás y se avisa;
    - si una clave se repite para el mismo rol, gana la última y se avisa;
    - los valores se parsean con las mismas reglas que `set`: números (un valor que da `inf`, como
      `1e400`, se rechaza) y `on`/`off`/`true`/`false` para `enable_thinking`.

  *Aceptación*:
  - un test con un `top_k` distinto en el fichero y en la variable: gana la variable, y una clave
    que solo está en el fichero se mantiene;
  - un test parametrizado de la gramática con `a=b=c`, `code.top_k`, `top_k=1`, `;;`, un `;` final,
    una clave duplicada y `code.top_k=1e400`;
  - un test que comprueba que la variable está en `ENVIRONMENT_VARIABLES`;
  - `tests/test_environment_isolation.py:155` sigue en verde sin cambios.
- **REQ-009 — Lectura en cada operación, sin reiniciar.**
  - Los parámetros se resuelven al empezar **cada operación**, con una caché que se invalida por
    `(st_mtime_ns, st_size, st_ino)` del fichero y por el valor de la variable. Se usa
    `st_mtime_ns`, no `st_mtime`.
  - Un cambio en el fichero se aplica en la operación siguiente del daemon, sin reiniciarlo.

  *Aceptación*:
  - un test que, en un mismo proceso, hace una operación, reescribe el fichero con `set`, hace otra
    y comprueba que el segundo cuerpo lleva el valor nuevo;
  - un test con dos `set` seguidos que dejan el fichero con el mismo tamaño (`top_k 20` → `top_k 30`)
    y comprueba que la segunda operación ve el 30;
  - en vivo, un `set` con el daemon arrancado cambia la llamada siguiente sin `/mcp` ni reinicio.
- **REQ-010 — La temperatura del rol pisa la de la tool.** Sin `temperature` configurada, cada tool
  conserva la suya: `classify` y `extract` 0, `boilerplate` 0,1 y el resto 0,2 (research §4).
  Configurada en un rol, pisa la de **todas** las tools que corren con ese rol, `classify` y
  `extract` incluidas. Esto es la capa 2 de REQ-012.
  *Aceptación*: un test parametrizado por tool.
  - Sin configurar, el cuerpo lleva la temperatura de hoy.
  - Con `mechanical.temperature=0.5`, llevan 0,5 `local_classify`, `local_extract` (entrada corta) y
    `local_summarize` (entrada corta).
  - `local_boilerplate` (rol `code`) no cambia.
- **REQ-011 — Razonamiento: `enable_thinking` con presupuesto obligatorio.**
  - Encender el razonamiento exige `enable_thinking=true` **y** un `reasoning_budget_tokens`
    efectivo (1–8192) en el mismo rol.
  - `set <role> enable_thinking on` sin presupuesto efectivo se rechaza con código ≠ 0. También se
    rechaza el `unset`/`reset` del presupuesto mientras `enable_thinking` siga encendido en el
    fichero.
  - Si la combinación sin presupuesto llega por un fichero editado a mano o por la variable,
    `enable_thinking` se ignora en ese rol y se avisa.
  - Con el razonamiento encendido, cada llamada real lleva
    `chat_template_kwargs: {"enable_thinking": true}`, `reasoning_budget_tokens` y
    `max_tokens = tope_de_la_tool + reasoning_budget_tokens`. Las llamadas reales son cada trozo,
    paso de map/reduce, reducción, reintento por esquema y respaldo. Las excepciones son REQ-015 y
    REQ-023.
  - `enable_thinking=false` manda `chat_template_kwargs: {"enable_thinking": false}` y no toca
    `max_tokens`.
  - **`reasoning_effort`** va en la **raíz** del cuerpo, igual en el producto y en el benchmark
    (REQ-020). Es el sitio que b10909 trata de forma explícita (`server-common.cpp:1324-1332`) y lo
    pasa a la plantilla como variable. Mandarlo dentro de `chat_template_kwargs` llega a la misma
    variable (research §2, `common/chat.cpp:915-919`), así que no da nada a cambio de mezclarse con
    `enable_thinking`. Por sí solo no enciende el razonamiento.

  *Aceptación*:
  - tests de `set`: el rechazo, el orden válido (primero el presupuesto, luego `enable_thinking`) y el
    `unset` del presupuesto;
  - un test por fichero y otro por variable con `enable_thinking` sin presupuesto: el cuerpo no
    lleva `chat_template_kwargs` y hay aviso;
  - un test con `mechanical.enable_thinking=on` y `mechanical.reasoning_budget_tokens=512`: en
    `local_classify`, el cuerpo lleva `max_tokens` = 16 + 512, `reasoning_budget_tokens: 512` y
    `chat_template_kwargs: {"enable_thinking": true}`;
  - en una operación troceada, **cada** cuerpo capturado suma el presupuesto a su tope.
- **REQ-012 — Regla de fusión en tres capas y respaldo.**
  - El cuerpo de cada llamada real se arma por capas, de abajo arriba. Las capas 1 (base de la
    tool) y 3 (contrato) las arma `_run_chat` (`server.py:2337-2347`) como hoy. La capa 2 (rol),
    con la suma del presupuesto, la comprobación de contexto de REQ-023 y la detección del rechazo
    de REQ-015, se aplica en `_call_model` (`server.py:2019`) sobre una **copia** del cuerpo, justo
    antes de `_post_chat`, porque solo ahí se conocen el modelo destino real (afinidad y respaldo)
    y el `http_400`. El `payload` compartido entre intentos no se muta. Las capas:
    1. **Base, valores de la tool**: `temperature` y `max_tokens` de la tool.
    2. **Parámetros del rol**: se aplican encima y pueden pisar `temperature`. El presupuesto de
       razonamiento **se suma** al `max_tokens` de la tool (REQ-011) y nunca lo sustituye.
    3. **Claves de contrato**: `model`, `messages`, `stream`, `response_format` y las demás de
       REQ-005 que ponga el producto. Van encima de todo y **nunca** se pisan.
  - Los parámetros se resuelven **una vez por operación** con el rol de origen y se llevan aparte
    en `_CurrentModel`, que hoy hace `self.role = None` tras un salto (`server.py:2427`). Así llegan
    iguales a todos los intentos, al respaldo y a los trozos posteriores a un salto.

  *Aceptación*:
  - un test con un backend falso en el que falla el primer modelo. Una operación troceada con el
    rol `code` configurado lleva los mismos parámetros en el cuerpo del primer modelo, en el del
    respaldo y en los trozos siguientes;
  - un test con `code.temperature=0.7`: el cuerpo lleva 0,7 y no la temperatura de la tool;
  - un test que comprueba que `model`, `messages`, `stream` y `response_format` son siempre los del
    producto.
- **REQ-013 — `local_delegate` con modelo explícito no lleva parámetros.**
  - Si la llamada fija `model=…`, el cuerpo no lleva ningún parámetro de rol, aunque hoy se pase
    `role="mechanical"` (`server.py:4684,4694`; `:2387` ya anula el rol con `explicit`). El evento
    no lleva `backend_params`.
  - Sin modelo explícito, `local_delegate` usa los parámetros de `mechanical`.

  *Aceptación*: un test con `mechanical.top_k=20` configurado.
  - Con modelo explícito, el cuerpo es igual al de hoy, con la comparación de REQ-022.
  - Sin modelo explícito, el cuerpo lleva `top_k: 20`.
- **REQ-014 — El modelo frontera no puede fijar nada.** Ninguna tool MCP gana argumentos.
  *Aceptación*: dos asserts.
  - **(a) Instantánea**: los nombres y tipos de los parámetros de las 11 tools coinciden con una
    instantánea tomada de `main` (`f2dd267`). Si falla, el mensaje dice: «si añadiste un argumento a
    propósito, actualiza la instantánea».
  - **(b) Guarda permanente**, independiente de la instantánea: ningún parámetro de ninguna tool se
    llama como una clave de REQ-004, una reservada de REQ-005, `role`, `backend_params` o
    `extra_body`, ni empieza por `reasoning`.
- **REQ-015 — Rechazo de los parámetros por el backend (400), una vez por operación.**
  - Si una llamada real que lleva parámetros de rol recibe `http_400`, el producto reintenta esa
    llamada **una vez** sin los parámetros de rol. El reintento lleva la `temperature` y el
    `max_tokens` de la tool, sin presupuesto, y conserva `response_format` si lo había.
  - Ese reintento va **antes** del reintento sin esquema de `JSON_SCHEMA=auto`
    (`server.py:2032-2038`).
  - El rechazo se detecta **una sola vez por operación**. Se marca en `_CurrentModel`, junto a los
    parámetros de REQ-012. Las llamadas siguientes de la operación (trozos, map/reduce, reducción y
    respaldo) van directamente sin parámetros y con el `max_tokens` de la tool.
  - El evento conserva `backend_params` con los valores intentados y añade
    `backend_params_rejected: true`. Si así funciona, `json_schema` no queda en `"fallback"`.
  - **Solo se marca el rechazo si el reintento sin parámetros funciona.** En ese caso se pone
    `backend_params_rejected` y se desactivan los parámetros en el resto de la operación.
  - Si el reintento sin parámetros también da 400, la causa no eran los parámetros:
    - no se marca nada;
    - los parámetros siguen activos en la operación;
    - se sigue el flujo de hoy (reintento sin esquema de `JSON_SCHEMA=auto`, respaldo), con los
      parámetros.
  - La prueba sin parámetros se hace **una sola vez por operación**, salga como salga. Los 400
    posteriores de la misma operación siguen directamente el flujo de hoy.
  - Sin parámetros de rol, el flujo es exactamente el de hoy.

  *Aceptación*: tests con un backend falso que devuelve 400 solo cuando el cuerpo lleva `top_k`.
  - `local_extract` con esquema: el resultado es correcto, el log trae
    `backend_params_rejected: true` y `backend_params` con los valores intentados, y `json_schema` es
    el de un éxito con esquema.
  - **Recuento de POST**: una operación de 3 trozos con `top_k` configurado hace exactamente 4
    peticiones (3 + 1, no 6). Ninguna operación hace más de una petición de más por el rechazo.
  - El reintento sin parámetros lleva el `max_tokens` y la `temperature` de la tool.
  - Si el backend falso da 400 con parámetros y sin ellos, el evento **no** lleva
    `backend_params_rejected`, el reintento sin esquema lleva los parámetros y el total de POST es
    el de hoy más uno.
  - Control sin parámetros: el 400 sigue llevando a `"fallback"`, como hoy.
  - Un caso en una tool sin esquema.
- **REQ-023 — Razonamiento que no cabe en el contexto.**
  - Antes de cada llamada real con el razonamiento encendido, el producto estima si cabe:
    `tokens_estimados + max_tokens_de_la_tool + reasoning_budget_tokens ≤ n_ctx`.
  - **Estimación de tokens**:
    `tokens_estimados = ceil((len(system) + len(user)) × REASONING_CONTEXT_MARGIN / CHARS_PER_TOKEN)`.
    - Cuenta el prompt de sistema **más** la entrada (el mensaje `user` completo), no solo la
      entrada.
    - `CHARS_PER_TOKEN` es la constante que ya existe (`config.py:513`, vale 4).
    - `REASONING_CONTEXT_MARGIN` es una constante nueva y fija, de valor **2**, es decir, se cuenta a
      2 caracteres por token. Por qué 2: el 4 es un promedio de texto en inglés, y en código y en
      español la densidad llega al doble (memoria «presupuesto en chars, límite en tokens»). Contar a
      2 cubre el peor caso medido.
    - Si la estimación se queda corta, el backend da un 400 y REQ-015 quita también el muestreo. Si
      se pasa, solo se pierde el razonamiento en esa llamada. Por eso el margen va del lado
      conservador.
  - **Contexto de cada modelo**: una función nueva, `model_context_size(model)`, da el `ctx_size`
    del modelo destino.
    - Lo lee de la config de llama-swap con los lectores que ya existen: `load_config`
      (`llamaswap_config.py:487`) y `_parse_cmd_flags` (`:240-247`), que reconoce `--ctx-size` y
      `-c`.
    - Tiene caché por `(st_mtime_ns, st_size, st_ino)`, como REQ-009.
    - Si no puede leerlo, usa un **estimado de 8192**. Pasa cuando no está el extra `[llamaswap]`
      (YAML, `_require_yaml`, `:51`), cuando falta la config o el modelo, o cuando el flag no es un
      número. En ese caso, `doctor` y `local_status` avisan de que el contexto de ese modelo es un
      estimado.
  - **El rol `vision` queda fuera de la comprobación**: su entrada es una imagen y no se puede
    estimar en caracteres. Razona o no según su configuración, sin comprobación de contexto.
  - Si no cabe, **esa llamada** va **sin razonamiento**:
    - lleva `chat_template_kwargs: {"enable_thinking": false}` y el `max_tokens` de la tool, sin
      `reasoning_budget_tokens`;
    - el resto de los parámetros del rol se aplica igual;
    - el evento lleva `reasoning_skipped: "context"`.
  - **No** se recorta la entrada ni se reduce el `MAX_CHARS` del rol.
  - `backend-params set` **avisa**, sin rechazar ni dejar de escribir, si
    `MAX_CHARS` del rol (`config.py:327-331`) en tokens + `CHUNK_MAX_TOKENS` (`config.py:488`) +
    presupuesto supera el `n_ctx` del modelo del rol. `show`, `doctor` y `local_status` repiten ese
    aviso.

  *Aceptación*: con `mechanical.enable_thinking=on`, `mechanical.reasoning_budget_tokens=512` y un
  modelo con `ctx_size` 8192 en una config de llama-swap de prueba.
  - **Entrada larga**: 20 000 caracteres. Cada cuerpo capturado va sin razonamiento, el evento
    trae `reasoning_skipped: "context"` y la entrada no se recorta.
  - **Control que puede pasar y fallar**: con la misma configuración y una entrada corta, la
    llamada **sí** lleva el razonamiento. Con presupuesto 512 y contexto 8192 cabe, así que el
    control no está decidido de antemano.
  - **Caso límite**: el test calcula con la fórmula una entrada (sistema + usuario) cuyo estimado
    da exactamente `n_ctx` y comprueba que lleva el razonamiento. Con un carácter más, que suba
    la estimación en un token, va sin él.
  - **Entrada densa**: una entrada de código (o de español) cuya longitud cabría a 4 caracteres por
    token pero no a 2 va sin razonamiento. Así se ve que el margen se aplica.
  - **Visión**: `local_describe_image` con razonamiento configurado en `vision` lo lleva siempre y
    nunca da `reasoning_skipped`.
  - **Aviso de `set`**: aparece, el código es 0 y el fichero queda escrito.
  - **Contexto desconocido**: sin YAML o sin el modelo en la config, se usa 8192 y `local_status`
    y `doctor` avisan de que es un estimado.
  - **Lectura del contexto**: un test de `model_context_size` con `--ctx-size N`, con `-c N`, sin el
    flag y con la config ausente.

### Visibilidad

- **REQ-016 — `local_status` y `doctor`.**
  - `local_status` muestra, debajo de los roles (`server.py:5526-5534`), una línea por rol con
    parámetros: claves de producto, valores, origen (`file`/`env`) y avisos, incluidos los de
    REQ-023.
  - `doctor` lo muestra en su cabecera con una función `backend_params_lines()`, con el mismo patrón
    que `language_lines()` (`doctor.py:48-66`), a partir del fichero. Si la variable está en **su**
    shell, lo dice, y advierte que puede no ser la del daemon.
  - **No** se añade ningún check: el total sigue en 25 (`tests/test_checks.py:93`).
  - Sin parámetros, ninguno de los dos añade líneas.

  *Aceptación*: tests de `local_status` y `doctor` con fichero, con variable y sin nada. Sin nada,
  la salida es idéntica a la de hoy. `tests/test_checks.py:93` y `tests/test_wiki.py:219,241` siguen
  sin cambios y en verde.
- **REQ-017 — Textos en el catálogo i18n es/en.**
  - Todo texto para personas que añade el cambio sale del catálogo `resources/i18n/{es,en}/*.json`,
    en el fichero de su superficie (`cli`, `doctor`, `mcp`, `panel`, `common`): avisos, errores y
    ayuda de `backend-params`, salida de `show`, líneas de `doctor` y `local_status`, marcas,
    títulos y `aria` del panel y del diálogo.
  - Ningún texto lleva valores de claves rechazadas.

  *Aceptación*:
  - `tests/test_i18n_parity.py:97,103,136` en verde con las claves nuevas;
  - la CI `test-lang-es` en verde;
  - un test que recorre los avisos en `es` y en `en` con los centinelas de REQ-006 y comprueba que
    no aparecen.
- **REQ-018 — Log de uso: `backend_params`, `reasoning_chars` y marcas de estado.** El evento de
  cada operación (`_log_event`, `server.py:726`) gana estos campos aditivos, con nombres en inglés,
  que se omiten cuando no aplican:
  - `backend_params`: `{"role": "<role>", "values": {<clave de producto>: <valor>}, "source":
    {<clave>: "env"}}`. Solo aparece si había alguna clave para la operación. `source` solo lista las
    claves que vienen de la variable.
  - `reasoning_chars`: suma, sobre **todas** las llamadas reales de la operación (fallidas
    incluidas), de `len(message.reasoning_content)` **más** los caracteres que `_strip_think`
    (`server.py:1468-1476`) quita del `content`. Solo aparece si es mayor que 0.
  - `backend_params_rejected: true`, según REQ-015.
  - `reasoning_skipped: "context"`, según REQ-023.

  Para eso, `ChatResult` y `Attempt` ganan `reasoning_chars: int | None`, que se rellena en
  `_post_chat` (`server.py:1354-1363`) y en `_body_failure`. El texto del razonamiento nunca se
  guarda.
  *Aceptación*: tests de `_log_event` sobre el modelo de `tests/test_lossless_summary_output.py`.
  - Los campos se omiten si no aplican.
  - La suma sobre `attempts` incluye un intento fallido.
  - Un backend falso que devuelve `<think>…</think>respuesta` sin `reasoning_content` da
    `reasoning_chars > 0`.
  - Ningún fragmento del razonamiento del backend falso, ni de `reasoning_content` ni de `<think>`,
    aparece en `usage-*.jsonl`.
- **REQ-019 — Panel: dos marcas y un diálogo de detalle.**
  - **Marcas** en la lista de delegaciones (`drawActivity`, `web/metrics.py:3095-3131`):
    - `reasonchip` cuando `reasoning_chars > 0`;
    - `paramschip` cuando hay `backend_params`, con un estado **rechazado**, de estilo y `title`
      propios, cuando el evento lleva `backend_params_rejected: true`.
    - Las dos son iconos o etiquetas cortas del catálogo, sin frase, y su `title` sale del catálogo.
      Son lo único nuevo en la fila.
  - **Diálogo de detalle**: al activar una fila se abre un diálogo de detalle que **reutiliza el
    patrón de `infoDlg`** (`web/metrics.py:1776`, apertura en `:3223`, cierre al pulsar fuera en
    `:3233`), con sus estilos.
    - Muestra una tabla clave → valor: rol, parámetros con su origen, estado
      rechazado/`reasoning_skipped`, `reasoning_chars`, `steps` y respaldo.
    - Sin prosa y sin filas vacías.
  - **Teclado**: la fila se activa con el ratón y con el teclado (`tabindex="0"`, Enter), y su
    `aria-label` sale del catálogo.
  - **Formato viejo**: los eventos sin los campos nuevos se pintan como hoy.
  - No se tocan `/api/events` (`web/metrics.py:517-541`) ni el espejo `acct` (`:2873-2910`).

  *Aceptación*:
  - casos nuevos en `tests/test_dashboard_states.py` (alrededor de `:787-834`): una fila con
    razonamiento y su control sin él, una con parámetros, una con parámetros rechazados y un evento
    del formato viejo;
  - un test de que la fila abre el diálogo con Enter;
  - `tests/test_metrics.py:1570` actualizado y `tests/test_dashboard_js.py:583` sin cambios;
  - capturas en tema **claro** y **oscuro** de la lista (con una fila con marcas y una fila del
    formato viejo, sin marcas) y del diálogo, guardadas en
    `.sdd/changes/backend-extra-params/evidence/`. Cada captura cumple que la marca se ve y no se
    solapa, que el diálogo no tiene filas vacías y que el contraste es legible en los dos temas.

### Benchmark

- **REQ-020 — Arreglo del `--reasoning-effort` del benchmark.**
  - El esfuerzo **efectivo** es el que calcula `effective_reasoning` (`benchmark.py:1019-1028`): el
    del caso, el del modelo o el de la opción.
  - Si ese esfuerzo no es `off`, el benchmark manda:
    - `chat_template_kwargs: {"enable_thinking": true}`;
    - `reasoning_effort: <nivel>` en la **raíz**, alineado con el producto (REQ-011);
    - `reasoning_budget_tokens`, que se suma al `max_tokens` del caso.
  - Ese esfuerzo exige un presupuesto `--reasoning-budget N` (1–8192). Sin él, la corrida termina
    con error, venga el esfuerzo de donde venga.
  - `off` queda como hoy: `chat_template_kwargs: {"enable_thinking": false}`.
  - El benchmark no aplica `backend-params.json` ni la variable, pero registra en los metadatos de
    la corrida si había parámetros de rol activos (solo los nombres de las claves).

  *Aceptación*:
  - `tests/test_benchmark.py:336-343` actualizado con la forma nueva de `reasoning_kwargs` para
    `off` y para `high`;
  - un test del error sin presupuesto pedido por la opción, y otro con un caso que trae
    `reasoning_effort: "high"` y no hay presupuesto;
  - un test de los metadatos;
  - en vivo, contra `gemma4-26b-a4b`:
    - una corrida corta con `--reasoning-effort high --reasoning-budget 256` trae `reasoning_content`
      no vacío, y con `off` no lo trae;
    - se comparan `low` y `high` con el razonamiento encendido. Si no hay diferencia medible (las
      plantillas de Qwen3.6 y Gemma 4 no leen la variable, research §2), se documenta en la wiki
      (REQ-021).

### Documentación y compatibilidad

- **REQ-021 — Documentación en los tres sitios, solo en español (decisión 11).**
  - `docs/wiki/Configuration.md`, sección nueva con:
    1. el fichero y el subcomando;
    2. la tabla de claves de REQ-004 y la de reservadas;
    3. la precedencia y la regla de fusión de REQ-012;
    4. que `summarize`, `extract`, `lint_summary` y `translate` cambian de rol según el tamaño de la
       entrada;
    5. que `reasoning_effort` solo no enciende el razonamiento, y el resultado de la comparación
       `low`/`high` de REQ-020;
    6. que el presupuesto se suma al tope y no se aplica si no cabe en el contexto (REQ-023);
    7. que en Qwen el exceso de razonamiento sin etiquetas se cuela en la respuesta y no se puede
       contar en `reasoning_chars`;
    8. que la variable exige reiniciar el daemon y el fichero no, y que la configuración va en cada
       máquina que delega. En una máquina sin la config de llama-swap, como la Mac, el contexto es
       el estimado de 8192 y los roles con más contexto se saltarán el razonamiento antes de lo
       necesario;
    9. que un cambio de temperatura se mide con el benchmark de afinidad antes de darlo por bueno.
  - `docs/wiki/Savings-and-metrics.md:33`, con los campos del log de REQ-018.
  - La tabla de variables de `README.md` (~l. 196-221).
  - `CHANGELOG.md` `[Unreleased]`.

  *Aceptación*:
  - un test nuevo en `tests/test_wiki.py` que comprueba que `Configuration.md` nombra
    `backend-params` y `LOCAL_DELEGATE_BACKEND_PARAMS`;
  - la revisión del resultado comprueba el diff de los cuatro ficheros contra los nueve puntos.
- **REQ-022 — Compatibilidad: sin parámetros, el cuerpo es el de hoy.**
  - Sin fichero (o con un fichero sin claves) y sin variable, el cuerpo de **cada** camino debe ser
    igual al de `main` (`f2dd267`), **con el mismo orden de claves**.
  - Los caminos son: tool simple, `local_extract` con esquema y su reintento sin esquema, trozo de
    map/reduce y reducción, visión, respaldo y `local_delegate` con modelo explícito.
  - El evento del log tiene el mismo **conjunto de claves** que hoy.

  *Aceptación*:
  - un test que captura el cuerpo de cada camino con un backend falso y lo compara, como JSON
    parseado que conserva el orden (`json.loads(..., object_pairs_hook=list)`), con fixtures.
    - El idioma, los modelos y la cadena de respaldo se fijan con los ayudantes `_env*` de
      `tests/conftest.py`.
    - El camino de visión usa una imagen mínima.
  - Las fixtures las genera un script versionado (en `scripts/` o con una marca de `conftest`),
    ejecutado sobre `f2dd267` **antes** de tocar `server.py`, y cada fixture anota el commit de
    origen.
  - Para el log se compara el conjunto de claves del evento, no sus valores.
  - Se repite con `{"version": 1, "roles": {}}` y con un rol vacío.
  - Control positivo: un mutante que añade una clave al cuerpo hace fallar el test, y se comprueba
    **qué** assert dispara.

## Fuera de alcance

- Las variables globales `LOCAL_DELEGATE_REASONING_EFFORT` y `LOCAL_DELEGATE_EXTRA_BODY`, y un
  «extra body» libre en JSON.
- Parámetros por tool o por modelo. Para ajustar modelo a modelo existe `filters.setParams` de
  llama-swap, que no se toca.
- Las claves aplazadas: `dry_sequence_breakers`, `top_n_sigma`, `dynatemp_range`,
  `dynatemp_exponent`, `min_keep`, `adaptive_target`, `adaptive_decay`, `reasoning_budget_message` y
  `reasoning_control`.
- `reasoning_chars` por paso dentro de `steps[]`.
- Recortar la entrada o reducir `MAX_CHARS` para que quepa el razonamiento (REQ-023 lo apaga en la
  llamada que no cabe).
- Cambios en el catálogo de modelos, en `config.yaml` de llama-swap o en `--reasoning off`.
- Medir la calidad de una temperatura o de un razonamiento nuevos: queda para el usuario, con el
  benchmark de afinidad.
- Quitar o contar el razonamiento que Qwen deja en `content` sin etiquetas: solo se documenta.
- Traducir el README, el wiki o el CHANGELOG (decisión 11).
- Dependencias nuevas y cualquier otra cosa del fork `magic-zagan/local-delegate`.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
| --- | --- |
| El razonamiento se come `max_tokens` y la tool falla como `CONFIGURATION`, que no salta al respaldo (`failures.py:185-201`, `server.py:1138,2230`) | Presupuesto obligatorio (1–8192) y sumado al tope (REQ-011). |
| La entrada más el tope más el presupuesto desbordan el contexto: `mechanical` admite 20 000 caracteres con `gemma3-4b` a 8192 de contexto (`config.py:327-331`) | Comprobación llamada a llamada que apaga el razonamiento si no cabe, y aviso en `set` (REQ-023). |
| Un 400 por los parámetros se atribuye al esquema o se repite en cada trozo | Una sola detección por operación, reintento sin parámetros antes del de esquema, y recuento de POST en la aceptación (REQ-015). |
| Parece que los parámetros se aplicaron cuando el backend los rechazó | `backend_params_rejected` en el log y `paramschip` en estado rechazado (REQ-018, REQ-019). |
| En Qwen el razonamiento que pasa del presupuesto aparece en `content` sin etiquetas | Se documenta (REQ-021). `reasoning_chars` cuenta lo que sí lleva etiquetas (REQ-018). |
| `reasoning_effort` da la impresión de encender el razonamiento | Solo se configura como variable de plantilla, sin `none`; la wiki lo dice y la prueba en vivo compara `low` y `high` (REQ-020). |
| Una temperatura por rol cambia `classify` y `extract`, que hoy van a 0 | Es lo que pidió el usuario (decisión 3). La wiki pide medir con el benchmark de afinidad. |
| Fuga de datos en avisos y logs | Lista cerrada; los avisos no usan valores rechazados ni el `raw` tras `=`, y lo prueban los centinelas (REQ-006/007/008/017); no se guarda el texto del razonamiento (REQ-018). |
| La variable se aplica al daemon y `doctor` mira la shell | `local_status` muestra el origen y `doctor` advierte (REQ-016); la wiki explica que la variable exige reiniciar el daemon. |
| Romper el contrato actual de peticiones | Comparación ordenada en todos los caminos con fixtures de `f2dd267` (REQ-022) e instantánea más guarda de los argumentos de las tools (REQ-014). |
| Una caché que no ve un cambio del mismo tamaño en el mismo segundo | Clave `(st_mtime_ns, st_size, st_ino)` y test específico (REQ-009). |
| Dos escritores a la vez dañan el fichero | Escritura atómica bajo cerrojo (REQ-002); la lectura tolerante nunca lanza (REQ-001). |
| La fidelidad del benchmark respecto a producción | El benchmark registra si había parámetros activos y manda el razonamiento igual que producción (REQ-020). |
| LF y CRLF mezclados en el repo | Respetar el fin de línea de cada fichero (`git ls-files --eol`) al editarlo. |

## Estrategia de verificación

1. **Tests unitarios y de integración**, con un backend falso que captura los cuerpos y cuenta los
   POST. Cubren de REQ-001 a REQ-020, REQ-022 y REQ-023. Se ejecutan con el cerrojo, desde la tool
   Bash: `bash ~/.claude/scripts/pesado.sh uv run pytest …`. La salida va a un fichero y se resume
   con `local_lint_summary(path=…)`. Al final se pasa la suite completa y la variante
   `test-lang-es`.
2. **Fixtures de compatibilidad** (REQ-022), generadas por un script versionado sobre `f2dd267`
   **antes** de tocar `server.py`, con el control positivo del mutante.
3. **Prueba en vivo marcada**:
   - Se abre la ventana con `local-delegate test-window start --label "backend-extra-params:
     verificación"`, se guarda el id y al acabar se cierra con `stop <id>`.
   - Se instala la versión de trabajo para el daemon
     (`uv tool install --force --reinstall --no-cache ".[llamaswap]"` + `schtasks /Run`).
   - Comprobaciones:
     - Con el daemon arrancado, `backend-params set code reasoning_budget_tokens 256` y
       `set code enable_thinking on` (REQ-009). Una llamada a `local_explain_code` da
       `reasoning_chars > 0` en el log (REQ-011, REQ-018).
     - Con `backend-params reset`, la misma llamada da un evento sin `backend_params` ni
       `reasoning_chars` (REQ-022 en vivo).
     - `local_status` muestra las líneas de REQ-016.
     - Corridas cortas del benchmark con `off`, `low` y `high` y `--reasoning-budget 256`
       (REQ-020).
4. **Capturas del panel** (REQ-019):
   - la lista con `reasonchip`, `paramschip` (normal y rechazado) y una fila del formato viejo, y el
     diálogo de detalle;
   - en tema claro y oscuro;
   - a partir de los eventos de la ventana de prueba (interruptor «Pruebas» encendido) y de un
     evento rechazado de prueba;
   - se guardan en `evidence/` y se revisan con los tres criterios de REQ-019.
5. **Benchmark de afinidad**: solo para comprobar que el arreglo de REQ-020 produce razonamiento
   cuando se le pide. Medir la calidad de una temperatura nueva no es criterio de aceptación.
6. **CI completo**, incluidos los checks que no son workflows: `gh pr checks <n>` (CodeQL, Socket,
   GitGuardian).

## Trazabilidad

| REQ | Ficheros probables (`fichero:línea` de research y de la revisión) |
| --- | --- |
| REQ-001 | `src/local_delegate/backend_params.py` (nuevo); `config.py:203-216` (`LOG_DIR`); patrón `test_windows.py:1-14,243` |
| REQ-002 | `backend_params.py`; patrón `test_windows.py:268-322` |
| REQ-003 | `cli.py:390,460-476,1341-1389`; `resources/i18n/{es,en}/cli.json` |
| REQ-004 | `backend_params.py` (catálogo); rangos de research §1 (`server-schema.cpp`, b10909); `ctx_size` en `llama-swap/config.yaml` |
| REQ-005 | `backend_params.py`; research §1 («lo que no existe o cambia de nombre»); `server.py:2028,2337-2347` |
| REQ-006 | `backend_params.py`; `i18n.py:124-165` (patrón de avisos) |
| REQ-007 | `backend_params.py`; `cli.py` (`cmd_backend_params`) |
| REQ-008 | `config.py:37-40,43-66,448-476,579`; `tests/conftest.py:24-40`; `tests/test_environment_isolation.py:155-189` |
| REQ-009 | `backend_params.py` (caché); patrón `web/metrics.py:557-560` |
| REQ-010 | `server.py:2337-2347,2508,2963,3182,4412-4415,4473,4503,4527-4530,4609-4612,4726,4910,4970,5081,5146-5151` |
| REQ-011 | `server.py:2337-2347,2395-2419,3009-3011,3264-3272,4412`; `failures.py:185-201`; research §1 (`server-common.cpp:1324-1332`) |
| REQ-012 | `server.py:2337-2347,2044-2058,2148-2210,2365-2370,2387,2395-2427`; `_OperationTurn` `:1757-1772` |
| REQ-013 | `server.py:4684,4694,2387` |
| REQ-014 | definiciones de tools en `server.py` (`:4326`, `:4412`, `:4473`, `:4609`, `:4684`, `:4726`, `:4910`, `:4970`, `:5081`, `:5143`); test nuevo |
| REQ-015 | `server.py:2028-2040,1330-1400,2395-2427`; `failures.py:159-162` |
| REQ-016 | `server.py:5526-5534,5638-5664`; `doctor.py:48-66` (patrón `language_lines()`); `tests/test_checks.py:93` |
| REQ-017 | `resources/i18n/{es,en}/{cli,doctor,mcp,panel,common}.json`; `tests/test_i18n_parity.py:97,103,136` |
| REQ-018 | `server.py:726-760,821-863,878-896,1120-1135,1354-1363,1468-1476`; `_body_failure`; `tests/test_lossless_summary_output.py` |
| REQ-019 | `web/metrics.py:1758,1776,3095-3131,3210-3215,3223,3233`; `tests/test_dashboard_states.py:787-834`; `tests/test_metrics.py:1570`; `tests/test_dashboard_js.py:583` |
| REQ-020 | `benchmark.py:993,1004-1028,1046,1065-1079,1288-1289,1417-1422`; `tests/test_benchmark.py:336-343`; `benchmarks/*/cases.json` |
| REQ-021 | `docs/wiki/Configuration.md` (cerca de l. 221-225); `docs/wiki/Savings-and-metrics.md:33`; `README.md:196-221`; `CHANGELOG.md:7`; `tests/test_wiki.py` |
| REQ-022 | `server.py:1330-1339,2028,2032-2038,2337-2347,2395-2419,2148-2210,5143`; `tests/conftest.py` (`_env*`); script de fixtures nuevo |
| REQ-023 | `config.py:327-331,488,513` (`CHARS_PER_TOKEN`); `llamaswap_config.py:51,240-247,365,487`; `server.py:2337-2347,5143` |

## Preguntas abiertas

Ninguna. La del idioma de la documentación la cerró la decisión 11 del brief: la documentación va
solo en español y el es/en se cumple en los textos del catálogo i18n (REQ-017, REQ-021).

Nota, sin bloqueo: la clave de producto del razonamiento se llama `enable_thinking`, como en la
decisión 9, en lugar del `thinking: on|off` que proponía research §3. El usuario sigue sin escribir
`chat_template_kwargs` en crudo.

## Cambios tras la revisión

Fuente: [review.md](review.md), 14 hallazgos.

| Hallazgo | Cómo quedó |
| --- | --- |
| 1. La temperatura del rol choca con «el producto gana» | REQ-012 define la fusión en tres capas: valores de la tool, encima los del rol (pueden pisar `temperature`, y el presupuesto se suma a `max_tokens`) y arriba las claves de contrato, que nunca se pisan. Su aceptación añade un caso de `temperature`. |
| 2. Presupuesto sin techo y desborde del contexto | El presupuesto va de 1 a 8192 (REQ-004, con justificación). El REQ-023, nuevo, comprueba llamada a llamada si cabe: si no, va sin razonamiento, con `reasoning_skipped: "context"`, sin recortar la entrada; `set` avisa sin rechazar. |
| 3. El reintento oculta el desborde y duplica llamadas | REQ-015 detecta el rechazo una sola vez por operación. Las llamadas siguientes van sin parámetros y con el `max_tokens` y la temperatura de la tool; `backend_params_rejected: true` y los valores intentados quedan en el evento, el panel pinta el estado rechazado y un test cuenta los POST (3 trozos → 4). |
| 4. Un aviso podría llevar el `raw` de la variable | REQ-008 solo usa el rol y la clave de `raw`, y el centinela de REQ-006 se aplica también a la variable. |
| 5. Gramática del formato plano | REQ-008 fija la gramática (`;`, espacios, primer `=`, primer `.`, duplicadas, `inf`) y la prueba con un test parametrizado. |
| 6. `ENVIRONMENT_VARIABLES` no se rellena solo | REQ-008: el lector vive en `config.py` y entra en el bucle `for _reader in (...)` (`config.py:465-476`). |
| 7. La caché debe incluir la identidad del fichero | REQ-009 invalida por `(st_mtime_ns, st_size, st_ino)`, con un test de dos `set` del mismo tamaño. |
| 8. La comparación byte a byte es frágil | REQ-022 compara el JSON parseado conservando el orden, con el entorno fijado por `_env*`, fixtures de un script versionado sobre `f2dd267`, conjunto de claves del evento, imagen mínima y control positivo. |
| 9. Instantánea frente a un `main` que se mueve | REQ-014 tiene dos asserts: una instantánea con un mensaje para actualizarla y una guarda permanente sobre los nombres prohibidos. |
| 10. La marca «razonó» no ve los `<think>` | REQ-018 suma también lo que quita `_strip_think`, con un test `<think>…</think>` sin `reasoning_content`; la wiki dice que el exceso sin etiquetas de Qwen no se puede contar. |
| 11. Diálogo y accesibilidad de la fila | REQ-019 reutiliza el patrón de `infoDlg`: fila activable con teclado (`tabindex`, Enter) y `aria` del catálogo, marcas cortas sin frase, y capturas en claro y oscuro con una fila del formato viejo y criterios por captura. |
| 12. El esfuerzo del caso o del modelo no exige presupuesto | REQ-020 exige el presupuesto para el esfuerzo efectivo de `effective_reasoning`, con un test de un caso con `"high"` sin presupuesto. |
| 13. `reasoning_effort` en sitios distintos | Se manda en la raíz en el producto y en el benchmark (REQ-011, REQ-020), que es donde b10909 lo trata de forma explícita (`server-common.cpp:1324-1332`). La prueba en vivo compara `low` y `high`, y si no hay diferencia se documenta. |
| 14. La cita de `doctor` apunta a la función de idioma | REQ-016 pide `backend_params_lines()` con el patrón de `language_lines()` (`doctor.py:48-66`). |
| Además (revisión, §Alcance y §Verificabilidad) | La decisión 6 queda escrita como respondida en negativo (Contexto). REQ-021 gana un test en `test_wiki.py`. La pregunta del idioma se cierra con la decisión 11. |
| S1. Estimación de tokens sin fuente | REQ-023 usa `CHARS_PER_TOKEN` (`config.py:513`) con un margen fijo `REASONING_CONTEXT_MARGIN = 2` (se cuenta a 2 caracteres por token, el peor caso medido en código y español), cuenta sistema + entrada, y la aceptación incluye una entrada densa. |
| S2. Control de REQ-023 que no podía pasar | La aceptación usa un presupuesto de 512 con contexto 8192, así que el control puede pasar y fallar, y añade el caso límite (exactamente `n_ctx` frente a un token más). |
| S3. No existía una función de contexto por modelo | REQ-023 define `model_context_size(model)` sobre `load_config` y `_parse_cmd_flags`, con caché y estimado de 8192. `doctor` y `local_status` avisan cuando es un estimado, y el punto 8 de REQ-021 documenta el caso de la Mac. |
| S4. Visión sin decidir | El rol `vision` queda fuera de la comprobación de contexto porque su entrada es una imagen, que no se estima en caracteres, y razona según su config. Lo cubre un test de aceptación. |
| S5. Rechazo marcado aunque el reintento también falle | REQ-015 solo marca y desactiva los parámetros si el reintento sin ellos funciona. Si no, sigue el flujo de hoy con los parámetros, la prueba sin parámetros se hace una sola vez por operación, y lo cubre un test. |
| S6. Justificación del 8192 exagerada | REQ-004 presenta el 8192 como una elección conservadora (el contexto del modelo menor), no como un límite, y remite a REQ-023 y al aviso de `set`. |
| Enmienda por la revisión del plan, P1: sin cambio de comportamiento | REQ-012 precisa dónde se arma cada capa: la 1 y la 3 en `_run_chat`; la 2 (rol, presupuesto, REQ-023 y detección de REQ-015) en `_call_model`, sobre una copia del cuerpo, porque solo ahí se conocen el modelo real y el `http_400`. Ninguna aceptación cambia. |
