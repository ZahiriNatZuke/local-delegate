# Verification: local_extract: aviso de valores sin respaldo y campos de línea por título

## Environment

- Revision: rama `fix/extract-fidelidad-campos` (PR #609) sobre `origin/main`.
- Relevant runtime and tool versions: Python del `.venv` del checkout principal con `PYTHONPATH=src`
  (importa el worktree, comprobado); ruff del mismo `.venv`.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-003 | tests/test_extract_field_fidelity.py: recorte sin duda (101/46, `uso`, `guiaHeadingLine`); aviso sin recorte con `tools_section_line`, `tool_heading_line`, `pasos_heading_line`, `intro_heading_line`; humo con `docs/wiki/Tools.md` de la 0.49.0 y el valor exacto que devolvió la tool en vivo | pass | humo: `` "`local_extract`: 101" ``, `` "`local_summarize`: 46" ``, sin `lines_unverified`; mutante sin la regla del plural hace fallar `tools_section_line` y `pasos_heading_line`; mutante con recorte por prefijo hace fallar `tool_heading_line` |
| REQ-004 | tests/test_extract_field_fidelity.py: 7 nombres de varios sitios (`capitulos_con_linea`, `line_of_each_heading`, `linea_de_cada_seccion`…) no son copia | pass | mutante sin `each`/`cada` hace fallar sus dos casos |
| REQ-005 | tests/test_extract_field_fidelity.py: `Título: línea 1` vale; `línea 2` (junto al encabezado), `línea 3` y un `# comentario` en bloque de código no; `title:` de front matter sigue valiendo | pass | mutante con la ventana hace fallar `test_a_comment_in_fenced_code_is_no_heading` |
| REQ-006 | review del diff de docstring, `docs/wiki/Tools.md` y CHANGELOG | pass | sin rastro de `ungrounded_keys` (`git grep`) |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| uv run --locked pytest (equivalente: `.venv` + `PYTHONPATH=src` + `-n 2`, con `pesado.sh`) | sí | pass | 6718 passed, 29 skipped |
| ruff check / ruff format --check (src tests scripts) | sí | pass | All checks passed; 367 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Retirado tras la revisión independiente: el aviso `ungrounded_keys` (antiguos REQ-001/002) daba
  avisos falsos en usos normales (traducciones, clasificaciones, fechas, paráfrasis). #586 queda
  para el cambio del prompt (`fix/extract-prompt-sin-relleno`).
- Conservador a propósito: un sujeto que acaba en `s` sin ser plural (`status_heading_line`) solo
  avisa, no recorta.
- Un encabezado que contiene una cita («Líneas 10-20») deja una cita falsa en el valor recortado:
  raro, y `check_values` lo marcaría como dudoso.
- Sin prueba contra el backend real del valor recortado: la tool instalada (0.49.0) reprodujo #594
  en vivo antes del cambio y el humo usa ese valor exacto.
- Excepciones de datos añadidas: cuatro nombres de campo en español en
  `scripts/data/name_exceptions.json` y `capitulos`/`doubtful` en el léxico, como en #568/#573.
