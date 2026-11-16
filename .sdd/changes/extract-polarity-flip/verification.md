# Verification: local_extract: aviso cuando un valor invierte la negacion de la fuente

## Environment

- Revision: rama `fix/extract-polarity-flip` sobre `main` 402f99e3
- Relevant runtime and tool versions: Python 3.14 del `.venv` del repo, pytest con xdist, ruff del proyecto; Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_the_value_comes_back_word_for_word` (texto y `path` con campo de ubicación) y `test_an_input_of_the_issue_size_is_one_call` | pass | el valor del modelo vuelve tal cual; 3219 caracteres son una llamada sin `chunked`: la causa es el modelo, no el post-proceso ni el troceado |
| REQ-002 | `test_a_flipped_clause_is_flagged` (6 casos) y `test_the_issue_flag_names_both_clauses` | pass | el texto exacto del issue sale con `flip` = `added` |
| REQ-003 | `test_a_faithful_clause_is_not_flagged` (17 casos), corte de línea en cada palabra, `test_no_answer_of_the_gate_is_flagged` y `test_every_sentence_copied_from_the_docs_stays_quiet` | pass | 0 avisos en 177 respuestas guardadas y en cada frase de la wiki y del CHANGELOG |
| REQ-004 | tests de orden del aviso, catálogos es/en, campos de ubicación, fuente enorme o vacía, excepción, presupuesto y tiempo lineal | pass | ver tests/test_extract_polarity.py |
| REQ-005 | suite completa con `pesado.sh` y `-n 2`; ruff | pass | ver «Commands» |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest -q -p no:cacheprovider -n 2 --dist loadgroup | 2026-11-16 10:05 (hora de Uruguay) | pass tras un arreglo | 7830 passed, 31 skipped, 1 failed: `test_repo_has_no_spanish_name_outside_the_exception_list` por palabras nuevas sin clasificar; clasificadas en `scripts/data/spanish_lexicon.json` y dos nombres de test pasados a inglés; ese test y los del área, 126 passed |
| pytest de los 11 ficheros `tests/test_extract_*` | 2026-11-16 | pass | 509 passed antes de la revisión; tras ella, `test_extract_polarity.py` en verde |
| ruff check . y ruff format --check src tests | 2026-11-16 | pass | sin avisos |
| control positivo sobre `main` | 2026-11-16 | pass | con el `server.py` de `main`, `test_local_extract_reports_a_flip_and_keeps_the_value` falla con `KeyError: '_local_delegate'` (no hay aviso: la razón del issue) y el del docstring también |
| mutantes de `polarity.py` | 2026-11-16 | pass | 12 de 12 muertos: alcance hacia delante, cláusula negada vecina, celdas, encabezado, línea `...:`, exclusión de la palabra negada, doble negación, unión de líneas, clave con prohibición, palabra negada en las dos ramas y el propio aviso |
| scripts/detect_spanish_names.py | 2026-11-16 | pass | 0 fuera de la lista y 0 sin clasificar |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Sin prueba en vivo: el prompt no cambia, así que no la necesita; la entrada real del issue no se
  publicó y los tests usan una reconstruida con su misma forma.
- Límites documentados en la wiki: una frase que el modelo une con otra hasta no parecerse a
  ninguna de la entrada, e idiomas sin raíces comunes con el de la entrada, no se ven.
