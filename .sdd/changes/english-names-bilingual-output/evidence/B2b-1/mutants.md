# Controles positivos de B2b-1

## M1 el título de la anotación depende del idioma
- fichero: `src/local_delegate/server.py`
- test: `tests/test_tool_contract.py::test_descriptions_do_not_depend_on_the_language`
- resultado: FALLA (bien)
- assert: `>       assert spanish == english`
- primera línea E: `E       AssertionError: assert [{'name': 'lo...'}, ...}, ...] == [{'name': 'lo...'}, ...}, ...]`

## M2 emisión doble (clave vieja junto a la nueva)
- fichero: `src/local_delegate/server.py`
- test: `tests/test_tool_contract.py::test_extract_meta_uses_the_new_keys`
- resultado: FALLA (bien)
- assert: `>       assert not _keys(result) & OLD_KEYS`
- primera línea E: `E       AssertionError: assert not ({'_local_delegate', 'a', 'approx_tokens', 'chars', 'read_server_side', 'truncado', ...} & {'aviso', 'crudo', 'leido_server_side', 'respaldo', 'tokens_aprox', 'truncado'})`

## M3 clave vieja del respaldo
- fichero: `src/local_delegate/server.py`
- test: `tests/test_tool_contract.py::test_fallback_info_uses_the_new_keys`
- resultado: FALLA (bien)
- assert: `>       assert set(info) == {"answered_by", "instead_of", "reason", "class"}`
- primera línea E: `E       AssertionError: assert {'answered_by..., 'respondio'} == {'answered_by...of', 'reason'}`

## M4 marcador de aviso viejo
- fichero: `src/local_delegate/sections.py`
- test: `tests/test_tool_contract.py::test_markers_are_the_new_ones_in_both_languages`
- resultado: FALLA (bien)
- assert: `>       assert server.WARNING_MARKER == "[local-delegate warning: "`
- primera línea E: `E       AssertionError: assert '[local-delegate aviso: ' == '[local-delegate warning: '`

## M5 valor por defecto cambiado
- fichero: `src/local_delegate/server.py`
- test: `tests/test_tool_contract.py::test_names_parameters_and_defaults_are_those_of_0_35`
- resultado: FALLA (bien)
- assert: `>           assert current == frozen[tool.name], tool.name`
- primera línea E: `E           AssertionError: local_summarize`

## M6 un Args: en español
- fichero: `src/local_delegate/server.py`
- test: `tests/test_tool_contract.py::test_descriptions_have_no_spanish`
- resultado: FALLA (bien)
- assert: `>       assert not found, found`
- primera línea E: `E       AssertionError: ['archivo', 'codigo', 'leido', 'ruta', 'servidor']`

## M7 sin singular en el aviso de secciones
- fichero: `src/local_delegate/sections.py`
- test: `tests/test_mcp_english.py::test_tool_outputs_have_no_spanish_in_english`
- resultado: FALLA (bien)
- assert: `>           assert expected in english, expected`
- primera línea E: `E           AssertionError: 1 section not summarized`
