# Propuesta de la ola B2 — salidas MCP, `local_status`, contrato, descripciones y prompts

Fase 1 (proponer, no aplicar). Rama `sdd/english-names-b2a` desde `origin/main` (`74f97d9`). Fuentes:
`plan.md` «#### B2» y «#### B2c» (con las enmiendas del 2026-10-14), D6, D9 y D10; `spec.md` REQ-010,
019, 023, 026, 027, 028, 033 y 041; `evidence/local-tools-review/report.md`; «Decisiones aprobadas»
de `waves/B1-proposal.md`; pendientes de `waves/B1b.md`, `B1c.md` y `B1d.md`; y el código de la rama.

**Los números de línea del plan están desfasados** (A7a/A7b movieron `server.py`). Los de hoy:

| El plan dice | Hoy | Qué es |
| --- | --- | --- |
| `:68-73` | `:69-77` | `MCPServer(title=…, description=…)` |
| `:474` | `:475` | `_truncation_prefix` («[local-delegate: entrada truncada …]») |
| `:1099` | `:1123` | `_fallback_notice` («[local-delegate aviso: respondió …]») |
| `:2169` | `:2204` | «[local-delegate respaldo: también fallaron …]» |
| `:2422` | `:2457` y `:2802` | «[local-delegate aviso: salida truncada por max_tokens]» |
| `:2964` | `:3000-3013` | reduce por defecto de `_chat_map_reduce` |
| `:3201-3316` | `:3205-3357` | `_LANGUAGE_NAMES`, `_commit_language_instruction`, `_guard`, `_lint_system`, `_translate_system`, resumen estructurado |
| `:3612-3631` | `:3648-3667` | subclaves de `_local_delegate` en `local_extract` |
| `:3879-3887` | igual | formato de `local_commit_msg` |
| `:4033` | `:4033` y `:4052` | `local_explain_code` y su `_read_input` con tope |

---

## 0. Cifra de partida (medida)

El propio guardián de B0b (`tests/test_no_uncatalogued_text.py::scan_source`) sobre los cinco
ficheros de `uncatalogued_pending/mcp.json` (volcado en el scratchpad, no versionado):

| Fichero | Apariciones | Únicos | De ellos |
| --- | ---: | ---: | --- |
| `server.py` | 172 | 116 | ~60 salidas (B2a), ~45 prompts (B2b-2, se quedan: ver §3.4), ~10 títulos/descripción (B2b-1), ~6 internos (excepción → inglés) |
| `failures.py` | 39 | 31 | 11 etiquetas, 12 detalles, ~7 pistas, 1 interno |
| `chains.py` | 2 | 2 | `residents_text` |
| `sections.py` | 4 | 3 | «(sin resumir)», aviso, «Introducción» |
| `questions.py` | 4 | 4 | 3 títulos de campo + 1 `logger.debug` |

El plan decía 159 + 33 + ~10 literales: cuadra si se cuentan apariciones. **Lo que el guardián no
ve** y B2 tiene que tocar igual: los 11 docstrings de tool (excluidos del escáner), las
f-strings de prompt sin palabra marcada (`:3442`, `:3518`, `:3569`, `:3615`, `:3687`, `:4021`,
`:4103-4104`), los docstrings de las clases de `questions.py` (Pydantic los mete en el JSON Schema
como `description`: **los ve el cliente MCP**) y los números con `:,` (`:2382`, `:3967`) o con coma
decimal a mano (`_describe_pace`, `:676`).

Prueba en vivo del problema de REQ-026 durante esta misma fase: `local_summarize` devolvió
«(leído server-side: 197,789 chars ≈ 97,433 tokens …)», en una frase en español.

---

## 1. Partición propuesta: cinco PR en serie (todos tocan `server.py`)

El plan prevé B2a → B2b → B2c. B2b, tal como está escrito, junta cinco cosas de naturaleza y riesgo
distintos (contrato incompatible, descripciones, prompts con su efecto en corpus y afinidad,
fronteras de medición y la muestra en vivo con 50 documentos). Propongo partirlo y sacar la muestra
en vivo al final, para que mida los prompts **definitivos** (B2c cambia el camino de
`local_explain_code`, que es una de las 4 tools de REQ-028):

| PR | Contenido | REQ | Tamaño estimado |
| --- | --- | --- | --- |
| **B2a** | salidas de las tools, errores, recibos, troceado, `local_status` (con idioma), `failures`, `chains`, `sections`, `questions`; números de máquina; `reason_text` | 019, 023, 026, 033 | ~125 textos × 2 idiomas; ~180 líneas de `server.py`; ~15 tests tocados + 2 nuevos |
| **B2b-1** | contrato `_local_delegate` y marcadores; descripciones, títulos y `description` en inglés; `tools.json`; wiki del contrato | 010, 027 | 11 docstrings (8 771 chars), 12 títulos, 5 subclaves + 4 internas, 4 marcadores; ~20 ficheros de test |
| **B2b-2** | idioma de respuesta (una función) en las 4 tools y en cada paso; `LOCAL_DELEGATE_OUTPUT_LANGUAGE`; idioma por defecto de `commit_msg`; corpus y celda de afinidad; `package_version` y `measurement_boundaries.json` | 028, 041 | ~14 sitios de prompt, 1 función, ~40 líneas de corpus/afinidad, 1 JSON nuevo, ~6 tests nuevos |
| **B2c** | cuerpo obligatorio y topes de `commit_msg`; troceado de `explain_code` y `extract` | (revisión del 2026-10-14) | ~250 líneas de `server.py`, 4–5 tests |
| **B2d** | `tests/fixtures/lang_sample/` (D10), arnés de la muestra, muestra en vivo D10 + `fr` + B2c en **una** ventana; vaciar «pendiente» de `rename-exceptions.md` | 028 (vivo), cierre | 40 + 10 documentos, 10 capturas, 1 script de `scripts/dev/`, 2 evidencias |

Los cinco salen en la **0.36.0** (REQ-010 y REQ-027 exigen la misma versión, no el mismo PR). Orden
fijo: B2a → B2b-1 → B2b-2 → B2c → B2d. Cada uno deja la suite verde por sí solo.

---

## 2. B2a — salidas y `local_status`

### 2.1 Catálogo `resources/i18n/{es,en}/mcp.json` (nuevo, LF)

Formato D5: plano, ordenado, primer segmento `mcp`, interpolación con nombre. Esquema de claves:

| Prefijo | Qué | Ejemplos |
| --- | --- | --- |
| `mcp.error.*` | texto tras `[local-delegate error] ` | `mcp.error.cooldown`, `mcp.error.max_tokens_reasoning`, `mcp.error.empty_response`, `mcp.error.connect`, `mcp.error.http_status`, `mcp.error.read_timeout`, `mcp.error.endpoint`, `mcp.error.unexpected_response`, `mcp.error.no_model_left`, `mcp.error.context_overflow`, `mcp.error.invalid_model`, `mcp.error.invalid_chunk`, `mcp.error.invalid_style`, `mcp.error.empty_diff` |
| `mcp.input.*` | `ValueError` de rutas y entrada | `mcp.input.outside_allowed`, `mcp.input.target_required`, `mcp.input.target_not_absolute`, `mcp.input.target_is_dir`, `mcp.input.target_exists`, `mcp.input.missing_file`, `mcp.input.text_or_path`, `mcp.input.image_extension`, `mcp.input.image_too_large` |
| `mcp.warning.*` | texto tras el marcador de aviso | `mcp.warning.output_truncated`, `mcp.warning.output_truncated_calls`, `mcp.warning.answered_instead`, `mcp.warning.sections_not_summarized` |
| `mcp.fallback.*` | texto tras el marcador de respaldo | `mcp.fallback.also_failed` |
| `mcp.receipt.*` | recibos | `mcp.receipt.read_server_side`, `mcp.receipt.read_server_side_tokens`, `mcp.receipt.chunked`, `mcp.receipt.map_reduce`, `mcp.receipt.commit_scope`, `mcp.receipt.written`, `mcp.receipt.input_truncated` |
| `mcp.status.*` | `local_status` | `mcp.status.backend.*`, `mcp.status.roles`, `mcp.status.turn.yes/no`, `mcp.status.cooldown.*`, `mcp.status.log.*`, `mcp.status.web.*`, `mcp.status.language.*`, `mcp.status.output_language.*`, `mcp.status.pace.*`, `mcp.status.deprecated` |
| `mcp.failure.label.<cause>` / `.detail.<cause>` / `.hint.<caso>` | `failures.py` | `mcp.failure.label.refused` = «nadie escucha» / «nothing listening» |
| `mcp.chains.*` | `chains.describe()` y `residents_text()` | `mcp.chains.fallback_on`, `mcp.chains.no_resident_unknown` |
| `mcp.sections.*` | `sections.py` | `mcp.sections.not_summarized`, `mcp.sections.introduction` |
| `mcp.question.*` | `questions.py` y las preguntas de `server.py` | `mcp.question.start_backend.message`, `.title`, `.field`; `mcp.question.choose_model.*`; `mcp.question.choose_format.*` |
| `mcp.turn.reason.remote_backend` | el motivo propio de `server.NO_TURN_REMOTE_BACKEND` | — |
| `mcp.extract.*` | valores de `error` en `_local_delegate` | `mcp.extract.not_json`, `mcp.extract.not_object` |

Unos 125 textos por idioma. El marcador, el prefijo `[local-delegate error]` y las claves de máquina
**no** van al catálogo (REQ-023).

### 2.2 `server.py` (CRLF)

- **Errores** (`_cooldown_error`, `_body_failure`, `_post_chat`, `_with_fallback`,
  `_chat_map_reduce`, `local_delegate`, `local_commit_msg`, `local_describe_image`): prefijo literal
  + `i18n.t("mcp.error.…", …)`. El prefijo pasa a constante `ERROR_PREFIX = "[local-delegate error] "`
  (ya lo usan `:3122` y `:3965` como texto).
- **Errores de entrada** (`_check_allowed_dir`, `_validate_target`, `_read_input`,
  `_validate_image_path`): `ValueError(i18n.t("mcp.input.…"))`. Son los que el cliente MCP ve como
  error de la tool.
- **Recibos y avisos de troceado** (`_savings_feedback`, `_chat_chunked`, `_chat_map_reduce`,
  `_truncation_prefix`, `_write_target`, alcance de `commit_msg`): catálogo. En B2a los
  marcadores conservan su forma vieja («aviso», «respaldo», «entrada truncada»); su cambio de forma
  es REQ-010 y va en B2b-1, en la misma versión. Para no tocar dos veces las mismas líneas, B2a ya
  los arma con **constantes** (`WARNING_MARKER`, `FALLBACK_MARKER`, `INPUT_TRUNCATED_MARKER`) que
  B2b-1 solo cambia de valor.
- **Números (REQ-026, decisión 3 de B1):** toda cifra de una salida MCP pasa por
  `i18n.format_number(n, machine=True)` (enteros sin separador, decimales con punto, en los dos
  idiomas): `_savings_feedback` (`:2379-2382`), alcance de `commit_msg` (`:3967`),
  `_describe_pace` (`:676`, hoy coma decimal a mano), enfriamiento (`:1083`, `:4372`, `:4384`),
  `max_chars` de `local_status`, `_cooldown_error` y el tamaño de imagen (`:3289`, `{:.1f}`).
- **`local_status`** entero al catálogo, más:
  - **idioma (REQ-019)**: la misma cabecera que `doctor` (idioma, origen, `language.json`, avisos y
    la línea de «volver a seguir al sistema»). Para no duplicarla, la parte de datos sale de
    `doctor.language_lines()` a `i18n.language_report()` (devuelve `lang`, rótulo del origen, ruta,
    avisos ya redactados, `follow_system`) y cada superficie la formatea con sus claves
    (`doctor.language.*` ya existe; `mcp.status.language.*` nueva). Toca `doctor.py` de B1 solo para
    llamar a la función movida (desviación pequeña, ver §8).
  - **turno**: `Turno: no ({motivo})` y `residents_text()` con `topology.reason_text()`; el motivo
    `server.NO_TURN_REMOTE_BACKEND` («backend remoto», valor de máquina que compara
    `checks._no_turn_is_fine`) se queda como valor y gana texto propio:
    `_turn_reason_text(reason)` = `mcp.turn.reason.remote_backend` si es ese, si no
    `topology.reason_text(reason)`. Con esto sale «sin LLAMASWAP_CONFIG» de `PENDING_FRAGMENTS` de
    `tests/test_doctor_english.py` (pendiente de B1c).
- **Internos que no son salida** pasan a inglés literal, sin catálogo: `:904` (`ValueError` de
  programación en `claude_tokens`), `:1380` (aserción de `_post_chat`). Los marcadores de desborde
  (`:2834-2848`, `_OVERFLOW_*`) y `NO_TURN_REMOTE_BACKEND` son **`verbatim`** en
  `uncatalogued_exceptions.json` (se comparan con texto de fuera o entre procesos).
- **`_fallback_info`**: el `motivo` del caso de enfriamiento es hoy prosa («en enfriamiento») que se
  escribe al log como `fallback_reason`. Ver pregunta 6.

### 2.3 `failures.py` (LF) — con `t_lang` para D6

`label(cause, *, language=None)`, `detail(…, language=None)` y `hint(…, language=None)`: redactan con
`i18n.t_lang(language or i18n.lang(), …)`. Sin `language`, el idioma del proceso (lo que necesitan
`local_status`, `doctor` y `probes`); B4 pasará el `?lang=` del panel (D6). `:297` (`ValueError` de
programación) a inglés literal; `:78` (`upstream command exited prematurely`, frase del log de
llama-swap) es `verbatim`. Arrastra a `doctor` las pistas y detalles del backend que B1b dejó
pendientes.

### 2.4 `chains.py`, `sections.py`, `questions.py`

- `chains.describe()` y `residents_text()` al catálogo, con el motivo vía `_turn_reason_text`
  (la función vive en `topology` o se pasa ya resuelta; ver §8, riesgo de ciclo).
- `sections.NOT_SUMMARIZED` e `INTRODUCTION` pasan a funciones (`not_summarized()`,
  `introduction()`) del idioma vigente, y se conservan las dos formas como conjunto
  (`NOT_SUMMARIZED_FORMS`) para leer salidas guardadas. **`scripts/measure_structured_summary.py`**
  compara con esas constantes (`:87`, `:96`, `:220`) y su `_WARNING` (`:71`) busca «leído
  server-side|resumido de»: hay que darle las dos formas (lectura dual de salidas guardadas,
  REQ-033). No está en la lista de B2 del plan: ver §8.
- `questions.py` (CRLF): los títulos de campo y del esquema y los docstrings de las clases (que
  Pydantic convierte en `description` del esquema que ve el cliente) se redactan **al preguntar**,
  no al importar: `ask()` reescribe `title`/`description` del `model_json_schema()` desde
  `mcp.question.*`. Así no se fija el idioma en la importación (i18n se resuelve perezosamente). El
  `logger.debug` pasa a inglés literal (log de desarrollo).
- `tests/data/uncatalogued_pending/mcp.json` se **borra** al final de B2a (la superficie `mcp`
  pasa a `CLOSED_SURFACES`); los ~45 prompts que quedan en `server.py` entran como excepciones
  `verbatim` con motivo (§3.4).

### 2.5 Tests de B2a y su control positivo

| Test | Qué afirma | Mutante → assert que dispara |
| --- | --- | --- |
| `test_mcp_english.py::test_tool_outputs_have_no_spanish` (nuevo, REQ-034) | con `LOCAL_DELEGATE_LANG=en` y backend falso, las salidas de las 11 tools (camino feliz, error de backend, troceado, map-reduce, respaldo, `extract` no JSON) y `local_status` no contienen ninguna cadena de `es/mcp.json` que difiera de la inglesa (salvo datos persistidos, REQ-033) | dejar `mcp.receipt.read_server_side` sin pasar por `t()` → falla con la cadena española en la salida |
| `…::test_numbers_are_machine_format` | `20027` aparece y `20,027`/`20.027` no, en `en` y en `es`; `1.5 tok/s` y no `1,5` | `format_number(…, machine=False)` en `_savings_feedback` → falla el de `en` con `20,027` |
| `…::test_status_shows_language` | `local_status` lleva idioma, origen y ruta, y el aviso de `LOCAL_DELEGATE_LANG=fr` | quitar la línea → falla; mutante de origen fijo `system` → falla con la variable puesta |
| `…::test_remote_backend_reason_has_its_text` | con backend remoto, «Turno: no» lleva el texto de `mcp.turn.reason.remote_backend`, no «backend remoto», en `en` | volver a `snapshot.reason` crudo → falla |
| `test_doctor_english.py` | `PENDING_FRAGMENTS` vacío de B2 | — (lo vigila su propio test) |
| `test_failures.py` (ampliado) | `label(c, language="en")` ≠ `label(c, language="es")` para las 11 causas | ignorar `language` → falla en la primera causa |

Los tests de siempre que afirman texto español siguen valiendo: la suite fija `es` (REQ-043).

---

## 3. B2b — contrato, descripciones y prompts

### 3.1 B2b-1: contrato `_local_delegate` y marcadores (REQ-010)

| Hoy | Nuevo |
| --- | --- |
| `truncado` | `truncated` |
| `aviso` | `warning` |
| `leido_server_side.{chars, tokens_aprox}` | `read_server_side.{chars, approx_tokens}` |
| `respaldo.{respondio, en_lugar_de, motivo, clase}` | `fallback.{answered_by, instead_of, reason, class}` |
| `crudo` | `raw` |
| `[local-delegate aviso: …]` | `[local-delegate warning: …]` |
| `[local-delegate respaldo: …]` | `[local-delegate fallback: …]` |
| `[local-delegate: entrada truncada — …]` | `[local-delegate: input truncated — …]` (el texto tras «input truncated» sí sale del catálogo) |
| `[local-delegate error]` | sin cambio |

Solo la forma nueva (sin emisión doble). Las claves internas del diccionario de respaldo
(`_fallback_info`, `_CurrentModel.hop`, `:2323-2354`, `:2464-2495`) se renombran a las mismas
inglesas; las columnas del log (`fallback_reason`, `fallback_class`) ya están en inglés y no cambian.
`CONTRACT_PREFIXES` del guardián gana los tres marcadores nuevos (con su test de clase
`contract_prefix`). `sections.py:271` usa la constante.

**Consumidores fuera de `server.py`** que hay que tocar o comprobar: `scripts/measure_structured_summary.py`
(`_WARNING` ya es genérico con `[local-delegate [^\]]*\]`: vale), `scripts/macos_mcp_canary.py`
(solo `[local-delegate error]`: vale), wiki `Configuration.md:221-240` y `Tools.md` (contrato y
ejemplos), y unos 20 ficheros de test que afirman claves o marcadores viejos
(`test_core.py`, `test_fallback.py`, `test_map_reduce.py`, `test_chunking.py`,
`test_structured_summary.py`, `test_density.py`, `test_measure_structured_summary.py`…; recuento
exacto con `search_text` de PyCharm al aplicar).

### 3.2 B2b-1: descripciones en inglés (REQ-027)

- Los 11 docstrings de tool (con sus `Args:`, que el SDK convierte en descripción de parámetro),
  los 11 títulos de `_annotations(...)` y `local_status`, el `title`/`description` del servidor:
  **literales en inglés**, nunca `t()`. Nombres de tool, nombres y tipos de parámetro y valores por
  defecto **no cambian**.
- Traducción: borrador con `local_translate(text=…, target_lang="inglés")` por docstring y
  revisión a mano (es texto que lee el modelo del cliente para decidir delegar: la primera frase
  «PREFER this tool over Read when…» conserva la fuerza de hoy).
- `resources/i18n/{es,en}/tools.json` (nuevo, LF): `tools.<tool>.summary`, 11 × 2. Lo usará el
  panel en B4 (REQ-027: entretanto el panel muestra la primera línea del docstring, en inglés; la
  spec lo acepta).

**Tests (`tests/test_tool_contract.py`, nuevo):**

| Test | Mutante → assert |
| --- | --- |
| las descripciones, títulos y esquemas de `mcp.list_tools()` son idénticos con `LOCAL_DELEGATE_LANG=es` y `=en` (con `i18n.reset()` entre medias) | pasar un docstring por `t()` → falla la igualdad |
| nombres de tool, nombres/tipos/defaults de parámetros = instantánea congelada de la 0.35.0 (`tests/data/tool_schema_0_35.json`, sin descripciones) | renombrar un parámetro → falla con el nombre |
| ningún docstring de tool ni título contiene palabras del léxico español (`scripts/data/spanish_lexicon.json`) | dejar un `Args:` en español → falla |
| `_local_delegate` trae `truncated`/`warning`/`read_server_side`/`fallback`/`raw` y ninguna clave vieja (`legacy_names` tiene la tabla) | volver a `truncado` → falla el «ninguna vieja» |
| los marcadores nuevos aparecen y los viejos no, en `en` y en `es` | dejar `aviso` en `_fallback_notice` → falla |

### 3.3 B2b-2: idioma de respuesta del modelo — una sola función

```python
# i18n.py (ver pregunta 2: el plan la pone en server.py)
class ResponseLanguage(NamedTuple):
    value: str            # "es", "en" o el texto de LOCAL_DELEGATE_OUTPUT_LANGUAGE
    source: str           # "output_variable" o el origen de i18n.current() (variable, preference…)
    problem: str | None   # aviso de una OUTPUT_LANGUAGE no válida (control_chars, too_long)

def response_language() -> ResponseLanguage:
    out = config.output_language()          # B0 ya valida: 1–40 chars, sin control ni saltos
    if out.value:
        return ResponseLanguage(out.value, "output_variable", None)
    current = current()
    return ResponseLanguage(current.lang, current.source, out.problem)
```

Se lee **en cada llamada** (no se cachea): `config.output_language()` lee el entorno al llamar,
como `commit_language()`. `server._response_language_clause()` la convierte en la orden del prompt:
`" Responde en {nombre}, aunque el contenido esté en otro idioma."`, con `{nombre}` de
`_LANGUAGE_NAMES` para códigos conocidos (`es`→español, `en`→inglés, `fr`→francés…, con la misma
normalización `es-CU`/`es_ES` que hoy usa el commit) y el valor tal cual si no se conoce
(`português`). La lógica de nombre se comparte con `_commit_language_instruction` (una función
`_language_name(code)`).

**Dónde va la orden (las 4 tools, en cada paso):** siempre **detrás** de lo que ya devuelve
`_guard`/`_lint_system`, nunca dentro: así `_guard` y `_translate_system` quedan byte a byte iguales
y las celdas de afinidad de `local_translate` y `local_delegate` conservan su base (§3.5).

| Tool | Llamada única | Map-reduce |
| --- | --- | --- |
| `local_summarize` | `system = _guard(…) + extra + clause` | `system` (map) + `reduce_extra=extra + clause` (reduce y reagrupado, que usan `reduce_system`) |
| `local_summarize` estructurado | `_structured_system(…, extra + clause)` | `_chunk_system` igual (las dos ramas) |
| `local_lint_summary` | `_lint_system(max_words) + clause` | igual + `reduce_extra=clause` |
| `local_explain_code` | `system + clause` | B2c: map, reagrupado y reduce |
| `local_describe_image` | `system + clause` | — |
| `local_commit_msg` | **no** (manda su propia regla) | — |

`local_status` y `doctor` muestran el valor efectivo y su origen («variable de salida» o el del
idioma vigente) y, si la hay, el aviso de `common.output_language.warning.*` (ya en el catálogo
desde B0a). `doctor` lo hace con la misma `response_language()` (una línea más en su cabecera:
toca `doctor.py`/`doctor.json` de B1, ver §8).

### 3.4 B2b-2: los prompts siguen en español (pregunta 1)

Propuesta: **no traducir** los prompts a inglés en B2; solo añadir la orden de idioma. Motivos:

1. Cambiar `_guard` o `_translate_system` deja **sin base** las 4 celdas aprobadas de afinidad
   (`matrix.CELLS`, huella `prompt_sha256`; `test_affinity.py::test_prompt_footprint_of_the_code_is_the_measured_one`)
   y obliga a re-evaluar traducción y delegación genérica, que REQ-028 ni siquiera toca.
2. El corpus F2 y el de afinidad recapturan `system`, `user_template` y `max_tokens`
   (`build_corpus._WATCHED_FIELDS`): traducir los ~45 prompts cambia los 82 casos a la vez.
3. Los prompts no son texto de interfaz: el usuario no los ve. Se quedan en `server.py` como
   excepciones `verbatim` («prompt del modelo local: entra en la huella de afinidad y en el corpus
   congelado; su idioma lo decide REQ-028»), unas 45 entradas en `uncatalogued_exceptions.json`.

### 3.5 B2b-2: corpus congelados y celda de afinidad — choque no previsto por el plan

Al añadir la orden de idioma cambia, a propósito, el prompt de producción de 4 tools; y B2c cambia el
de `commit_msg`. Eso rompe tres guardianes que hoy están en verde:

| Guardián | Qué rompe B2b-2 | Qué rompe B2c |
| --- | --- | --- |
| `test_corpus.py:49` `check_versioned(catalogo-2026-09) == []` | `system` de summarize ×5, lint, explain ×2, describe ×2 (10 casos) | `system` y `max_tokens` de commit ×2 |
| `test_corpus.py:1000` `check_versioned_affinity(afinidad-2026-10) == []` | lint ×4, summarize ×1 | commit ×40 |
| `test_affinity.py:548` huella de las celdas | la celda `local_lint_summary`/`gemma4-26b-a4b` | — |

Y `doctor` (`checks.py:1673`) dirá «sin base» para la celda de lint: la afinidad deja de mandar
`lint_summary` al 26B cargado hasta re-evaluar. Es el comportamiento honesto (se midió otro prompt),
pero es un cambio de producto. **Propuesta (pregunta 3):**

- `build_corpus.py` gana una lista versionada de cambios de prompt **esperados**,
  `PROMPT_BOUNDARIES = {"0.36.0": {"local_summarize", "local_lint_summary", "local_explain_code",
  "local_describe_image", "local_commit_msg"}}`. `check_versioned*` informa esos casos como «medido
  con prompts anteriores a 0.36.0» (aviso, no error) **solo** en los campos `system` y `max_tokens`;
  cualquier otro campo, u otra tool, sigue fallando. Los corpus no se regeneran (sus respuestas se
  midieron con el prompt viejo).
- Test: el conjunto de casos que difieren es exactamente el de esas tools. Control positivo:
  cambiar `_translate_system` hace fallar el test (tool fuera de la lista).
- `matrix.CELLS`: la celda de lint se queda con su huella vieja y el test de huella pasa a afirmar
  que **solo** esa celda la perdió. Control: cambiar `_guard` hace fallar (perderían base las tres).
- `F2_COMMIT_LANGUAGE` pasa de `""` al valor explícito de la regla del diff (pregunta 4), para que
  su recaptura siga dando el prompt de hoy tras el cambio de defecto de B2b-2.

### 3.6 B2b-2: `local_commit_msg` (enmienda del 2026-10-14)

`_commit_language_instruction()`:

1. `LOCAL_DELEGATE_COMMIT_LANGUAGE` puesta con el valor reservado de la regla del diff (propuesto:
   `diff`, sin distinguir mayúsculas) → el prompt de hoy, byte a byte.
2. Puesta con otro valor → «… en {nombre}.» (como hoy).
3. Sin poner → idioma vigente del producto: `i18n.lang()` → `es`→«en español», `en`→«en inglés».
   **No** mira `LOCAL_DELEGATE_OUTPUT_LANGUAGE`.

`tests/test_commit_language.py` (ampliado) y `tests/test_corpus.py:101-134` (sus afirmaciones de
`_ASKS_DIFF_LANGUAGE` pasan a usar `diff`):

| Test | Mutante → assert |
| --- | --- |
| sin variable, `LANG=es` → termina en «en español.»; `LANG=en` → «en inglés.» | volver al «predominante» por defecto → falla el de «sin la variable» |
| con `fr` manda la variable aunque `LANG=en` | — |
| con `diff` → el texto de hoy (constante congelada en el test) | — |
| `commit_msg` idéntico con y sin `OUTPUT_LANGUAGE=fr` | aplicar la salida a commit → falla |

### 3.7 B2b-2: tests de REQ-028 con backend falso que captura los prompts

| Test | Mutante → assert |
| --- | --- |
| `OUTPUT_LANGUAGE=fr` y `=português` → la orden está en el `system` de las 4 tools, en llamada única | ignorar la variable → falla «puesta» |
| ídem en **cada** llamada del map-reduce (map, reagrupado y reduce) de summarize, summarize estructurado, lint y (tras B2c) explain | ponerla solo en el reduce (`reduce_extra` sin la del map) → falla en la primera llamada del map |
| vacía, `"a\nb"` y 41 caracteres → orden del idioma vigente, y `local_status` lleva el aviso | tratar el no válido como válido → falla |
| sin variable, `LANG=en` → «Responde en inglés» en las 4; `LANG=es` → «en español» | constante fija → falla una de las dos |
| `local_translate`, `extract`, `classify`, `boilerplate` y `delegate` no llevan la orden | aplicarla en `_guard` → falla (y falla la huella) |

### 3.8 B2b-2: fronteras de medición (REQ-041, D9)

- `_log_event` escribe `package_version` (= `get_version()`) en **cada** fila de `usage-*.jsonl`.
  Comprobar que `legacy_names.normalize("usage", …)`, `cost.merge` y el panel ignoran la clave
  nueva (test: una fila con ella se cuenta igual).
- `scripts/data/measurement_boundaries.json` (nuevo, LF):
  `{"package_version_after": "0.36.0", "hook_hashes_after": "scripts/data/hook_hashes_after.json"}`.
- Lector mínimo `scripts/measurement_boundaries.py`: `load()` y `usage_side(row) -> "before"|"after"`
  (comparación de versión con `packaging.version`, ya dependencia transitiva; si no, tupla de
  enteros); `hook_hashes()` devuelve `set()` si el fichero de B3 no existe. **`measure_adoption.py`
  no se toca** (es de B3).
- Tests: fila con `package_version` 0.35.0 y fecha posterior → «before»; fila sin versión y fecha
  posterior → «before»; 0.36.0 → «after»; sin `hook_hashes_after.json` → conjunto vacío sin error.
  Control: clasificar por fecha hace fallar el de «sin versión».

---

## 4. B2c — cuerpo de `local_commit_msg` y troceado de `explain_code`/`extract`

### 4.1 Cuerpo y topes del commit

- Formato (las dos variantes): «cuerpo **obligatorio** de 2 a 6 viñetas '- ' que digan qué cambia y
  para qué» en vez de «cuerpo opcional». El reduce (`_build_reduce`, `:3935`) repite la exigencia.
- Topes: llamada única `max_tokens` 256 → **700**; paso final `max_words` 90 → **250**
  (`_tokens(250)` = 564); `partial_max_words=350` sin cambio.
- Tests (backend falso que captura `system` y `max_tokens`): el `system` de la llamada única y el
  del reduce piden el cuerpo; `max_tokens` ≥ 700 y ≥ 564. Mutante: el formato y los topes de hoy →
  fallan **por el assert del cuerpo** (primero) y por el del tope (segundo), comprobado con
  `pytest -x` sobre cada mutante por separado.

### 4.2 Troceado de `local_explain_code`

- Entrada entera (`_read_input(…, _NO_TRUNCATE)`); si `len(content) <= max_chars_for_role("code")`,
  la llamada única de hoy (+ orden de idioma). Si no, `_chat_map_reduce`:
  - **trozos** por `def`/`class` de primer nivel: nuevo `_split_by_top_level_defs(text)` (regex
    `^(?:@|async\s+def\s|def\s|class\s)` en columna 0; los decoradores se pegan a la definición que
    sigue; lo anterior a la primera definición es un trozo), empaquetados con `_pack(…, budget)`;
    un trozo mayor que el presupuesto cae a `_chunk_text`. Sin ninguna definición (otro lenguaje),
    `_chunk_text` directamente.
  - **inventario** calculado en el servidor (como `_diff_inventory`): la lista de nombres de primer
    nivel, que va **siempre** al reduce. Es lo que evita el fallo de la revisión (lista de
    subcomandos de `cli.py` dada por completa sin `doctor`, `benchmark` ni `llamaswap`).
  - **map**: «notas por función/clase de este fragmento: qué hace cada una»; **reduce**: el formato
    de hoy («explicación clara en prosa…», `max_words=250`) con la **pregunta** (si la hay) y el
    inventario; orden de idioma en los tres pasos.
- Test: fichero de ~60 000 caracteres con `def ZZZ_marker` al final → aparece en el `user` de alguna
  llamada capturada, y el inventario del reduce lo nombra. Mutante: el camino de hoy (truncado) →
  falla en el assert de `ZZZ_marker`.

### 4.3 Troceado de `local_extract`

- Entrada entera; si cabe en el rol (`mechanical`/`long` por tamaño), la llamada de hoy. Si no,
  `_chat_map_reduce` con `response_format` de schema **en cada paso** (hace falta pasar
  `response_format` y `json_schema_fallback` a través de `_CurrentModel.call`) y sin ningún sufijo
  de texto (el JSON tiene que seguir siendo parseable): nuevo parámetro `feedback=False` para que
  `_chat_map_reduce` no pegue «(resumido de…)», el ahorro ni el aviso de truncado; esos datos van a
  `_local_delegate`.
- **map**: el mismo prompt de extracción por trozo (JSON con las claves, `null` si no está); **reduce**
  por el modelo con los parciales y los campos pedidos (pregunta 7).
- Test: ~60 000 caracteres con el valor de un campo solo al final → llega al backend y sale en el
  objeto. Mutante: el camino de hoy → falla.
- Consecuencia de contrato: con el troceado, `extract` deja de truncar la entrada, así que
  `truncated`/`warning` solo saldrían si un parcial acaba por `length` (pregunta 8).

### 4.4 Efectos colaterales de B2c

- Corpus: los 42 casos de commit cambian `system` y `max_tokens` (cubiertos por
  `PROMPT_BOUNDARIES` de §3.5). Los casos de `explain_code` (15 400 y 20 000 chars) y `extract`
  (2 056 y 48 000) siguen cabiendo en una llamada: `kind=quality, n==1` no cambia.
- La wiki `Tools.md` (topes y troceado) y `Configuration.md` (`LOCAL_DELEGATE_MAX_CHARS_CODE` deja de
  ser un truncado para `explain_code`).

---

## 5. B2d — muestras en vivo (diseño; nada se ejecuta en esta fase)

### 5.1 El problema de fondo: un idioma por proceso

El daemon resuelve el idioma una vez (`i18n.current()` cacheado) y cambiarlo exige reiniciarlo, lo
que tira el MCP de la sesión. Para tener respuestas con idioma vigente `en` y `es` **sin reiniciar el
daemon**, propongo (pregunta 5) un arnés `scripts/dev/lang_sample.py` que:

- abre **una** ventana: `local-delegate test-window start --label "B2 muestra de idioma (D10, fr, B2c)"`
  y guarda el id;
- lanza **tres procesos hijos** (`LOCAL_DELEGATE_LANG=en`, `=es`, y `=es` con
  `LOCAL_DELEGATE_OUTPUT_LANGUAGE=fr`) que importan `local_delegate.server` y llaman a las tools
  **en proceso** contra el mismo backend local (llama-swap en loopback, sin pasar por el daemon);
- escribe cada respuesta con su detector y cierra la ventana (`stop <id>`) aunque algo falle.

Requisito a verificar antes (sin pedir la clave al usuario): que el llama-swap local responde sin
credencial desde un proceso que no es el daemon. Si exige la del lanzador, la alternativa es pedir
al usuario un reinicio planificado del daemon con `LOCAL_DELEGATE_LANG=en` y `/mcp` después.

### 5.2 `tests/fixtures/lang_sample/` (D10)

| Tool | `es` (se manda con vigente `en`) | `en` (se manda con vigente `es`) |
| --- | --- | --- |
| `local_summarize` | 5 extractos de `docs/wiki/` de 2–6 kB | 5 piezas inglesas: descripciones de B2b-1 y `en/*.json` agrupadas por tema |
| `local_lint_summary` | 5 logs de pytest de la suite con asserts en español | 5 logs de pytest/ruff en inglés |
| `local_explain_code` | 5 ficheros de `git show 8ec2f1d:<ruta>` (0.34.0) | 5 ficheros del repo actual |
| `local_describe_image` | 5 capturas de `site/index.html` en ES | 5 en EN (Playwright, bajo `pesado.sh`) |

Los `.py` de muestra se guardan como **`.py.txt`** (pytest no los recoge, ruff no los mira y
«ningún `.py` en `evidence/`» se cumple también en fixtures). `manifest.json` con origen, sha256 e
idioma de cada documento. Al menos uno de los `explain_code` supera 20 000 caracteres para pasar por
el troceado de B2c.

### 5.3 Corridas y criterio

| Corrida | Llamadas | Criterio | Evidencia |
| --- | ---: | --- | --- |
| D10 | 4 tools × 5 docs × 2 idiomas = 40 | por tool e idioma vigente, 5 de 5 en el idioma vigente (`detect_language`, `min_tokens=20`, margen 0,15; `unknown` = fallo) | `evidence/B2/lang-sample.json` con id de ventana |
| `fr` (REQ-028, issue #260) | 4 tools × 10 docs (los mismos, `es`+`en`) = 40 | ≥ 90 % en francés por tool — **sin juez hoy** (pregunta 9) | mismo fichero, sección `fr` |
| B2c | `commit_msg` sobre los diffs de B0a y B1a; `explain_code` sobre `cli.py` | español con cuerpo de 2–6 viñetas; la explicación nombra `doctor`, `benchmark` y `llamaswap` | `evidence/B2c/live.md` |

### 5.4 Cierre de B2

`rename-exceptions.md`: la sección «pendiente» queda vacía (lo de REQ-010 sale en B2b-1). Detector de
nombres a 0. `uncatalogued_pending/mcp.json` ya borrado en B2a.

---

## 6. Finales de línea

| Fichero | EOL |
| --- | --- |
| `server.py`, `questions.py` | **CRLF** (escribir con `newline=""` o con Edit; nunca `write_text`) |
| `failures.py`, `chains.py`, `sections.py`, `i18n.py`, `doctor.py`, `config.py`, `matrix.py`, `scripts/build_corpus.py`, `scripts/measure_structured_summary.py`, `tests/test_corpus.py`, `tests/test_affinity.py`, `tests/test_no_uncatalogued_text.py`, `tests/data/uncatalogued_exceptions.json`, `docs/wiki/Configuration.md`, catálogos `i18n/*/*.json` | LF |
| nuevos (`mcp.json`, `tools.json`, `measurement_boundaries.json`, `measurement_boundaries.py`, `test_mcp_english.py`, `test_tool_contract.py`, `tool_schema_0_35.json`, `lang_sample/`, `lang_sample.py`) | LF |

Comprobación al cerrar cada PR: `git ls-files --eol` sobre los tocados (nunca `grep -c $'\r$'`).

---

## 7. Tamaño frente al plan

| | Plan | Medido / estimado |
| --- | --- | --- |
| B2a | 159 + 33 + ~10 literales | 172 + 39 + 10 apariciones (116 + 31 + 9 únicos); ~125 claves × 2 |
| B2b | 11 docstrings, 11 títulos + 1 descripción, 5 subclaves, 3 marcadores, ~14 sitios de prompt | igual, más **4** marcadores (el aviso está en dos funciones y en `sections.py`), 4 claves internas del respaldo, ~20 ficheros de test, el ajuste de 2 corpus y 1 celda (no previsto) |
| B2c | ~2 cambios + 2 troceados | ~250 líneas: splitter, inventario de código, `response_format`/`feedback` en el map-reduce |
| Muestra | 40 llamadas | 40 (D10) + 40 (`fr`) + 3 (B2c) = 83 llamadas, 1 ventana |

---

## 8. Riesgos y contradicciones entre plan, spec y código

1. **Spec REQ-028 contradice la enmienda del plan sobre `commit_msg`.** `spec.md:418-420` y `:436`
   siguen diciendo «idioma predominante del diff» por defecto y que «un test de que el prompt de
   `local_commit_msg` no cambia con el idioma vigente» lo comprueba; el plan (`:1292-1301`), por
   decisión del usuario, dice lo contrario. Y `plan.md:997` («B2b exige que el prompt de
   `local_commit_msg` quede idéntico») también choca. **Hay que enmendar la spec antes del gate de
   B2b-2.**
2. **Los corpus congelados y la celda de afinidad de lint** (§3.5): el plan no lo prevé; sin
   decisión, B2b-2 y B2c no pueden dejar la suite en verde.
3. **El juez del francés no existe:** `detect_language` responde `es`, `en` o `unknown`
   (D10); el criterio «≥ 90 % en francés» no tiene con qué medirse.
4. **Muestra en vivo y un idioma por proceso** (§5.1): el plan no dice cómo se obtienen respuestas
   con vigente `en` y `es` del mismo daemon.
5. **Propiedad de ficheros fuera de la lista de B2:** `doctor.py`/`doctor.json` (cabecera de
   idioma de salida y la función movida a `i18n`), `scripts/measure_structured_summary.py`
   (lectura dual de «(sin resumir)» e «Introducción»), `scripts/build_corpus.py`,
   `tests/test_corpus.py`, `tests/test_affinity.py`, `matrix.py` (comentario de la celda) y la wiki
   `Tools.md` y `Configuration.md` fuera de `:221-234` (la fila de `LOCAL_DELEGATE_COMMIT_LANGUAGE`,
   `:44`, describe el defecto viejo).
6. **Ciclo de importación:** `chains` importa `topology`; si `_turn_reason_text` vive en `server`,
   `chains` no puede llamarla. Propuesta: mover el texto del motivo remoto a `topology` (una clave
   más en `_REASON_KEYS`, sin tocar el valor de máquina) — `topology.py` es de B1c, otra desviación
   pequeña.
7. **`affinity --check` de `scripts/dev/affinity_batch.py` y doctor:** tras B2b-2, `doctor` informa
   la celda de lint «sin base». Debe anunciarse en el CHANGELOG de la 0.36.0 junto al contrato.
8. **Una orden en español para responder en inglés** puede no bastarle al modelo mecánico
   (gemma3-4b); solo la muestra en vivo lo dice, y llega en B2d, al final. Si falla, hay que tocar
   el texto de la orden (y recapturar la frontera de prompts) otra vez.
9. **`questions.py`:** el esquema de elicitation se fija hoy al importar (títulos y docstrings de
   Pydantic). Redactarlo al preguntar es un cambio de comportamiento pequeño pero real; sin él, el
   idioma de las preguntas quedaría congelado al de la primera importación.
10. **`extract` troceado** cambia el número de llamadas al backend (y el log: `chunks`) para
    entradas grandes; el panel y el corpus lo verán como una tool que antes era de una llamada.

---

## 9. Preguntas abiertas (con recomendación)

1. **¿Se traducen los prompts al inglés en B2?** Recomiendo **no**: solo la orden de idioma detrás
   de `_guard`. Traducirlos deja sin base las 4 celdas de afinidad y cambia los 82 casos de corpus,
   sin que REQ-028 lo pida. Si se quiere, que sea una ola propia con su medición.
2. **¿Dónde vive `response_language()`?** El plan dice `server.py`; recomiendo **`i18n.py`**, porque
   `doctor` tiene que usarla y no importa `server` (lo hace perezosamente y solo en dos checks).
   `server` la llama desde ahí. Es la misma función única.
3. **Corpus y celda de lint tras el cambio de prompts:** recomiendo `PROMPT_BOUNDARIES` versionado
   en `build_corpus.py` (aviso para `system`/`max_tokens` de las 5 tools de la 0.36.0; error para
   todo lo demás) y aceptar que la celda de lint pierde la base hasta re-evaluarla, anunciándolo.
   Alternativas descartadas: regenerar los corpus (rompe el vínculo con lo medido) o poner la orden
   en el mensaje de usuario para esquivar la huella (esconde un cambio de prompt).
4. **Valor explícito de la regla del diff en `LOCAL_DELEGATE_COMMIT_LANGUAGE`:** recomiendo
   **`diff`** (sin distinguir mayúsculas). Es corto, no es un idioma y se documenta en la wiki.
5. **Cómo obtener respuestas con vigente `en` y `es` sin reiniciar el daemon:** recomiendo el arnés
   en proceso de §5.1, tras comprobar que llama-swap local no pide credencial. Si la pide, un
   reinicio planificado del daemon con el usuario delante.
6. **`fallback.reason` del caso de enfriamiento:** hoy escribe prosa («en enfriamiento») al log como
   `fallback_reason`. Recomiendo escribir el **valor de máquina `cooldown`** (los demás motivos ya son
   códigos) y leer el viejo tal cual (REQ-033); el aviso visible lo redacta el catálogo.
7. **Reduce de `extract` troceado:** recomiendo **reduce por el modelo con schema** sobre los
   parciales (resuelve conflictos con contexto), y cortocircuito en código si un solo parcial trae
   valores no nulos (sin llamada extra).
8. **`truncated`/`warning` de `_local_delegate` tras B2c:** `extract` deja de truncar la entrada.
   Recomiendo que las dos claves pasen a significar «un parcial acabó por `max_tokens`» (salida
   truncada), y que la wiki lo diga; así el contrato de REQ-010 sigue teniendo un caso real.
9. **Juez del francés:** recomiendo ampliar `detect_language` con una lista de palabras funcionales
   `fr` y un control propio congelado **antes** de la corrida (20 frases, ≥ 95 %), con la misma
   regla de «no ajustar a la vista de los fallos»; la alternativa barata («ni `es` ni `en`») no
   distingue francés de basura.
10. **Partición:** recomiendo los cinco PR de §1 (B2a, B2b-1, B2b-2, B2c, B2d) en serie, con la
    muestra en vivo al final y en una sola ventana.
11. **Spec:** recomiendo enmendar REQ-028 (commit y su test) en un commit de SDD antes de aplicar
    B2b-2.

---

## 10. Llamadas `local_*` de esta fase

| # | Llamada | Para qué | Resultado |
| --- | --- | --- | --- |
| 1 | `local_summarize(path=server.py, focus="textos en español de las salidas…", max_words=400)` | mapa de salidas, marcadores y recibos | estructurado por comentarios de cabecera, pobre en literales; dejó la prueba de REQ-026 («197,789 chars») |
| 2 | `local_summarize(path=server.py, focus="_chat_map_reduce y _chat_chunked…", max_words=400)` | troceado y qué tools usan qué camino | confirmó que `explain_code` y `extract` van por `_chat` sin troceado |

**Pasos hechos a mano y por qué:** las franjas literales de `server.py` (`:1077-1158`,
`:2882-3470`, `:3584-3700`, `:3784-4122`, `:4360-4580`) se leyeron con `Read` porque la propuesta cita
prompts, topes y claves exactos, y los dos resúmenes (troceo por cabeceras de comentario) no
conservaban literales; `local_explain_code`/`local_extract` no sirven sobre `server.py` (truncan a
20 000 de 203 553, que es justo el fallo de B2c). Los conteos del guardián los dio el propio
`scan_source` (un programa, no un modelo). `plan.md`, `spec.md` y los informes de ola se leyeron
por franjas o con `grep`: son la fuente normativa y hacía falta su texto exacto. Ninguna llamada en
vivo, ninguna ventana de prueba, el daemon no se tocó.

---

## 11. Decisiones aprobadas (sesión principal y usuario, 2026-10-14)

- **Partición (10):** cinco PR en serie, B2a → B2b-1 → B2b-2 → B2c → B2d.
1. Los prompts no se traducen; solo la orden de idioma detrás de `_guard`.
2. `response_language()` vive en `i18n.py`.
3. **Decisión del usuario:** se acepta perder la base de afinidad de lint durante el desarrollo, con
   `PROMPT_BOUNDARIES` versionada en `build_corpus.py`, y se añade el lote **B2-affinity**
   (re-evaluación de afinidad en vivo) después de B2d y antes del release 0.36.0, para que la 0.36.0
   salga con la base nueva. Los tres tests de corpus/afinidad que se rompan se actualizan en el lote
   que los rompa, con su motivo.
4. Valor explícito de la regla del diff: `diff`.
5. Arnés en proceso si el llama-swap local no pide clave; si la pide, se para y se pregunta antes de
   planificar ningún reinicio del daemon.
6. `fallback.reason` del enfriamiento: valor de máquina `cooldown`.
7. Paso final de `extract` troceado: el modelo, con schema.
8. `truncated`/`warning` = «salida truncada en un trozo»; documentado en el contrato y el CHANGELOG.
9. **No** se amplía el detector a francés. La muestra en vivo de `LOCAL_DELEGATE_OUTPUT_LANGUAGE` usa
   el idioma **contrario** al del producto (producto `es` + variable `en`, y al revés), con el
   criterio de ≥ 90 %; `fr`/`português` solo en tests unitarios con backend falso.
11. Se enmiendan `spec.md` (REQ-028) y `plan.md:997` (hecho el 2026-10-14).
- **Desviaciones de propiedad aprobadas:** `doctor.py`/`doctor.json`, `topology.py`,
  `measure_structured_summary.py`, `build_corpus.py`, `matrix.py` y la wiki `Tools.md`/
  `Configuration.md`, cada una en el lote que la necesite y registrada.
