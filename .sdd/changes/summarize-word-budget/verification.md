# Verification: local_summarize corta el resumen a mitad de frase con el max_words por defecto (#580)

## Environment

- Revision: rama `fix/summarize-word-budget` sobre `origin/main` fae612c7.
- Relevant runtime and tool versions: Python 3.11 (venv del worktree, `PYTHONPATH=src`), ruff y
  pytest del proyecto; backend real para la medición: llama-swap local con gemma4-26b-a4b y
  gemma3-4b, local-delegate 0.48.0 instalado (daemon).

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test `test_the_single_call_asks_three_tokens_per_word` | pass | 514 con 150 y 184 con 40; mutante 2w+64 → `assert [364] == [514]` |
| REQ-002 | test `test_the_map_reduce_uses_the_same_cap` | pass | todas las llamadas del map/reduce piden 514; mutante sin `max_tokens_for` → `{364} == {514}` |
| REQ-003 | test `test_trim_to_last_sentence` (11 casos) y `test_a_cut_answer_ends_at_its_last_sentence_with_the_notice` | pass | mutantes sin `_close_structure`, sin paridad de backticks y sin filtro de `1.` fallan en sus casos |
| REQ-004 | tests de aviso es/en y sin frontera | pass | mutante sin `trim_cut` → el texto conserva «Tercera a medi» y el aviso viejo |
| REQ-005 | test `test_an_answer_that_ends_well_comes_back_unchanged` y suite | pass | salida con `stop` idéntica; tres asserts existentes fijaban 364 (ver desviaciones) |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `uv run ruff check src tests` | sí | pass | All checks passed |
| `uv run ruff format --check` | sí (hook pre-commit) | pass | hook ruff-format Passed |
| `uv run pytest -n 2` | sí | ver PR | volcado a fichero y resumido |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Tres asserts existentes fijaban el tope viejo de `local_summarize` (364 = 2w+64):
  `test_structured_summary.py::test_without_headings_the_payload_is_mains`,
  `::test_with_the_switch_off_the_payload_is_mains` y
  `test_lossless_summary_output.py::test_the_other_tools_keep_the_shared_chunk_cap`. Ese número es
  justo lo que el issue pide cambiar; se actualizó solo el número (514 / 150*3+64), en un commit
  aparte, sin tocar la intención de cada test.
- Medición: 6 llamadas reales (ventana de prueba `w-20261104T174214Z`); muestra pequeña, pero
  coherente con el log del mes (todos los cortes planos exactamente en 2w+64). El recorte cubre el
  resto.
- El map/reduce no recorta su salida final (su aviso cuenta las llamadas cortadas, no solo la última).
