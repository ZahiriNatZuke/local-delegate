# Verification: Tools de texto: rechazo de binarios y rutas exactas en lint_summary

## Environment

- Revision: rama `fix/text-tools-binary-and-lint-paths` rebasada sobre `origin/main` el 2026-11-23 (antes sobre 31c2d0b8).
- Relevant runtime and tool versions: Windows 11, Python del `.venv` del repo, pytest con xdist `-n 2`.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `tests/test_binary_input.py` (JPEG en las 6 tools, PNG/GIF/WebP) y prueba en vivo | pass | rojo antes (`evidence/red-before-fix.txt`), verde después; en vivo el JPEG y el PNG dan error que remite a `local_describe_image` |
| REQ-002 | PDF, ZIP, gzip, 7z, NUL, UTF-16 sin BOM, 20 % de control; NUL suelto, NUL fuera de la muestra, BEL en fichero diminuto y retrocesos de `man` se leen | pass | `tests/test_binary_input.py`, `test_overstrike_text_is_not_refused`; rojos con el código anterior (`evidence/red-before-review-fixes.txt`) |
| REQ-003 | test parametrizado sobre las seis tools | pass | `test_a_jpeg_is_refused_by_every_text_tool_before_the_model` |
| REQ-004 | controles de texto y suite de #672 intacta | pass | `test_text_files_are_not_refused` (12 formas), `tests/test_input_encoding.py` sin cambios; en vivo UTF-8 con acentos resumido bien |
| REQ-005 | unión absoluta/relativa | pass | `tests/test_lint_exact_paths.py`; en vivo la ruta de `testclient.py` sale una vez |
| REQ-006 | URL fuera | pass | tests y en vivo: la URL del pie ya no sale como fichero |
| REQ-007 | ficheros en verde fuera del inventario | pass | tests del prompt y de «sin mencionar»; progreso con colores, `-v`, xdist y línea partida (`tests/test_lint_exact_paths.py`) |
| REQ-010 | aviso por programa de entradas para ficheros en verde | pass | `test_the_tool_warns_of_entries_for_clean_files` (rojo antes, `evidence/red-before-clean-entries.txt`) y su mutante; rol largo y troceado con mutante; en vivo (en proceso, `gemma3-4b`, ventana `lint-688`) 3 de 3 respuestas con entrada para ficheros en verde llevan el aviso, antes 0 de 3 (`evidence/live-688-before.json`, `evidence/live-688-after.json`) |
| REQ-008 | carpetas inventadas | pass | `tests/test_lint_exact_paths.py` (forma de #690, 8 controles); tests de #525 intactos |
| REQ-009 | CHANGELOG, wiki `Tools.md`, i18n es/en | pass | diff |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test | `pytest -n 2` vía `pesado.sh`, tras el rebase y los arreglos de la revisión | pass | 8360 passed, 31 skipped; los 2 rojos (`test_no_uncatalogued_text`, cabecera de pytest sin excepción; `test_detect_spanish_names`, palabras de los tests nuevos) se arreglaron en datos y se repasaron en verde (90 passed) |
| lint | `ruff check` y `ruff format --check` | pass | hook de pre-commit |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- #688 en vivo: el modelo mecánico (`gemma3-4b`) sigue dando entrada a los ficheros en verde que
  lee en el propio log (en 3 de 3 corridas, antes y después); ahora el programa lo avisa debajo del
  resumen y dice qué fichero sí reporta el log. El aviso nombra el primer fichero de la línea de
  entrada (`tests/test_mod_00.py - tests/test_mod_13.py` sale como `tests/test_mod_00.py`): avisa,
  pero no enumera todos. No se quita el texto del modelo: una entrada puede llevar a la vez el aviso
  real atribuido a otro fichero, y borrarla perdería el dato.
- #690 no se reprodujo en vivo (el modelo no inventó carpetas con esta entrada); el aviso está
  cubierto por tests.
- El prompt de sistema de lint no se tocó (huella de afinidad).
