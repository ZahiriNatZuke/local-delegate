# Plan de implementación: parámetros por rol en las peticiones al backend

Cambio SDD `backend-extra-params`. Spec aprobada: [spec.md](spec.md) (23 REQ). Decisiones del
usuario 1–11 y reglas para agentes: [brief.md](brief.md). Base técnica: [research.md](research.md)
(sobre todo la «Segunda ronda»). Revisión del gate: [review.md](review.md).

**Este plan lo ejecuta una sesión limpia que solo tiene estos ficheros.** Todo lo que necesita
está aquí o enlazado por ruta. Si algo de este plan choca con la spec, **manda la spec**, y se
anota en `verification.md` como desviación.

Las líneas citadas (`fichero:línea`) se tomaron sobre `main` en `f2dd267` (2026-10-20). Si `main`
se ha movido, localiza por nombre de función con `grep -n`, no por número.

---

## 1. Resumen y orden de lotes

### Diseño en una página

- **Módulo único `src/local_delegate/backend_params.py`** (nuevo): catálogo cerrado de 21 claves
  con tipo y rango, claves reservadas, gramática de la variable, lectura tolerante del fichero
  `LOG_DIR/backend-params.json`, escritura atómica bajo `FileLock`, caché por
  `(st_mtime_ns, st_size, st_ino)` + valor de la variable, `effective(role)` y `to_body(...)`.
  Devuelve **códigos** de aviso (`role`, `key`, `code`), nunca valores; los textos salen del
  catálogo i18n.
- **Lector de la variable** `backend_params_override()` en `config.py`, con el patrón
  `(value, problem, raw)` de `output_language()` (`config.py:454`) y metido en el bucle
  `for _reader in (...)` (`config.py:467`).
- **`model_context_size(model)`** en `llamaswap_config.py`, sobre `load_config` (`:487`) y
  `_parse_cmd_flags` (`:240`), con caché y estimado de 8192.
- **Embudo de `server.py`**: un objeto nuevo por operación, `_RoleParams` (parámetros resueltos
  una vez con el rol de origen + banderas `probed`/`rejected`/`reasoning_skipped` +
  `reasoning_chars` acumulado). Hoy los trozos y los pasos de map/reduce van **en serie** (no hay
  `ThreadPoolExecutor` ni `as_completed` en `server.py`); el objeto puede llevar un
  `threading.Lock` como defensa barata, pero no hay ninguna carrera que perseguir. Se
  crea en `_chat` (`server.py:2503`), `_chat_chunked` (`:2955`) y `_chat_map_reduce` (`:3172`),
  viaja en `_CurrentModel` (`:2365`, que hoy pierde el rol en `:2427`) y en `_run_chat` (`:2306`)
  hasta `_with_fallback` (`:2146`) → `_attempt` → `_call_model` (`:2019`). **La fusión final de
  cada llamada real se hace en `_call_model`**, que es el único punto que conoce el modelo destino
  real (lo necesita REQ-023) y el único que ve el 400 (REQ-015). `_run_chat` sigue armando la base
  (capa 1) y el contrato (capa 3) igual que hoy; `_call_model` aplica la capa 2 (rol, presupuesto,
  REQ-023 y detección de REQ-015) sobre una copia del cuerpo. Es lo que dice REQ-012 tras la
  enmienda de la revisión del plan (P1).
- **Orden de claves** (REQ-022): sin parámetros, el cuerpo es exactamente el de hoy
  (`{"model", "messages", "max_tokens", "temperature", "stream"[, "response_format"]}`). Con
  parámetros: `temperature` y `max_tokens` se sustituyen **en su sitio** y las claves nuevas del rol
  se añaden **al final**. Defensa extra: un `assert`/filtro que impide que una clave del rol
  coincida con una reservada.
- **Log**: campos aditivos `backend_params`, `reasoning_chars`, `backend_params_rejected`,
  `reasoning_skipped` en `_log_event` (`server.py:726`).
- **Panel**: `reasonchip` y `paramschip` en `drawActivity` (`web/metrics.py:3095`) y un diálogo de
  detalle por fila con el patrón de `infoDlg` (`web/metrics.py:1776`, `:3209-3233`).
- **Benchmark**: `reasoning_kwargs` (`benchmark.py:1004`) pasa a mandar `enable_thinking: true` +
  `reasoning_effort` en la raíz + `reasoning_budget_tokens`, con `--reasoning-budget` obligatorio.

### Lotes (cada uno, una PR)

| Lote | Contenido | Tareas | Depende de | Tamaño orientativo |
| --- | --- | --- | --- | --- |
| **L0** Red de compatibilidad | Fixtures de los cuerpos de `f2dd267` (script versionado) y test de comparación ordenada; instantánea y guarda de los argumentos de las tools | T1, T2 | — | ~350 |
| **A1** Reglas puras | Catálogo, validación de valores, gramática de la variable, `to_body`; lector en `config.py`; textos de aviso en `common.json` | T3, T4, T5 | L0 **para mezclar** (el paso 7 de T3 edita `tests/test_tool_signatures.py`, de T2); se trabaja en paralelo | ~550 |
| **A2** Fichero y resolución | `load`/escritura atómica/cerrojo/caché/`effective`/informe y reglas de `set`; `model_context_size` | T6, T7 | A1 | ~550 |
| **B** CLI y `doctor` | Subcomando `backend-params show/set/unset/reset` y textos; `backend_params_lines()` en `doctor` | T8, T9 | A2 | ~550 |
| **C1** Fusión en el embudo | `_RoleParams`, capas, temperatura, presupuesto sumado, `local_delegate` explícito, visión; test REQ-022 con parámetros vacíos | T10 | L0, A2 | ~500 |
| **C2** Rechazo y contexto | REQ-015 (400 una vez por operación) y REQ-023 (contexto con `model_context_size`) | T11, T12 | C1 | ~550 |
| **D** Log y `local_status` | `reasoning_chars` en `ChatResult`/`Attempt`, campos del log; líneas en `local_status` | T13, T14 | C2 | ~450 |
| **E** Panel | Marcas, diálogo de detalle, teclado, `panel.json`; test de Playwright | T15, T16 | — (solo los nombres de campos de la spec) | ~500 |
| **F** Benchmark | Arreglo de `--reasoning-effort`, `--reasoning-budget`, metadatos | T17 | A2, B (comparte `cli.json`) | ~300 |
| **G** Documentación y prueba en vivo | Wiki, README, CHANGELOG, test de wiki; prueba en vivo, benchmark corto, capturas, `verification.md` | T18, T19 | todos | ~200 + evidencias |

**19 tareas en 10 lotes.**

### Por qué se ajusta el orden sugerido

- **(a) se parte en A1 y A2**: el módulo con sus tests pasa de 600 líneas; A1 son funciones puras
  (fáciles de revisar), A2 es E/S y caché.
- **(c) se parte en C1 y C2**: la fusión y el rechazo/contexto juntos pasan de 600 líneas y tocan
  el mismo camino crítico; separados, C1 deja el contrato de hoy probado antes de añadir reintentos.
- **`doctor` sube a B**: solo depende de A2 y no toca `server.py`; así D solo toca `server.py`.
- **L0 va primero, en paralelo con A1**: REQ-022 exige generar las fixtures sobre `f2dd267`
  **antes** de tocar `server.py`, y REQ-014 toma su instantánea de `f2dd267`. Ninguno toca código
  de producción.
- **F después de B**: los dos añaden claves a `resources/i18n/{es,en}/cli.json`.

### Qué va en paralelo

```
Ola 1:  L0  ∥  A1  ∥  E
Ola 2:  A2                      (E puede seguir)
Ola 3:  B   ∥  C1               (C1 exige L0 y A2 mezclados)
Ola 4:  C2  ∥  F                (F exige B mezclado)
Ola 5:  D
Ola 6:  G   (T18 puede empezar en la ola 5; T19 exige todo mezclado)
```

- **En serie obligatoria**: A1 → A2 → C1 → C2 → D (mismo módulo o `server.py`). Además, A1 se
  mezcla **después** de L0 (P11): se desarrollan a la vez, pero el paso 7 de T3 solo se hace con
  L0 ya en `main`.
- **Paralelo de verdad**: L0, A1 y E en la ola 1; B y C1; C2 y F.
- **Cuello de botella**: `server.py` (C1, C2, D en serie) y los comandos pesados (pytest, Playwright,
  `uv tool install`), que van de uno en uno por el cerrojo en toda la máquina aunque los agentes
  trabajen en paralelo.
- Cada lote trabaja en su worktree (`D:/Projects/ld-wt-<lote>`), rama `feat/backend-params-<lote>`,
  y se rebasa sobre `main` antes de la PR.

### Ficheros de catálogo i18n (exclusividad)

Cada fichero de catálogo tiene un solo dueño por ola:

| Fichero | Dueño |
| --- | --- |
| `resources/i18n/{es,en}/common.json` | T5 (todos los códigos de aviso del módulo, incluidos los de contexto de REQ-023) |
| `resources/i18n/{es,en}/cli.json` | T8 (ola 3), luego T17 (ola 4) |
| `resources/i18n/{es,en}/doctor.json` | T9 |
| `resources/i18n/{es,en}/mcp.json` | T14 |
| `resources/i18n/{es,en}/panel.json` | T15 |

---

## 2. Tareas por lote

Formato de cada tarea: objetivo · REQ · ficheros que posee · pasos · tests · verificación · hecho ·
delegación local. «Posee» significa que **solo esa tarea** edita ese fichero mientras está abierta;
dos tareas del mismo lote que poseen el mismo fichero van en serie (se dice).

Comando base de tests (siempre desde la tool Bash, desde la raíz del worktree):

```bash
bash ~/.claude/scripts/pesado.sh uv run pytest <ficheros> -q > "$TMP_OUT" 2>&1; echo "exit=$?"
```

con `TMP_OUT` en el scratchpad de la sesión (p. ej.
`<scratchpad>/pytest-T3.txt`), y el resumen con `local_lint_summary(path=TMP_OUT)`.

---

### Lote L0 — Red de compatibilidad

#### T1 — Fixtures de los cuerpos de hoy y comparación ordenada

- **Objetivo**: congelar el cuerpo exacto (con orden de claves) que manda `main` en cada camino, y
  el conjunto de claves del evento del log, antes de tocar `server.py`.
- **REQ**: REQ-022 (base; el resto de su aceptación la completa T10).
- **Posee**: `scripts/capture_request_bodies.py` (nuevo), `tests/fixtures/request_bodies/*.json`
  (nuevo), `tests/test_request_body_compat.py` (nuevo).
- **Pasos**:
  1. Crear el worktree **sobre `f2dd267`** (`git worktree add D:/Projects/ld-wt-l0 f2dd267 -b
     feat/backend-params-l0`).
  2. Escribir el script: parchea `server._post_chat` (`server.py:1330`) con un backend falso que
     captura `(model, payload)` y devuelve un `ChatResult` válido (modelo de captura:
     `tests/test_fallback.py:662`, `monkeypatch.setattr(server, "_post_chat", post_chat)`). Corre
     cada camino y guarda una fixture JSON por camino con `{"commit": "<sha>", "bodies": [...],
     "event_keys": [...]}`. Los cuerpos se guardan como lista de pares para conservar el orden.
  3. Caminos: los siete de REQ-022, con la reducción de map/reduce contada aparte. Una fixture
     por nombre:
     - `simple`: tool simple (`local_summarize` corta);
     - `extract_schema`: `local_extract` con esquema;
     - `extract_schema_retry`: `local_extract` con esquema y su reintento sin esquema (backend
       falso que da `http_400` con `response_format`);
     - `map_chunk`: un trozo de map/reduce (`local_summarize` larga);
     - `reduce`: la reducción de esa misma operación;
     - `vision`: `local_describe_image` con una PNG mínima de 1×1 generada en el script;
     - `fallback`: primer modelo con fallo saltable (`failures.FailureClass.MODEL`) y respaldo;
     - `delegate_explicit`: `local_delegate` con modelo explícito.
  4. Entorno fijado: `LOCAL_DELEGATE_LANG=es`, modelos por rol y cadena de respaldo por variables
     explícitas, `LOG_DIR` temporal. El test reutiliza la fixture `reload_config` y el aislamiento
     `env_without_package_variables`/`isolate_runtime_logs` de `tests/conftest.py:23-64,200-229`
     (lo que la spec llama «ayudantes `_env*`»: los lectores `_env*` de `config.py` se vacían por
     `ENVIRONMENT_VARIABLES` y se recargan).
  5. El test compara con `json.loads(..., object_pairs_hook=list)` (orden incluido) cada cuerpo
     capturado contra la fixture, y el **conjunto** de claves del evento de `usage-*.jsonl`.
     Parametrizado por camino. Con un modo «sin parámetros» que T10 ampliará con `{"version":1,
     "roles":{}}` y un rol vacío.
  6. Generar las fixtures con el script **en `f2dd267`**, comprobar el test en verde ahí, y
     después rebasar sobre `main` (el script y el test no tocan producción).
  7. **Control positivo**: mutante temporal que añade `"x": 1` al `payload` de `_run_chat`
     (`server.py:2337-2345`): el test debe fallar **en el assert de igualdad del cuerpo** (no en
     uno de forma); anotar el nombre del assert en la PR y revertir.
- **Tests**: `tests/test_request_body_compat.py::test_body_matches_main[<camino>]`,
  `::test_event_keys_match_main[<camino>]`.
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_request_body_compat.py -q`
  y `uv run ruff check scripts tests && uv run ruff format --check scripts tests`.
- **Hecho**: las 8 fixtures nombradas en el paso 3, cada una anotando `f2dd267`; test verde en `f2dd267` y en `main`;
  mutante falla en el assert del cuerpo.
- **Delegación local**:
  - *Agente*: `local_boilerplate(spec="script pytest-free que parchea server._post_chat…",
    language="python", target=<worktree>/scripts/capture_request_bodies.py)` para el esqueleto,
    revisado línea a línea; salida de pytest → `local_lint_summary(path=…)`; diff → `local_commit_msg(path=…, style="conventional")`.
    **No** para leer `_run_chat`/`_call_model`: hay que citar líneas exactas; leer la franja con
    `sed -n`/`Read offset`.
  - *Orquestador*: la entrega del agente → `local_summarize(path=<entrega>, focus="caminos cubiertos, assert del mutante, desviaciones")`.

#### T2 — Instantánea y guarda de los argumentos de las tools

- **Objetivo**: que ninguna tool MCP gane argumentos sin que se note.
- **REQ**: REQ-014.
- **Posee**: `tests/test_tool_signatures.py` (nuevo), `tests/fixtures/tool_signatures.json` (nuevo).
- **Pasos**:
  1. Obtener nombres y tipos de parámetros de las 11 tools (definiciones en `server.py:4301`
     `local_summarize`, `:4396`, `:4447`, `:4588`, `:4621`, `:4702`, `:4803`, `:4945`, `:4989`,
     `:5108`, `:5496`) con `inspect.signature` o desde el registro del servidor MCP. Estas son
     las líneas de los `def` y **mandan sobre las de REQ-014** de la spec (`:4326`, `:4412`…),
     que apuntan al cuerpo de cada función.
  2. Guardar la instantánea en `f2dd267`.
  3. Assert (a): igualdad con la instantánea; mensaje «si añadiste un argumento a propósito,
     actualiza la instantánea» (en el `assert`, es texto de test, no de producto).
  4. Assert (b), independiente: ningún parámetro se llama como una clave de REQ-004, una reservada
     de REQ-005, `role`, `backend_params` o `extra_body`, ni empieza por `reasoning`. Hasta A1 la
     lista de claves se escribe literal en el test; T3 la sustituye por
     `backend_params.ALLOWED_KEYS | backend_params.RESERVED_KEYS` (T3 posee esa edición, ver T3).
  5. Control positivo: mutante que añade `top_k: int = 0` a `local_classify`: fallan (a) y (b); se
     anota cuál dispara cada uno.
- **Tests**: `test_tool_parameters_match_snapshot`, `test_no_tool_parameter_is_a_backend_param`.
- **Verificación**: pytest del fichero por el cerrojo; ruff.
- **Hecho**: 11 tools en la instantánea; los dos asserts verdes; mutante probado.
- **Delegación local**: *Agente*: salida de pytest → `local_lint_summary`; diff →
  `local_commit_msg`. No conviene `local_explain_code` sobre `server.py` (250 KB, regla 1b):
  localizar las tools con `grep -n "^def local_"`. *Orquestador*: `local_summarize(path=<entrega>,
  focus="tools de la instantánea, nombres prohibidos de la guarda y qué assert disparó cada mutante")`.

---

### Lote A1 — Reglas puras

#### T3 — Catálogo, validación, gramática y `to_body`

- **Objetivo**: la regla única de qué se acepta y cómo va al cuerpo, sin E/S.
- **REQ**: REQ-004, REQ-005, REQ-006, REQ-007, REQ-008 (gramática), REQ-011 (parte de reglas),
  REQ-012 (capas en `to_body`).
- **Posee**: `src/local_delegate/backend_params.py` (nuevo, primera mitad), `tests/test_backend_params_rules.py`
  (nuevo); al final, la edición de `tests/test_tool_signatures.py` del paso 7 (después de mezclar L0).
- **Pasos**:
  1. Constantes: `ROLES = ("mechanical", "long", "code", "vision")`; `ALLOWED_KEYS` con las 21
     claves de la tabla de REQ-004 (grupo, tipo, rango, destino); `RESERVED_KEYS` con las 27 de
     REQ-005; `DEFERRED_KEYS` con las de «Fuera de alcance» (rechazadas igual); `BUDGET_MIN=1`,
     `BUDGET_MAX=8192`; `MAX_FILE_BYTES=64*1024`; `MAX_OVERRIDE_CHARS=2048`.
  2. `validate_value(key, value) -> (ok, code)`: rechaza `bool` como número, `NaN`, `±inf`, tipo
     equivocado y fuera de rango; enum de `reasoning_effort` sin `none`.
  3. `parse_cli_value(key, text)`: números (rechaza lo que da `inf`, p. ej. `1e400`),
     `on/off/true/false` para `enable_thinking`.
  4. `parse_override(text) -> (entries, warnings)` con la gramática exacta de REQ-008 (`;`,
     espacios, primer `=`, primer `.`, trozos mal formados, duplicadas → gana la última y avisa).
     Los avisos solo llevan rol y clave; **nunca** el texto tras `=`.
  5. `Warning = (role, key, code)` como `NamedTuple`; códigos estables en inglés
     (`unknown_role`, `unknown_key`, `reserved_key`, `deferred_key`, `bad_type`, `out_of_range`,
     `malformed_entry`, `duplicate_key`, `override_too_long`, `thinking_without_budget`,
     `file_unreadable`, `file_bad_version`, `file_too_large`, `context_estimated`,
     `context_overflow`). `warning_text(w)` usa `i18n.t("common.backend_params.warning.<code>",
     role=…, key=…)`.
  6. `to_body(values, *, tool_temperature, tool_max_tokens, thinking_allowed=True) -> (overrides,
     extra)`: devuelve qué sustituir en su sitio (`temperature`, `max_tokens` = tope +
     presupuesto) y qué añadir al final (`top_k`…, `reasoning_budget_tokens`, `reasoning_effort`
     en la raíz, `chat_template_kwargs: {"enable_thinking": bool}`). Con `thinking_allowed=False`
     (REQ-023) manda `enable_thinking: false`, sin presupuesto y con el tope de la tool. Nunca
     devuelve una clave reservada (assert).
  7. Tras mezclar L0: sustituir la lista literal de T2 por las constantes del módulo.
- **Tests** (`tests/test_backend_params_rules.py`): `test_catalog_has_exactly_21_keys`,
  `test_value_validation[<clave>-<caso>]` (válido, tipo equivocado, cada límite, `NaN`, `inf`,
  `true`, presupuesto `0` y `8193`, `reasoning_effort: none`),
  `test_reserved_and_deferred_keys_are_rejected[<clave>]`, `test_override_grammar[<caso>]`
  (`a=b=c`, `code.top_k`, `top_k=1`, `;;`, `;` final, duplicada, `code.top_k=1e400`),
  `test_override_warnings_never_carry_values` (centinelas `SENTINEL-7Q`/`SENTINEL-8R` de REQ-006),
  `test_to_body_layers` (temperatura sustituida en su sitio, presupuesto sumado, clave reservada
  imposible), `test_to_body_without_thinking_allowed`.
- **Verificación**: pytest de los dos ficheros de test por el cerrojo; `uv run ruff check src tests`;
  `uv run ruff format --check src tests`.
- **Hecho**: todos verdes; 21 claves; ningún aviso con valor; control positivo hecho (mutante que
  mete el valor en el aviso → falla `test_override_warnings_never_carry_values` en el assert de
  centinela).
- **Delegación local**:
  - *Agente*: esqueleto del módulo y de los tests parametrizados con `local_boilerplate(spec=<tabla
    de REQ-004 + firmas del paso 1-6>, language="python", target=…)`, **siempre revisado** contra
    la tabla de la spec; `local_explain_code(path="src/local_delegate/test_windows.py",
    question="cómo carga, valida y cuenta lo que no entiende")` (pesa menos de 50 KB) para copiar el
    patrón; salida de pytest/ruff → `local_lint_summary`; diff → `local_commit_msg`. **No** para la
    tabla de rangos: se copia literal de `spec.md` REQ-004.
  - *Orquestador*: `local_summarize(path=<entrega>, focus="códigos de aviso definidos, desviaciones de la tabla")`.

#### T4 — Lector de la variable en `config.py`

- **Objetivo**: `LOCAL_DELEGATE_BACKEND_PARAMS` registrada y leída al llamar.
- **REQ**: REQ-008 (lectura, tope, registro).
- **Posee**: `src/local_delegate/config.py`, `tests/test_backend_params_env.py` (nuevo).
- **Pasos**:
  1. `backend_params_override() -> tuple[str | None, str | None, str | None]` con `_env` al llamar
     (patrón `output_language`, `config.py:448-462`): `(value, problem, raw)`, `problem =
     "override_too_long"` si pasa de 2048 caracteres (entonces `value=None`).
  2. Añadirla al bucle `for _reader in (...)` (`config.py:467-476`) para que entre en
     `ENVIRONMENT_VARIABLES` (`config.py:579`).
  3. No parsea la gramática: eso es `backend_params.parse_override` (T3). Si T3 aún no está
     mezclado, T4 solo depende de la firma.
- **Tests**: `test_variable_is_registered` (`"LOCAL_DELEGATE_BACKEND_PARAMS" in
  config.ENVIRONMENT_VARIABLES`), `test_read_at_call_time` (con `monkeypatch.setenv` sin recargar),
  `test_too_long_is_ignored_whole`. Y correr **sin cambios** `tests/test_environment_isolation.py`
  (su guarda de `:155-189`).
- **Verificación**: pytest de `tests/test_backend_params_env.py tests/test_environment_isolation.py`
  por el cerrojo; ruff.
- **Hecho**: verdes; `test_environment_isolation.py` sin tocar.
- **Delegación local**: *Agente*: `config.py` pesa poco más de 20 KB, pero hay que editar líneas
  exactas: leer la franja `448-476` con `Read offset/limit`, no resumir; pytest → `local_lint_summary`;
  diff → `local_commit_msg(path=…, style="conventional")`. *Orquestador*: `local_summarize(path=<entrega>,
  focus="registro en ENVIRONMENT_VARIABLES, tope de 2048 y guarda de aislamiento sin cambios")`.

#### T5 — Textos de aviso en `common.json`

- **Objetivo**: un texto es/en por cada código de aviso de T3, sin valores.
- **REQ**: REQ-017 (avisos), REQ-006/007/008 (textos sin valor).
- **Posee**: `src/local_delegate/resources/i18n/es/common.json`,
  `src/local_delegate/resources/i18n/en/common.json`, `tests/test_backend_params_i18n.py` (nuevo).
- **Pasos**:
  1. Claves `backend_params.warning.<code>` con marcadores `{role}` y `{key}` solamente.
  2. Respetar LF de los dos JSON (`git ls-files --eol`: `i/lf`) y el orden/estilo del fichero.
- **Tests**: `test_every_warning_code_has_text_in_es_and_en`, `test_warning_texts_have_no_value_placeholder`
  (ningún marcador fuera de `{role}`/`{key}`), `test_rendered_warnings_hide_sentinels[es|en]`
  (recorre **todos** los códigos con `warning_text()` a partir de entradas que llevan
  `SENTINEL-7Q`/`SENTINEL-8R`, con `LOCAL_DELEGATE_LANG` fijado por `reload_config`; ninguno
  aparece en el texto), y que `tests/test_i18n_parity.py` siga verde. Si T3 aún no está mezclado,
  este test se escribe contra la firma de `warning_text` y se activa al mezclar A1 (T3 y T5 van en
  el mismo lote).
- **Verificación**: pytest de `tests/test_backend_params_i18n.py tests/test_i18n_parity.py
  tests/test_no_uncatalogued_text.py` por el cerrojo.
- **Hecho**: paridad verde; todos los códigos con texto.
- **Delegación local**: *Agente*: `local_translate` para el borrador en inglés de cada texto
  español (revisado: el inglés va al catálogo); pytest → `local_lint_summary`; diff →
  `local_commit_msg`. *Orquestador*: lee la entrega entera sin delegar, porque es corta (una lista
  de claves y el resultado de la paridad); resumirla costaría más que leerla.

**Cierre de A1**: PR con T3+T4+T5; suite completa (§4.1); `gh pr checks`.

---

### Lote A2 — Fichero y resolución

#### T6 — Fichero, escritura atómica, caché, `effective` e informe

- **Objetivo**: la parte con E/S del módulo.
- **REQ**: REQ-001, REQ-002, REQ-009 (caché), REQ-011 (reglas de `set`/`unset`), REQ-023 (aviso de
  `set`), REQ-008 (precedencia).
- **Posee**: `src/local_delegate/backend_params.py` (segunda mitad; después de mezclar A1),
  `tests/test_backend_params_file.py` (nuevo).
- **Pasos**:
  1. `path(log_dir=None) -> Path` = `config.LOG_DIR / "backend-params.json"`.
  2. `load(log_dir=None) -> LoadResult(roles, warnings)`: nunca lanza; ausente/vacío/`{"version":1,"roles":{}}`
     = sin parámetros; JSON roto, `version != 1` o > 64 KB → ignorado entero con aviso; rol
     desconocido fuera con aviso; clave inválida/reservada/fuera de rango fuera con aviso, el resto
     del rol queda. Patrón: `test_windows.py:243` (`load`).
  3. `write(mutator)`: `FileLock` + `mkstemp` en el mismo directorio + `os.replace`; patrón
     `test_windows.py:268-322`. Si `os.replace` falla, el original queda y el temporal se borra.
  4. `set_value(role, key, text)`, `unset(role, key)`, `reset(role=None)`: validan **antes** de
     escribir (REQ-003/011): `enable_thinking on` sin presupuesto efectivo → error; `unset`/`reset`
     del presupuesto con `enable_thinking` encendido en el fichero → error. Devuelven
     `(ok, code, warnings)`; nunca el valor en el error.
  5. `effective(role) -> Effective(values, source, warnings)`: fusión clave a clave variable >
     fichero (`source[key] = "env"` solo para las de la variable); `enable_thinking=true` sin
     presupuesto efectivo → se quita con aviso `thinking_without_budget`. Caché por
     `(st_mtime_ns, st_size, st_ino)` del fichero + valor crudo de la variable (patrón:
     `topology.py:541`, clave `(path, st.st_mtime_ns, st.st_size)`, a la que se añade `st_ino`).
  6. `context_warnings(role) -> list[Warning]`: si `enable_thinking` encendido, compara
     `ceil(max_chars_for_role(role) / CHARS_PER_TOKEN) + CHUNK_MAX_TOKENS + presupuesto` con
     `model_context_size(modelo del rol)` (T7); `context_overflow` si no cabe y `context_estimated`
     si el contexto es el estimado. `vision` excluido. (`config.py:327-345`, `:488`, `:513`).
     Nota: la fórmula de `set` es la de REQ-023 último punto (MAX_CHARS en tokens + CHUNK_MAX_TOKENS
     + presupuesto), no la de llamada a llamada.
  7. `report() -> list[RoleReport]`: lo que pintan `show`, `doctor` y `local_status` (rol, clave,
     valor, origen, avisos). Solo datos; el texto lo arma cada superficie.
- **Tests** (`tests/test_backend_params_file.py`): `test_load_tolerates[absent|empty|broken|version2|too_large|unknown_role]`
  (código de problema esperado, nunca lanza), `test_failed_replace_keeps_original_and_no_temp`,
  `test_concurrent_sets_keep_both_keys` (dos hilos con `set`; JSON válido con las dos claves),
  `test_env_wins_key_by_key`, `test_file_change_seen_without_restart`,
  `test_same_size_rewrite_is_seen` (`top_k 20` → `30`), `test_set_rejects_thinking_without_budget`,
  `test_set_budget_then_thinking_ok`, `test_unset_budget_rejected_while_thinking_on`,
  `test_reset_budget_rejected_while_thinking_on[role|all]` (`reset code` y `reset` global),
  `test_thinking_without_budget_from_file_and_env_is_dropped`, `test_file_and_env_drop_only_bad_key`
  (los dos casos de REQ-006 y REQ-007, sin centinelas en avisos ni en `report()`),
  `test_set_context_warning_writes_anyway` (con un `model_context_size` falso a 8192).
- **Verificación**: pytest de los tests del módulo por el cerrojo; ruff.
- **Hecho**: verdes; el test concurrente pasa 5 veces seguidas (`--count` no existe: bucle de 5 en
  Bash con el cerrojo); control positivo: mutante que usa `st_mtime` en vez de `st_mtime_ns` y
  quita `st_size` → falla `test_same_size_rewrite_is_seen` en el assert del valor 30.
- **Delegación local**: *Agente*: `local_explain_code(path="src/local_delegate/test_windows.py",
  question="cómo hace la escritura atómica bajo FileLock y qué limpia si falla")`; esqueleto de
  tests con `local_boilerplate` (revisado); pytest → `local_lint_summary`; diff →
  `local_commit_msg`. *Orquestador*: `local_summarize(path=<entrega>, focus="API pública final del módulo y desviaciones")`.

#### T7 — `model_context_size(model)`

- **Objetivo**: el `ctx_size` del modelo destino, con estimado de 8192.
- **REQ**: REQ-023 (contexto).
- **Posee**: `src/local_delegate/llamaswap_config.py`, `tests/test_model_context_size.py` (nuevo).
- **Pasos**:
  1. `model_context_size(model) -> tuple[int, bool]` (`(n_ctx, is_estimate)`). Ruta:
     `config.llamaswap_config_path()` (`config.py:406`). Lee con `load_config` (`:487`) y
     `_parse_cmd_flags` (`:240-247`) el `cmd` del modelo; acepta `--ctx-size N` y `-c N`.
  2. Sin PyYAML (`_require_yaml`, `:51`), sin config, sin el modelo o con un flag no numérico →
     `(8192, True)`. Nunca lanza.
  3. Caché por `(ruta, st_mtime_ns, st_size, st_ino)` (patrón: `topology.py:541`).
  4. `ESTIMATED_CONTEXT = 8192` como constante con nombre.
- **Tests**: `test_ctx_size_long_flag`, `test_ctx_size_short_flag`, `test_ctx_size_missing_flag_is_estimate`,
  `test_ctx_size_missing_config_is_estimate`, `test_ctx_size_without_yaml_is_estimate`
  (parchear `_require_yaml` para que lance), `test_ctx_size_cache_sees_rewrite`.
- **Verificación**: pytest del fichero por el cerrojo; ruff.
- **Hecho**: verdes; nunca lanza.
- **Delegación local**: *Agente*: `llamaswap_config.py` pesa unos 20 KB:
  `local_explain_code(path=…, question="qué devuelve _parse_cmd_flags y cómo se lee el cmd de un modelo con load_config")`;
  pytest → `local_lint_summary`; diff → `local_commit_msg`. *Orquestador*: lee la entrega sin
  delegar, porque es corta (una función y seis tests).

T7 puede ir en paralelo con T6 (ficheros distintos); T6 usa `model_context_size` por su firma.

---

### Lote B — CLI y `doctor`

#### T8 — Subcomando `backend-params`

- **Objetivo**: `show [--json]`, `set`, `unset`, `reset [<role>]`.
- **REQ**: REQ-003, REQ-011 (rechazos de `set`), REQ-023 (aviso de `set`), REQ-005/007 (rechazo por
  `set`), REQ-017.
- **Posee**: `src/local_delegate/cli.py` (CRLF), `src/local_delegate/resources/i18n/{es,en}/cli.json`
  (LF), `tests/test_cli_backend_params.py` (nuevo).
- **Pasos**:
  1. `cmd_backend_params(args)` con el modelo de `cmd_test_window` (`cli.py:390`).
  2. `_add_backend_params_parser(sub)` junto a `_add_test_window_parser` (`cli.py:460-476`),
     registrado en `build_parser` (`cli.py:1208`, la llamada de `test-window` está en `:1389`).
  3. `show` imprime primero la ruta del fichero (`backend_params.path()`) y luego, por rol, clave, valor, origen y avisos (de `backend_params.report()` y
     `context_warnings`); `--json` con claves en inglés (`role`, `key`, `value`, `source`,
     `warnings[{code, key}]`). Sin parámetros, «sin parámetros» del catálogo.
  4. `set`: error → código ≠ 0, motivo sin valor, fichero intacto (bytes y `mtime`). Avisos de
     contexto → código 0 y fichero escrito.
  5. Textos y ayuda de `--help` en `cli.json` (`cli.backend_params.*`, `cli.help.backend_params.*`).
     El armazón de argparse ya se traduce solo.
- **Tests**: `test_show_empty`, `test_show_json_shape`, `test_set_valid_writes`,
  `test_set_invalid_leaves_file_untouched[<caso>]` (rol, clave, reservada, tipo, rango; compara
  bytes y `st_mtime_ns`), `test_set_thinking_without_budget_exit_nonzero`,
  `test_set_context_warning_exit_zero`, `test_unset`, `test_reset_role`, `test_reset_all`,
  `test_messages_never_echo_value` (centinela en el valor de un `set` inválido, en es y en),
  `test_show_hides_sentinels[file|env]` (fichero con `{"code": {"top_k": 20, "foo":
  "SENTINEL-7Q"}}` y variable `code.foo=SENTINEL-7Q;code.top_k=SENTINEL-8R;code.min_p=0.1`; ni
  en el texto ni en `--json`), `test_show_prints_file_path` (la ruta del fichero, para la
  comprobación de `LOG_DIR` del §4.4).
- **Verificación**: pytest de `tests/test_cli_backend_params.py tests/test_cli_english.py
  tests/test_i18n_parity.py tests/test_no_uncatalogued_text.py` por el cerrojo; ruff; a mano,
  `uv run local-delegate backend-params --help` con `LOCAL_DELEGATE_LANG=es` y `=en`.
- **Hecho**: verdes; `--help` correcto en los dos idiomas; `cli.py` sigue en CRLF.
- **Delegación local**: *Agente*: `cli.py` pesa ~60 KB (por encima de la regla 1b): **no** resumirlo;
  `grep -n` y leer las franjas `390-480` y `1208-1395`. Borrador inglés de los textos con
  `local_translate`; pytest → `local_lint_summary`; diff → `local_commit_msg`. *Orquestador*:
  `local_summarize` de la entrega con `focus="salida de show, códigos de salida y desviaciones"`.

#### T9 — `backend_params_lines()` en `doctor`

- **Objetivo**: líneas de cabecera de `doctor`, sin check nuevo.
- **REQ**: REQ-016 (`doctor`), REQ-023 (aviso de estimado y de contexto en `doctor`), REQ-017.
- **Posee**: `src/local_delegate/doctor.py`, `src/local_delegate/resources/i18n/{es,en}/doctor.json`,
  `tests/test_doctor_backend_params.py` (nuevo).
- **Pasos**:
  1. `backend_params_lines()` con el patrón de `language_lines()` (`doctor.py:48-66`), invocada
     donde se pintan las de idioma (`doctor.py:120`).
  2. Lee el fichero; si `LOCAL_DELEGATE_BACKEND_PARAMS` está en **esta** shell, lo dice y advierte
     que puede no ser la del daemon.
  3. Repite los avisos de contexto (`context_overflow`, `context_estimated`).
  4. Sin parámetros, ninguna línea.
- **Tests**: `test_doctor_lines_from_file`, `test_doctor_lines_with_env_warns_about_daemon`,
  `test_doctor_no_lines_without_params` (salida idéntica a la de hoy: comparar contra
  `doctor` sin el fichero), `test_doctor_context_estimated_warning`,
  `test_doctor_hides_sentinels[file|env]` (los centinelas de REQ-006, por fichero y por variable
  en la shell de `doctor`). Y sin cambios:
  `tests/test_checks.py:93` (25 checks) y `tests/test_wiki.py:219,241`.
- **Verificación**: pytest de `tests/test_doctor_backend_params.py tests/test_doctor.py
  tests/test_checks.py tests/test_wiki.py` por el cerrojo; ruff.
- **Hecho**: verdes; `len(checks.CHECKS) == 25`.
- **Delegación local**: *Agente*: `local_explain_code(path="src/local_delegate/doctor.py",
  question="cómo pinta la cabecera language_lines y dónde")` (fichero pequeño); pytest →
  `local_lint_summary`; diff → `local_commit_msg`. *Orquestador*: lee la entrega sin delegar,
  porque es corta (una función y cinco o seis tests).

T8 y T9 en paralelo (ficheros distintos).

---

### Lote C1 — Fusión en el embudo

#### T10 — `_RoleParams`, capas y aplicación

- **Objetivo**: cada llamada real lleva los parámetros del rol de origen, fusionados por capas; sin
  parámetros, el cuerpo de hoy.
- **REQ**: REQ-009 (resolución por operación), REQ-010, REQ-011 (aplicación), REQ-012, REQ-013,
  REQ-022 (completa), REQ-014 (sigue verde).
- **Posee**: `src/local_delegate/server.py` (CRLF), `tests/test_backend_params_server.py` (nuevo),
  `tests/test_request_body_compat.py` (ampliación).
- **Pasos**:
  1. Clase `_RoleParams` cerca de `_CurrentModel` (`server.py:2365`): `role`, `values`, `source`,
     `budget`, `thinking`, y banderas para C2 (`probed`, `rejected`, `reasoning_skipped`) más
     `threading.Lock`. Fábrica `_role_params_for(role, explicit)`: `None` si `explicit` o si no hay
     claves (así el camino sin parámetros no cambia nada).
  2. Resolver **una vez por operación**: en `_chat` (`server.py:2503`, antes de `_run_chat` en
     `:2546`), en `_chat_chunked` (`:2994`) y en `_chat_map_reduce` (`:3255`) al crear
     `_CurrentModel`. `_CurrentModel` guarda el objeto aparte del `role` (que se sigue anulando en
     `:2427` tras un salto) y lo pasa en `call` (`:2406`).
  3. `_run_chat` (`:2306`) gana el kw `role_params: _RoleParams | None = None` y lo pasa a
     `_with_fallback` (`:2146`) → `_attempt` (`:2044`) → `_call_model` (`:2019`).
  4. En `_call_model`, antes de `_post_chat` (`:2028`): `request_body = {"model": model,
     **payload}` como hoy; si hay `role_params`, aplica `to_body`: sustituye `temperature` y
     `max_tokens` en su sitio y añade al final las claves del rol. El `payload` compartido entre
     intentos **no se muta** (se copia).
  5. Temperatura: la del rol pisa la de la tool en todas las tools del rol (REQ-010); sin
     configurar, ninguna diferencia.
  6. `local_delegate` (`server.py:4621`, rol en `:4684,4694`): con `model=` explícito,
     `explicit=True` ya llega (`:2387`): `_role_params_for` devuelve `None`. Sin modelo explícito,
     rol `mechanical`.
  7. Visión: `local_describe_image` (`server.py:5108`) entra por `_chat` con rol `vision`: mismos
     pasos, `user` es lista.
  8. Ampliar `tests/test_request_body_compat.py`: repetir todos los caminos con `{"version": 1,
     "roles": {}}` y con un rol vacío (`{"code": {}}`).
- **Tests** (`tests/test_backend_params_server.py`, backend falso que captura cuerpos y cuenta
  POST): `test_role_temperature_overrides_tool[<tool>]` (sin configurar = hoy; con
  `mechanical.temperature=0.5`: `local_classify`, `local_extract` corta, `local_summarize` corta
  llevan 0,5; `local_boilerplate` no cambia), `test_code_temperature_0_7`,
  `test_contract_keys_always_from_product` (`model`, `messages`, `stream`, `response_format`),
  `test_thinking_on_classify_sums_budget` (`max_tokens == 16 + 512`, `reasoning_budget_tokens:
  512`, `chat_template_kwargs == {"enable_thinking": True}`),
  `test_thinking_off_sends_false_and_keeps_max_tokens`, `test_every_chunk_sums_budget`,
  `test_params_survive_fallback_and_later_chunks` (primer modelo falla; respaldo y trozos
  siguientes con los mismos parámetros), `test_explicit_model_carries_no_params` (cuerpo igual a la
  fixture de L0) y `test_local_delegate_without_model_uses_mechanical` (`top_k: 20`),
  `test_file_change_applies_next_operation` (REQ-009: dos operaciones con un `set` entre medias),
  `test_thinking_without_budget_body_has_no_template_kwargs[file|env]` (REQ-011: el cuerpo no
  lleva `chat_template_kwargs` y hay aviso),
  `test_reserved_key_never_reaches_body[<clave>]` por fichero y por variable (REQ-005),
  `test_bad_keys_dropped_rest_applied` (REQ-006/007 con centinelas: ni en el cuerpo ni en el log).
- **Verificación**: pytest de `tests/test_backend_params_server.py tests/test_request_body_compat.py
  tests/test_tool_signatures.py tests/test_fallback.py tests/test_chunking.py tests/test_core.py`
  por el cerrojo; después la suite completa (§4.1); ruff.
- **Hecho**: todo verde; REQ-022 verde sin fichero, con roles vacíos y con un rol vacío. Controles
  positivos (anotar qué assert dispara):
  - mutante «añadir `"top_k": 0` siempre en `_call_model`» → falla `test_body_matches_main` en el
    assert de igualdad del cuerpo (no un mutante que reordena claves con un rol vacío: con el rol
    vacío no se añade nada y no discriminaría);
  - mutante que resuelve los parámetros con `self.role` (que se anula tras el salto) en vez del
    objeto guardado → falla `test_params_survive_fallback_and_later_chunks`.
- **Delegación local**:
  - *Agente*: **nada de `local_explain_code`/`local_summarize` sobre `server.py`** (250 KB, ~9 min y
    22 trozos; regla 1b): localizar con `grep -n` (`_run_chat`, `_CurrentModel`, `_call_model`,
    `_attempt`, `_with_fallback`, `_chat_chunked`, `_chat_map_reduce`) y leer franjas con `Read
    offset/limit`. Esqueleto del backend falso y de los tests con `local_boilerplate` (revisado);
    pytest → `local_lint_summary(path=…)`; diff → `local_commit_msg(path=…)`.
  - *Orquestador*: `local_summarize(path=<entrega>, focus="dónde se fusiona, qué assert disparó cada mutante, desviaciones de REQ-012")`.

---

### Lote C2 — Rechazo y contexto

#### T11 — Rechazo por el backend (400), una vez por operación

- **Objetivo**: un 400 por los parámetros no rompe la tool ni se repite en cada trozo.
- **REQ**: REQ-015.
- **Posee**: `src/local_delegate/server.py`, `tests/test_backend_params_rejection.py` (nuevo).
- **Pasos**:
  1. En `_call_model` (`server.py:2019-2040`), si hay `role_params` con claves aplicadas, el
     resultado es `http_400` y `not role_params.probed`: marcar `probed` (bajo el lock); repetir
     la llamada con la base de la tool (sin claves del rol, `temperature` y `max_tokens` de la
     tool, **conservando** `response_format`).
     - Si funciona: `rejected = True`; el resultado es ese; `json_schema_status` = `"used"` si
       había esquema.
     - Si vuelve a dar 400: no marcar nada; seguir el flujo de hoy (`:2032-2040`, reintento sin
       esquema) **con** los parámetros.
  2. Este reintento va **antes** del de `JSON_SCHEMA=auto`.
  3. Con `rejected`, toda llamada posterior de la operación (trozos, map/reduce, reducción,
     respaldo) va directamente sin parámetros y con el `max_tokens` de la tool.
  4. El POST extra del rechazo va **dentro del mismo `Attempt`**, como hoy el reintento sin esquema
     (dos POST en un `Attempt`, `server.py:2032-2038` y `:2052-2053`): `chunks` y `attempts` no
     cambian de significado. `reasoning_chars` de los dos POST se suma en ese `Attempt` (T13, paso
     3). El recuento de POST de REQ-015 se mide **en el backend falso**, no en `attempts`.
- **Tests** (backend falso que da 400 solo si el cuerpo lleva `top_k`):
  `test_extract_schema_rejected_params_then_ok` (resultado correcto, `json_schema` de éxito, el
  objeto marca `rejected`; los campos del log los prueba T13), `test_three_chunks_make_four_posts`,
  `test_retry_without_params_uses_tool_values`, `test_400_with_and_without_params_does_not_mark`
  (POST = hoy + 1; el reintento sin esquema lleva los parámetros), `test_no_params_400_still_fallback`
  (control), `test_rejection_in_tool_without_schema`.
- **Verificación**: pytest de `tests/test_backend_params_rejection.py tests/test_backend_params_server.py
  tests/test_request_body_compat.py tests/test_fallback.py` por el cerrojo; ruff.
- **Hecho**: verdes; recuento exacto de POST; control positivo: mutante que no marca `probed` →
  falla `test_three_chunks_make_four_posts` (6 ≠ 4).
- **Delegación local**: igual que T10 (sin resúmenes de `server.py`; franjas con `grep`);
  pytest → `local_lint_summary`. *Orquestador*: `local_summarize` de la entrega con
  `focus="recuento de POST y casos de doble 400"`.

#### T12 — Razonamiento que no cabe en el contexto

- **Objetivo**: llamada a llamada, apagar el razonamiento si no cabe.
- **REQ**: REQ-023 (comprobación por llamada).
- **Posee**: `src/local_delegate/server.py` (después de T11, en serie), `tests/test_backend_params_context.py` (nuevo).
- **Pasos**:
  1. Constante `REASONING_CONTEXT_MARGIN = 2` (en `backend_params.py` o `config.py`: la sesión
     elige y lo anota; si `backend_params.py`, la edición la hace esta tarea con permiso explícito
     de A2 ya mezclado).
  2. En `_call_model`, con `thinking` encendido y rol ≠ `vision`:
     `estimado = ceil((len(system) + len(user)) * REASONING_CONTEXT_MARGIN / CHARS_PER_TOKEN)`;
     si `estimado + max_tokens_tool + budget > model_context_size(model)[0]` → esa llamada va
     con `to_body(..., thinking_allowed=False)` y `role_params.reasoning_skipped = "context"`.
     `model` es el destino real (incluye respaldo).
  3. No recorta la entrada ni toca `MAX_CHARS`.
- **Tests** (config de llama-swap de prueba con `ctx_size 8192`, `LLAMASWAP_CONFIG` por
  `reload_config` o `monkeypatch`): `test_long_input_skips_reasoning` (20 000 caracteres; cada
  cuerpo sin razonamiento; entrada sin recortar), `test_short_input_keeps_reasoning` (control),
  `test_boundary_exact_fits_one_more_char_skips` (entrada calculada con la fórmula),
  `test_dense_input_uses_margin` (cabe a 4, no a 2), `test_vision_never_skips`,
  `test_unknown_context_uses_8192`.
- **Verificación**: pytest de `tests/test_backend_params_context.py` + los de T10/T11 por el
  cerrojo; ruff; suite completa al cerrar el lote.
- **Hecho**: verdes; control positivo: mutante con margen 1 (o sin `system`) → falla
  `test_dense_input_uses_margin`.
- **Delegación local**: como T10/T11. *Orquestador*: `local_summarize` de la entrega con
  `focus="fórmula aplicada y caso límite"`.

---

### Lote D — Log y `local_status`

#### T13 — `reasoning_chars` y campos del log

- **Objetivo**: el evento dice qué parámetros llevó, si razonó, si se rechazaron y si se saltó el
  razonamiento.
- **REQ**: REQ-018, REQ-006 (centinelas en el log), REQ-015/023 (marcas en el evento).
- **Posee**: `src/local_delegate/server.py`, `tests/test_backend_params_log.py` (nuevo).
- **Pasos**:
  1. `ChatResult` (`server.py:1101`) y `Attempt` (`:1120`) ganan `reasoning_chars: int | None =
     None` (en `Attempt`, `compare=False` como `timings`).
  2. `_post_chat` (`:1330`, retorno en `:1354-1363`): `len(message.reasoning_content or "")` +
     caracteres que quita `_strip_think` (`:1468-1476`) del `content`. Igual en `_body_failure`
     (`:1206`) cuando hay `data`. El texto nunca se guarda.
  3. `_call_model` suma los `reasoning_chars` de sus POST internos (T11) en el `Attempt`.
  4. `_log_event` (`:726`) gana kw opcionales y escribe, omitiéndolos si no aplican:
     `backend_params` (`{"role","values","source"}`; `source` solo con claves `env`),
     `reasoning_chars` (suma sobre `attempts`, fallidos incluidos; solo si > 0),
     `backend_params_rejected: true`, `reasoning_skipped: "context"`. Llamadas en `:2593`, `:3059`,
     `:3474`.
  5. `local_delegate` con modelo explícito: el evento no lleva `backend_params`.
- **Tests** (modelo: `tests/test_lossless_summary_output.py:73-98`):
  `test_fields_omitted_when_not_applicable` (y el conjunto de claves igual al de la fixture de L0),
  `test_reasoning_chars_sums_failed_attempt`, `test_think_tags_count_without_reasoning_content`,
  `test_reasoning_text_never_logged` (fragmentos del falso ni en `reasoning_content` ni en `<think>`
  aparecen en `usage-*.jsonl`), `test_rejected_event_keeps_tried_values`,
  `test_reasoning_skipped_in_event`, `test_sentinels_never_in_log`,
  `test_explicit_model_event_has_no_backend_params` (REQ-013, con `mechanical.top_k=20`
  configurado).
- **Verificación**: pytest de los ficheros nuevos + `tests/test_lossless_summary_output.py
  tests/test_request_body_compat.py` por el cerrojo; ruff.
- **Hecho**: verdes; control positivo: mutante que guarda `reasoning_content` en el evento → falla
  `test_reasoning_text_never_logged`.
- **Delegación local**: sin resúmenes de `server.py`; `local_explain_code(path="tests/test_lossless_summary_output.py", question="cómo captura el evento del log")`
  (fichero pequeño); un `usage-*.jsonl` grande de una prueba → `local_extract(path=…,
  fields=["backend_params","reasoning_chars","backend_params_rejected","reasoning_skipped"])`;
  pytest → `local_lint_summary`; diff → `local_commit_msg`. *Orquestador*:
  `local_summarize(path=<entrega>, focus="campos del evento, cuándo se omiten y assert del mutante")`.

#### T14 — Líneas de `local_status`

- **Objetivo**: `local_status` muestra los parámetros efectivos del daemon.
- **REQ**: REQ-016 (`local_status`), REQ-023 (avisos de contexto), REQ-017.
- **Posee**: `src/local_delegate/server.py` (después de T13), `src/local_delegate/resources/i18n/{es,en}/mcp.json`,
  `tests/test_backend_params_status.py` (nuevo).
- **Pasos**:
  1. Debajo de los roles (`server.py:5526-5534`), una línea por rol con parámetros: claves,
     valores, origen (`file`/`env`) y avisos (incluidos `context_overflow` y `context_estimated`).
     Función `_describe_backend_params()` con el patrón de `_describe_language` (`:5638`).
  2. Sin parámetros, ninguna línea (salida idéntica a la de hoy).
- **Tests**: `test_status_with_file`, `test_status_with_env_shows_source`,
  `test_status_without_params_unchanged`, `test_status_context_estimated`,
  `test_status_hides_sentinels`.
- **Verificación**: pytest de esos tests + `tests/test_i18n_parity.py
  tests/test_no_uncatalogued_text.py` por el cerrojo; suite completa al cerrar D; ruff.
- **Hecho**: verdes.
- **Delegación local**: *Agente*: franja `5496-5560` y `5638-5664` con `Read`; borrador inglés con
  `local_translate`; pytest → `local_lint_summary`; diff → `local_commit_msg`. *Orquestador*: lee
  la entrega sin delegar, porque es corta (una función de pintado y cinco tests).

---

### Lote E — Panel

#### T15 — Marcas y diálogo de detalle

- **Objetivo**: ver en la lista qué llamada llevó parámetros, si se rechazaron y si razonó; el
  detalle en un diálogo.
- **REQ**: REQ-019, REQ-017 (panel).
- **Posee**: `src/local_delegate/web/metrics.py` (CRLF), `src/local_delegate/resources/i18n/{es,en}/panel.json`,
  `tests/test_dashboard_states.py`, `tests/test_metrics.py`.
- **Pasos**:
  1. En `drawActivity` (`web/metrics.py:3095-3131`): `reasonchip` si `reasoning_chars > 0`;
     `paramschip` si hay `backend_params`, con variante rechazada (clase y `title` propios) si
     `backend_params_rejected`. Etiquetas cortas o iconos y `title` del catálogo
     (`panel.activity.*`). Nada más nuevo en la fila.
  2. Fila activable: `tabindex="0"`, Enter y clic; `aria-label` del catálogo.
  3. Diálogo de detalle con el patrón y los estilos de `infoDlg` (`:1776`, apertura `:3209-3223`,
     cierre al pulsar fuera `:3233`): un `<dialog>` hermano (p. ej. `id="eventDlg"`) con tabla
     clave → valor: rol, parámetros con origen, rechazado / `reasoning_skipped`,
     `reasoning_chars`, `steps`, respaldo. Sin filas vacías, sin prosa.
  4. Formato viejo: eventos sin campos nuevos se pintan como hoy (la fila sigue siendo activable,
     el diálogo solo enseña lo que hay).
  5. No tocar `/api/events` (`:517-541`) ni `acct` (`:2873-2910`). Todos los ids y clases en
     inglés.
  6. Validar el JS: `uv run python scripts/extract_dashboard_js.py dashboard.js && node --check
     dashboard.js` (lo hace el CI en `lint`).
- **Tests**: en `tests/test_dashboard_states.py` (junto a `:787-834`, con node):
  `test_activity_reasoning_chip` y su control sin razonamiento, `test_activity_params_chip`,
  `test_activity_params_rejected_chip`, `test_activity_old_event_unchanged`,
  `test_event_dialog_rows_without_empty`. `tests/test_metrics.py:1570` actualizado con las cadenas
  nuevas; `tests/test_dashboard_js.py:583` **sin cambios**.
- **Verificación**: pytest de `tests/test_dashboard_states.py tests/test_metrics.py
  tests/test_dashboard_js.py tests/test_i18n_parity.py` por el cerrojo; validación del JS; ruff.
- **Hecho**: verdes; `metrics.py` sigue en CRLF; control positivo: mutante que pinta `reasonchip`
  siempre → falla el control sin razonamiento.
- **Delegación local**: *Agente*: `metrics.py` pesa 185 KB: **no** resumirlo; `grep -n` de
  `drawActivity`, `infoDlg`, `openInfo`, `fbchip` y franjas con `Read`. `local_explain_code(path="tests/test_dashboard_states.py", question="cómo se prueba drawActivity con node")`
  (pesa 33 KB: por debajo de la regla 1b). Borrador inglés de los textos de `panel.json` con
  `local_translate` (revisado); validación del JS y pytest volcados a fichero →
  `local_lint_summary`; diff → `local_commit_msg`; una captura de prueba en local →
  `local_describe_image` como primera pasada. *Orquestador*: `local_summarize(path=<entrega>,
  focus="marcas y clases nuevas, filas del diálogo, ids en inglés y assert del mutante")`.

#### T16 — La fila abre el diálogo con Enter (Playwright)

- **Objetivo**: probar el cableado real en navegador.
- **REQ**: REQ-019 (teclado).
- **Posee**: `tests/test_dashboard_ui.py` (**CRLF**: comprobar con `git ls-files --eol` y
  conservarlo).
- **Pasos**: con el patrón del fichero (fixtures `new_page`, `browser_locale` de
  `tests/conftest.py:182-199`), servir un log con un evento con marcas, enfocar la fila con Tab y
  pulsar Enter: el diálogo se abre y tiene filas; Escape lo cierra.
- **Tests**: `test_event_row_opens_dialog_with_enter`.
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_dashboard_ui.py -q`
  (requiere `uv sync --group dev --group ui` y `uv run playwright install chromium`, por el
  cerrojo).
- **Hecho**: verde en local y en el job `lint` del CI.
- **Delegación local**: *Agente*: pytest volcado a fichero → `local_lint_summary`; diff →
  `local_commit_msg`. *Orquestador*: lee la entrega sin delegar, porque es la entrega de un solo
  test; lo que mira es que el test pasó en el job `lint` del CI (`gh pr checks`).

T15 y T16 van en serie (T16 necesita el DOM de T15) pero en el mismo lote.

---

### Lote F — Benchmark

#### T17 — Arreglo de `--reasoning-effort` y `--reasoning-budget`

- **Objetivo**: que el benchmark encienda el razonamiento igual que producción.
- **REQ**: REQ-020, REQ-017 (ayuda).
- **Posee**: `src/local_delegate/benchmark.py`, `tests/test_benchmark.py`,
  `src/local_delegate/resources/i18n/{es,en}/cli.json` (después de B).
- **Pasos**:
  1. `reasoning_kwargs(effort, budget)` (`benchmark.py:1004-1016`) pasa a devolver las claves del
     cuerpo: `off` → `{"chat_template_kwargs": {"enable_thinking": False}}`; otro nivel →
     `{"chat_template_kwargs": {"enable_thinking": True}, "reasoning_effort": <nivel>,
     "reasoning_budget_tokens": budget}`; `None` → nada. Ajustar `build_payload` (`:1031`) para
     fusionarlas en la raíz y sumar el presupuesto al `max_tokens` del caso.
  2. `--reasoning-budget N` (1–8192, validado con `backend_params.validate_value`) junto a
     `--reasoning-effort` (`:1417-1422`), ayuda en `cli.json`.
  2b. **Enum del esfuerzo (decisión del orquestador, P16)**: `REASONING_EFFORTS`
     (`benchmark.py:993`, hoy `off/low/medium/high`) pasa a ser `("off",) +` el enum del producto
     (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`), tomado de `backend_params` para que no
     haya dos copias. Vale para la opción y para el `reasoning_effort` de un caso o de un modelo;
     un valor fuera del enum es error de la corrida. Test: `test_effort_enum_matches_product`
     (el enum es exactamente `off` + el del producto) y `test_unknown_effort_in_case_fails`.
  3. Si el esfuerzo **efectivo** (`effective_reasoning`, `:1019-1028`: caso > modelo > opción) no
     es `off` y no hay presupuesto → la corrida termina con error antes de llamar al backend.
  4. Metadatos de la corrida (`:1288-1289`): `role_params_active: {role: [claves]}` con solo los
     nombres de `backend_params.effective`. El benchmark **no** los aplica.
- **Tests**: `tests/test_benchmark.py:336-343` actualizado (`off` y `high` con la forma nueva),
  `test_effort_without_budget_from_option_fails`, `test_case_effort_without_budget_fails`,
  `test_budget_is_added_to_max_tokens`, `test_run_metadata_lists_active_param_names` (sin valores).
- **Verificación**: pytest de `tests/test_benchmark.py tests/test_i18n_parity.py` por el cerrojo;
  ruff.
- **Hecho**: verdes; control positivo: mutante que no suma el presupuesto → falla
  `test_budget_is_added_to_max_tokens`.
- **Delegación local**: *Agente*: `benchmark.py` pesa 60 KB (por encima de 1b): franjas con
  `grep -n` (`reasoning_kwargs`, `effective_reasoning`, `build_payload`, `--reasoning-effort`);
  pytest → `local_lint_summary`; diff → `local_commit_msg`. *Orquestador*:
  `local_summarize(path=<entrega>, focus="forma nueva de reasoning_kwargs, enum aceptado y error sin presupuesto")`.

---

### Lote G — Documentación y prueba en vivo

#### T18 — Wiki, README y CHANGELOG (solo en español)

- **Objetivo**: los tres sitios de la regla de release, con los nueve puntos de REQ-021.
- **REQ**: REQ-021 (y REQ-020 punto 5, con el resultado de T19).
- **Posee**: `docs/wiki/Configuration.md` (LF), `docs/wiki/Savings-and-metrics.md` (LF),
  `README.md` (CRLF), `CHANGELOG.md` (LF), `tests/test_wiki.py` (LF).
- **Pasos**:
  1. `Configuration.md`: sección nueva (cerca de l. 221-225) con los puntos 1–9 de REQ-021,
     tabla de las 21 claves (copiada de la spec) y la de reservadas.
  2. `Savings-and-metrics.md:33`: campos del log de REQ-018.
  3. `README.md` (~l. 196-221): fila de `LOCAL_DELEGATE_BACKEND_PARAMS` y mención del subcomando.
  4. `CHANGELOG.md` `[Unreleased]` (l. 7): una entrada `Added` y una `Fixed` (benchmark).
  5. El punto 5 (`low`/`high`) se escribe con el resultado de T19; si T18 va antes, se deja
     marcado y se completa en el mismo lote.
- **Tests**: `tests/test_wiki.py::test_configuration_documents_backend_params` (nombra
  `backend-params` y `LOCAL_DELEGATE_BACKEND_PARAMS`).
- **Verificación**: pytest de `tests/test_wiki.py` por el cerrojo; `git ls-files --eol` de los
  cuatro ficheros sin cambio de fin de línea.
- **Hecho**: test verde; los nueve puntos presentes (checklist en la PR).
- **Delegación local**: *Agente*: `local_summarize(path="docs/wiki/Configuration.md", focus="estructura de secciones y dónde encaja una sección de parámetros del backend")`
  antes de editar (luego franja literal con `Read` para insertar); pytest de `test_wiki.py` volcado
  a fichero → `local_lint_summary`; diff → `local_commit_msg(path=…, style="conventional")`.
  **No** para la tabla de claves: se copia literal de la spec. *Orquestador*: revisar el diff
  contra los nueve puntos con `local_summarize(path=<diff volcado>, focus="los nueve puntos de REQ-021: cuáles están y cuáles faltan")`
  y comprobar a mano los que dude.

#### T19 — Prueba en vivo, benchmark corto y capturas

- **Objetivo**: evidencia real contra el daemon y el backend.
- **REQ**: REQ-009 (en vivo), REQ-011, REQ-016, REQ-018, REQ-019 (capturas), REQ-020 (en vivo),
  REQ-022 (en vivo).
- **Posee**: `.sdd/changes/backend-extra-params/evidence/` (nuevo), `.sdd/changes/backend-extra-params/verification.md`.
- **Pasos**: los de §4.4 y §4.5.
- **Tests**: no añade; produce evidencia.
- **Hecho**: todas las comprobaciones de §4.4 y §4.5 anotadas en `verification.md` con id de la
  ventana de prueba y rutas de las capturas; ventana cerrada; panel de `:9494` parado y su
  `LOG_DIR` temporal borrado; daemon con la versión instalada.
- **Delegación local**: ver §4.4 y §4.5.

---

## 3. Matriz REQ → tarea → test/evidencia

| REQ | Tarea(s) | Test / evidencia |
| --- | --- | --- |
| REQ-001 Fichero por rol | T6 | `test_backend_params_file.py::test_load_tolerates[*]` |
| REQ-002 Escritura atómica | T6 | `test_failed_replace_keeps_original_and_no_temp`, `test_concurrent_sets_keep_both_keys` |
| REQ-003 Subcomando | T8 | `test_cli_backend_params.py` (cada verbo, `show --json`, `set` inválido con bytes y `mtime`) |
| REQ-004 Lista cerrada | T3 | `test_catalog_has_exactly_21_keys`, `test_value_validation[*]` |
| REQ-005 Reservadas | T3, T6, T8, T10 | `test_reserved_and_deferred_keys_are_rejected`, `test_set_invalid_leaves_file_untouched[reserved]`, `test_reserved_key_never_reaches_body[*]` |
| REQ-006 Quitar sola la clave | T3, T6, T10, T13, T14, T8/T9 | `test_override_warnings_never_carry_values`, `test_file_and_env_drop_only_bad_key`, `test_bad_keys_dropped_rest_applied`, `test_sentinels_never_in_log`, `test_status_hides_sentinels`, `test_messages_never_echo_value`, `test_show_hides_sentinels[file\|env]`, `test_doctor_hides_sentinels[file\|env]` |
| REQ-007 Fuera de rango | T3, T6, T8 | `test_file_and_env_drop_only_bad_key` (top_p 1.5, top_k=x), `test_set_invalid_leaves_file_untouched` |
| REQ-008 Variable y precedencia | T3, T4, T6 | `test_override_grammar[*]`, `test_variable_is_registered`, `test_env_wins_key_by_key`, `test_environment_isolation.py` sin cambios |
| REQ-009 Sin reiniciar | T6, T10, T19 | `test_same_size_rewrite_is_seen`, `test_file_change_applies_next_operation`; en vivo (§4.4) |
| REQ-010 Temperatura | T10 | `test_role_temperature_overrides_tool[*]` |
| REQ-011 Razonamiento | T3, T6, T8, T10, T19 | `test_set_rejects_thinking_without_budget`, `test_thinking_without_budget_from_file_and_env_is_dropped`, `test_reset_budget_rejected_while_thinking_on[role\|all]`, `test_thinking_without_budget_body_has_no_template_kwargs[file\|env]`, `test_thinking_on_classify_sums_budget`, `test_every_chunk_sums_budget`; en vivo `reasoning_chars > 0` |
| REQ-012 Capas y respaldo | T3, T10 | `test_to_body_layers`, `test_params_survive_fallback_and_later_chunks`, `test_code_temperature_0_7`, `test_contract_keys_always_from_product` |
| REQ-013 Modelo explícito | T10, T13 | `test_explicit_model_carries_no_params`, `test_local_delegate_without_model_uses_mechanical`, `test_explicit_model_event_has_no_backend_params` |
| REQ-014 Sin argumentos nuevos | T2 (T3 cambia la lista) | `test_tool_parameters_match_snapshot`, `test_no_tool_parameter_is_a_backend_param` |
| REQ-015 Rechazo 400 | T11, T13 | `test_backend_params_rejection.py` (6 tests), `test_rejected_event_keeps_tried_values` |
| REQ-016 `local_status` y `doctor` | T9, T14, T19 | `test_doctor_backend_params.py`, `test_backend_params_status.py`, `test_checks.py:93` sin cambios; en vivo |
| REQ-017 i18n | T5, T8, T9, T14, T15, T17 | `test_i18n_parity.py`, `test_backend_params_i18n.py` (incluido `test_rendered_warnings_hide_sentinels[es\|en]`), `test_no_uncatalogued_text.py`, CI `test-lang-es` |
| REQ-018 Log | T13, T19 | `test_backend_params_log.py`; en vivo (evento con y sin parámetros) |
| REQ-019 Panel | T15, T16, T19 | `test_dashboard_states.py` (casos nuevos), `test_metrics.py:1570`, `test_dashboard_js.py:583` sin cambios, `test_event_row_opens_dialog_with_enter`; capturas claro/oscuro en `evidence/` |
| REQ-020 Benchmark | T17, T19, T18 | `test_benchmark.py` (forma nueva, errores sin presupuesto, metadatos, `test_effort_enum_matches_product`); corridas cortas `off`/`low`/`high` |
| REQ-021 Documentación | T18 | `test_configuration_documents_backend_params`; revisión del diff contra los 9 puntos |
| REQ-022 Compatibilidad | T1, T10, T13, T19 | `test_request_body_compat.py` (8 caminos × sin fichero / roles vacíos / rol vacío), mutante; en vivo tras `reset` |
| REQ-023 Contexto | T6, T7, T9, T12, T14 | `test_model_context_size.py`, `test_backend_params_context.py` (6 casos), `test_set_context_warning_writes_anyway`, `test_set_context_warning_exit_zero`, `test_doctor_context_estimated_warning`, `test_status_context_estimated` |

Sin huecos: los 23 REQ tienen tarea y test o evidencia.

---

## 4. Verificación

### 4.1 Suite completa

Al cerrar cada lote (no en cada tarea), desde la tool Bash:

```bash
cd D:/Projects/ld-wt-<lote>
bash ~/.claude/scripts/pesado.sh uv run pytest -q -n auto --dist loadgroup > "<scratchpad>/pytest-<lote>.txt" 2>&1; echo "exit=$?"
```

- `-n auto --dist loadgroup` es lo que usa el CI (`.github/workflows/ci.yml:161`). Si la máquina va
  cargada, `-n 2`.
- Resumen: `local_lint_summary(path="<scratchpad>/pytest-<lote>.txt")`. Si hay fallos, leer
  **solo** las franjas de los tests que fallan (`grep -n "FAILED\|Error" …`), no el fichero entero.
- **Delegación local**: *Agente*: lo anterior. *Orquestador*: no lee la salida de pytest; lee la
  entrega con `local_summarize(path=…, focus="fallos y su causa")`.

### 4.2 Lint y formato

```bash
uv run ruff check . > "<scratchpad>/ruff-<lote>.txt" 2>&1
uv run ruff format --check . >> "<scratchpad>/ruff-<lote>.txt" 2>&1
uv run python scripts/extract_dashboard_js.py "<scratchpad>/dashboard.js" && node --check "<scratchpad>/dashboard.js"   # solo lote E
```

- Ruff con `line-length = 100` (`pyproject.toml:128-155`). Si `ruff format` cambia algo, se
  aplica con `uv run ruff format <ficheros del lote>` (solo los del lote).
- **Delegación local**: *Agente*: `local_lint_summary(path="<scratchpad>/ruff-<lote>.txt")` si sale
  largo; si son 2–3 avisos, leerlos directamente. *Orquestador*: no delega nada aquí, porque no lee
  la salida de ruff: solo el veredicto (verde o no) que viene en la entrega.

### 4.3 CI `test-lang-es`

- En local, al menos al cerrar B, D y E (los lotes con textos):
  `LANG=es_ES.UTF-8 bash ~/.claude/scripts/pesado.sh uv run pytest -q -n auto --dist loadgroup > "<scratchpad>/pytest-es-<lote>.txt" 2>&1`
  (en Windows `LANG` puede no tener efecto; el que manda es el job `test-lang-es` del CI,
  `ci.yml:195-220`).
- En cada PR: `gh pr checks <n>` hasta que **todos** (jobs del CI, `ci-gate`, CodeQL, Socket,
  GitGuardian) estén en verde. `gh run list` no ve los que no son workflows.
- **Delegación local**: *Agente*: si un check falla, `gh run view <id> --log-failed > "<scratchpad>/ci-<n>.txt"`
  y `local_lint_summary(path=…)`. *Orquestador*: lee solo el veredicto de la entrega.

### 4.4 Prueba en vivo (T19)

Requiere todos los lotes mezclados en `main` (o en una rama de integración). Pasos:

1. Abrir la ventana: `local-delegate test-window start --label "backend-extra-params: verificación"`;
   **guardar el id**.
2. Instalar el código sin publicar para el daemon, desde la raíz del checkout con el código:
   `bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache ".[llamaswap]"`.
   **Reiniciar el daemon** con el mecanismo del propio producto, que comprueba el pid por
   `/api/daemon` (`update.restart_daemon`, `update.py:669`), usando el intérprete de la herramienta
   instalada (no publica nada ni toca PyPI):
   ```bash
   TOOL_PY="$(uv tool dir)/local-delegate-mcp/Scripts/python.exe"
   "$TOOL_PY" -c "from pathlib import Path; from local_delegate import update; raise SystemExit(update.restart_daemon(update.Options(home=Path.home())))"
   ```
   `local-delegate update` **no** sirve: reinstala desde PyPI y pisaría el código sin publicar.
   A mano, solo si lo anterior falla: `schtasks /End /TN LocalDelegateDaemon`, comprobar que el
   pid que daba `/api/daemon` ya no existe (si sigue vivo, terminarlo: `/End` no mata el proceso
   desacoplado, `update.py:696-704`) y `schtasks /Run /TN LocalDelegateDaemon` (nombre de la
   tarea en `update.py:47`).
   **Reiniciar el daemon tira el MCP de la sesión**: pedir al usuario `/mcp` y comprobar con
   `local_status` (versión nueva, pid distinto) antes de seguir o de lanzar agentes.
3. **Mismo `LOG_DIR` en la CLI y en el daemon**: la ruta que imprime `local-delegate
   backend-params show` (su primera línea, T8) debe estar en el mismo directorio que el log de
   uso que muestra `local_status`. Si no coinciden, parar y arreglar el entorno (p. ej. un
   `LOCAL_DELEGATE_LOG_DIR` distinto en el lanzador del daemon): si no, el `set` del paso 4 escribiría un
   fichero que el daemon no lee. Después, `local_status` sin parámetros: ninguna línea nueva
   (REQ-016).
4. Con el daemon arrancado: `local-delegate backend-params set code reasoning_budget_tokens 256` y
   `set code enable_thinking on` (REQ-009: sin `/mcp` ni reinicio).
5. `local_explain_code` sobre un fichero pequeño del repo: el evento del log trae `backend_params`
   del rol `code` y `reasoning_chars > 0` (REQ-011, REQ-018). Comprobar el evento con
   `local_extract(path=<usage-YYYYMM.jsonl>, fields=[...])` o con `tail -n 1 | python -m json.tool`.
6. `local_status`: línea del rol `code` con origen `file` (REQ-016).
7. `local-delegate backend-params reset`: la misma llamada da un evento **sin** `backend_params` ni
   `reasoning_chars` (REQ-022 en vivo).
8. Benchmark corto contra `gemma4-26b-a4b` (REQ-020): `off`, `low` y `high` con
   `--reasoning-budget 256`, un caso o dos (`local-delegate benchmark --help` para las opciones de
   filtro). `high` trae `reasoning_content` no vacío; `off`, no. Comparar `low` y `high`; si no hay
   diferencia medible, anotarlo para el punto 5 de REQ-021.
9. Cerrar la ventana: `local-delegate test-window stop <id>`.
10. Dejar instalada en el daemon la versión con el cambio (regla «entorno local con todo
    habilitado») y `backend-params.json` vacío salvo que el usuario diga otra cosa.

- **Delegación local**: *Agente*: salida del benchmark → `local_lint_summary(path=…)` o
  `local_extract(path=<resultado.json>, fields=["reasoning_effort","reasoning_chars","ok"])`; el
  `usage-*.jsonl` → `local_extract`. Es la prueba en vivo del propio producto: estas llamadas
  **también** quedan dentro de la ventana de prueba. *Orquestador*: `local_summarize(path="verification.md", focus="comprobaciones en vivo y su resultado")`.

### 4.5 Capturas del panel (T19)

1. **Las capturas no salen del panel del daemon** (`:9393`, que lee el `LOG_DIR` real), sino de
   un panel aparte contra un `LOG_DIR` temporal sembrado con eventos de ejemplo. Así no se publica
   actividad real y el evento rechazado no tiene que existir en el log de verdad.
   - **Sembrar**: un script en el scratchpad (no en el repo) escribe
     `<scratchpad>/panel-logdir/usage-<YYYYMM actual>.jsonl` con eventos de hoy, copiando la forma
     de los que genera `tests/test_dashboard_ui.py::_events` (`:61`) y añadiendo los campos
     nuevos. Cinco eventos como mínimo:
     - **viejo**: sin ningún campo nuevo;
     - **con parámetros**: `backend_params` con `role`, `values` (p. ej. `top_k`, `temperature`)
       y `source` con una clave `env`;
     - **razonó**: `backend_params` con `enable_thinking`/`reasoning_budget_tokens` y
       `reasoning_chars` > 0, con `steps` de map/reduce para que el diálogo los enseñe;
     - **omitido por contexto**: `backend_params` con razonamiento y `reasoning_skipped: "context"`;
     - **rechazado**: `backend_params` y `backend_params_rejected: true`, más un respaldo
       (`model_requested`, `fallback_reason`) para la fila de respaldo del diálogo.
   - **Servir** solo la app del panel con el código del worktree, en otro puerto (patrón de
     `scripts/dev/capture_dashboard.py:33-38`: `local-delegate serve` es singleton y no vale), en
     segundo plano y con tope de tiempo:
     ```bash
     LOCAL_DELEGATE_LOG_DIR="<scratchpad>/panel-logdir" LOCAL_DELEGATE_LANG=es        timeout 1800 uv run python -c "import uvicorn; from local_delegate.web import metrics; uvicorn.run(metrics.app, host='127.0.0.1', port=9494)"
     ```
     (`run_in_background` de la tool Bash; anotar el id para cerrarlo).
2. Playwright (MCP `playwright`) contra `http://127.0.0.1:9494/`: lista con `reasonchip`,
   `paramschip` normal y rechazado y una fila del formato viejo; y el diálogo de detalle abierto.
   En `prefers-color-scheme: light` y `dark` (`browser_emulate_media`).
3. Guardar en `.sdd/changes/backend-extra-params/evidence/panel-{lista,dialogo}-{claro,oscuro}.png`.
4. Criterios por captura: la marca se ve y no se solapa; el diálogo no tiene filas vacías; el
   contraste es legible en los dos temas.
5. Cerrar el navegador y **parar el panel de `:9494`** (`TaskStop` del proceso en segundo plano;
   comprobar con `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9494/` que ya no responde)
   y borrar `<scratchpad>/panel-logdir`.

- **Delegación local**: *Agente*: `local_describe_image(path=<captura>)` como primera pasada (¿se ven
  las marcas, hay solapes, filas vacías?); la **verificación final** la hace Claude mirando la
  captura con `Read`. *Orquestador*: mira él mismo las cuatro capturas antes de aprobar.

---

## 5. Reglas de ejecución para la sesión de implementación

Del brief (§«Reglas para todo agente») y de las trampas conocidas del repo:

1. **Primer paso de cada agente**: cargar las tools `local_*` (ver «Delegación local: reglas»).
2. **Worktrees en ruta corta**: `git worktree add D:/Projects/ld-wt-<lote> -b feat/backend-params-<lote> main`.
   En el scratchpad falla por ruta larga. Borrarlos al mezclar (`git worktree remove`).
3. **Comandos pesados por el cerrojo y desde la tool Bash**: `bash ~/.claude/scripts/pesado.sh
   <comando>`. El `bash` de PowerShell es WSL: no usarlo. Pytest, Playwright, `uv sync`,
   `uv tool install` y el benchmark, de uno en uno en toda la máquina. Salida larga a fichero.
4. **LF y CRLF por fichero**: antes de editar, `git ls-files --eol <fichero>`. Hoy: `server.py`,
   `cli.py`, `web/metrics.py` y `README.md` en **CRLF**; `config.py`, `doctor.py`,
   `benchmark.py`, `llamaswap_config.py`, `test_windows.py`, los JSON de i18n, `CHANGELOG.md` y
   `docs/wiki/*` en **LF**. **Los tests no son todos LF**: `tests/test_dashboard_ui.py` (el de T16),
   `test_clients.py`, `test_ctrl_c.py`, `test_questions.py`, `test_smoke.py` y `test_vendor.py`
   están en **CRLF**. Regla: respetar el EOL de cada fichero según `git ls-files --eol`, nunca
   suponerlo. Nada de `write_text` a ciegas; los ficheros nuevos en LF. Comprobar con `git ls-files --eol` y `git diff --stat` antes de cada commit (un fichero que
   cambia entero es un fin de línea roto). Nunca contar `\r` con `grep -c $'\r$'` en Git Bash.
5. **Commits firmados y sin coautoría de Claude**: regla del usuario, que **anula** la del harness.
   Ni `Co-Authored-By` ni `Claude-Session` en commits. Sin `--no-verify` ni `--no-gpg-sign`. El
   hook `ggshield` pre-push debe pasar. Sin firma, `main` queda `BLOCKED`.
6. **Antes de dar una PR por cerrada**: `gh pr checks <n>` (ve CodeQL, Socket y GitGuardian; `gh run
   list` no).
7. **Las alertas de CodeQL se arreglan**, no se descartan, y sus hilos se resuelven.
8. **La suite se aísla sola del entorno**: la variable nueva entra en `ENVIRONMENT_VARIABLES` (T4) y
   la borra `env_without_package_variables`; usar `reload_config`/`monkeypatch` y los lectores
   `_env*` de `config.py`, nunca `os.environ` a pelo en producción.
9. **Todo el código en inglés** (módulos, funciones, clases, campos JSON, ids del DOM, códigos de
   aviso, opciones); **los textos para personas, en el catálogo es/en**. La documentación, solo en
   español (decisión 11).
10. **Control positivo de cada test nuevo**: un mutante que lo haga fallar, mirando **qué assert**
    dispara y que el mutante de verdad muta (un mutante que no cambia nada no prueba nada).
    Anotarlo en la PR.
11. **Sin secretos ni valores rechazados** en avisos, logs, specs o memoria; centinelas en los
    tests.
12. **Sin dependencias nuevas** (fuera de alcance). Si hiciera falta una, parar y volver a la spec.
13. **No tocar `state.json` a mano** ni ficheros fuera de los que posee la tarea.
14. **Nada huérfano al acabar**: ningún shell, servidor, navegador, espera ni ventana de prueba
    abierta. Toda espera con tope (`timeout`). Cada entrega lo confirma.
15. **Entregas en español**, con: ficheros tocados, tests añadidos, assert del mutante, salida
    resumida de pytest/ruff, llamadas `local_*` hechas y confirmación de «nada en segundo plano».
16. Una release toca CHANGELOG, README y `docs/wiki/` (los tres los cubre T18); publicar no es
    parte de este plan (§7).

### Delegación local: reglas

- **Carga como primer paso**, del orquestador al empezar y de cada agente en su encargo:
  `ToolSearch("select:mcp__local-delegate__local_summarize,mcp__local-delegate__local_extract,mcp__local-delegate__local_lint_summary,mcp__local-delegate__local_boilerplate,mcp__local-delegate__local_commit_msg,mcp__local-delegate__local_explain_code")`
  (más `local_translate`, `local_describe_image` y `local_status` donde se usen). Los tipos de
  agente sin MCP (`personal-sdd-implementer`, `personal-sdd-*-reviewer`) no las tienen: usar
  `general-purpose` o un especialista que las incluya.
- **Recuento en cada entrega**: lista de llamadas `local_*` hechas; «0» exige motivo.
- **Espera**: hasta 10 minutos antes de abandonar una llamada lenta.
- **Si el MCP cae** o devuelve `[local-delegate error]`: hacerlo a mano y seguir. Tras reiniciar el
  daemon (T19), pedir `/mcp` y comprobar con `local_status` antes de lanzar agentes: un subagente
  lanzado con el MCP caído no lo recupera.
- **Dónde rinden**: salida de pytest/ruff/CI volcada a fichero → `local_lint_summary(path=…)`; diff
  del lote → `local_commit_msg(path=…, style="conventional")` (revisado y sin coautoría); entregas
  largas y `verification.md` → `local_summarize(path=…, focus=…)`; módulos pequeños ajenos
  (< ~50 KB) → `local_explain_code(path=…, question=…)`; esqueletos de tests o del módulo →
  `local_boilerplate(..., target=…)`, siempre revisados; campos de un JSON/JSONL grande →
  `local_extract(path=…, fields=[…])`; borrador inglés de textos del catálogo → `local_translate`;
  capturas → `local_describe_image` como primera pasada.
- **Dónde no**: cuando hay que citar o editar un `fichero:línea` exacto (el resumen no sirve para
  editar); sobre `server.py` (250 KB, ~9 min en 22 trozos), `web/metrics.py` (185 KB), `cli.py`
  (60 KB) o `benchmark.py` (60 KB) enteros: `grep -n` y franjas; la tabla de rangos de REQ-004 y
  las listas de reservadas, que se copian literal de la spec; la verificación final de las capturas.

---

## 6. Riesgos del plan y puntos de reapertura

| Riesgo | Señal | Qué hacer |
| --- | --- | --- |
| Las fixtures de L0 no se pueden generar en `f2dd267` (un camino necesita algo que no existe) | El script no reproduce un camino | Anotar el camino; si es crítico (respaldo, visión), volver a la spec (REQ-022). |
| El orden de claves de hoy no es estable entre caminos | Una fixture sale distinta en dos corridas | Investigar la causa antes de relajar el test; relajar el orden es **reabrir REQ-022**. |
| La CLI y el daemon no usan el mismo `LOG_DIR` (otro `LOCAL_DELEGATE_LOG_DIR` en el entorno del daemon) | El `set` del §4.4 no cambia la llamada siguiente | Comprobación previa del §4.4 (paso 3): la ruta que imprime `backend-params show` y el `log_dir` de `local_status` deben coincidir. Si no, arreglar el entorno, no el código: REQ-009 en vivo fallaría por el entorno. |
| El reinicio del daemon no reinicia: `schtasks /End` no mata el proceso desacoplado y `/Run` arranca una instancia que no puede escuchar (`update.py:696-704`) | `local_status` sigue dando la versión vieja o el mismo pid | Reiniciar con `update.restart_daemon`, que comprueba el pid por `/api/daemon` (§4.4 paso 2); a mano, solo con la comprobación del pid. |
| La prueba en vivo da `reasoning_chars = 0` con `enable_thinking` encendido | §4.4 paso 5 | Mirar si el modelo del rol `code` en el daemon tiene plantilla con `enable_thinking`. Dos iteraciones; si sigue, documentar el límite y volver a REQ-011/decisión 9. |
| `--reasoning-budget` en el benchmark choca con casos que ya traen `reasoning_effort` | Corridas antiguas dejan de funcionar | Es lo que pide REQ-020; anotarlo en el CHANGELOG. |
| Lote por encima de ~600 líneas | Diff grande | Partir en dos PR dentro del lote, sin cambiar dueños. |
| Hace falta una dependencia nueva | — | Fuera de alcance: parar y volver a la spec. |
| `test_checks.py:93` o `test_wiki.py:219,241` tienen que cambiar | Fallan | No se cambian: es que algo añadió un check. Revertir. |

Se vuelve a la spec (y a su gate) si cambia un REQ, un nombre de campo del log, el catálogo de
claves, la regla de fusión o el contrato de alguna tool.

---

## 7. Fuera del plan: release y versión

Propuesta, **no** parte de este plan (publicar es otra decisión del usuario):

- **Versión 0.37.0** (minor): funcionalidad nueva y aditiva (subcomando, variable, campos del log,
  panel) más un arreglo del benchmark; sin cambios de contrato de las tools (REQ-014, REQ-022).
- **Release** (regla de los tres sitios):
  - `CHANGELOG.md`: mover `[Unreleased]` a `[0.37.0]` con fecha; `Added` (parámetros por rol,
    `backend-params`, `LOCAL_DELEGATE_BACKEND_PARAMS`, campos del log, marcas del panel) y `Fixed`
    (`--reasoning-effort` del benchmark; nota de que ahora exige `--reasoning-budget`).
  - `README.md`: tabla de variables y mención del subcomando (ya en T18), revisar versión si
    aparece.
  - `docs/wiki/`: `Configuration.md` y `Savings-and-metrics.md` (T18); sincronizar con
    `scripts/sync_wiki.py` como en releases anteriores.
  - `scripts/release.py`/`bump_version.py` como en la 0.36.1.
- Después: instalar la 0.37.0 desde PyPI en esta PC, revisar el depscore de Socket del paquete
  frente a la 0.36.1 y avisar de que la Mac la actualiza el usuario.

---

## Cambios tras la revisión del plan

Fuente: «Revisión del plan» al final de [review.md](review.md) (P1–P16), aplicada el 2026-10-20.

| Hallazgo | Cómo quedó |
| --- | --- |
| P1. La capa del rol en `_call_model` chocaba con el texto de REQ-012 | REQ-012 enmendado en `spec.md` (capas 1 y 3 en `_run_chat`; capa 2, presupuesto, REQ-023 y detección de REQ-015 en `_call_model` sobre una copia), con su línea en «Cambios tras la revisión» de la spec, sin cambio de comportamiento. Quitados el condicional de §1 y la fila de §6. |
| P2. Centinelas sin probar en `show` y `doctor` | T8 gana `test_show_hides_sentinels[file\|env]` (texto y `--json`); T9, `test_doctor_hides_sentinels[file\|env]`. |
| P3. Avisos renderizados en es/en sin centinelas | T5 gana `test_rendered_warnings_hide_sentinels[es\|en]` sobre todos los códigos, con el idioma fijado por `reload_config`. |
| P4. REQ-011 en el cuerpo y en el `reset` | T10 gana `test_thinking_without_budget_body_has_no_template_kwargs[file\|env]`; T6, `test_reset_budget_rejected_while_thinking_on[role\|all]`. |
| P5. Evento de `local_delegate` explícito | T13 gana `test_explicit_model_event_has_no_backend_params`. |
| P6. Reinicio del daemon y `LOG_DIR` | §4.4 paso 2 reinicia con `update.restart_daemon` (pid comprobado por `/api/daemon`) desde el intérprete de la herramienta instalada, con la alternativa a mano `schtasks /End` + comprobación del pid + `/Run` sobre `LocalDelegateDaemon` (`update.py:47`, `:593-601`, `:696`). Paso 3 nuevo: la ruta de `backend-params show` (T8 la imprime) y el log de `local_status` en el mismo `LOG_DIR`. Dos filas nuevas en §6. |
| P7. «Los tests en LF» era falso | Regla 4 de §5: respetar el EOL de cada fichero según `git ls-files --eol`; `tests/test_dashboard_ui.py` y otros cinco están en CRLF. Anotado en T16. |
| P8. Puntero de caché erróneo en T6 | Sustituido por `topology.py:541` (+ `st_ino`). |
| P9. POST extra del rechazo | T11 paso 4: va dentro del mismo `Attempt`, como el reintento sin esquema; el recuento de POST se mide en el backend falso. Quitada la fila de §6 que reabría REQ-018. |
| P10. Concurrencia inexistente | Quitada la fila de riesgo; §1 aclara que los trozos van en serie y el lock es solo defensa. |
| P11. Dependencia implícita A1 → L0 | Tabla de lotes y «Qué va en paralelo»: A1 se desarrolla en paralelo y se mezcla después de L0. |
| P12. Citas | `_attempt` corregido a `:2044`; T2 dice que las líneas de los `def` mandan sobre las de REQ-014. |
| P13. Delegación local genérica | `focus` concreto en T2, T4, T13, T15 y T17; motivo explícito donde el orquestador lee sin delegar (T5, T7, T9, T14, T16 y §4.2); T15 añade `local_translate` y `local_describe_image`; T18 añade `local_lint_summary` y `local_commit_msg`; `local_commit_msg` en todas las tareas que cierran con diff. |
| P14. Origen de los eventos de las capturas | §4.5: panel aparte (`metrics.app` con uvicorn en `:9494`) contra un `LOG_DIR` temporal sembrado con cinco eventos (viejo, con parámetros, razonó, omitido por contexto, rechazado), con tope de tiempo y cierre al acabar. |
| P15. «8 caminos» sin nombres | T1 enumera las ocho fixtures: `simple`, `extract_schema`, `extract_schema_retry`, `map_chunk`, `reduce`, `vision`, `fallback`, `delegate_explicit`. |
| P16. Enum del benchmark | Decisión del orquestador: el benchmark acepta `off` + el enum del producto (`minimal`…`max`), tomado de `backend_params` (T17, paso 2b, con dos tests). REQ-020 no fija el enum, así que no hace falta enmendar la spec. |
