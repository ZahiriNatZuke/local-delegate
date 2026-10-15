# Mutantes de la orden de etiquetas de lint (B2d-fix)

Aplicados de verdad sobre `src/local_delegate/server.py` (CRLF, por bytes) por `lint_mutants.py` (scratchpad): comprueban que el texto sustituido aparece una sola vez y que el sha256 cambia, corren `tests/test_language_hardening.py` y `tests/test_response_language.py` (sin xdist, bajo `pesado.sh`) y restauran comprobando el sha256 original.

| Mutante | Qué cambia | Fallan | Assert que salta |
|---|---|---|---|
| L1 | lint vuelve a la orden de summarize (system y reduce) | 14 | `_assert_lint_labels`, primer `in` («También van en {idioma} las etiquetas en negrita…», `test_language_hardening.py:78`), en la llamada única, en cada paso del troceado y en el test nuevo; y los `endswith(_order_for(...))` de `test_response_language.py` |
| L2 | solo el reduce vuelve a la orden de summarize | 5 | el mismo `in` de `:78`, solo en los tests de troceado (`_lint_in_chunks` en las dos tandas y el test nuevo de map y reduce) y el `all(...endswith)` de `test_response_language.py:154`: el map sigue bien, falla el reduce |
| L3 | se quita la frase de las etiquetas, deja el resto | 14 | el mismo `in` de `:78` |

La orden de `local_summarize` no cambia: `test_the_summarize_order_does_not_change` la compara byte a byte con el texto de `71846c1` y pasa con y sin los mutantes.

## Registro literal

```text
original sha256 de930ae171cf027065ff2d8db61005a43cdd35a17892f6e63ea40cd4d8713917

## L1 lint keeps the summarize order (system and reduce)
mutated sha256 a5d1c4d7101f836947434c36bb841439ea55b50c4775179a5ade8786fe61dce4
result: 14 failed, 28 passed in 0.91s
failed:
  tests/test_language_hardening.py::test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_lint_summary-es-en-ingl\xe9s]
  tests/test_language_hardening.py::test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_lint_summary-en-es-espa\xf1ol]
  tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-es-en-ingl\xe9s]
  tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-en-es-espa\xf1ol]
  tests/test_language_hardening.py::test_lint_labels_go_in_the_requested_language_in_map_and_reduce[es-en-ingl\xe9s]
  tests/test_language_hardening.py::test_lint_labels_go_in_the_requested_language_in_map_and_reduce[en-es-espa\xf1ol]
  tests/test_response_language.py::test_the_output_variable_reaches_the_four_tools[fr-franc\xe9s]
  tests/test_response_language.py::test_the_output_variable_reaches_the_four_tools[portugu\xeas-portugu\xeas]
  tests/test_response_language.py::test_without_the_variable_the_order_follows_the_current_language[es-espa\xf1ol]
  tests/test_response_language.py::test_without_the_variable_the_order_follows_the_current_language[en-ingl\xe9s]
  tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[a\nb]
  tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]
  tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[
  tests/test_response_language.py::test_the_order_is_in_every_step_of_the_chunking[_lint_in_chunks]
assert lines hit: tests\test_language_hardening.py:122, tests\test_language_hardening.py:139, tests\test_language_hardening.py:160, tests\test_language_hardening.py:70, tests\test_language_hardening.py:78, tests\test_response_language.py:102, tests\test_response_language.py:114, tests\test_response_language.py:125, tests\test_response_language.py:154

## L2 only the reduce keeps the summarize order
mutated sha256 f15068b017d9b5695425553e6da2a8c81ec6cc65e5a0d59094d8f16a8fd34c59
result: 5 failed, 37 passed in 0.94s
failed:
  tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-es-en-ingl\xe9s]
  tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-en-es-espa\xf1ol]
  tests/test_language_hardening.py::test_lint_labels_go_in_the_requested_language_in_map_and_reduce[es-en-ingl\xe9s]
  tests/test_language_hardening.py::test_lint_labels_go_in_the_requested_language_in_map_and_reduce[en-es-espa\xf1ol]
  tests/test_response_language.py::test_the_order_is_in_every_step_of_the_chunking[_lint_in_chunks]
assert lines hit: tests\test_language_hardening.py:139, tests\test_language_hardening.py:160, tests\test_language_hardening.py:70, tests\test_language_hardening.py:78, tests\test_response_language.py:154

## L3 the label sentence is dropped from the lint order
mutated sha256 7b454ce7b5ea6511b2f741e6b8cac70a24373e4c1e6903206ecb153e80eeb7ee
result: 14 failed, 28 passed in 0.94s
failed:
  tests/test_language_hardening.py::test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_lint_summary-es-en-ingl\xe9s]
  tests/test_language_hardening.py::test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_lint_summary-en-es-espa\xf1ol]
  tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-es-en-ingl\xe9s]
  tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-en-es-espa\xf1ol]
  tests/test_language_hardening.py::test_lint_labels_go_in_the_requested_language_in_map_and_reduce[es-en-ingl\xe9s]
  tests/test_language_hardening.py::test_lint_labels_go_in_the_requested_language_in_map_and_reduce[en-es-espa\xf1ol]
  tests/test_response_language.py::test_the_output_variable_reaches_the_four_tools[fr-franc\xe9s]
  tests/test_response_language.py::test_the_output_variable_reaches_the_four_tools[portugu\xeas-portugu\xeas]
  tests/test_response_language.py::test_without_the_variable_the_order_follows_the_current_language[es-espa\xf1ol]
  tests/test_response_language.py::test_without_the_variable_the_order_follows_the_current_language[en-ingl\xe9s]
  tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[a\nb]
  tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]
  tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[
  tests/test_response_language.py::test_the_order_is_in_every_step_of_the_chunking[_lint_in_chunks]
assert lines hit: tests\test_language_hardening.py:122, tests\test_language_hardening.py:139, tests\test_language_hardening.py:160, tests\test_language_hardening.py:70, tests\test_language_hardening.py:78, tests\test_response_language.py:102, tests\test_response_language.py:114, tests\test_response_language.py:125, tests\test_response_language.py:154

restored sha256 de930ae171cf027065ff2d8db61005a43cdd35a17892f6e63ea40cd4d8713917
```
