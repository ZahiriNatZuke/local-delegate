# Controles positivos de B2b-2

## M1 ignorar la variable de salida
- fichero: `src/local_delegate/i18n.py`
- test: `tests/test_response_language.py::test_the_output_variable_reaches_the_four_tools`
- resultado: FALLA (bien)
- assert: `>           assert captured[0]["system"].endswith(_order(name)), tool`
- primera línea E: `E           AssertionError: local_summarize`

## M2 aplicar la variable de salida al commit
- fichero: `src/local_delegate/server.py`
- test: `tests/test_commit_language.py::test_the_output_language_does_not_reach_the_commit`
- resultado: FALLA (bien)
- assert: `>       assert with_it == without`
- primera línea E: `E       AssertionError: assert 'Responde dir...) en franc�s.' == 'Responde dir...) en espa�ol.'`

## M3 la orden solo en el paso de reducción
- fichero: `src/local_delegate/server.py`
- test: `tests/test_response_language.py::test_the_order_is_in_every_step_of_the_chunking[_summarize_in_chunks]`
- resultado: FALLA (bien)
- assert: `>       assert all(c["system"].endswith(_order("franc�s")) for c in captured), [`
- primera línea E: `E       AssertionError: ['en prosa clara. M�ximo 150 palabras. Nada fuera del formato.', 'en prosa clara. M�ximo 150 palabras. Nada fuera del ...a clara. M�ximo 150 palabras. Nada fuera del formato.', 'esponde en franc�s, aunque el contenid`

## M4 volver al «predominante» por defecto
- fichero: `src/local_delegate/server.py`
- test: `tests/test_commit_language.py::test_without_variable_the_message_is_in_the_product_language`
- resultado: FALLA (bien)
- assert: `>       assert system.endswith(f"(primera l�nea y cuerpo) en {name}.")`
- primera línea E: `E       AssertionError: assert False`

## M5 fila sin versión al tramo «después»
- fichero: `scripts/measurement_boundaries.py`
- test: `tests/test_response_language.py::test_the_boundary_is_decided_by_version_not_by_date`
- resultado: FALLA (bien)
- assert: `>       assert mb.usage_side({"ts": late}, boundaries) == mb.BEFORE`
- primera línea E: `E       AssertionError: assert 'after' == 'before'`

## M6 local_status sin el aviso de la variable no válida
- fichero: `src/local_delegate/server.py`
- test: `tests/test_response_language.py::test_status_and_doctor_warn_about_an_invalid_variable`
- resultado: FALLA (bien)
- assert: `>           assert "tiene saltos de l�nea o caracteres de control y se ignora" in text`
- primera línea E: `E           AssertionError: assert 'tiene saltos de l�nea o caracteres de control y se ignora' in 'Idioma: es (variable; C:\\Users\\Yohan\\AppData\\Local\\Temp\\pytest-of-Yohan\\pytest-1871\\test_status_and_doctor_warn_ab0\\language.json)\n`

## M7 cambio de prompt NO declarado (traducción)
- fichero: `src/local_delegate/server.py`
- test: `tests/test_corpus.py::test_versioned_corpus_still_mirrors_production`
- resultado: FALLA (bien)
- assert: `>       assert build.check_versioned(DESTINATION, notices=notices) == []`
- primera línea E: `E       AssertionError: assert ['traducir-42... constructor'] == []`

## M8 lint sin la orden (la celda conservaría la base)
- fichero: `src/local_delegate/server.py`
- test: `tests/test_affinity.py::test_prompt_footprint_of_the_code_is_the_measured_one`
- resultado: FALLA (bien)
- assert: `>               assert digest != cell.footprint["prompt_sha256"], cell.tool`
- primera línea E: `E               AssertionError: local_lint_summary`
