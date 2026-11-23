# Implementation plan: Tools de texto: rechazo de binarios y rutas exactas en lint_summary

## Approach

- **R3:** `_read_input` (`server.py:1149`) es el único lector de `path` de las tools de texto
  (summarize 8154, extract 8766, lint 9391, commit_msg 9509, translate 9708, explain_code 9751) y
  corre antes de cualquier llamada al backend. Ahí se leen los bytes, una función pura
  `_binary_kind(raw)` decide (firma → NUL → proporción de control) y, si es binario, sale
  `InputError` con un mensaje i18n. `_decode_input_file` pasa a decodificar los bytes ya leídos.
- **R4:** en `lint_patterns.py`, `files_by_frequency` descarta los spans dentro de una URL y une
  cada absoluta a su relativa; `reported_files` quita además los ficheros que solo nombran líneas
  de progreso de pytest en verde, y es lo que usan el inventario (`server._lint_inventory`,
  `_lint_final_inventory`, `_lint_map_user`) y `not_mentioned`. `invented_files` compara ruta
  completa y carpetas con un límite de carpeta, sin tocar `mentions` (que usa también
  `not_mentioned` y explain_code: cambiarlo volvería más estricta la otra dirección).

## Ordered tasks

- [x] T1 — Tests rojos de R3 y R4 antes del arreglo (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008)
  - Files or modules: `tests/test_binary_input.py`, `tests/test_lint_exact_paths.py`
  - Verification: corren contra `main` y fallan por el assert del arreglo; los controles (UTF-8 con acentos, UTF-16 con BOM) pasan ya
  - Depends on: none
- [x] T2 — Rechazo de binarios en `_read_input` (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: `src/local_delegate/server.py`, `src/local_delegate/resources/i18n/{es,en}/mcp.json`
  - Verification: `tests/test_binary_input.py` y `tests/test_input_encoding.py` en verde
  - Depends on: T1
- [x] T3 — Rutas exactas en lint (REQ-005, REQ-006, REQ-007, REQ-008)
  - Files or modules: `src/local_delegate/lint_patterns.py`, `src/local_delegate/server.py`, i18n del aviso de inventados
  - Verification: `tests/test_lint_exact_paths.py` y toda la suite de lint en verde
  - Depends on: T1
- [x] T5 — Arreglos de la revisión del PR #709 (REQ-002, REQ-004, REQ-007)
  - Files or modules: `src/local_delegate/server.py`, `src/local_delegate/lint_patterns.py`, `tests/test_binary_input.py`, `tests/test_lint_exact_paths.py`
  - Verification: NUL suelto, NUL fuera de la muestra y BEL en fichero diminuto se leen (rojos con el código anterior); progreso con colores, `-v` y xdist en verde; `_decode_input_file` sin uso, quitado
  - Depends on: T2, T3
- [x] T6 — Aviso por programa de entradas para ficheros en verde (REQ-010)
  - Files or modules: `src/local_delegate/lint_patterns.py` (`clean_files`, `clean_file_entries`), `src/local_delegate/server.py` (`_lint_check_clean`), i18n es/en, `docs/wiki/Tools.md`
  - Verification: `tests/test_lint_exact_paths.py` (rojo antes en `evidence/red-before-clean-entries.txt`; mutante sin el control dispara el assert del aviso); prueba en vivo en proceso dentro de `test-window`
  - Depends on: T5
- [x] T4 — CHANGELOG y suite completa (REQ-009)
  - Files or modules: `CHANGELOG.md`
  - Verification: suite completa con `pesado.sh` y `-n 2`; prueba en vivo contra el daemon dentro de `test-window`
  - Depends on: T2, T3, T5, T6

## Test strategy

- Unit: `_binary_kind` con firmas reales mínimas y textos que no deben caer; `files_by_frequency`, `reported_files` e `invented_files` con las formas de #688 y #690.
- Integration: las seis tools con backend falso: 0 llamadas con binario; lint con la salida de pytest de #688 mira el prompt que llega al modelo.
- End-to-end or manual: prueba en vivo con el daemon (JPEG, PNG, pytest de #688, log de #690) dentro de `test-window`.
- Security and secret scanning: sin secretos; entradas sintéticas; control positivo con mutantes (quitar el control, quitar la unión de rutas).

## Migration and compatibility

- Cambio visible: un binario que antes se «leía» como Latin-1 ahora da error. Un UTF-16 sin BOM, también (antes salía basura). Va en el CHANGELOG.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
