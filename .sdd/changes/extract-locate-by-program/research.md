# Research: local_extract: las líneas las calcula el programa y el esquema tiene tipos por campo (#692, #694, #696, #697, #698)

Punto de partida: `.sdd/changes/text-tools-common-cause/research.md` (2026-11-23, código de `main`
en `a776da37`, v0.53.0). Aquí no se repite: se cita por sección (§N) y se añade lo que pide este
cambio, que es el arreglo R1 (§7, «Localizar por programa») más R2 («Contrato tipado»). Las
causas que ataca son C1, C2 (en extract), C3, C4 (llamada única de extract) y C6 (§6).

Lecturas de esta investigación: `server.py` por rangos localizados con `grep` (8560-9250,
6495-6530, 8064-8090, 5160-5240, 5690-5710), `line_check.py` 795-1394, los 5 issues abiertos y
los 7 cerrados de la familia, y los tests de `tests/test_extract_*.py`. Sin pruebas en vivo (la PC
va cargada). Las tools `local_*` no estaban cargadas al empezar y llegaron a mitad de la sesión; no
se usaron para no cargar el modelo con la RAM justa (0 llamadas).

## Current behavior

Camino de un campo de ubicación hoy (`server.py`, `local_extract`, 8699-9247):

1. `line_check.is_location_field(name)` (`line_check.py:827-852`) decide por palabras del nombre
   si el campo pide líneas. Funciona: `lista_de_ficheros_con_sus_lineas` sí es de ubicación.
2. Con `path` y un campo así, el contenido va **numerado** (`N| línea`, `_number_lines`), con el
   esquema de títulos de un Markdown **con sus números de línea** delante (`_extract_outline_block`,
   8589-8598), y con la cláusula `_EXTRACT_LINES_CLAUSE` (8578-8583), cuyo ejemplo es
   «Título: líneas 120-160». **El modelo escribe los números.**
3. Solo en un diff y solo si el nombre pasa `asks_for_diff_files`/`asks_for_diff_hunks`
   (`line_check.py:997-1028`), el programa pone los rangos (`diff_file_hunks`). Esas dos funciones
   exigen que **todas** las palabras del sujeto estén en `_DIFF_FILE_SUBJECT_WORDS`: «sus» no está,
   así que `lista_de_ficheros_con_sus_lineas` vuelve al modelo (#697, comprobado en §2).
4. Llamada única con `max_tokens=512` fijo (8893); si se corta y hay campos de ubicación, se rehace
   en mitades (#666, 8915-8939).
5. Después, `line_check.check_values` (1311-1361) da por buena una cita si **una** palabra de 4+
   letras del valor aparece en la ventana, y usa la línea entera como nombre si el tramo previo no
   nombra nada (`_text_items`, 1239-1252): falsos negativos (#696, #694) y falsos positivos (#696,
   prueba A de §8). `outline_copy` (#594) y `section_only` (#633) son más heurísticas encima.
6. Esquema JSON (`_json_schema_payload`, 6509-6525): cada campo `string|number|boolean|null`; no
   hay arrays, así que una lista de 60 entradas va en una cadena y una lista corta puede acabar en
   `true` (#692).
7. Rol: `_extract_role` → `_table_role` → por tamaño (`_role_for_size`, 5697-5704; umbral 6000):
   un `.ts` de 5 K con un campo de líneas va a `gemma3-4b` (#694, prueba B de §8). Nunca `code`.
8. Troceado: `_numbered_code_pieces` solo corta por `def`/`class` de Python (`_TOP_LEVEL_NAME`,
   5161); un `.ts` se corta por párrafos.

## Lo que prometió cada arreglo cerrado (comportamientos que el rediseño conserva)

| Issue | Prometió | Cómo queda con el rediseño |
| --- | --- | --- |
| #460 | `local_explain_code` da líneas y verifica las citadas | Fuera de este cambio: explain_code y `line_check.check`/`citations` no se tocan (fase 2 de R1). |
| #568 | Un Markdown grande troceado no deja todo a null: cada trozo ve sus líneas absolutas y las ubicaciones se unen por programa, nunca en la reducción del modelo | Se conserva la unión por programa y la reducción sin campos de ubicación; el «ver las líneas» se sustituye por índice o anclas (las líneas ya no las ve ni las escribe el modelo). |
| #594 | Un campo de UN título (`x_heading_line`) da ese título, no el esquema entero; la línea 1 que es título no es dudosa | El modelo elige nombres del catálogo o copia un ancla; el programa da la línea. No hay copia posible del esquema con números; `outline_copies` se retira. |
| #616, #627 | explain_code no marca falsas citas correctas (constantes, prosa) | Fuera: explain_code intacto. |
| #633 | Pedir elementos (`tareas_con_lineas`) no devuelve solo el rango del apartado; un rango correcto no sale como dudoso | Cada elemento lleva su línea por ancla; `section_only_keys` se conserva como comprobación por programa sobre los elementos ya ubicados; ya no hay «dudosos» porque no hay números del modelo. |
| #665, #687 | Ficheros y hunks de un diff por programa; preámbulo en `.patch`; error del modelo al lado de los valores del programa (`model_error`); sin llamada al backend si todo lo contesta el programa, con fila `program_only` | Se conserva todo; se amplía a cualquier nombre que nombre ficheros (#697) y a todos los índices (no solo diff). |
| #666 | JSON cortado en la llamada única: se rehace en mitades, una sola fila de uso, el error dice `max_tokens` | Se conserva; además el tope de salida se calcula a la medida (menos cortes). La verificación `raw` de líneas citadas desaparece porque no hay números del modelo que verificar. |
| #586, #650, #667, #473, #455/#497 | Marcadores «sin dato», filas cruzadas, polaridad (las dos saltan los campos de ubicación), aviso de nulls al trocear, texto exacto y orden de `warning` | Se conservan sin cambios; los avisos nuevos se añaden al final, como hoy. |

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `server.py` `local_extract` (8699-9247) | Numerar, pedir números al modelo, verificar por palabras | Integra el índice y las anclas; quita la numeración, `check_values`, `outline_copy` y `_strip_extract_prefixes` del camino de extract | §Current behavior 2-5 |
| `server.py` 8560-8694 | Cláusula de líneas, esquema con números, unión de valores de ubicación | Cláusula nueva sin números; unión por `(name, start, end)` de elementos ya ubicados | 8578-8694 |
| `server.py` `_json_schema_payload` (6509) | Esquema primitivo igual para todos los campos | Delegado a un módulo nuevo con tipos por campo | 6509-6525; `tests/test_core.py:215-223` |
| `server.py` `_extract_role` (8081) | Rol por tamaño o tabla | Rol `code`/`long` para campos de ubicación que necesitan modelo | 8064-8087, 5697-5704 |
| `server.py` 8893 | `max_tokens=512` fijo | Tope por campo, con suelo 512 | #698 |
| `line_check.py` 795-1394 | Detección de campos, esquema Markdown, diff, verificación por palabras | Se quedan `is_location_field`, `markdown_outline`, `diff_file_hunks`; `asks_for_diff_*`, `check_values`, `outline_copy` y sus auxiliares se borran al final | 997-1028, 1311-1361 |
| Módulo nuevo `locate.py` (+ `locate_ts.py`) | — | Índices por tipo de fichero, clasificación de campos, resolución de anclas | R1 §7 |
| Módulo nuevo `extract_schema.py` | — | Tipo de cada campo, esquema, validación, presupuesto de salida | R2 §7 |
| i18n `resources/i18n/{es,en}/mcp.json` | Avisos `extract_lines_unverified`, `extract_outline_copies`, `extract_section_only` | Avisos nuevos (`unlocated`, `type_mismatch`, `role_reason` de ubicación); se retiran los dos primeros | `mcp.json:227-233` |
| Docs: docstring de `local_extract`, `README.md`, `docs/wiki/Tools.md:210-242`, `CHANGELOG.md`, `resources/skills/local-delegation/SKILL.md:104-110`, `resources/memory/local-delegate.md:21` | Describen la forma «Título: líneas X-Y» y `lines_unverified` | Forma nueva del valor y claves nuevas | grep de `lines_unverified`, `_con_lineas` |
| Tests | Ver inventario | Ver inventario | abajo |

## Inventario de tests que fijan líneas y tipos de `local_extract`

Leyenda: **conserva** (pasa sin tocarlo), **cambia** (misma promesa, otra forma de comprobarla),
**se borra** (la promesa desaparece con el diseño; motivo).

| Test | Qué fija hoy | Veredicto | Motivo |
| --- | --- | --- | --- |
| `test_extract_line_numbers.py::test_location_fields`, `test_not_location_fields` | Qué nombres piden líneas | conserva | `is_location_field` no cambia (se añaden casos en tests nuevos). |
| `…::test_markdown_outline_skips_fenced_code` | Esquema sin bloques de código | conserva | `markdown_outline` se reutiliza. |
| `…::test_every_chunk_carries_its_absolute_lines_and_the_outline` | Cada trozo numerado con líneas absolutas y esquema con números | cambia | Ahora: ningún trozo lleva `N| ` ni números en el catálogo; el catálogo de títulos va sin líneas; los trozos cortan por bloques del índice. |
| `…::test_a_single_call_is_numbered_too` | Llamada única numerada | cambia | Igual que el anterior para la llamada única (sin numeración, con catálogo). |
| `…::test_an_outline_too_long_is_left_out` | Esquema demasiado largo fuera del prompt | cambia | Se conserva el tope de catálogo (15 % del presupuesto), sin números. |
| `…::test_without_a_location_field_the_prompt_is_unchanged`, `…chunks_are_bare`, `…inline_text_is_never_numbered` | Sin campo de ubicación o con `text=`, nada cambia | conserva | REQ-019. |
| `…::test_the_prefix_leaves_the_other_fields` | Quitar `N| ` copiado en otros campos | se borra | La entrada ya no va numerada; `_strip_extract_prefixes` se retira. |
| `…::test_a_table_row_is_not_a_prefix` | `2|3` no se toca | conserva | Sigue siendo cierto (ya no hay limpieza de prefijos). |
| `…::test_the_model_reading_the_prefix_answers_with_real_lines` | El modelo lee el prefijo y da la línea real | cambia | `sections_with_lines` lo contesta el índice sin modelo; el test comprueba la línea exacta de `### Patronbq` con forma nueva. |
| `…::test_cited_lines_are_checked` | `lines_unverified` con líneas equivocadas del modelo | cambia | Pasa a «los números del modelo nunca llegan a la salida» (REQ-001). |
| `…::test_value_shapes_of_check_values`, `test_a_loose_number_next_to_an_explicit_citation_is_not_a_line`, `test_each_citation_is_checked_against_its_own_name` | Verificación por palabras | se borra | `check_values` se retira de extract (sin números del modelo no hay nada que verificar por palabras). |
| `…::test_the_lines_warning_is_appended_to_an_earlier_one` | Orden de avisos | cambia | El aviso de elementos sin ubicar se añade tras el de claves ausentes, con el mismo orden. |
| `…::test_sixty_sections_are_joined_by_program_without_a_reduce`, `…survive_a_cut_reduce` | 60 secciones unidas por programa | cambia | Mismas 60 secciones, ahora por índice y en forma `{name,start,end}`; la reducción cortada sigue sin perderlas. |
| `test_extract_section_lines.py::test_a_section_range_is_held_by_its_heading`, `…in_another_section_is_still_reported`, `…without_the_outline_the_check_is_unchanged` | `check_values` con esquema | se borra | Verificación por palabras retirada. |
| `…::test_section_only_depends_on_what_the_field_asks_for`, `test_items_with_their_lines_are_not_section_only` | `section_only` | cambia | `section_only` recibe elementos ya ubicados; la parte de `check_values` del segundo se quita. |
| `…::test_the_shape_of_the_issue_is_reported_and_its_ranges_hold` | #633 de punta a punta | cambia | Forma nueva; `section_only_keys` se sigue informando. |
| `…::test_the_prompt_does_not_ask_for_each_item` | El prompt acaba en «(por ejemplo «Título: líneas 120-160»).» | cambia | Fija el ejemplo que causa #694; pasa a comprobar que el prompt no contiene números ni «Título». |
| `test_extract_field_fidelity.py` (11 tests de `outline_copy`, #594) | Copia del esquema en un campo de un título | se borra (9) / cambia (2) | `outline_copy` se retira: la copia con números no puede darse. Se conservan, con forma nueva, `test_a_generic_title_on_a_heading_holds` → «un campo de un título da solo ese título» y `test_a_comment_in_fenced_code_is_no_heading` (catálogo sin comentarios de bloques). |
| `test_extract_diff_files_and_cut.py::test_fields_that_ask_for_the_files_of_a_diff`, `test_fields_that_do_not` | `asks_for_diff_files` | cambia | Pasan a `locate.classify_field`; `fichero_con_lineas` (singular) y `hunks_with_lines` dejan de ser «no»: van al índice del diff (uno elegido por el modelo; hunks). `files` y `file_name` siguen sin ser de ubicación. |
| `…::test_every_file_of_a_chunked_diff_comes_back`, `test_a_single_call_diff_is_answered_by_program_too`, `…survive_an_answer_that_is_not_json`, `…backend_error_beside_the_diff_files_is_not_silent`, `…json_that_is_not_an_object_keeps_the_diff_files`, `…cut_call_with_only_diff_files_is_not_retried` | #665 | cambia | Misma promesa; valor en forma nueva y meta `located` en vez de `diff_files`. |
| `…::test_another_location_field_over_a_diff_keeps_the_models_value` | Otro campo sobre diff conserva el valor del modelo | cambia | Ahora conserva los elementos que el modelo ancló, con líneas del programa; nunca su número. |
| `…::test_a_file_that_is_not_a_diff_is_left_to_the_model`, `test_an_inline_diff_is_left_to_the_model` | No inventar diff | conserva (forma nueva en el primero) | |
| `…::test_a_cut_single_call_is_retried_in_halves`, `test_a_retried_call_is_one_usage_row_that_reads_the_file_once`, `test_a_cut_call_too_small_to_split_says_max_tokens`, `test_a_cut_answer_without_location_fields_is_not_retried`, `test_an_answer_that_is_not_json_without_a_cut_keeps_its_error` | #666 | conserva / cambia | El reintento en mitades y el error con `max_tokens` se conservan; el doble del backend ajusta la forma (anclas en vez de números). |
| `…::test_an_answer_that_stays_cut_says_max_tokens_and_checks_its_lines`, `test_a_cut_chunk_beside_good_ones_has_its_lines_checked` | Verificación `raw:` de líneas de respuestas cortadas | cambia | Se queda «dice `max_tokens`»; la parte `raw:` en `lines_unverified` se borra (no hay números del modelo). |
| `test_extract_diff_files_names.py` (4 de nombres) | `asks_for_diff_hunks`, `changed_files` | cambia | A `classify_field`; se añaden `lista_de_ficheros_con_sus_lineas`, `ficheros_que_cambian_con_sus_lineas`. `test_counts_stay_counts` conserva. |
| `…` (11 de servidor: 92 KB, 6000 líneas, preámbulo, sin cabeceras, sin hunks, `program_only`, fila de uso, panel, `read_server_side`, campo extra) | #665/#687 | cambia (forma) | Misma promesa, forma nueva; `test_a_patch_without_file_headers_says_so` conserva el aviso. |
| `test_core.py::test_json_schema_payload_restricts_properties_to_primitives` | Todo campo `string/number/boolean/null` | cambia | Tipos por campo: sin `boolean` salvo preguntas; `items` primitivos o el objeto fijo de ubicación; sin objetos anidados libres (la protección de gemma3-4b sigue). |
| `test_summarize_word_budget.py:80-90` | Tope del map de extract `{512}` con un campo escalar | conserva | El presupuesto nuevo tiene suelo 512. |
| `test_extract_polarity.py::test_the_value_comes_back_word_for_word_with_path_and_lines`, `test_location_fields_are_not_checked` | Polaridad salta ubicación | conserva | El valor de ubicación con forma vieja provoca un reintento de tipos y luego null; las aserciones no dependen de él. |
| `test_extract_cross_fill.py:299-303` | `cross_filled(skip=…)` | conserva | |
| `test_extract_cross_fill.py::test_local_extract_reports_a_cross_and_keeps_the_value` (259-263) y 273-286 | Números en campos con nombre plural (`licensed_user_limits: 40`) | conserva | REQ-016: un número no incumple `list`; sin reintento. Hallazgo de la revisión del plan. |
| `test_extract_placeholder_values.py::test_the_issue_comment_case` (202-220), `::test_no_recount` (311-316) | Recuentos `number_of_*` sin `_local_delegate` | conserva | REQ-015: `count` admite número; sin reintento ni `type_mismatch_keys`. |
| `test_extract_failed_usage_row.py` | Fila fallida con JSON cortado | conserva | Un JSON que no se parsea no es un fallo de tipos; sin reintento nuevo. |
| `test_explain_code_*.py` | Citas de explain_code | conserva | Fuera de alcance. |
| `test_extract_table_routing.py`, `test_extract_table_routing_docs.py` | Regla de tabla y su `role_reason` | conserva | La regla de ubicación es otra razón; la de tabla no cambia. |

## Existing conventions

- Código y claves JSON en inglés; textos de salida en es + en por i18n (memoria
  `cli-nombres-en-ingles`); paridad comprobada por `tests/test_i18n_parity.py` y
  `tests/test_no_uncatalogued_text.py`.
- Avisos: `warning` conserva su texto y orden (contrato #455/REQ-010); lo nuevo se **añade al final**
  y lleva además su propia clave estructurada.
- Fila única de uso por llamada a la tool; un reintento se pliega (`_fold_retried_row`, #666).
- Una respuesta 100 % del programa escribe fila `program_only` con `PROGRAM_MODEL` (#687).
- Un fix no rompe otra cosa: tests existentes intactos salvo los listados arriba, con motivo
  (memoria `fix-sin-regresiones`).
- Sin dependencias nuevas (el lexer de TS/JS se escribe; `ast` es stdlib). Expresiones regulares
  lineales, sin retroceso catastrófico sobre la entrada.
- Presupuesto en caracteres y límite del modelo en tokens (memoria `presupuesto-en-chars-limite-en-tokens`):
  los números se tokenizan casi a un token por dígito; quitarlos de la entrada y de la salida
  también ahorra tokens.

## Dependencies and integrations

- SDD hermano `text-tools-binary-and-lint-paths` (otro agente, R3 y R4): toca `_decode_input_file`
  y `_read_input` (`server.py:1090-1170`) y `lint_patterns.py`. Este cambio **depende** de su punto
  de control de binarios: el índice se construye sobre el texto que devuelve `_read_input`, y sin
  ese control un binario leído como latin-1 daría un índice vacío y anclas que no casan (null con
  aviso, no un fallo, pero se gasta una llamada). No se duplica: aquí no se toca la lectura.
  **Actualización 2026-11-23:** ya está mezclado en `main` (`ce09fc5a`, PR #709): `_read_input`
  rechaza binarios antes de decodificar. Los implementadores parten de `origin/main` con ese commit;
  los tests de servidor de este cambio no necesitan cubrir binarios. Conflicto previsible solo en
  `CHANGELOG.md` (`[Unreleased]`).
- Producción trocea (memoria `produccion-trocea`): las pruebas de troceado deben usar entradas por
  encima de `max_chars` del rol que toque (`code` 20 000, `long` 48 000).
- Clientes: hook de subagentes, skill y memoria que recomiendan `…_con_lineas` (§4 de la causa
  común). Este cambio solo actualiza el texto que describe la forma; el resto de R7 queda fuera.

## Risks and unknowns

- **Riesgo alto, cambio de contrato visible**: los valores de ubicación dejan de ser cadenas. Los
  consumidores son agentes que leen JSON y la descripción de la tool; se documenta en la
  descripción, CHANGELOG, README y wiki. Sin interruptor de compatibilidad (decisión D3 del spec).
- **Lexer de TS/JS**: plantillas anidadas, regex literales y JSX pueden confundirlo. Mitigación:
  si las llaves no cuadran al final, el índice se descarta para ese fichero y se avisa; las anclas
  siguen dando la línea.
- **Hecho comprobado**: `gemma4-26b-a4b` dio bien las 60 líneas cuando el trozo era pequeño (§5);
  el fallo era el corte y la verificación. **Suposición pendiente**: que un modelo copie anclas
  literales con fidelidad suficiente; se mide en la prueba en vivo final (no ahora).
- **Suposición**: el modelo elige bien nombres de un catálogo de hasta 300 entradas con `enum` en
  el esquema; llama-server admite `enum` en la gramática JSON (a confirmar en la prueba en vivo; si
  no, el nombre va como cadena libre y el programa lo empareja exacto).
