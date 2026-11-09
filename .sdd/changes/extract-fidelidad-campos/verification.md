# Verification: local_extract: aviso de valores sin respaldo y campos de línea por título

## Environment

- Revision: rama `fix/extract-fidelidad-campos` sobre `origin/main` (`ac33807a`).
- Relevant runtime and tool versions: Python del `.venv` del checkout principal con `PYTHONPATH=src`
  (importa el worktree, comprobado); ruff del mismo `.venv`.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests/test_extract_field_fidelity.py (veredicto inventado, tildes/plurales/subcadena, aviso añadido al final) | pass | 25 passed; mutante `words = []` hace fallar `test_a_made_up_verdict_is_said` y `test_the_warning_is_appended_to_an_earlier_one` por su assert |
| REQ-002 | tests/test_extract_field_fidelity.py (valores exentos, valores copiados de la entrada sin meta) y los 4 tests existentes que fijan valores sin `_local_delegate` | pass | `-k "extract or line_check or i18n or core"`: 356 passed sin tocar tests existentes |
| REQ-003 | tests/test_extract_field_fidelity.py (recorte a 101/46, sin título único se deja) + humo con `docs/wiki/Tools.md` de la 0.49.0 y el valor exacto que devolvió la tool en vivo | pass | humo: `"`local_extract`: 101"`, `"`local_summarize`: 46"`, sin `lines_unverified`; mutante `if False:` hace fallar los dos tests de recorte |
| REQ-004 | tests/test_extract_field_fidelity.py (`sections_with_lines` intacto; plurales `tools_with_lines`, `tool_sections_with_lines`, `local_headings_lines` nunca se recortan) | pass | mutante sin la regla de plural hace fallar los 3 casos plurales |
| REQ-005 | tests/test_extract_field_fidelity.py (`Título: línea 1` vale, `línea 3` no) | pass | mutante sin la regla hace fallar `test_a_generic_title_on_a_heading_holds`; sin la palabra como alternativa falla `test_a_title_word_on_a_front_matter_still_holds` |
| REQ-006 | review del diff de docstring, `docs/wiki/Tools.md` y CHANGELOG | pass | límite «otra fila» explicado en los tres |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| uv run --locked pytest (equivalente: `.venv` + `PYTHONPATH=src` + `-n 2`, con `pesado.sh`) | sí | pass | 6723 passed, 29 skipped (suite completa tras la revisión) |
| ruff check / ruff format --check (ficheros tocados) | sí | pass | All checks passed; formato aplicado a line_check.py |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Tras la revisión (review.md F1–F6): JSON decodificado (mutante falla `test_a_json_input_is_read_decoded`) y nulos en listas (mutante falla `test_normalized_answers_and_nulls_in_a_list_are_not_flagged`).

- El umbral de palabras (5+ letras, sin dígitos) deja fuera números y palabras cortas: un número
  inventado o «algo» no se avisan. Se eligió así porque cuatro tests existentes fijan que esos
  valores salen sin `_local_delegate` y porque los números se reformatean.
- No se detecta un valor copiado de otra fila u otro campo de la entrada (caso HTML del
  2026-11-08): sus palabras están en la entrada. Arreglarlo pide reforzar el prompt de
  `local_extract`, lo que cambia las fixtures `tests/fixtures/request_bodies/extract_schema*.json`
  (tests existentes) y exige una frontera en `PROMPT_BOUNDARIES`: fuera de alcance, #586 queda con
  `Refs`.
- Falsos avisos posibles: una traducción o normalización legítima («Spanish» de un texto en
  español) sale con aviso; el valor no se toca.
- Sin prueba contra el backend real: reinstalar el daemon tiraría el MCP de los otros agentes de
  la jornada; la tool instalada (0.49.0) sí reprodujo #594 en vivo antes del cambio.
