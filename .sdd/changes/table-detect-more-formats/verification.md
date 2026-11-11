# Verification: Detector de tablas: GFM sin tuberías externas, |-|-|, CSV, TSV y ARIA; local_summarize sube a long con tabla (#650)

## Environment

- Revision: rama `fix/table-detect-more-formats` sobre `332f0e36` (v0.51.0)
- Relevant runtime and tool versions: Python 3.11 del `.venv` del checkout principal con `PYTHONPATH=src`; ruff del mismo `.venv`

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests GFM sin tuberías externas, compact, alineado | pass | tests/test_table_detect.py::test_the_shapes_of_650_are_seen_with_their_format; mutante «sin GFM» matado |
| REQ-002 | tests CSV, CSV con celda vacía, comillas, punto y coma, CRLF, TSV | pass | mismo test; mutante «sin CSV/TSV» matado |
| REQ-003 | 21 negativos de prosa, código, logs, YAML, JSON; barrido de src, tests y docs | pass | test_prose_code_logs_yaml_and_json_are_not_tables; test_the_python_and_markdown_sources_of_the_repo_are_not_csv_or_tsv; mutante «sin filtro de prosa» matado |
| REQ-004 | ARIA positivo, clases negativas | pass | test_the_shapes_the_rule_does_not_see_stay_false; mutante «sin ARIA» matado |
| REQ-005 | 12 entradas hostiles de 1 MB en proceso hijo, menos de 1 s; sin `re` | pass | test_a_hostile_input_ends_in_less_than_a_second; test_the_module_uses_no_regular_expression |
| REQ-006 | lectura del docstring | pass | src/local_delegate/table_detect.py líneas 1 a 40 |
| REQ-007 | `format` en role_reason de extract | pass | tests/test_extract_table_routing.py (casos de la investigación y formatos de #650); mutante «extract sin format» matado |
| REQ-008 | lectura de la descripción de local_extract | pass | server.py, docstring de `local_extract` |
| REQ-009 | summarize sube con tabla, aviso con formato, fila con role_reason; prosa y grande no | pass | tests/test_summarize_table_routing.py; mutantes «summarize sin regla» y «sin aviso» matados |
| REQ-010 | interruptor apagado, por defecto encendido, registrado, independiente | pass | test_the_switch_turns_it_off, test_the_switch_is_on_by_default_and_registered, test_extract_switch_does_not_turn_off_summarize |
| REQ-011 | docstring, sin fuga, sin camino estructurado | pass | test_the_docstring_names_the_rule_and_its_switch, test_the_reason_does_not_leak_to_the_next_operation, test_a_raised_small_input_keeps_the_single_call |
| REQ-012 | superficies nombran el interruptor, `format`, TSV, ARIA y la receta | pass | test_each_surface_names_the_switch, test_the_docs_name_format_and_the_recipe_names_the_rule |
| REQ-013 | CSV y TSV no abren las cifras de #630 | pass | tests/test_summarize_grounding.py::test_csv_and_tsv_do_not_open_the_figures_check; mutante «cifras en todo formato» matado |
| REQ-014 | TSV y CSV con última celda vacía | pass | casos tsv-empty-last-cell y csv-empty-last-cell; mutante «rstrip quita tab final» matado |
| REQ-015 | backend que falla tras subir el rol | pass | test_a_failed_call_still_logs_the_reason |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| ruff check (src/local_delegate y tests tocados) | sí | pass | All checks passed |
| ruff format --check (ficheros tocados) | sí | pass | 6 files already formatted |
| pytest de la zona (5 ficheros) | sí | pass | 215 passed |
| mutantes de control positivo (9) | sí | pass | los 9 matados, ficheros restaurados |
| pytest suite entera con -n 2 | no | skip | pausa por recursos ordenada por el coordinador; se corta y queda para cuando avise (o el CI del PR) |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Calibrado del detector: un script de scratchpad pasó `table_format` por todo el árbol del repo
  (fuentes, docs, SDD, benchmarks; unos 4 400 ficheros de texto). Resultado: ningún `csv`/`tsv` en
  `.py`, `.md`, `.json`, `.jsonl`, `.log`, `.yaml`, `.toml`, `.js`, `.ts`, `.sh`; los aciertos
  nuevos son 33 `.csv`, 3 `.tsv`, 28 `.txt` con salidas tabulares de git (`ls-files --eol`,
  `name-status`) y 2 diffs que traen tablas; ninguna tabla que viera la regla vieja se pierde. Dos
  falsos positivos encontrados (una lista de ficheros partida en un commit y un `.ps1` con `@(`) se
  corrigieron y quedaron como tests. Del holdout del #586, el CSV con `;` y coma decimal (c20) y el
  TSV (c21) se ven; la lista Markdown (c24) y las notas `clave: valor` no.
- Volumen: no se midió cuántos resúmenes pequeños subirán a `long` en el uso real; el log de uso
  real queda fuera de este encargo. Riesgo: más cambios de modelo en el backend compartido. Se
  apaga con `LOCAL_DELEGATE_SUMMARIZE_TABLE_LONG=0`.
- No cambia ningún prompt; la prueba en vivo de latencia y del aviso la decide la sesión principal.
