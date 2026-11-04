# Verification: local_extract numera las líneas con path para campos de ubicación (#568)

## Environment

- Revision: rama `fix/extract-line-numbers` desde `origin/main` 2ef5cf44
- Relevant runtime and tool versions: Python del `.venv` del repo, `PYTHONPATH=src` (worktree)

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test `test_every_chunk_carries_its_absolute_lines_and_the_outline`, `test_a_single_call_is_numbered_too` | pass | tests/test_extract_line_numbers.py; fallan con el server.py de main |
| REQ-002 | tests `test_location_fields`, `test_not_location_fields`, `test_without_a_location_field_*`, `test_inline_text_is_never_numbered` | pass | prompt byte a byte igual al de main |
| REQ-003 | test `test_the_prefix_leaves_the_other_fields` | pass | en main devuelve `3\| Juan Pérez` |
| REQ-004 | tests `test_every_chunk_carries_...`, `test_markdown_outline_skips_fenced_code`, `test_an_outline_too_long_is_left_out` | pass | esquema con línea real, sin lo de dentro de bloques de código |
| REQ-005 | test `test_cited_lines_are_checked`, `test_the_model_reading_the_prefix_answers_with_real_lines` | pass | `lines_unverified` con la línea equivocada y la de fuera del fichero |
| REQ-006 | review del diff de SKILL.md y SKILL.en.md | pass | frase nueva tras «Citar `archivo:línea`…» |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest (suite completa, `-n 2`) | sí | pass | 6504 passed, 30 skipped; el único fallo (léxico: `outline`, `qualifiers`) se arregló y su test pasa (86 passed en detector + tests nuevos) |
| control positivo | sí | pass | con el `server.py` de main fallan 7 tests nuevos; mutante sin descuento del esquema → falla `assert 38963 <= 38444` |
| ruff check / ruff format --check | sí | pass | sin hallazgos |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- La comprobación de líneas es por palabras (≥4 letras) del elemento: si el elemento solo nombra
  palabras genéricas que también están en la línea citada («Componente»), una línea equivocada
  pasa. Es un aviso conservador, no una prueba de exactitud.
- El esquema de encabezados no va al recibo (gastaría contexto de Claude); solo al prompt.
