# Controles positivos de B2a

## M1 recibo de lectura fuera del catálogo
- fichero: `src/local_delegate/server.py`
- test: `tests/test_mcp_english.py::test_tool_outputs_have_no_spanish_in_english`
- resultado: FALLA (bien)
- assert: `>       assert not _spanish_in(english, words), _spanish_in(english, words)`
- primera línea E: `E       AssertionError: ['contexto', 'entraron', 'le�do']`

## M2 cifras con separador del idioma
- fichero: `src/local_delegate/server.py`
- test: `tests/test_mcp_english.py::test_numbers_are_machine_format`
- resultado: FALLA (bien)
- assert: `>       assert "20027" in text`
- primera línea E: `E       AssertionError: assert '20027' in 'the summary\\n\\n(le\xeddo server-side: 20.027 chars \u2248 10.013 tokens de Claude que no entraron a tu contexto)'`

## M3 motivo del turno crudo
- fichero: `src/local_delegate/server.py`
- test: `tests/test_mcp_english.py::test_remote_backend_reason_has_its_text`
- resultado: FALLA (bien)
- assert: `>       assert server._describe_turn() == expected`
- primera línea E: `E       AssertionError: assert 'Turn: no (backend remoto)' == 'Turn: no (remote backend)'`

## M4 failures ignora el idioma pedido
- fichero: `src/local_delegate/failures.py`
- test: `tests/test_mcp_english.py::test_failure_texts_follow_the_requested_language`
- resultado: FALLA (bien)
- assert: `>           assert text("en") != text("es"), cause`
- primera línea E: `E           AssertionError: dns`

## M5 language_report sin avisos
- fichero: `src/local_delegate/i18n.py`
- test: `tests/test_mcp_english.py::test_status_warns_about_an_invalid_variable`
- resultado: FALLA (bien)
- assert: `>       assert len(lines) >= 2`
- primera línea E: `E       AssertionError: assert 1 >= 2`

## M6 lectura de una sola forma de «(sin resumir)»
- fichero: `scripts/measure_structured_summary.py`
- test: `tests/test_mcp_english.py::test_the_measurement_reads_both_forms`
- resultado: FALLA (bien)
- assert: `>       assert (r["paired"], r["completed_by_server"]) == (1, 1)`
- primera línea E: `E       assert (2, 0) == (1, 1)`

## M7 título del campo de la pregunta sin catálogo
- fichero: `src/local_delegate/questions.py`
- test: `tests/test_questions.py::test_the_elicitation_schemas_keep_their_fields_and_visible_titles`
- resultado: FALLA (bien)
- assert: `>       assert questions._localized_schema(form) == expected`
- primera línea E: `E       AssertionError: assert {'description...Backend', ...} == {'description...Backend', ...}`

## M8 residente con el motivo crudo
- fichero: `src/local_delegate/chains.py`
- test: `tests/test_mcp_english.py::test_residents_text_says_the_reason_in_the_current_language`
- resultado: FALLA (bien)
- assert: `>       assert chains.residents_text() == "no resident (unknown: no LLAMASWAP_CONFIG)"`
- primera línea E: `E       AssertionError: assert 'no resident ...ASWAP_CONFIG)' == 'no resident ...ASWAP_CONFIG)'`
