# Mutantes de B2d-fix (aplicados de verdad y restaurados)

Cada mutante se aplica sobre el fichero real (reemplazo que debe aparecer UNA vez), se comprueba que el sha256 del fichero cambió (el mutante muta), se corre `pytest -p no:xdist` sobre `tests/test_language_hardening.py`, `tests/test_response_language.py` y `tests/test_structured_summary.py` con el cerrojo, y se restaura comprobando el sha256. Por cada test que falla: la línea `>` del assert que dispara (la más interna) y la primera `E`.

## M1 — la orden de idioma de antes en summarize y lint_summary
- muta: server.py; resultado: `24 failed, 66 passed in 2.91s`
- `test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_summarize-es-en-ingl\xe9s]`: **FALLA**
    - `>       assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un resumen en prosa clara. Máximo 150 palabras. Nada fuera del formato. Responde e`
- `test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_summarize-en-es-espa\xf1ol]`: **FALLA**
    - `>       assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un resumen en prosa clara. Máximo 150 palabras. Nada fuera del formato. Responde e`
- `test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_lint_summary-es-en-ingl\xe9s]`: **FALLA**
    - `>       assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un resumen de los problemas agrupados por archivo, con el conteo por tipo de error`
- `test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_lint_summary-en-es-espa\xf1ol]`: **FALLA**
    - `>       assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un resumen de los problemas agrupados por archivo, con el conteo por tipo de error`
- `test_the_hardened_order_is_in_every_step_of_the_chunking[_structured-es-en-ingl\xe9s]`: **FALLA**
    - `>       assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un resumen en prosa clara. Máximo 1 palabras. Nada fuera del formato. Responde en `
- `test_the_hardened_order_is_in_every_step_of_the_chunking[_structured-en-es-espa\xf1ol]`: **FALLA**
    - `>       assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un resumen en prosa clara. Máximo 1 palabras. Nada fuera del formato. Responde en `
- `test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-es-en-ingl\xe9s]`: **FALLA**
    - `>       assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un resumen de los problemas agrupados por archivo, con el conteo por tipo de error`
- `test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-en-es-espa\xf1ol]`: **FALLA**
    - `>       assert f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma" in (`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un resumen de los problemas agrupados por archivo, con el conteo por tipo de error`
- `test_the_output_variable_reaches_the_four_tools[fr-franc\xe9s]`: **FALLA**
    - `>           assert captured[0]["system"].endswith(_order_for(tool, name)), tool`
    - `E           AssertionError: local_summarize`
- `test_the_output_variable_reaches_the_four_tools[portugu\xeas-portugu\xeas]`: **FALLA**
    - `>           assert captured[0]["system"].endswith(_order_for(tool, name)), tool`
    - `E           AssertionError: local_summarize`
- `test_without_the_variable_the_order_follows_the_current_language[es-espa\xf1ol]`: **FALLA**
    - `>           assert captured[0]["system"].endswith(_order_for(tool, name)), tool`
    - `E           AssertionError: local_summarize`
- `test_without_the_variable_the_order_follows_the_current_language[en-ingl\xe9s]`: **FALLA**
    - `>           assert captured[0]["system"].endswith(_order_for(tool, name)), tool`
    - `E           AssertionError: local_summarize`
- `test_an_invalid_variable_falls_back_to_the_current_language[a\nb]`: **FALLA**
    - `>           assert captured[0]["system"].endswith(_order_for(tool, "español")), tool`
    - `E           AssertionError: local_summarize`
- `test_an_invalid_variable_falls_back_to_the_current_language[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]`: **FALLA**
    - `>           assert captured[0]["system"].endswith(_order_for(tool, "español")), tool`
    - `E           AssertionError: local_summarize`
- `test_an_invalid_variable_falls_back_to_the_current_language[   ]`: **FALLA**
    - `>           assert captured[0]["system"].endswith(_order_for(tool, "español")), tool`
    - `E           AssertionError: local_summarize`
- `test_the_order_is_in_every_step_of_the_chunking[_summarize_in_chunks]`: **FALLA**
    - `>       assert all(c["system"].endswith(_hardened_order("francés")) for c in captured), [`
    - `E       AssertionError: ['esponde en francés, aunque el contenido esté en otro idioma.', 'esponde en francés, aunque el contenido esté en otro... en francés, aunque el contenido esté en otro idioma.',`
- `test_the_order_is_in_every_step_of_the_chunking[_structured_in_chunks]`: **FALLA**
    - `>       assert all(c["system"].endswith(_hardened_order("francés")) for c in captured), [`
    - `E       AssertionError: ['esponde en francés, aunque el contenido esté en otro idioma.', 'esponde en francés, aunque el contenido esté en otro...rancés, aunque el contenido esté en otro idioma.', 'esp`
- `test_the_order_is_in_every_step_of_the_chunking[_lint_in_chunks]`: **FALLA**
    - `>       assert all(c["system"].endswith(_hardened_order("francés")) for c in captured), [`
    - `E       AssertionError: ['esponde en francés, aunque el contenido esté en otro idioma.', 'esponde en francés, aunque el contenido esté en otro... en francés, aunque el contenido esté en otro idioma.',`
- `test_without_headings_the_payload_is_mains`: **FALLA**
    - `>       assert payload["messages"][0]["content"] == MAIN_SYSTEM`
    - `E       AssertionError: assert 'Responde dir... otro idioma.' == 'Responde dir...a o de error.'`
- `test_with_the_switch_off_the_payload_is_mains`: **FALLA**
    - `>       assert payload["messages"][0]["content"] == MAIN_SYSTEM`
    - `E       AssertionError: assert 'Responde dir... otro idioma.' == 'Responde dir...a o de error.'`
- `test_focus_arrives_sanitized_and_not_in_the_log`: **FALLA**
    - `>       assert system.endswith(LANGUAGE_ORDER)`
    - `E       AssertionError: assert False`
- `test_empty_focus_is_absent`: **FALLA**
    - `>       assert seen[0]["messages"][0]["content"] == MAIN_SYSTEM`
    - `E       AssertionError: assert 'Responde dir... otro idioma.' == 'Responde dir...a o de error.'`
- `test_with_the_mechanical_model_it_goes_in_prose_even_with_headings`: **FALLA**
    - `>       assert seen[0]["messages"][0]["content"] == MAIN_SYSTEM`
    - `E       AssertionError: assert 'Responde dir... otro idioma.' == 'Responde dir...a o de error.'`
- `test_with_the_default_value_the_tool_summarizes_in_prose`: **FALLA**
    - `>       assert seen[0]["messages"][0]["content"] == MAIN_SYSTEM`
    - `E       AssertionError: assert 'Responde dir... otro idioma.' == 'Responde dir...a o de error.'`
- todos los que fallan (24): `tests/test_language_hardening.py::test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_summarize-es-en-ingl\xe9s]`, `tests/test_language_hardening.py::test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_summarize-en-es-espa\xf1ol]`, `tests/test_language_hardening.py::test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_lint_summary-es-en-ingl\xe9s]`, `tests/test_language_hardening.py::test_summarize_and_lint_ask_for_full_sentences_in_the_requested_language[local_lint_summary-en-es-espa\xf1ol]`, `tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_structured-es-en-ingl\xe9s]`, `tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_structured-en-es-espa\xf1ol]`, `tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-es-en-ingl\xe9s]`, `tests/test_language_hardening.py::test_the_hardened_order_is_in_every_step_of_the_chunking[_lint_in_chunks-en-es-espa\xf1ol]`, `tests/test_response_language.py::test_the_output_variable_reaches_the_four_tools[fr-franc\xe9s]`, `tests/test_response_language.py::test_the_output_variable_reaches_the_four_tools[portugu\xeas-portugu\xeas]`, `tests/test_response_language.py::test_without_the_variable_the_order_follows_the_current_language[es-espa\xf1ol]`, `tests/test_response_language.py::test_without_the_variable_the_order_follows_the_current_language[en-ingl\xe9s]`, `tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[a\nb]`, `tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]`, `tests/test_response_language.py::test_an_invalid_variable_falls_back_to_the_current_language[   ]`, `tests/test_response_language.py::test_the_order_is_in_every_step_of_the_chunking[_summarize_in_chunks]`, `tests/test_response_language.py::test_the_order_is_in_every_step_of_the_chunking[_structured_in_chunks]`, `tests/test_response_language.py::test_the_order_is_in_every_step_of_the_chunking[_lint_in_chunks]`, `tests/test_structured_summary.py::test_without_headings_the_payload_is_mains`, `tests/test_structured_summary.py::test_with_the_switch_off_the_payload_is_mains`, `tests/test_structured_summary.py::test_focus_arrives_sanitized_and_not_in_the_log`, `tests/test_structured_summary.py::test_empty_focus_is_absent`, `tests/test_structured_summary.py::test_with_the_mechanical_model_it_goes_in_prose_even_with_headings`, `tests/test_structured_summary.py::test_with_the_default_value_the_tool_summarizes_in_prose`

## M2 — la introducción en el idioma del producto (i18n.t), como antes
- muta: sections.py; resultado: `3 failed, 87 passed in 2.87s`
- `test_the_introduction_is_in_the_response_language[es-en-Introduction]`: **FALLA**
    - `>       assert plan[0].heading == expected`
    - `E       AssertionError: assert 'Introducción' == 'Introduction'`
- `test_the_introduction_is_in_the_response_language[en-es-Introducci\xf3n]`: **FALLA**
    - `>       assert plan[0].heading == expected`
    - `E       AssertionError: assert 'Introduction' == 'Introducción'`
- `test_the_b2d_case_comes_out_once_and_summarized`: **FALLA**
    - `>       assert "Introducción" not in output, output`
    - `E       AssertionError: ## Introducción`
- todos los que fallan (3): `tests/test_language_hardening.py::test_the_introduction_is_in_the_response_language[es-en-Introduction]`, `tests/test_language_hardening.py::test_the_introduction_is_in_the_response_language[en-es-Introducci\xf3n]`, `tests/test_language_hardening.py::test_the_b2d_case_comes_out_once_and_summarized`

## M3 — complete() empareja solo por texto (sin positional)
- muta: sections.py; resultado: `2 failed, 88 passed in 2.84s`
- `test_a_translated_heading_is_not_duplicated_and_gets_its_wording_back`: **FALLA**
    - `>       assert len(headings) == len(EXPECTED), done.text`
    - `E       AssertionError: ## Instalación`
- `test_the_rescue_keeps_the_level_of_the_heading`: **FALLA**
    - `>       assert "### Configuración\nVariables" in done.text`
    - `E       AssertionError: assert '### Configuración\nVariables' in '### Instalación\nSe instala con uv y nada más.\n\n### Configuration\nVariables de entorno y un fichero de configuraci... path y devuel`
- todos los que fallan (2): `tests/test_language_hardening.py::test_a_translated_heading_is_not_duplicated_and_gets_its_wording_back`, `tests/test_language_hardening.py::test_the_rescue_keeps_the_level_of_the_heading`

## M4 — M2 + M3 a la vez: el caso en vivo de B2d
- muta: sections.py; resultado: `5 failed, 85 passed in 2.88s`
- `test_the_introduction_is_in_the_response_language[es-en-Introduction]`: **FALLA**
    - `>       assert plan[0].heading == expected`
    - `E       AssertionError: assert 'Introducción' == 'Introduction'`
- `test_the_introduction_is_in_the_response_language[en-es-Introducci\xf3n]`: **FALLA**
    - `>       assert plan[0].heading == expected`
    - `E       AssertionError: assert 'Introduction' == 'Introducción'`
- `test_the_b2d_case_comes_out_once_and_summarized`: **FALLA**
    - `>       assert "Introducción" not in output, output`
    - `E       AssertionError: ## Introduction`
- `test_a_translated_heading_is_not_duplicated_and_gets_its_wording_back`: **FALLA**
    - `>       assert len(headings) == len(EXPECTED), done.text`
    - `E       AssertionError: ## Instalación`
- `test_the_rescue_keeps_the_level_of_the_heading`: **FALLA**
    - `>       assert "### Configuración\nVariables" in done.text`
    - `E       AssertionError: assert '### Configuración\nVariables' in '### Instalación\nSe instala con uv y nada más.\n\n### Configuration\nVariables de entorno y un fichero de configuraci... path y devuel`
- todos los que fallan (5): `tests/test_language_hardening.py::test_the_introduction_is_in_the_response_language[es-en-Introduction]`, `tests/test_language_hardening.py::test_the_introduction_is_in_the_response_language[en-es-Introducci\xf3n]`, `tests/test_language_hardening.py::test_the_b2d_case_comes_out_once_and_summarized`, `tests/test_language_hardening.py::test_a_translated_heading_is_not_duplicated_and_gets_its_wording_back`, `tests/test_language_hardening.py::test_the_rescue_keeps_the_level_of_the_heading`

## M5 — el rescate sin filtro de nivel (acepta subsecciones y negritas)
- muta: sections.py; resultado: `2 failed, 88 passed in 2.89s`
- `test_the_rescue_does_not_take_what_is_not_a_translation[subsection_level]`: **FALLA**
    - `>       assert done.missing >= 1`
    - `E       AssertionError: assert 0 >= 1`
- `test_the_rescue_does_not_take_what_is_not_a_translation[bold_line]`: **FALLA**
    - `>       assert done.missing >= 1`
    - `E       AssertionError: assert 0 >= 1`
- todos los que fallan (2): `tests/test_language_hardening.py::test_the_rescue_does_not_take_what_is_not_a_translation[subsection_level]`, `tests/test_language_hardening.py::test_the_rescue_does_not_take_what_is_not_a_translation[bold_line]`

## M6 — el rescate sin exigir un solo faltante en el hueco
- muta: sections.py; resultado: `1 failed, 89 passed in 2.86s`
- `test_the_rescue_does_not_take_what_is_not_a_translation[two_missing_in_a_slot]`: **FALLA**
    - `>       assert done.missing >= 1`
    - `E       AssertionError: assert 0 >= 1`
- todos los que fallan (1): `tests/test_language_hardening.py::test_the_rescue_does_not_take_what_is_not_a_translation[two_missing_in_a_slot]`
