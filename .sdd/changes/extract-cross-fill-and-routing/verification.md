# Verification: local_extract: aviso de valor cruzado entre claves y subida al rol long en tablas (#586)

## Environment

- Revision: `ff8f1efc` (rama `feat/usage-log-project-t5`); nada de este cambio instalado ni escrito en `src/`.
- Relevant runtime and tool versions: daemon y segundo proceso con el paquete publicado
  `local-delegate-mcp` 0.50.0 (`uv tool`); backend local `127.0.0.1:9292`; `gemma3-4b` (rol
  `mechanical`) y `gemma4-26b-a4b` (rol `long`); Python 3.14 para los scripts de `gate/`.

## Puerta (T1)

Medida el 2026-11-10 entre las 12:24 y las 12:35 (hora de Uruguay), dentro de la ventana de prueba
`w-20261110T152416Z` (etiqueta `sdd-586-t1`, 33 filas, cerrada a las 12:34:01). Una llamada cada
vez y al menos 3 s entre llamadas (comprobado en las horas de las filas del log).

### Veredicto (tabla «Puertas» de la spec, aplicada literalmente)

| Puerta | Criterio | Medido | Resultado |
| --- | --- | --- | --- |
| Enrutado | REQ-001 (1): cruce en 1 caso como mucho de los 8 que cruzaron con `gemma3-4b` | 0 de 8 casos; 0 claves cruzadas de 39 | pasa |
| Enrutado | REQ-001 (2): 1 clave fallada como mucho de 44 en los 8 limpios | 0 de 44 | pasa |
| Enrutado | REQ-001 (3): ninguna respuesta con `error`/`raw` | 0 de 16 | pasa |
| Enrutado | REQ-003: mediana de inferencia ≤ 6,5 s | 2,944 s (mín. 1,918 s; máx. 6,085 s) | pasa |
| Enrutado | REQ-007: la fuente congelada de `extraer-toml-2k` no trae tabla y `tests/test_corpus.py` pasa sin tocar | `has_table` = `False`; 63 passed | pasa |
| Aviso | REQ-004 (1): 0 avisos sobre las respuestas anotadas a mano | **1 aviso** (`c01/price`) | **falla** |
| Aviso | REQ-004 (2): 0 avisos sobre las respuestas de `gemma3-4b` en las claves sin cruce | **1 aviso** (`c01/price`, valor correcto) | **falla** |

**Enrutado: pasa. Aviso: falla.** Combinación «Pasa / Falla» de la spec: el enrutado sigue y se
publica; el aviso no entra en esta versión y vuelve a diseño en un cambio SDD nuevo con su propia
puerta. Las enmiendas que eso pide (Non-goals, transición en `state.json`, `[-]` en T4 y en el
commit del aviso de T5) son de la sesión coordinadora; T1 no las hace.

El aviso en falso, dicho con el caso: en `c01` (hervidor, inglés, HTML) la clave `price` vale `39`
y su fila es «Retail cost (USD)», que no comparte ninguna palabra con `price`; el mismo `39` está en
la fila «Noise level (dB)», que casa con la clave pedida `noise_level`. La regla estricta lo marca
como `{"row": "Noise level (dB)", "other_key": "noise_level"}`. Es exactamente el cupo «número
repetido en dos filas con la fila propia de etiqueta sinónima» que la revisión había anticipado. El
umbral es 0 y no se ajusta: un solo caso basta para que falle.

### Versión del detector que se congela

- `gate/detector_frozen.py`: copia byte a byte de `detector.py`, `sha256`
  `0b940737e792a6787ef96c02f64227046225ca08446f621b77fab67a359a18d7`; variante estricta,
  `LONG_CELL_CHARS = 60`.
- Comprobación: sobre las cuatro corridas grabadas marca exactamente lo mismo que
  `outputs/evaluation.json` (idéntico en `g3-extract`, `g3-proxy`, `g4-proxy` y `g4-extract`).
- **La corrección de plurales no se aplicó ni se midió.** La spec dice dos veces (REQ-004 y
  «Traceability») que esa corrección «solo puede hacerse antes de congelar el conjunto nuevo», y
  `holdout/` ya estaba congelado (11:14) cuando empezó T1; el paso 2 del plan la coloca después del
  conjunto. Se siguió la spec. No cambia el veredicto: el único aviso en falso es de número
  repetido, no de plurales, y la corrección de plurales no lo toca.

### Conjunto nuevo (`holdout/`, REQ-004 y REQ-005)

- `sha256sum -c SHA256SUMS`: 25 de 25 `OK` (el `cases.json` y los 24 ficheros de `inputs/`),
  antes de usarlo. No se modificó.
- 24 casos, 115 pares (caso, clave) distintos, 113 con valor no nulo, en español y en inglés.
- Cupos contados por programa sobre las respuestas a mano (`gate/gate_offline.py`): número repetido
  con etiqueta sinónima 2 casos (c01, c02); subcadena de la fila de otra clave 2 (c03, c04); celda
  propia de más de 60 caracteres 2 (c05: 79, c06: 81); plurales `-ies` 2 (c07, c08); plurales `-es`
  2 (c09, c10); tablas con claves parecidas 4 (c11 a c14); JSON con prosa 2 (c15, c16); líneas
  `etiqueta: frase` 2 (c17, c18); CSV 2 (c19, c20) y un TSV (c21). Todos llegan al mínimo; en
  ningún cupo el valor anotado difiere del valor del cupo.

| Pasada | Claves sin cruce | Avisos (falsos) | Cruces reales | Cruces marcados |
| --- | --- | --- | --- | --- |
| 1. Sin modelo, respuestas anotadas a mano | 115 | 1 (`c01/price`) | — | — |
| 2. `gemma3-4b` por el producto | 115 | 1 (`c01/price`) | 0 entre claves pedidas | 0 |
| Control positivo: respuestas cruzadas a mano (`crossed`, no cuenta) | — | 1 (`c01/price`) | 49 | 27 |

Respuestas de `gemma3-4b` sobre el conjunto nuevo (`outputs/gate-g3-holdout.json`, puntuadas en
`outputs/gate-g3-holdout-score.json`): 110 de 115 exactas; 0 `error`/`raw`; 0 cruces entre claves
pedidas. Las 5 que no coinciden, con veredicto a mano tras leer la fuente: `c08/fleet_size` `22`
por «22 vans» y `c12/descuento` `10` por «10 %» (fila propia, sin unidad); `c22/seeds_optional`
`true` por «yes» (fila propia); `c19/basic_plus_support` `"email"` por «email and chat» (trozo de la
celda propia y, a la vez, la celda entera de la fila «Basic»: ambiguo); `c20/precio_rebajado_pantalon_m`
`"39,90"` donde la celda está vacía (el valor es la columna «precio» de la misma fila, que nadie
pidió).

**REQ-005 (CSV):** en `c20` el modelo rellenó una celda vacía con la celda vecina de su fila, una
celda que nadie pidió: cruza, aunque no con otra clave pedida. En `c19` no hay cruce claro (el caso
ambiguo de arriba). Pasa al issue de seguimiento de REQ-039; la regla no cambia en este cambio.

### Un solo campo (REQ-002)

`gemma3-4b` por el MCP del daemon, una clave por llamada (`outputs/gate-g3-single.json`),
puntuadas con `evaluate.classify` y la anotación de `cases/cases.json`:

| Caso / clave | Esperado | Respuesta | Veredicto |
| --- | --- | --- | --- |
| 01 y 02 / `licensed_user_limits` | `null` | `"1–5, 1–3 per region, 600, 6 000, 30 days, 365 days"` | cruce (fila «Custom domains») |
| 06 / `limite_usuarios_con_licencia` | `null` | `75` | cruce (fila «Límite de usuarios activos») |
| 12 / `ip_allowlist` | `null` | `null` | bien |
| 21 / `storage_per_user` | `null` | `"2 TB"` | cruce (fila «Storage per workspace») |
| 21 / `api_requests_per_day` | `null` | `"6 000"` | cruce (fila «API requests per minute») |
| 22 / `almacenamiento_por_usuario` | `null` | `"25 GB"` | cruce (fila «Almacenamiento por proyecto») |
| 23 / `puestos_adicionales` | `null` | `"5"` | cruce (fila «Puestos incluidos») |
| 26 / `enterprise_seats` | `null` | `250` | cruce (fila «factory seats») |

1 de 8 bien, 7 mal: el enrutado dispara también con un campo. **`_TABLE_LONG_MIN_FIELDS = 1`.**
Por el plan («Mutantes»), con el mínimo en 1 el mutante del mínimo y su test se retiran.

### Tanda con `gemma4-26b-a4b` (REQ-001, REQ-003)

`outputs/gate-g4-research.json` (respuestas, filas del log temporal y puntuación con
`evaluate.classify`):

| Caso | Grupo | Claves | Acertadas | Cruzadas | Falladas | Inferencia (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | cruzó con `gemma3-4b` | 5 | 5 | 0 | 0 | 6085 |
| 02 | cruzó | 3 | 3 | 0 | 0 | 2352 |
| 06 | cruzó | 5 | 5 | 0 | 0 | 3156 |
| 12 | cruzó | 5 | 5 | 0 | 0 | 2403 |
| 21 | cruzó | 5 | 5 | 0 | 0 | 3176 |
| 22 | cruzó | 5 | 5 | 0 | 0 | 2943 |
| 23 | cruzó | 5 | 5 | 0 | 0 | 3240 |
| 26 | cruzó | 6 | 6 | 0 | 0 | 2404 |
| 07 | limpio | 6 | 6 | 0 | 0 | 2945 |
| 08 | limpio | 6 | 6 | 0 | 0 | 3373 |
| 09 | limpio | 6 | 6 | 0 | 0 | 4046 |
| 10 | limpio | 4 | 4 | 0 | 0 | 1918 |
| 11 | limpio | 4 | 4 | 0 | 0 | 2088 |
| 17 | limpio | 6 | 6 | 0 | 0 | 2473 |
| 24 | limpio | 6 | 6 | 0 | 0 | 3690 |
| 25 | limpio | 6 | 6 | 0 | 0 | 2822 |

Las 16 filas del log temporal llevan `tool: local_extract`, `model: gemma4-26b-a4b`,
`remote_turn: granted`, `json_schema: used` y `finish_reason: stop`; ninguna respuesta trae
`error` ni `raw`. Mediana de inferencia 2944 ms (mín. 1918, máx. 6085). La puntuación discrimina:
el mismo `evaluate.classify` marca como cruce 7 de las 8 respuestas de un campo de `gemma3-4b`.

### Vía de la tanda grande (REQ-006)

- Visto bueno del usuario: dado hoy para la vía A (segundo proceso del producto que hereda la
  credencial con una tarea programada temporal creada desde una copia del lanzador seguro).
- Copia del lanzador: solo cambia el entorno (`LOCAL_DELEGATE_LONG_INPUT_CHARS=0`, `LOG_DIR` y
  `LOG` temporales, `LOCAL_DELEGATE_WEB_PORT=9394`, `LOCAL_DELEGATE_TURN_URL=http://127.0.0.1:9393/`,
  `LOCAL_DELEGATE_REMOTE_WEB_TOKEN` desde la variable de usuario del token web, `Remove-Item
  Env:LLAMASWAP_CONFIG`) y el comando (`pythonw -I gate/run_g4.py`). La credencial la resolvió el
  mismo mecanismo DPAPI del original; nadie la leyó ni la imprimió. En el `LOG_DIR` temporal, copias
  de `backend-params.json` (mismo `sha256` que el del daemon) y de `language.json` (preferencia de
  idioma, para que el proceso hable igual que el daemon).
- Entorno visto por el proceso: versión 0.50.0, `LONG_INPUT_CHARS=0`, `WEB_PORT=9394`, `TURN_URL`
  a `127.0.0.1:9393`, sin `LLAMASWAP_CONFIG`, token remoto presente.
- Llamada de validación sin tabla (`name`, `city` sobre una frase): fila del log temporal con
  `remote_turn: granted`, `model: gemma4-26b-a4b`, `model_swap: true`; a la vez el `inflight.json`
  del daemon mostró la entrada `remote:<host>/46640-1` con `tool: local_extract`, `source: remote`,
  `host_via: lease`. Pasa.
- Al acabar, una llamada pequeña sin tabla por el MCP del daemon fue a `gemma3-4b` y `local_status`
  mostró `llama-swap /running: gemma3-4b (ready)`.

### Cambios de modelo en el backend compartido

| Hora (Uruguay) | Cambio | Por qué |
| --- | --- | --- |
| 12:24:27 | carga en frío de `gemma3-4b` (no había ningún modelo montado) | primera llamada de la tanda 3 |
| 12:31:02 | `gemma3-4b` → `gemma4-26b-a4b` | llamada de validación del segundo proceso |
| 12:33:44 | `gemma4-26b-a4b` → `gemma3-4b` | llamada de comprobación por el MCP al acabar |

Dos cambios de modelo provocados (ida y vuelta) y una carga inicial.

## Implementación (T2, T3, T5, T6)

Hecha el 2026-11-10 por la tarde (hora de Uruguay) en la rama `feat/extract-table-routing`, desde
`origin/main` en `7f1ca2ee`. Un commit por tarea, firmados; sin T4 ni nada del aviso (D11).

- **T2, fixtures**: los 17 ficheros de `cases/` y `cases.json`, copiados byte a byte en
  `tests/fixtures/extract_table_routing/` con un `README.md` de una línea; `.gitattributes` los
  marca `-text` para que el tamaño en bytes (el que decide el rol por `path`) no cambie en un
  checkout de Windows. Recuento por programa (`test_the_fixtures_hold_the_research_set`): 26 casos,
  130 claves, 22 pequeños y 16 de ellos con tabla. El sdist no arrastra `.sdd` (`/.sdd` está en
  `exclude`). Esta carpeta del cambio entra en el mismo commit; `ruff` la salta
  (`extend-exclude` y `force-exclude`, porque el hook de pre-commit pasa los ficheros por nombre y
  sin eso reformateaba `gate/detector_frozen.py`, cuyo `sha256` está anotado arriba).
- **T3, `table_detect.has_table`**: módulo puro, sin `re` y sin importar nada del paquete. Sobre
  los 22 pequeños, `True` en los 16 con tabla y `False` en los 6 sin ella; `False` fijado en CSV,
  TSV, GFM sin tuberías externas, `|-|-|` y `<div>`; `<track>`, `<tablet>`, `<trace>` y `<table`
  al final del texto no son tabla; cinco entradas hostiles de 1 000 000 de caracteres en un proceso
  hijo con tope duro de 10 s, todas bajo 1 s; importarlo carga solo `local_delegate` y
  `local_delegate.table_detect`; la fuente congelada de `extraer-toml-2k` da `False` (REQ-007).
- **T5, cableado**: `_extract_role` envuelve `_role_for_size` (que no cambia) y se llama después de
  `_read_input`; `_TABLE_LONG_MIN_FIELDS = 1` (D12); `config.EXTRACT_TABLE_LONG` con
  `_env_flag("LOCAL_DELEGATE_EXTRACT_TABLE_LONG", True)`, que entra solo en
  `config.ENVIRONMENT_VARIABLES`. El motivo viaja por dos sitios: una `ContextVar`
  (`server._ROLE_REASON`) que `_log_event` lee para las filas que la operación escribe desde su
  hilo, y el token de la llamada (`cancellation.Token.role_reason`, atributo nuevo) que
  `_log_stopped` pasa a `_log_event` para las filas que escribe el middleware fuera de ese
  contexto. El ámbito de la `ContextVar` lo abre y lo cierra el decorador `_role_reason_scope`
  (`functools.wraps`, debajo de `@mcp.tool`), con el cuerpo dentro de `local_extract`, así que el
  motivo no se filtra a la operación siguiente. `role_reason` entra en `_local_delegate` también en las dos respuestas de
  error. Texto nuevo `mcp.warning.extract_role_reason_table` en `es` y `en`.
- **T6, documentación**: CHANGELOG (`### Cambiado` de `[Unreleased]`), README (fila de la tool y
  de la variable), `docs/wiki/Tools.md`, `Configuration.md` (variable, tabla de roles y contrato de
  `_local_delegate`), `Architecture.md`, `Savings-and-metrics.md` (campo del log, después de
  `routing`) y la receta de Claude Code (que decía «mecánico»). Guardián:
  `tests/test_extract_table_routing_docs.py`.
- **Guardianes que pidieron entradas** (solo altas): `scripts/data/spanish_lexicon.json` (10
  palabras inglesas de los tests y de un fixture: `div`, `endless`, `gfm`, `licensed`, `pipes`,
  `pythondontwritebytecode`, `see`, `sits`, `tablet`, `thumbnail`) y
  `scripts/data/name_exceptions.json` (`catalogo-2026-09` y `extraer-toml-2k.toml` en
  `tests/test_table_detect.py`, dato congelado del corpus). Cada entrada va en el commit de la
  tarea que la necesita, para que ningún commit deje un test en rojo.

Desviaciones:

- `cancellation.py` no estaba en la lista de ficheros de T5: el atributo `role_reason` del token
  es la vía que el plan nombra («en el token de la operación»), y es una línea con su comentario.
- `pyproject.toml` (exclusión de `ruff`) y `.gitattributes` tampoco estaban en T2; los dos son
  necesarios para que el commit de la carpeta del cambio no la reescriba y los fixtures conserven
  sus bytes.
- El test que comprueba que `server.py` llama a `has_table` sin repetir la regla (REQ-010) está en
  `tests/test_extract_table_routing.py` y no en `tests/test_table_detect.py`, para que el commit de
  T3 no quede en rojo antes del cableado.
- El primer cableado movía el cuerpo a `_local_extract` y rompía dos tests existentes que leen
  `inspect.getsource(server.local_extract)` (`test_density::test_no_chars_per_token_in_the_conversion`
  y `test_dashboard_cost::test_forbidden_phrases`). Se arregló en el código, no en los tests: el
  ámbito pasa a un decorador y el cuerpo vuelve a `local_extract` (commit `fix(extract)` aparte).
  Los 17 mutantes se repitieron después del cambio, con el mismo resultado.

## Tabla antes/después (REQ-037), sin backend

«Antes»: rol y modelo de las corridas grabadas de la investigación (`outputs/g3-extract.json` para
los 22 pequeños, `outputs/g4-extract.json` para los 4 grandes), claves cruzadas de
`outputs/evaluation.json` y, para los grandes, inferencia de `outputs/log-window-rows.json` (en los
pequeños las filas no casan una a una con los casos y se deja «—»; la mediana con `gemma3-4b` fue de
0,84 s). «Después»: el `local_extract` de esta rama con un doble de backend (`_post_chat`
sustituido, `BASE_URL` a un puerto cerrado, log temporal), por `path`, con la configuración por
defecto: modelo pedido, `role_reason` en la respuesta y en la fila del log. Script:
`gate/routing_before_after.py`; salida: `outputs/routing-before-after.json`. Sin llamadas al
backend: las cruzadas «después» de los 16 con tabla son las de la puerta (T1) con el modelo grande
por el producto, y las de la prueba en vivo se anotarán en «Prueba en vivo».

| Caso | Bytes | Tabla | Antes: rol / modelo | Antes: cruzadas | Antes: inf. (ms) | Después: rol / modelo | `role_reason` (respuesta / log) | Cruzadas en la puerta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | 957 | sí | mechanical / `gemma3-4b` | 1 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 02 | 957 | sí | mechanical / `gemma3-4b` | 1 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 03 | 468 | no | mechanical / `gemma3-4b` | 0 | — | mechanical / `gemma3-4b` | — / — | sin cambio |
| 04 | 2157 | no | mechanical / `gemma3-4b` | 0 | — | mechanical / `gemma3-4b` | — / — | sin cambio |
| 05 | 468 | no | mechanical / `gemma3-4b` | 0 | — | mechanical / `gemma3-4b` | — / — | sin cambio |
| 06 | 437 | sí | mechanical / `gemma3-4b` | 1 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 07 | 270 | sí | mechanical / `gemma3-4b` | 0 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 08 | 778 | sí | mechanical / `gemma3-4b` | 0 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 09 | 264 | sí | mechanical / `gemma3-4b` | 0 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 10 | 417 | sí | mechanical / `gemma3-4b` | 0 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 11 | 179 | sí | mechanical / `gemma3-4b` | 0 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 12 | 583 | sí | mechanical / `gemma3-4b` | 1 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 13 | 396 | no | mechanical / `gemma3-4b` | 0 | — | mechanical / `gemma3-4b` | — / — | sin cambio |
| 14 | 243 | no | mechanical / `gemma3-4b` | 0 | — | mechanical / `gemma3-4b` | — / — | sin cambio |
| 15 | 6611 | sí | long / `gemma4-26b-a4b` | 0 | 9233 | long / `gemma4-26b-a4b` | — / — | sin cambio |
| 16 | 6051 | sí | long / `gemma4-26b-a4b` | 0 | 5969 | long / `gemma4-26b-a4b` | — / — | sin cambio |
| 17 | 430 | sí | mechanical / `gemma3-4b` | 0 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 18 | 927 | no | mechanical / `gemma3-4b` | 0 | — | mechanical / `gemma3-4b` | — / — | sin cambio |
| 19 | 29382 | sí | long / `gemma4-26b-a4b` | 0 | 26115 | long / `gemma4-26b-a4b` | — / — | sin cambio |
| 20 | 29382 | sí | long / `gemma4-26b-a4b` | 0 | 16832 | long / `gemma4-26b-a4b` | — / — | sin cambio |
| 21 | 957 | sí | mechanical / `gemma3-4b` | 2 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 22 | 437 | sí | mechanical / `gemma3-4b` | 1 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 23 | 778 | sí | mechanical / `gemma3-4b` | 1 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 24 | 264 | sí | mechanical / `gemma3-4b` | 0 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 25 | 270 | sí | mechanical / `gemma3-4b` | 0 | — | long / `gemma4-26b-a4b` | table / table | 0 |
| 26 | 430 | sí | mechanical / `gemma3-4b` | 1 | — | long / `gemma4-26b-a4b` | table / table | 0 |

Controles negativos, leídos de la tabla: los 6 casos sin tabla (03, 04, 05, 13, 14, 18) no cambian
de rol ni de modelo y no llevan `role_reason`; los 4 grandes (15, 16, 19, 20) siguen en `long` y no
ganan `role_reason`. Los 16 pequeños con tabla suben todos, con `role_reason` en la respuesta y en
la fila del log; las 9 claves que cruzaban con `gemma3-4b` (8 casos) dieron 0 cruces con el modelo
grande en la puerta. Los valores «después» de los 6 sin tabla no se recalculan: el prompt y el
modelo son los mismos (REQ-018, test byte a byte), así que solo los da la prueba en vivo.

## Mutantes (REQ-036)

Los 17 de la tabla del plan, cada uno solo, con `PYTHONDONTWRITEBYTECODE=1`, por un guion que
aplica el cambio de texto (comprobando que el fragmento aparece una sola vez), corre la sonda en
un proceso hijo con el código sin mutar y con el mutante, corre el fichero de tests nombrado y
restaura los bytes del fuente en un `finally` (al final comprueba el `sha256` de
`table_detect.py` y `server.py`: restaurados). Las sondas llaman al código del árbol con un doble de
backend y un log temporal. Después, para fijar la aserción, cada mutante se repitió con solo el
test nombrado. **17 de 17 mutan y mueren por el test y la aserción nombrados; ningún superviviente.**

| # | Mutante | Sonda: sin mutar → mutante | Test que falla | Aserción que dispara | Otros que caen |
| --- | --- | --- | --- | --- | --- |
| M01 | `has_table` solo mira HTML | caso 06: `True` → `False` | `test_a_markdown_table_is_a_table` | `assert has_table(<caso 06>) is True` (una tabla Markdown es tabla) | 9 (los casos Markdown del reparto 16/6, CRLF) |
| M02 | no exige línea separadora | `a \| b \| c`: `False` → `True` | `test_a_pipe_without_separator_line_is_not_a_table` | `assert has_table('a \| b \| c') is False` | 1 |
| M03 | distingue mayúsculas | `<TABLE><TR>`: `True` → `False` | `test_table_is_a_table_in_any_case` | `assert has_table('<TABLE><TR><TD>5…') is True` | 0 |
| M04 | no mira el carácter que sigue a la etiqueta | `<track>`: `False` → `True` | `test_track_and_tablet_are_not_tables` | `assert has_table("<track src='a.vtt'>") is False` (y `<tablet>`, `<trace>`, `<table`, `<tr`) | 0 |
| M05 | `re.search(r"(?:\|[^\n]*)+\n[ \t\|:]*--")` | 1 000 000 de `\|`: 0,0 s → más de 10 s (tope duro) | `test_a_hostile_input_ends_in_less_than_a_second[pipes-one-line]` | `pytest.fail("pipes-one-line: has_table did not end within 10.0 s")` | 2 (la GFM sin tuberías externas pasa a `True`; «no usa regex») |
| M06 | el rol sigue saliendo solo del tamaño | caso 01: `gemma4-26b-a4b` → `gemma3-4b` | `test_a_small_table_goes_to_the_long_model_by_path` | «the small table goes to the long model» | 28 |
| M07 | mínimo de 2 campos | caso 01, un campo: `gemma4-26b-a4b` → `gemma3-4b` | `test_with_one_field_the_small_table_goes_to_the_long_model` | «with one field, the small table goes to the long model» | 1 (`_TABLE_LONG_MIN_FIELDS == 1`) |
| M08 | cambia el modelo pero no el rol | caso 01: rol `long` → `mechanical` | `test_a_small_table_goes_to_the_long_model_by_path` | «the call carries role='long'» | 22 |
| M09 | la regla pasa `explicit=True` | caso 01 con el largo fallando: `answered_by` `qwen36-35b-a3b` → ninguno | `test_when_the_long_model_fails_the_code_model_answers` | «fallback.answered_by is the model of code» | 1 (sin los parámetros del rol `long`) |
| M10 | el interruptor no se lee | caso 01 apagado: `gemma3-4b` → `gemma4-26b-a4b` | `test_with_the_switch_off_a_small_table_stays_on_the_mechanical_model` | «switched off, it goes to the mechanical model» | 1 |
| M11 | la regla se mete en el camino compartido (`local_summarize` llama a `_extract_role`) | `local_summarize` con el caso 06: `gemma3-4b` → `gemma4-26b-a4b` | `test_the_other_three_tools_stay_on_the_mechanical_model` | «the other three tools stay on mechanical» | 0 |
| M12 | una frase más en el `system` | caso 01: el `system` acaba distinto | `test_system_and_user_message_are_identical_byte_for_byte` | «system and message identical» | 0 |
| M13 | `role_reason` siempre que el rol es `long` | caso 15: sin `role_reason` → con él | `test_by_size_there_is_no_role_reason` | «by size there is no role_reason» | 0 |
| M14 | `role_reason` fuera de la respuesta de error | caso 01, respuesta que no es JSON: con `role_reason` → sin él | `test_the_error_answer_carries_role_reason` | «the error answer carries role_reason» | 0 |
| M15 | el motivo no va en el token | caso 01, plazo propio agotado: fila de `_log_stopped` `table` → sin campo | `test_the_deadline_row_of_log_stopped_carries_role_reason` | «the _log_stopped row carries role_reason» | 2 (cola saturada y excepción) |
| M16 | el texto de `role_reason` va a `warning` | caso 10: sin `warning` → con él | `test_role_reason_adds_nothing_to_warning` | «warning does not exist» | 0 |
| M17 | el docstring no nombra la clave nueva | `local_extract.__doc__`: nombra las dos → ninguna | `test_the_docstring_names_role_reason_and_its_switch` | `assert 'role_reason' in doc` | 0 |

Un test se corrigió por esta tabla, como pide el plan («si falla por otra, se corrige el test, no
el mutante»): con M09 disparaba antes «`loaded` is empty: the code model answers» (la lista de
modelos llamados) que la de `fallback.answered_by`; se adelantó la aserción de `answered_by`.

## Prueba en vivo (REQ-038): pasos (resultado al final de la sección)

No la hizo el agente de implementación (encargo expreso). La hace la sesión principal, junto con
otra prueba, con el daemon reinstalado desde la rama. Pasos:

1. **Antes**: CI de la rama en verde; avisar de que el reinicio corta el MCP de las sesiones
   abiertas. Copia de `~/.codex/config.toml` si luego se corre `install`/`update`.
2. **Instalar la rama en el daemon** (código sin publicar; con `--force .` a secas uv reutiliza la
   rueda en caché): parar la tarea `LocalDelegateDaemon` y matar su `pythonw` por PID; desde el
   worktree de la rama, `uv tool install --force --reinstall --no-cache ".[llamaswap]"`;
   arrancar con `schtasks /Run /TN LocalDelegateDaemon`; `/mcp` en la sesión; comprobar con
   `local_status` la versión y que el entorno del daemon **no** trae
   `LOCAL_DELEGATE_EXTRACT_TABLE_LONG=0` ni `LOCAL_DELEGATE_LONG_INPUT_CHARS` distinto de 6000.
3. `local-delegate test-window start --label sdd-586-live`; anotar el id y la hora (Uruguay).
4. **Las 26 llamadas**, por el MCP del daemon, de una en una y al menos 3 s entre llamadas, en
   este orden (agrupadas por modelo: primero los 6 sin tabla con el mecánico, después los 16 con
   tabla y los 4 grandes con el largo). Cada una es
   `local_extract(fields=<fields>, path="<ruta absoluta de tests/fixtures/extract_table_routing>/<fichero>")`:

   | # | Caso | Grupo | Fichero | `fields` |
   | --- | --- | --- | --- | --- |
   | 1 | `03-pr-view-es` | sin tabla | `03-pr-view-es.json` | `["review_verdict", "comments_authors_and_gist", "number_of_reviews", "closes_issue", "body_summary"]` |
   | 2 | `04-pytest-log-en` | sin tabla | `04-pytest-log-en.log` | `["number_of_failed_tests", "first_failed_test", "total_duration_seconds", "coverage_percent", "python_version"]` |
   | 3 | `05-pr-view-es-booleans` | sin tabla | `03-pr-view-es.json` | `["includes_database_migration", "mentions_windows", "body_language"]` |
   | 4 | `13-aviso-obras-es` | sin tabla | `13-aviso-obras-es.txt` | `["fecha_inicio", "fecha_fin", "responsable", "presupuesto", "ubicacion_temporal", "fecha_de_inspeccion"]` |
   | 5 | `14-service-conf-en` | sin tabla | `14-service-conf-en.conf` | `["db_host", "db_port", "cache_host", "cache_port", "queue_host", "queue_port", "db_timeout_seconds"]` |
   | 6 | `18-thumbnailer-py` | sin tabla | `18-thumbnailer-py.py` | `["function_names", "shell_command_used", "http_port", "database_table_name"]` |
   | 7 | `01-pricing-table-en` | tabla | `01-pricing-table-en.html` | `["plans_with_monthly_price", "licensed_user_limits", "custom_domain_limits", "storage_per_workspace", "sso_availability"]` |
   | 8 | `02-pricing-table-en-3fields` | tabla | `01-pricing-table-en.html` | `["plans_with_monthly_price", "licensed_user_limits", "self_hosted_options"]` |
   | 9 | `06-limits-table-es` | tabla | `06-limits-table-es.md` | `["limite_usuarios_activos", "limite_usuarios_con_licencia", "limite_usuarios_invitados", "limite_de_proyectos", "almacenamiento_por_proyecto"]` |
   | 10 | `07-gateway-table-en` | tabla | `07-gateway-table-en.md` | `["max_upload_size", "max_download_size", "max_request_body_size", "idle_timeout", "request_timeout", "connect_timeout"]` |
   | 11 | `08-managed-service-es` | tabla | `08-managed-service-es.html` | `["sso_disponible", "frecuencia_backups", "sla_soporte", "retencion_logs", "limite_llamadas_api", "usuarios_con_licencia"]` |
   | 12 | `09-allowances-table-en` | tabla | `09-allowances-table-en.md` | `["licensed_user_limits", "storage_quota", "sla_uptime", "data_region", "custom_domain_limits", "staging_environments"]` |
   | 13 | `10-spec-sheet-en` | tabla | `10-spec-sheet-en.html` | `["weight", "color", "warranty", "battery_life"]` |
   | 14 | `11-ficha-suministro-es` | tabla | `11-ficha-suministro-es.md` | `["titular", "fecha_de_alta", "ciudad", "tarifa"]` |
   | 15 | `12-capabilities-repeated-en` | tabla | `12-capabilities-repeated-en.html` | `["audit_log", "single_sign_on", "priority_support", "custom_roles", "ip_allowlist"]` |
   | 16 | `17-plans-transposed-en` | tabla | `17-plans-transposed-en.html` | `["studio_seats", "studio_storage", "factory_storage", "hobby_monthly_builds", "studio_bandwidth", "factory_seats"]` |
   | 17 | `21-pricing-table-en-near-miss` | tabla | `01-pricing-table-en.html` | `["storage_per_user", "api_requests_per_day", "custom_domains", "audit_log_retention", "build_log_retention"]` |
   | 18 | `22-limits-table-es-near-miss` | tabla | `06-limits-table-es.md` | `["limite_usuarios_activos", "limite_de_tableros", "almacenamiento_por_usuario", "retencion_de_la_papelera", "retencion_de_copias"]` |
   | 19 | `23-managed-service-es-near-miss` | tabla | `08-managed-service-es.html` | `["copias_de_seguridad", "tiempo_de_respuesta_del_soporte", "tiempo_de_restauracion", "puestos_incluidos", "puestos_adicionales"]` |
   | 20 | `24-allowances-table-en-near-miss` | tabla | `09-allowances-table-en.md` | `["seats", "disk_quota", "bandwidth_quota", "uptime_guarantee", "support_response_time", "sandbox_environments"]` |
   | 21 | `25-gateway-table-en-near-miss` | tabla | `07-gateway-table-en.md` | `["max_upload_size", "max_message_size", "max_concurrent_connections", "max_concurrent_streams", "idle_timeout", "connect_timeout"]` |
   | 22 | `26-plans-transposed-en-near-miss` | tabla | `17-plans-transposed-en.html` | `["hobby_seats", "hobby_storage", "studio_monthly_builds", "factory_monthly_builds", "enterprise_seats", "studio_price"]` |
   | 23 | `15-pricing-page-large-en` | grande | `15-pricing-page-large-en.html` | `["plans_with_monthly_price", "licensed_user_limits", "self_hosted_options", "api_rate_limits"]` |
   | 24 | `16-manual-plan-equipo-large-es` | grande | `16-manual-plan-equipo-large-es.md` | `["limite_usuarios_activos", "limite_usuarios_con_licencia", "limite_usuarios_invitados", "limite_de_proyectos", "almacenamiento_por_proyecto"]` |
   | 25 | `19-pricing-page-noisy-en-3fields` | grande | `19-pricing-page-noisy-en.html` | `["plans_with_monthly_price", "licensed_user_limits", "self_hosted_options"]` |
   | 26 | `20-pricing-page-noisy-en-5fields` | grande | `19-pricing-page-noisy-en.html` | `["plans_with_monthly_price", "licensed_user_limits", "custom_domain_limits", "storage_per_workspace", "sso_availability"]` |

5. **Guardar** las 26 respuestas tal cual, en ese orden, en `outputs/live-answers.json`
   (`{"<id del caso>": <objeto devuelto>}`), y las 26 filas del log de uso de la ventana con
   `tool: local_extract`, en el mismo orden, en `outputs/live-log-rows.jsonl` (solo esas filas;
   sin `tool_use_id` ni campos de atribución si se prefiere: el puntuador no los lee).
6. **Puntuar**, desde la carpeta del cambio: `python -I gate/score_live.py
   outputs/live-answers.json outputs/live-log-rows.jsonl`. Escribe `outputs/live-score.json` y sale
   con 1 si algo falla. Control positivo y negativo del puntuador hechos con las respuestas grabadas
   de la investigación: pasa con ellas, y falla si a la fila de `07` le falta `role_reason` o si
   el caso `14` (sin tabla) sale del modelo largo.
7. `local-delegate test-window stop <id>`; comprobar que no queda ningún proceso ni espera de la
   prueba. Después, dejar el daemon con lo que toque (la versión publicada cuando salga).

Lo que debe dar (criterios de REQ-038 y del plan):

| Qué | Esperado |
| --- | --- |
| Casos 1 a 6 (sin tabla) | `model: gemma3-4b` en la fila del log; ni la respuesta ni la fila llevan `role_reason` |
| Casos 7 a 22 (tabla pequeña) | `model: gemma4-26b-a4b`; respuesta con `_local_delegate.role_reason` = `{"role": "long", "reason": "table", "notice": "la entrada trae una tabla y por eso fue al modelo de contexto largo, …; LOCAL_DELEGATE_EXTRACT_TABLE_LONG=0 lo apaga"}` (en el idioma del daemon); fila con `role_reason: "table"`; sin `warning` por la regla |
| Casos 23 a 26 (grandes) | `model: gemma4-26b-a4b`, sin `role_reason` en respuesta ni fila |
| Cruces | 1 caso como mucho de los 8 que cruzaban con `gemma3-4b` (01, 02, 06, 12, 21, 22, 23, 26); en la puerta fueron 0 |
| `error`/`raw` | ninguno de los 26 |
| Inferencia de los 16 con tabla | mediana cerca de los 2,944 s de la puerta (6,5 s como techo de REQ-003); la primera tras el cambio de modelo paga la carga (unos 10 a 13 s más) |
| Cambios de modelo | dos como mínimo: al pasar del caso 6 al 7 (`gemma3-4b` → `gemma4-26b-a4b`) y la vuelta en la siguiente llamada mecánica de quien sea |
| Fila del log, campos | además de `role_reason`, `routing` no aparece (no es afinidad), `json_schema: used`, `finish_reason: stop`; la ventana separa las 26 filas del panel |

Si falla un criterio, el #586 sigue abierto y solo se comenta el resultado (T8).

### Prueba en vivo (REQ-038), resultado

Hecha por la sesión principal el 2026-11-10 entre las 16:05 y las 16:16 (hora de Uruguay), dentro
de la ventana `w-20261110T190517Z` (etiqueta `live-2026-11-10`, cerrada a las 16:16:39, 32 filas:
las 26 de este cambio y 6 de la prueba en vivo de `usage-log-project-and-own-repo-exclusion`), con
el daemon instalado desde la rama local de integración de los PR #637, #643, #645 y #646 (las filas
llevan `v: 0.50.0`, la versión del árbol antes del salto a 0.51.0). Antes de mezclar el PR #643
(mezclado a las 16:44). Puntuado desde la carpeta del cambio con `python -I gate/score_live.py
outputs/live-answers.json <filas en jsonl>`; las filas se guardan en `outputs/live-log-rows.json`
(lista JSON; el repo ignora `*.jsonl`) con solo los campos que lee el puntuador y los de la tabla
de esperados, sin `host`, `path` ni atribución.

| Qué | Esperado | Medido | Resultado |
| --- | --- | --- | --- |
| Llamadas | 26, de una en una | 26 respuestas y 26 filas `local_extract` | pass |
| Puntuador | `pass: true` | `pass: true`, `problems: []` | pass |
| Casos 1 a 6 (sin tabla) | `gemma3-4b`, sin `role_reason` | `gemma3-4b`, sin `role_reason` en respuesta ni fila | pass |
| Casos 7 a 22 (tabla pequeña) | `gemma4-26b-a4b`, `role_reason` `table` en respuesta y fila | los 16, con `role_reason` `table` en las dos | pass |
| Casos 23 a 26 (grandes) | `gemma4-26b-a4b`, sin `role_reason` | los 4, sin `role_reason` | pass |
| Cruces | 1 caso como mucho de los 8 | 0 de 8 (`crossed_cases_of_the_8: []`) | pass |
| `error`/`raw` | ninguno | 0 | pass |
| Inferencia de los 16 con tabla | mediana ≤ 6,5 s | mediana 3,09 s (3.086,5 ms); la primera tras el cambio de modelo, 9,96 s (la carga) | pass |
| Valores de los sin tabla | sin cambio | mismos veredictos que la corrida grabada; `05/body_language` sigue inventado, igual que antes | pass |
| Ventana | cerrada | cerrada a las 16:16:39 | pass |

Inferencia «después» caso a caso (ms, de `outputs/live-log-rows.json`; veredictos por clave en
`outputs/live-score.json`), que completa la tabla antes/después de REQ-037:

| Grupo | Caso: inferencia (ms) |
| --- | --- |
| Sin tabla (`gemma3-4b`) | 03: 889 · 04: 1.152 · 05: 428 · 13: 1.075 · 14: 1.023 · 18: 735 |
| Tabla pequeña (`gemma4-26b-a4b`) | 01: 9.955 · 02: 2.394 · 06: 3.289 · 07: 3.042 · 08: 3.441 · 09: 4.283 · 10: 2.014 · 11: 2.242 · 12: 2.395 · 17: 2.703 · 21: 3.294 · 22: 3.131 · 23: 3.242 · 24: 3.683 · 25: 2.798 · 26: 2.488 |
| Grandes (`gemma4-26b-a4b`) | 15: 4.964 · 16: 5.603 · 19: 13.199 · 20: 14.099 |

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | 16 casos con `gemma4-26b-a4b` por `local_extract` en el segundo proceso | pass | `outputs/gate-g4-research.json`; 0 de 8 casos cruzan, 0 de 44 claves falladas, 0 `error`/`raw` |
| REQ-002 | 8 claves solas con `gemma3-4b` por el MCP del daemon | pass (valor fijado: 1) | `outputs/gate-g3-single.json`; 1 de 8 bien → `_TABLE_LONG_MIN_FIELDS = 1` |
| REQ-003 | mediana de inferencia de los 16 casos | pass | 2944 ms (1918–6085) ≤ 6500 ms |
| REQ-006 | vía A con validación del turno | pass | fila temporal `remote_turn: granted` y entrada `remote:<host>/46640-1` en el daemon |
| REQ-007 | `has_table` del prototipo sobre `extraer-toml-2k.toml` y `tests/test_corpus.py` | pass | `False` (`outputs/gate-offline.json`); `63 passed`; con el `has_table` del paquete, `test_the_frozen_toml_source_of_the_corpus_has_no_table` y `tests/test_corpus.py` sin tocar, en verde |
| REQ-008 | reparto 16/6 de los 22 pequeños, formas que no ve, mayúsculas, `<track>`/`<tablet>`, tubería sin separadora | pass | `tests/test_table_detect.py`; mutantes M01 a M04 |
| REQ-009 | cinco entradas hostiles de 1 000 000 de caracteres en un proceso hijo (tope 10 s), sin `re` | pass | `tests/test_table_detect.py::test_a_hostile_input_ends_in_less_than_a_second`; mutante M05 |
| REQ-010 | importar el módulo en un proceso aparte sin cargar `server`; `server` llama a `has_table` sin repetir la regla | pass | `test_the_module_imports_without_loading_the_server`, `test_the_server_calls_the_rule_and_does_not_repeat_it` |
| REQ-011 | caso 01 por `path` y caso 06 por `text` al modelo de `long` con `role="long"`; los 16 pequeños con tabla | pass | `tests/test_extract_table_routing.py`; mutantes M06 y M08 |
| REQ-012 | los 6 sin tabla siguen en `gemma3-4b`, sin `role_reason`; `tests/test_core.py` y `tests/test_request_body_compat.py` sin tocar | pass | `test_a_small_input_without_a_table_stays_on_the_mechanical_model`; tabla antes/después; suite |
| REQ-013 | un solo campo con tabla, a `long` | pass | `test_with_one_field_the_small_table_goes_to_the_long_model`; mutante M07 |
| REQ-014 | `LOCAL_DELEGATE_EXTRACT_TABLE_LONG=0` (recarga de `config` desde el entorno): rol por tamaño, sin `role_reason` en respuesta ni fila | pass | `test_with_the_switch_off_a_small_table_stays_on_the_mechanical_model`; mutante M10 |
| REQ-015 | `local_summarize`, `local_lint_summary` y `local_translate` con el caso 06 siguen en `mechanical` | pass | `test_the_other_three_tools_stay_on_the_mechanical_model`; mutante M11 |
| REQ-016 | `role_reason` exacto; también en las dos respuestas de error; no por tamaño; no en `warning` | pass | `test_by_size_there_is_no_role_reason`, `test_the_error_answer_carries_role_reason`, `test_a_json_that_is_not_an_object_carries_role_reason`, `test_role_reason_adds_nothing_to_warning`; mutantes M13, M14 y M16 |
| REQ-017 | fila del camino bueno y filas de `_log_stopped` (plazo propio, `queue_saturated`, excepción) con `role_reason: "table"`; sin tabla, sin campo; no se filtra a la operación siguiente | pass | `test_the_good_path_row_carries_role_reason`, `test_the_deadline_row_of_log_stopped_carries_role_reason`, `test_the_aborted_rows_of_log_stopped_carry_role_reason`, `test_the_reason_does_not_leak_to_the_next_operation`; mutante M15 |
| REQ-018 | `messages` y `response_format` idénticos con la regla y sin ella; la temperatura del rol `long` de `backend-params.json` se aplica | pass | `test_system_and_user_message_are_identical_byte_for_byte`, `test_the_parameters_of_the_long_role_apply_to_the_call`; mutante M12 |
| REQ-019 | con el largo fallando responde `config.MODEL_CODE` (`loaded` vacío) | pass | `test_when_the_long_model_fails_the_code_model_answers`; mutante M09 |
| REQ-031 | el docstring nombra `role_reason`, la tabla y el interruptor; `test_tool_contract`, `test_mcp_english` y `test_i18n_parity` sin tocar | pass | `test_the_docstring_names_role_reason_and_its_switch`; mutante M17; suite |
| REQ-032 | guardián de superficies (7 ficheros) y la clave de texto en `es` y `en` | pass | `tests/test_extract_table_routing_docs.py` |
| REQ-033 | lectura de CHANGELOG y `docs/wiki/Tools.md` contra «Coste» y «Límites»: cifras de la puerta (0 de 8, 0 de 44, 2,944 s frente a 0,84 s), de 10 a 13 s si no estaba cargado, p90 31,9 s, respaldo al de `code`, otros clientes, cómo se apaga, lo que no ve, el caso de 33 KB y el aviso fuera | pass (lectura del implementador; la revisión de resultado la repite) | `CHANGELOG.md` `[Unreleased]` → «Cambiado»; `docs/wiki/Tools.md` → `local_extract` |
| REQ-034 | `git diff --name-only origin/main...HEAD` sobre skills, memoria, plugin, hooks y `web/` | pass | 0 ficheros |
| REQ-035 | `git diff --name-status origin/main...HEAD -- tests` y suite entera | pass | 22 `A` (3 tests y 19 fixtures), ningún `M`/`D` (en `da15a6f6`, `--diff-filter=MDR -- tests` vacío); suite entera sobre el código final: CI del PR #643, 22 checks en verde (corrida 42887304570), y CI de `main` en `da15a6f6` en verde (corrida 42888361529) |
| REQ-036 | 17 mutantes, uno a uno | pass | «Mutantes (REQ-036)»: 17 de 17 mueren por la aserción nombrada |
| REQ-037 | tabla antes/después de los 26 casos con un doble de backend, y valores «después» de la prueba en vivo | pass | «Tabla antes/después (REQ-037), sin backend» y «Prueba en vivo (REQ-038), resultado»: los 6 sin tabla siguen en `gemma3-4b` sin `role_reason` y con los mismos veredictos que antes (incluido el `body_language` inventado de `05`, igual que en `outputs/evaluation.json`); los 4 grandes no ganan `role_reason` |
| REQ-038 | prueba en vivo por el daemon con el paquete de la rama, ventana `w-20261110T190517Z` | pass | `gate/score_live.py` → `pass: true`; 0 cruces de 8, 0 `error`/`raw`, mediana 3,09 s; `outputs/live-answers.json`, `outputs/live-log-rows.json`, `outputs/live-score.json`; ventana cerrada; antes de mezclar el PR #643 |
| REQ-039 | cierre del #586, issue de seguimiento y tarjetas | pass | #586 cerrado con comentario (https://github.com/ZahiriNatZuke/local-delegate/issues/586#issuecomment-6777699868) cuya primera línea dice lo que queda fuera; seguimiento público #650 (caso de 33 KB con criterio de reapertura, aviso con `c01`, `c20` y `c19`); tarjeta del seguimiento y tarjeta del #630 en el tablero |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `sha256sum -c SHA256SUMS` (en `holdout/`) | 2026-11-10 12:2x | 25 OK | salida de la sesión |
| `python -I gate/gate_offline.py` | sí | REQ-004 pasada 1, cupos, REQ-007, cordura | `outputs/gate-offline.json` |
| `python -I gate/score_holdout.py` | sí | REQ-004 pasada 2, REQ-005 | `outputs/gate-g3-holdout-score.json` |
| `python -I gate/score_g4.py <out> <log temporal>` | sí | REQ-001, REQ-003 | `outputs/gate-g4-research.json` |
| `pesado.sh .venv/Scripts/python.exe -m pytest tests/test_corpus.py -q -n 2` | sí | 63 passed | salida de la sesión |
| `pesado.sh python -m pytest -q -n 2` (suite completa, una vez) | 2026-11-10, antes del decorador | 6974 passed, 31 skipped, 3 failed, 400 s | dos fallos por `getsource` (ver Desviaciones, arreglados en el código) y `test_build_hook::test_sdist_carries_what_regenerates_the_mod`, del entorno: `register.js` generado en el worktree (trampa conocida, se borró) |
| `pesado.sh python -m pytest -n 2` sobre los 15 ficheros afectados (los 3 nuevos, `test_build_hook`, `test_dashboard_cost`, `test_density`, `test_tool_contract`, `test_tool_signatures`, `test_mcp_english`, `test_turn_wait_notice`, `test_core`, `test_extract_placeholder_values`, `test_fallback`, `test_request_body_compat`, `test_aborted_delegations`) | 2026-11-10, tras el decorador | 424 passed | salida de la sesión |
| driver de mutantes (17, uno a uno, `PYTHONDONTWRITEBYTECODE=1`) | 2026-11-10 13:2x (UTC−3), tras el decorador | 17 mutan, 17 mueren por la aserción nombrada | tabla «Mutantes» |
| `ruff check .` y `ruff format --check .` | 2026-11-10 | sin errores, 463 ficheros formateados | salida de la sesión |
| `gitleaks git --redact --log-opts=origin/main..HEAD` y `gitleaks dir --redact` de la carpeta del cambio y del test | 2026-11-10 | no leaks found | salida de la sesión |
| `python -I gate/routing_before_after.py` | 2026-11-10 | 26 casos | `outputs/routing-before-after.json` |

## Quality checks

- [x] Project-native tests pass (salvo el fallo del entorno de `test_build_hook` en el worktree, ver Commands; el CI del PR es la prueba limpia).
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- **Prueba en vivo sobre la integración de cuatro PR**: el daemon se instaló desde una rama local
  con #637, #643, #645 y #646, no desde la rama de este cambio sola. Es un superconjunto, más cerca
  de lo que salió en 0.51.0; ninguno de los otros tres toca el enrutado de `local_extract`.
- **Test del cambio retocado al sacar la release**: `tests/test_extract_table_routing_docs.py`
  exigía la entrada en `[Unreleased]` del CHANGELOG; el commit de la release 0.51.0 (`034fe612`)
  la cambia por `test_the_changelog_entry_is_newer_than_0_50_0`. Es un test de este cambio, no uno
  existente (REQ-035 no se toca), pero el diff revisado (`da15a6f6`) ya no es el código vigente en
  ese fichero.
- **Una línea `---` sin tuberías cuenta como separadora**: tras una línea con dos `|`, da tabla
  (front matter YAML con `|`, título subrayado). La spec lo admite al pie de la letra y cae del
  lado de subir de más; no está en «Límites» ni en la documentación. Propuesto para el seguimiento
  #650 (hallazgo de la revisión de resultado; el comentario en el issue queda por hacer).
- REQ-004 y REQ-005 (la puerta del aviso y el caso CSV) ya no los define la spec: están en
  «Non-goals». Lo medido sigue en «Puerta (T1)»: 1 aviso en falso en cada pasada (`c01/price`;
  `outputs/gate-offline.json`, `outputs/gate-g3-holdout-score.json`) y, en el CSV, `c20` con la
  celda vecina y `c19` ambiguo; todo va al seguimiento #650.
- La corrección de plurales no se aplicó (ver «Versión del detector que se congela»): la spec y el
  plan no coinciden en cuándo se decide; se siguió la spec. No cambia el veredicto.
- El segundo proceso no prueba la capa MCP por HTTP, el middleware de cancelación ni las plazas
  compartidas con otras sesiones (ver el plan); para la pregunta de la puerta es el mismo código.
- `gemma3-4b` no cruzó entre claves pedidas en el conjunto nuevo, así que la pasada 2 solo mide
  avisos en falso, no aciertos del detector.
