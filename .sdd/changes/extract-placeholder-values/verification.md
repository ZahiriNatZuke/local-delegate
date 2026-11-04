# Verification: local_extract: marcadores de sin dato a null y cuentas de listas vacías

## Environment

- Revision: rama `fix/extract-placeholder-values` desde `main` (`58e37d54`).
- Windows 11, Python del `.venv` del checkout principal con `PYTHONPATH=src` (importa el worktree).
- Backend falso (`_run_chat` doblado); la prueba en vivo con el backend real la hace la sesión principal.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | marcadores y su conversión a null de extremo a extremo | pass | `tests/test_extract_placeholder_values.py::test_markers`, `::test_markers_become_null_and_missing` |
| REQ-002 | `missing_keys` en orden, `placeholder_keys`, avisos separados; tras un renombrado | pass | `::test_omitted_and_marker_keys_in_request_order`, `::test_marker_on_a_renamed_key` |
| REQ-003 | `none`, `NA`, `0`, `false`, listas, objetos, textos con un marcador dentro no cambian | pass | `::test_legitimate_values_are_not_markers`, `::test_legitimate_values_pass_untouched` |
| REQ-004 | el relleno desde parciales salta un marcador | pass | `::test_fill_from_partials_skips_a_marker`, `::test_fill_from_partials_keeps_a_real_value` |
| REQ-005 | aplazado: el cambio de prompt rompe la red del corpus congelado (4 tests de `tests/test_corpus.py`) y 2 fixtures | skip | se implementó, se vio fallar la suite y se retiró; ver spec |
| REQ-006 | recuento: caso del comentario del issue, grafías, cuenta omitida, ocho casos sin recuento | pass | `::test_the_issue_comment_case`, `::test_count_key_spellings`, `::test_an_omitted_count_is_filled_and_not_missing`, `::test_no_recount` |
| REQ-007 | suite completa `pesado.sh pytest -n 2`; ruff check y format | pass | ver «Suite» |
| REQ-008 | entrada en CHANGELOG `[Unreleased]` → Corregido | pass | `CHANGELOG.md` |

## Control positivo (mutantes)

- `_null_placeholders` devuelve `{}` sin tocar nada: fallan los 3 tests de marcadores de extremo a
  extremo por el assert de datos (`{'review_verdict': 'N/A'} == {'review_verdict': None}`) o por
  `KeyError: '_local_delegate'` (no hay metadatos porque no se detectó nada).
- `_recount_lists` devuelve `{}`: fallan los 6 de recuento por el assert de datos
  (`{'number_of_reviews': None} == {'number_of_reviews': 2}`, `{'commentCount': None} == {'commentCount': 0}`).
- `_EXTRACT_NO_DATA_CLAUSE = ""`: fallan los 2 del prompt (`'su valor es null' in …`, y
  `all(... 'Una lista vacía tiene 0 elementos' ...)`). La primera versión del test de troceado
  comparaba con la propia constante y no fallaba con el mutante (`"" in s`); se corrigió para
  buscar el texto literal.
- El relleno desde parciales sin la guarda de marcador: falla
  `test_fill_from_partials_skips_a_marker` (`{'a': 'N/A', 'b': '-'} == {'a': 'real', 'b': 'otro'}`).

- (El mutante de la cláusula del prompt ya no aplica: la cláusula se retiró.)

- Segunda revisión (guardas del recuento y prefijo numerado): sin la guarda (a) fallan los 7
  casos de total legítimo de `test_no_recount` (`'_local_delegate' not in …`, p. ej. `comment_count`
  57 → 2); sin la guarda (b) fallan 5 (`number_of_reviews: 2` con 2 reviews pasa a recontarse en
  el caso del issue, y las cifras iguales o menores); sin quitar el prefijo, falla
  `test_a_numbered_marker_is_null` (`KeyError: '_local_delegate'`: el `"N/A"` pasaba por valor).

## Revisión independiente

- Agente revisor de resultado: «no aprobado» por los textos fuera del catálogo (ya resuelto al
  retirar la cláusula y con una excepción para `sin información`) y ajustes: `"."` legítimo
  convertido a null (arreglado), recuento que pisaba una cuenta del propio JSON (arreglado: no se
  recuenta si el JSON trae la clave pedida), `ValueError` de enteros de >4300 dígitos (arreglado),
  docstring y wiki sin los campos nuevos (añadidos), pruebas de extremo a extremo del aviso tras
  truncado y del relleno troceado (añadidas), BOM y float `2.0` (arreglados). Todos con test.

- Segunda revisión de la sesión principal: CodeQL `py/side-effect-in-assert` en dos tests
  (arreglado sacando la llamada a una variable); el recuento pisaba totales legítimos con otro
  nombre (guardas (a) y (b)); `--` y `...` fuera de los marcadores; prefijo `N| ` quitado antes de
  buscar el marcador en modo numerado. El refuerzo del prompt queda fuera de la 0.49.0 (decisión
  del usuario; el PR pasa a `Refs #586`).

## Suite

- `pesado.sh pytest -n 2` (Windows, local): 6680 passed, 30 skipped, 2 failed. Los 2 fallos son
  `tests/test_corpus.py::test_affinity_check_is_ok_with_any_environment_language[None|en]` y solo
  difieren en `selection.step` (0 → 1), que sale de `git log main` del clon local
  (`select_commits`), no del árbol de trabajo: fallan igual sin este cambio en este clon (ya
  fallaban en la primera corrida, junto a los del prompt). El CI decide.
- `ruff check` y `ruff format --check`: limpios.
- Tras la segunda revisión: 6686 passed, 4 failed. Los dos de afinidad de arriba (entorno); uno del
  léxico por el nombre `unprefix` (renombrado a `strip_prefix`, ya pasa); y
  `test_build_hook.py::test_sdist_carries_what_regenerates_the_mod`, por un `register.js` generado
  e ignorado que dejó la propia suite en el worktree (el sdist de un worktree no lee `.gitignore`):
  borrado, el test pasa.

## Final result

- Merged in `main` as `c5f8333c` (PR #591, 2026-11-04T22:58:25Z), with `Refs #586` (the prompt part, REQ-005, stays open in the issue by the user's decision).
- PR checks: 22 of 22 green (`gh pr checks 591`: tests on ubuntu/windows/macos, plugin ubuntu/windows/macos, Python 3.11–3.15 matrix, lint, secrets, audit, install-smoke, test-lang-es, ci-gate, CodeQL, Socket, GitGuardian).
- `main` CI on `c5f8333c`: CI (run 41929860741), CodeQL, Vendor audit and Wiki green.
- Closed on 2026-11-04 in the 0.49.0 release PR (`chore/release-0.49.0-b`).
