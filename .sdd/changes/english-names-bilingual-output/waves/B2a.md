# Ola B2a — salidas MCP y `local_status` en dos idiomas

Primer PR de B2 (`waves/B2-proposal.md`, «Decisiones aprobadas»; plan, «#### B2», enmienda del
2026-10-14). Rama `sdd/english-names-b2a`, sobre `origin/main` `74f97d9` (B1e mezclada como #315). Sin
commit ni push: los hace la sesión principal.

- **REQ:** 023 (errores tras el prefijo, avisos, recibos, troceado, `local_status`, etiquetas de causa y
  descripción de cadenas en el idioma del proceso), 026 (salidas MCP: enteros sin separador y decimales
  con punto en los dos idiomas), 019 (`local_status` dice el idioma del proceso servidor, su origen, el
  `language.json` y sus avisos), 033 (lectura dual de lo ya escrito) y 034 (humo en inglés de la
  superficie MCP); 045 (se cierra la superficie `mcp`: se borra `uncatalogued_pending/mcp.json`);
  decisión 6 de B2 (`cooldown` como valor de máquina del motivo de respaldo).
- **Resultado:** suite **2880 passed, 2 skipped** con `LANG=en_US.UTF-8` y con `LANG=es_ES.UTF-8`
 , las dos con `-n 4 --dist loadgroup` bajo `pesado.sh`; `ruff check` y `ruff format
  --check` limpios; guardián de textos en verde con `mcp` en `CLOSED_SURFACES`; detector de nombres del
  frente A **0 fuera de la lista y 0 sin clasificar**, corrido al final; **8 controles positivos**, los 8
  disparan el assert esperado; sin ciclos de importación a nivel de módulo por los ficheros tocados.

## Qué se hizo

| Fichero | EOL | Cambio |
| --- | --- | --- |
| `src/local_delegate/resources/i18n/{es,en}/mcp.json` (nuevos) | LF | 147 claves por idioma: `mcp.error.*`, `mcp.input.*`, `mcp.receipt.*`, `mcp.warning.*`, `mcp.fallback.*`, `mcp.status.*`, `mcp.failure.{label,detail,hint}.*`, `mcp.chains.*`, `mcp.sections.*`, `mcp.question.*`, `mcp.extract.*`. En español, byte a byte los textos de antes salvo las cifras (REQ-026) |
| `src/local_delegate/resources/i18n/{es,en}/cli.json` | LF | `cli.topology.reason.remote_backend` («backend remoto» / «remote backend») |
| `src/local_delegate/server.py` | **CRLF** (conservado) | errores con `ERROR_PREFIX` + catálogo; errores de entrada (`ValueError`) del catálogo; recibos, troceado, map-reduce, alcance del commit y avisos por el catálogo; marcadores nombrados (`WARNING_MARKER`, `FALLBACK_MARKER`, `INPUT_TRUNCATED_MARKER`) con su forma vieja, para que B2b-1 cambie una línea; `_machine()` = `i18n.format_number(…, machine=True)` en toda cifra de salida (lectura server-side, alcance, ritmo `1.5 tok/s`, enfriamiento, RAM, tamaño de imagen); `local_status` entero por el catálogo, con la cabecera de idioma (`_describe_language`) y el motivo del turno con `topology.reason_text`; preguntas al cliente por el catálogo; `_fallback_info` escribe `cooldown` (`COOLDOWN_REASON`) y el aviso lo dice traducido; mensajes internos de programación en estilo id (`not_a_failure`, `unknown_conversion_kind`, `_post_chat: unreachable`, `models_body_without_data_list`) |
| `src/local_delegate/failures.py` | LF | `label`, `detail` y `hint` con `language=None` (D6: el panel pasará el del visitante; sin él, el del proceso), textos en `mcp.failure.*`; la lógica de `hint` pasa a `_hint_key` |
| `src/local_delegate/chains.py` | LF | `describe()` y `residents_text()` por el catálogo, el motivo con `topology.reason_text` |
| `src/local_delegate/sections.py` | LF | `not_summarized()` e `introduction()` en el idioma vigente; `NOT_SUMMARIZED_FORMS` e `INTRODUCTION_FORMS` con las dos formas (REQ-033); el aviso por el catálogo con `WARNING_MARKER` |
| `src/local_delegate/questions.py` | **CRLF** (conservado) | `_localized_schema()`: título, descripción y título del campo del esquema de elicitation salen del catálogo **al preguntar** (antes, de la clase y del docstring, fijos en español); las clases llevan títulos de máquina en inglés; `logger.debug` en inglés |
| `src/local_delegate/i18n.py` | LF | `language_report()` y `LanguageReport` (idioma, rótulo del origen, ruta, avisos ya redactados, `follow_system`): los mismos datos para `doctor` y `local_status` |
| `src/local_delegate/doctor.py` | LF | `language_lines()` usa `i18n.language_report()` (salida idéntica) — desviación aprobada |
| `src/local_delegate/topology.py` | LF | `REMOTE_BACKEND = "backend remoto"` con su clave en `_REASON_KEYS`; `server.NO_TURN_REMOTE_BACKEND` es ese valor (no cambia) — desviación aprobada |
| `scripts/measure_structured_summary.py` | LF | lee las dos formas de «(sin resumir)», «Introducción» y los recibos (`resumido de`/`summarized from`, `leído server-side`/`read server-side`) — desviación aprobada |
| `tests/test_mcp_english.py` (nuevo) | LF | 23 casos (ver «Controles positivos») |
| `tests/test_questions.py` | CRLF | el test de esquemas mira `_localized_schema` (español idéntico al de antes) y uno nuevo por idioma |
| `tests/test_core.py`, `test_density.py`, `test_map_reduce.py`, `test_slowness.py`, `test_dashboard_cost.py` | LF | REQ-026: `2000`, `84350`, `1328`, `40.5 tok/s` en vez de `2,000`, `84,350`, `1,328`, `40,5`; la unidad `image_bytes` |
| `tests/test_structured_summary.py` | LF | `sections.introduction()` |
| `tests/test_doctor_english.py` | LF | `PENDING_FRAGMENTS` vacío (los tres eran de B2) |
| `tests/test_no_uncatalogued_text.py` | LF | `CLOSED_SURFACES = {"doctor", "cli", "mcp"}` |
| `tests/data/uncatalogued_pending/mcp.json` | — | borrado (quedan `hooks`, `install` y `panel`) |
| `tests/data/uncatalogued_exceptions.json` | LF | 53 excepciones `verbatim`: 40 prompts del modelo local (huella de afinidad y corpus congelados; REQ-028 decide su idioma y no se traducen), 6 descripciones/títulos de tool y del servidor (REQ-027: solo inglés y fuera del catálogo; B2b-1 los pasa a inglés), 5 marcas de desborde que se buscan en el error del backend, la frase de llama-swap de `failures` y el motivo `backend remoto` |
| `scripts/data/spanish_lexicon.json` | LF | 4 españolas (`activa`, `exclusivo`, `inactiva`, `persistente`) y 4 inglesas (`bmp`, `inactive`, `localized`, `processed`) |

## Controles positivos (`evidence/B2a/mutants.md`)

Cada mutante se aplicó, se corrió solo su test con `-x` y se restauró (script en el scratchpad, bajo
`pesado.sh`). Los 8 fallan, y por el assert que dicen:

| Mutante | Test | Assert que dispara |
| --- | --- | --- |
| M1 recibo de lectura fuera del catálogo | `test_tool_outputs_have_no_spanish_in_english` | `assert not _spanish_in(english, words)` → `['contexto', 'entraron', 'leído']` |
| M2 cifras con el separador del idioma | `test_numbers_are_machine_format[es]` | `assert "20027" in text` (sale `20.027`) |
| M3 motivo del turno crudo | `test_remote_backend_reason_has_its_text` | `'Turn: no (backend remoto)' == 'Turn: no (remote backend)'` |
| M4 `failures` ignora el idioma pedido | `test_failure_texts_follow_the_requested_language` | `text("en") != text("es")` en `dns` |
| M5 `language_report` sin avisos | `test_status_warns_about_an_invalid_variable` | `len(lines) >= 2` |
| M6 una sola forma de «(sin resumir)» | `test_the_measurement_reads_both_forms` | `(paired, completed) == (1, 1)` da `(2, 0)` |
| M7 título del campo sin catálogo | `test_the_elicitation_schemas_keep_their_fields_and_visible_titles` | igualdad del esquema |
| M8 residente con el motivo crudo | `test_residents_text_says_the_reason_in_the_current_language` | `== "no resident (unknown: no LLAMASWAP_CONFIG)"` |

El humo en inglés lleva su guarda de «esto llegó a comprobar algo»: 18 frases inglesas que tienen que
estar en la salida (recibo de lectura, map-reduce, troceado, entrada truncada, cada error, la cabecera
de idioma, «(not summarized)»…), y la misma tanda en español **sí** trae palabras de la lista.

## Revisión a mano de las salidas en inglés

Volcado con backend falso (sin daemon): `evidence/B2a/outputs-en.txt` y `outputs-es.txt` (89 líneas
cada uno: recibos, map-reduce, troceado con entrada truncada, 7 errores, aviso de truncado, error de
conexión con su causa, HTTP 500, `local_status` completo y un resumen estructurado completado). Leído
entero. Lo que queda en español en la salida inglesa es, a propósito, de B2b-1: la palabra `aviso` de
`[local-delegate aviso: …]` y la clave `crudo` de `_local_delegate` (REQ-010). Detalles vistos:

- «1 sections not summarized» (y «1 secciones» en español, igual que antes): sin plural por número. No
  se cambia aquí (sería texto nuevo en los dos idiomas); anotado para B2b-1, que toca ese aviso.
- `local_status` mira el puerto del panel con un `connect` local (`Metrics web: active`), como ya hacían
  los tests de siempre; ninguna llamada a la API del daemon.

## Desviaciones

- **Ficheros fuera de la lista de B2** (aprobados por la sesión principal): `doctor.py` (usa
  `i18n.language_report`), `topology.py` (`REMOTE_BACKEND` y su clave), `cli.json` (esa clave),
  `scripts/measure_structured_summary.py` (lectura dual) y `scripts/data/spanish_lexicon.json`.
- **`failures.hint` reestructurado** en `hint` + `_hint_key`: mismas ramas, mismo resultado en español.
- **Mensajes internos** (excepciones de programación que no llegan a una persona) en estilo id, sin
  catálogo ni excepción del guardián.
- **Los esquemas de elicitation** dejan de fijarse en la clase: el título visible sale del catálogo al
  preguntar. En español, byte a byte el de antes (lo afirma el test de siempre).

## Pendientes para B2b-1 y siguientes

- B2b-1: forma nueva de los marcadores (`WARNING_MARKER`, `FALLBACK_MARKER`, `INPUT_TRUNCATED_MARKER` y
  el de `sections`) y de las subclaves de `_local_delegate` (`crudo`, `truncado`, `aviso`,
  `leido_server_side`, `respaldo` y sus internas); vaciar `PENDING_MARKERS` de `test_mcp_english.py`;
  descripciones en inglés (sus 6 excepciones `verbatim` siguen, ya en inglés); plural de
  `sections_not_summarized`.
- B2b-2: los 40 prompts siguen en español y como `verbatim`; la orden de idioma va detrás de `_guard`.
- B4: `failures.label/detail/hint(language=…)` con el `?lang=` del panel (D6).

## Llamadas `local_*`

| # | Llamada | Para qué | Resultado |
| --- | --- | --- | --- |
| 1 | `local_lint_summary(path=evidence/B2a/suite-es.txt)` | resumir la corrida entera | 2 `DeprecationWarning` de `testclient`, ningún fallo; su propio recibo aún dice «143,074»/«4,107» con coma: el daemon es la 0.35.0 |
| 2 | `local_commit_msg(path=<scratchpad>/b2a.diff)` | borrador del mensaje | «feat(i18n): implement full internationalization for local-delegate», **en inglés y de una línea**: es justo el fallo que arregla B2c (y el idioma, B2b-2). El mensaje se redactó a mano |

A mano y por qué: las ediciones de `server.py` y `questions.py` (CRLF) con un script de sustituciones
exactas que exige una coincidencia por texto (una tool local no puede editar conservando bytes); la
lectura literal de las franjas de `server.py` que se reescribieron; los conteos del guardián y del
detector, que los da el propio programa; la revisión del volcado inglés, que es revisión humana por
definición.
