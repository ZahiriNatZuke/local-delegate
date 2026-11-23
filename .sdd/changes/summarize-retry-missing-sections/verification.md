# Verification: local_summarize troceado: reintentar una vez las secciones que faltan y nombrarlas en el aviso (#691)

## Environment

- Revision: rama `fix/691-705-summarize-retry-doctor-disabled` sobre `ce09fc5a` (worktree propio, `PYTHONPATH=src`).
- Relevant runtime and tool versions: Python 3.11.15, pytest con xdist (`-n 2`), ruff; Windows 11.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_left_out_the_first_time_and_summarized_the_second y test_left_out_twice_is_named_once_in_the_notice: un solo reintento con solo las secciones que faltan | pass | rojo antes (`assert 0 == 1`), verde después |
| REQ-002 | test_left_out_the_first_time…, test_an_empty_heading_is_retried_and_filled_in_place, test_merge_retry_puts_the_sections_in_their_slot | pass | secciones en su sitio y en orden; rojo antes |
| REQ-003 | test_left_out_twice_is_named_once_in_the_notice, test_complete_naming_the_missing_inserts_nothing, test_empty_in_the_chunk_and_again_in_the_retry_is_named_once_and_leaves_the_body, test_complete_naming_the_missing_drops_an_empty_heading (0.54.1, rojos antes) | pass | 0 «(sin resumir)», cada título una vez en el aviso |
| REQ-004 | test_an_obedient_model_gets_no_retry, test_a_failed_retry_keeps_the_summary_and_names_them | pass | sin reintento si no falta nada; un 500 en el reintento devuelve el resumen |
| REQ-005 | test_left_out_the_first_time… (`chunks == len(seen) == len(steps)`, un paso `sections_retry`) | pass | un único evento de log |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2 --dist loadgroup` (con `pesado.sh`) | 2026-11-23 | pass | 8379 pasados, 31 saltados; el único fallo (`test_detect_spanish_names`, 6 palabras inglesas nuevas sin clasificar) se arregló en el léxico y su test pasa |
| `ruff check .` y `ruff format --check` | 2026-11-23 | pass | sin hallazgos |
| prueba en vivo (`test-window` `w-20261123T124639Z`) | 2026-11-23 | skip | ver «Deviations» |
| `pytest -q -n 2` (0.54.1, con `pesado.sh`) | 2026-11-23 | pass | 8659 pasados, 31 saltados, con el arreglo de J1 |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Prueba en vivo: con la versión instalada (0.53.0, por el daemon) y dos documentos de 70–92 K
  troceados en 2 y 3 partes, el modelo real no omitió ninguna sección: el defecto no se reprodujo
  (como ya decía el research). La rama no se puede ejecutar en proceso contra el backend real: pide
  una clave que solo tiene el daemon (401), y no se reinicia el daemon ni se pide la clave. El
  comportamiento nuevo queda verificado con backend simulado; la prueba en vivo de la rama queda para
  cuando se instale la versión.
- Riesgo residual: una llamada más cuando falta algo (alarga la operación); con tope de una vuelta
  y solo si queda tiempo según el presupuesto de la llamada.
