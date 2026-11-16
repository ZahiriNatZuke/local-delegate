# Verification: local_describe_image no mide: aviso por programa ante alineación, píxeles o saltos de línea (#663)

## Environment

- Revision: rama `fix/describe-image-not-a-measurement` sobre main
- Relevant runtime and tool versions: Python 3.11.15 del `.venv` del checkout principal con `PYTHONPATH=src`; ruff del mismo `.venv`

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | la docstring nombra alineación, medir y `getBoundingClientRect` | pass | tests/test_vision_measurement_notice.py::test_the_description_says_it_does_not_measure |
| REQ-002 | caso del issue, del comentario y 13 frases es/en con aviso detrás de la respuesta intacta | pass | test_the_alignment_question_of_the_issue_gets_the_notice, test_the_wrap_claim_of_the_comment_gets_the_notice_without_a_question, test_measurement_words_in_question_or_answer_get_the_notice |
| REQ-003 | 5 descripciones sin medidas sin aviso; error del backend sin aviso; prompt del sistema igual | pass | test_a_description_that_does_not_measure_has_no_notice, test_a_backend_error_gets_no_notice, test_the_prompt_is_not_changed |
| REQ-004 | wiki, skill es/en, CHANGELOG; paridad de catálogos | pass | tests/test_i18n_parity.py; lectura de los ficheros |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest tests/test_vision_measurement_notice.py sin el arreglo | sí | 9 fallan, 5 pasan (los negativos y el del prompt) | reproducción antes del arreglo |
| pytest test_vision_measurement_notice, test_vision y detector de nombres | sí | 82 passed | tras la revisión |
| pytest suite completa -n 2 --dist loadgroup | sí | 7772 passed, 2 failed y arreglados (excepción del guardián de textos para la regex; artefacto register.js suelto de una corrida cortada), 69 passed al repetirlos | cerrojo pesado.sh |
| ruff check y ruff format --check | sí | pass | src y test nuevo |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Guarda por palabras: un modelo que afirme una desalineación con otras palabras no lleva aviso; la docstring y la skill lo previenen antes de llamar.
- Una descripción que use esas palabras sin medir («un margen amplio») lleva el aviso; una línea, aceptado.
- Sin prueba en vivo: el prompt no cambia. Prueba opcional descrita en el PR.
