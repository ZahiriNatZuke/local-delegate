# Verification: Lectura con path: ficheros que no son UTF-8 y falsos «datos inventados» con m²/m³ (#672)

## Environment

- Revision: rama `fix/path-input-encoding` sobre `402f99e3` (main)
- Relevant runtime and tool versions: Python 3.11.15 del `.venv` del checkout principal con `PYTHONPATH=src`; ruff del mismo `.venv`

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | UTF-8 con CRLF y con BOM igual que `read_text`, sin aviso | pass | tests/test_input_encoding.py::test_a_utf8_file_reads_as_before_and_carries_no_encoding, test_a_utf8_file_with_its_bom_reads_as_before |
| REQ-002 | cp1252, Latin-1 con bytes no definidos, UTF-16 LE y BE con BOM, BOM con cuerpo roto | pass | tests/test_input_encoding.py, tests del lector |
| REQ-003 | aviso en summarize (llamada única, troceado y estructurado), extract (respuesta y error), explain_code, lint_summary (con hallazgos y limpio), commit_msg y translate; error con su prefijo | pass | tests/test_input_encoding.py, una prueba por tool y test_an_error_keeps_its_prefix_first |
| REQ-004 | repro del issue de punta a punta; `m²` frente a `m2`; tilde descompuesta | pass | test_summarize_of_the_issue_warns_of_the_encoding_and_not_of_invented_data, test_a_unit_with_a_superscript_is_not_a_foreign_word, test_a_decomposed_accent_in_the_source_holds_the_composed_word |
| REQ-005 | CHANGELOG Unreleased, docs/wiki/Tools.md, paridad de catálogos | pass | tests/test_i18n_parity.py; lectura de CHANGELOG.md y Tools.md |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest tests/test_input_encoding.py sin el arreglo | sí | 18 fallan, 2 pasan (los de control UTF-8) | reproducción antes del arreglo |
| pytest de las áreas tocadas (core, summarize, extract, explain, lint, commit, i18n) | sí | 1221 passed | -n 2 |
| pytest suite completa -n 2 --dist loadgroup | sí | 7775 passed, 31 skipped | cerrojo pesado.sh; antes, 1 fallo del detector de nombres arreglado |
| ruff check y ruff format --check | sí | pass | src y test nuevo |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Orden: el test de la repro y el arreglo se escribieron antes que spec.md y plan.md; las puertas se pasaron después, con el código ya revisado.
- Un fichero casi todo UTF-8 con un solo byte inválido se lee entero como cp1252 (sus tildes UTF-8 salen como «Ã¡»); antes solo se perdía ese byte. El aviso lo dice.
- La revisión de idioma de #630 ya no juzga caracteres que no son letras: un cambio de unidad (`m³` por `m²`) no avisa; esa revisión es de idioma, no de unidades.
- Un binario o un UTF-16 sin BOM se lee como cp1252 con aviso, no peor que antes.
