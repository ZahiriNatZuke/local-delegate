# Verification: local_summarize: no sacar secciones de las cadenas de un fichero de código

## Environment

- Revision: rama `fix/summarize-code-string-literals` desde `origin/main` (`6eea8660`).
- Windows 11, Python del `.venv` del checkout principal con `PYTHONPATH=src` (importa el worktree).
- Backend falso (`backend_mock`); la prueba en vivo con el backend real la hace la sesión principal.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `.mjs` sintético de >6000 chars con un template literal Markdown: el prompt no lleva «Secciones, en orden» y la salida no gana títulos | pass | `tests/test_summarize_code_string_literals.py::test_a_code_file_does_not_take_the_structured_path`; con el arreglo revertido falla en `"Secciones, en orden" not in user` (la lista traía `state: ${status}`, `Specs`, `Plan`…) |
| REQ-002 | respuesta que copia `## state: ${status}`, `## Specs`, `## Verify`: aviso que los nombra, antes del recibo de ahorro; también en texto en línea | pass | `test_a_summary_that_copies_the_fixture_is_warned`, `test_inline_code_on_the_structured_path_is_warned`, tests del escáner; con la guarda anulada fallan en el `assert «…» in warning` |
| REQ-003 | resumen estructurado correcto de un `.md` con acentos graves sueltos, código en línea, comillas y una valla con template: sin aviso | pass | `test_a_real_markdown_document_is_not_warned`, `test_markdown_prose_with_stray_backticks_and_quotes_has_no_literal_lines`, `test_a_good_summary_of_the_code_has_no_copied_heading` |
| REQ-004 | entrada en CHANGELOG `[Unreleased]` → Corregido con (#539) | pass | `CHANGELOG.md` |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest` (suite completa, `-n 2`, con el cerrojo `pesado.sh`) | sí | ver entrega | salida en el scratchpad de la sesión |
| `ruff check src tests` | sí | pass | All checks passed! |
| `ruff format --check` (ficheros tocados) | sí | pass | formateado |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes. (lo hace el CI: GitGuardian)
- [x] No unrelated changes are present.

## Deviations and residual risk

- Texto en línea (sin `path`) que es código sigue yendo por el camino estructurado si tiene títulos:
  no hay extensión que mirar y cambiar `sections.detect` para todos arriesgaba documentos Markdown
  reales. La guarda sí avisa en ese caso.
- El escáner de literales es ligero, no un parser: un template abierto tras algo que no sea
  `= ( , : [ { + ? => return` no se ve; en código el `${…}` sin resolver cubre el caso del issue.
- Sin cambios de prompt.
