# Verification: local_extract: aviso de valor cruzado entre claves (cross_filled_keys, #650)

## Environment

- Revision: rama `feat/extract-cross-filled-warning` sobre `332f0e36` (v0.51.0).
- Relevant runtime and tool versions: Python 3.14 del `.venv` del checkout principal con
  `PYTHONPATH=src`; pytest con xdist (`-n 2`), ruff del mismo `.venv`. Sin backend: el detector se
  mide sobre respuestas, no sobre un modelo, y `local_extract` se prueba con `_run_chat` doblado.

## Puerta de medición

| Conjunto | Respuestas | Avisos en falso | Cruces detectados | Cruces sin aviso |
| --- | --- | --- | --- | --- |
| Nuevo (`tests/data/cross_fill/new_cases.json`, 36 tablas) | 71 | 0 | 40 | 25 |
| `holdout` correctas (24 casos del 2026-11-10) | 24 | 0 | — | — |
| `holdout` cruzadas | 24 | 0 | 30 de 49 | 19 |
| Respuestas reales grabadas (`recorded_runs.json`) | 58 | 0 | 5 de 12 | 7 |

Cruces del #586 detectados con su fila y clave: `01-pricing-table-en/licensed_user_limits`
(«Custom domains», `custom_domain_limits`) en `g3-extract` y `g3-proxy`, y
`06-limits-table-es/limite_usuarios_con_licencia` en las dos. El aviso en falso de ayer
(`c01/price`, «Retail cost (USD)») ya no salta. Lo fija `test_gate_totals` (0 falsos positivos y al
menos 75 cruces).

## Control positivo (mutantes)

Segunda pasada: los 15 mutantes mueren (M6 lo mata el caso n36). Cada mutante se aplicó al código y se corrió `tests/test_extract_cross_fill.py`; se restauró después
(comprobado con `cmp`).

| Mutante | Resultado |
| --- | --- |
| M1 sin la regla de fila única | muere (1 test) |
| M2 sin contar el valor en el texto | muere (2) |
| M3 el empate cuenta | muere (27) |
| M4 sin filtro de triviales | muere (1) |
| M5 server no llama al detector | muere (2) |
| M6 una palabra suelta basta para casar | muere (3) |
| M7 prosa alrededor de celdas cuenta | muere (4) |
| M8 trozo de celda cuenta | muere (3) |
| M9 coma CSV como coma decimal | muere (4) |
| M10 cabecera solo en tablas de más de dos columnas | sobrevivía: la regla era redundante con el encaje real y se quitó |
| M11 sin saltar los campos de ubicación | muere (1) |
| M12 cabeceras de varias columnas suman | muere (3) |
| M13 la fila no tiene que ser la propia de la otra clave | muere (2) |
| M14 presupuesto en celdas y no en caracteres | muere (1) |
| M15 sin tope para el HTML | muere (1) |
| M16 captura solo ValueError | muere (5) |

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_a_value_from_the_row_of_another_key_is_flagged | pass | pytest tests/test_extract_cross_fill.py |
| REQ-002 | test_local_extract_reports_a_cross_and_keeps_the_value | pass | pytest |
| REQ-003 | test_a_value_repeated_elsewhere_is_not_flagged, n31, n32 | pass | pytest; M1 y M2 mueren |
| REQ-004 | test_label_words_are_normalized | pass | pytest |
| REQ-005 | test_trivial_values_are_not_flagged | pass | pytest; M4 muere |
| REQ-006 | test_strings_inside_a_list_or_an_object_are_checked | pass | pytest |
| REQ-007 | test_gate_totals | pass | tabla «Puerta de medición» |
| REQ-008 | test_the_crosses_of_586_are_flagged | pass | pytest |
| REQ-009 | test_yesterdays_false_positive_stays_quiet | pass | pytest |
| REQ-010 | test_new_set_flags_only_crossed_keys y los parametrizados del holdout y lo grabado | pass | pytest |
| REQ-011 | test_the_warning_is_appended_after_an_earlier_one | pass | el aviso anterior queda exacto; M5 muere |
| REQ-012 | test_the_docstring_names_cross_filled_keys; CHANGELOG y wiki | pass | pytest; git diff |
| REQ-013 | git diff de server.py | pass | solo import, llamada, aviso y descripción |
| REQ-014 | casos n26 a n30 | pass | M6, M7 y M8 mueren |
| REQ-015 | test_location_fields_are_not_checked | pass | M11 muere |
| REQ-016 | test_an_odd_source_never_breaks_the_answer, test_a_long_row_label_is_cut_in_the_warning | pass | pytest |
| REQ-017 | casos n33 a n36; test_a_big_html_page_is_not_scanned, test_the_budget_counts_characters_not_cells, test_an_unexpected_error_never_breaks_the_answer | pass | pytest; M12 a M16 mueren |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test (zona) | pytest tests/test_extract_cross_fill.py y vecinos de extract, i18n y textos catalogados | pass | 355 passed; tras el último cambio, 300 passed (cross_fill, nombres en español, enrutado de tablas) |
| test | pytest -q -n 2 (suite entera, tras la segunda pasada) | pass | 7545 passed, 30 skipped, 1 failed: test_build_hook por un register.js generado (ignorado por git) que dejó la corrida anterior en el worktree; borrado, ese test pasa (2 passed). La primera corrida dio 7477 passed y el fallo de nombres en español, ya arreglado |
| lint | ruff check y ruff format --check sobre los ficheros tocados | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- El detector se prototipó durante la investigación para medir el diseño con datos, antes de la
  spec (lo pedía el encargo: «decide tú con datos»).
- Riesgo residual: entradas reales con etiquetas que casen de verdad con otra clave y un valor
  correcto que no se repite (no visto en 177 respuestas). El aviso no cambia el valor.
- Cobertura limitada a propósito: valores repetidos, empates, etiquetas en otro idioma y filas que
  no son de ninguna clave pedida no avisan.
- `_DIGIT_GAP` puede unir dos números separados por un espacio al contar (ver review.md F10).
- Prueba en vivo no hecha: no cambia el prompt ni el enrutado; la puede hacer la sesión principal.
- Se añadieron 18 palabras inglesas a `scripts/data/spanish_lexicon.json` (las pide `test_detect_spanish_names` para los identificadores nuevos).
