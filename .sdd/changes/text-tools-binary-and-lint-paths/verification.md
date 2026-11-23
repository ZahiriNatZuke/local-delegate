# Verification: Tools de texto: rechazo de binarios y rutas exactas en lint_summary

## Environment

- Revision: rama `fix/text-tools-binary-and-lint-paths` sobre `main` (31c2d0b8).
- Relevant runtime and tool versions: Windows 11, Python del `.venv` del repo, pytest con xdist `-n 2`.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `tests/test_binary_input.py` (JPEG en las 6 tools, PNG/GIF/WebP) y prueba en vivo | pass | rojo antes (`evidence/red-before-fix.txt`), verde después; en vivo el JPEG y el PNG dan error que remite a `local_describe_image` |
| REQ-002 | PDF, ZIP, gzip, 7z, NUL, UTF-16 sin BOM, 20 % de control | pass | `tests/test_binary_input.py` |
| REQ-003 | test parametrizado sobre las seis tools | pass | `test_a_jpeg_is_refused_by_every_text_tool_before_the_model` |
| REQ-004 | controles de texto y suite de #672 intacta | pass | `test_text_files_are_not_refused` (9 formas), `tests/test_input_encoding.py` sin cambios; en vivo UTF-8 con acentos resumido bien |
| REQ-005 | unión absoluta/relativa | pass | `tests/test_lint_exact_paths.py`; en vivo la ruta de `testclient.py` sale una vez |
| REQ-006 | URL fuera | pass | tests y en vivo: la URL del pie ya no sale como fichero |
| REQ-007 | ficheros en verde fuera del inventario | pass | tests del prompt y de «sin mencionar»; en vivo el modelo mecánico los sigue nombrando leyendo el log (riesgo residual) |
| REQ-008 | carpetas inventadas | pass | `tests/test_lint_exact_paths.py` (forma de #690, 8 controles); tests de #525 intactos |
| REQ-009 | CHANGELOG, wiki `Tools.md`, i18n es/en | pass | diff |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test | `pytest -n 2` vía `pesado.sh` | pass | 8332 passed, 31 skipped; el único rojo (`test_detect_spanish_names`, nombres de fichero de los tests nuevos) se arregló y se repasó en verde |
| lint | `ruff check` y `ruff format --check` | pass | hook de pre-commit |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- #688 en vivo: el inventario ya no lleva la URL ni la ruta doble ni los ficheros en verde, pero el
  modelo mecánico (`gemma3-4b`) sigue listando esos ficheros porque los lee en el propio log, y
  atribuyó el aviso a otro fichero. Eso es del modelo; un control por programa de entradas para
  ficheros limpios (como el de #641 para fallos) queda como seguimiento.
- #690 no se reprodujo en vivo (el modelo no inventó carpetas con esta entrada); el aviso está
  cubierto por tests.
- El prompt de sistema de lint no se tocó (huella de afinidad).
