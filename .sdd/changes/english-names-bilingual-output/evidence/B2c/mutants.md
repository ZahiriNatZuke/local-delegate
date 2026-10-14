# Mutantes de B2c (aplicados de verdad y restaurados)

## M1a — formato del commit de hoy (cuerpo opcional)
- `test_the_single_call_asks_for_a_body_and_has_room_for_it`: **FALLA**
    - `>       assert BODY in calls[0]["system"], calls[0]["system"]`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un mensaje de commit estilo Conventional Commits: primera línea 'tipo(scope): resu`
    - `E       assert 'cuerpo OBLIGATORIO de 2 a 6 viñetas' in 'Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un mensaje de commit es...ué cambia y para qué. N`
- `test_the_final_step_of_the_chunking_asks_for_a_body_and_has_room_for_it`: **FALLA**
    - `>       assert BODY in final["system"], final["system"]`
    - `E       AssertionError: Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un mensaje de commit estilo Conventional Commits: primera línea 'tipo(scope): resu`
    - `E       assert 'cuerpo OBLIGATORIO de 2 a 6 viñetas' in 'Responde directo desde el input. NO uses herramientas, NO busques en internet. Output EXACTO: un mensaje de commit es...ué cambia y para qué. N`

## M1b — topes del commit de hoy (256 tokens, 90 palabras)
- `test_the_single_call_asks_for_a_body_and_has_room_for_it`: **FALLA**
    - `>       assert calls[0]["max_tokens"] >= 700`
    - `E       assert 256 >= 700`
- `test_the_final_step_of_the_chunking_asks_for_a_body_and_has_room_for_it`: **FALLA**
    - `>       assert final["max_tokens"] >= 564`
    - `E       assert 244 >= 564`

## M2 — explain_code por el camino de hoy (trunca y una llamada)
- `test_explain_code_reads_a_large_file_whole`: **FALLA**
    - `>       assert any("def ZZZ_marker" in c["user"] for c in calls), "el final del fichero no llegó"`
    - `E       AssertionError: el final del fichero no llegó`
    - `E       assert False`

## M3 — extract por el camino de hoy (trunca y una llamada)
- `test_extract_reads_a_large_input_whole`: **FALLA**
    - `>       assert data["a"] == "ZZZ_value", "el final de la entrada no llegó"`
    - `E       AssertionError: el final de la entrada no llegó`
    - `E       assert None == 'ZZZ_value'`

## M4 — sin atajo: siempre reduce por el modelo
- `test_extract_reads_a_large_input_whole`: **FALLA**
    - `>       assert all("Combina" not in c["system"] for c in calls), "redujo sin necesidad"`
    - `E       AssertionError: redujo sin necesidad`
    - `E       assert False`

## M5 — sin inventario de nombres en el paso final
- `test_explain_code_reads_a_large_file_whole`: **FALLA**
    - `>       assert "ZZZ_marker" in final["user"].split("\n\n", 1)[0], "el inventario no lo nombra"`
    - `E       AssertionError: el inventario no lo nombra`
    - `E       assert 'ZZZ_marker' in 'Estas son notas EN ORDEN sobre los fragmentos de un mismo fichero de código. La lista de arriba es el inventario COMPLETO de sus definiciones de primer nivel; las notas`

## M6 — truncated deja de reflejar la salida truncada
- `test_extract_truncated_means_a_truncated_output_in_the_chunking`: **FALLA**
    - `>       meta = data["_local_delegate"]`
    - `E       KeyError: '_local_delegate'`
- `test_extract_truncated_means_a_truncated_output_in_one_call`: **FALLA**
    - `>       assert data["_local_delegate"]["truncated"] is True`
    - `E       KeyError: '_local_delegate'`

## M7 — los decoradores no se pegan a su definición
- `test_split_by_top_level_defs_keeps_the_text_and_the_decorators`: **FALLA**
    - `>       assert [p.split("\n", 1)[0] for p in pieces] == [`
    - `E       AssertionError: assert ['import os',...ync def g():'] == ['import os',...ync def g():']`
    - `E`
- `test_explain_code_does_not_split_a_definition`: **FALLA**
    - `>           assert piece.count("@decorator(") == piece.count("def function_"), piece[:80]`
    - `E           AssertionError: """Módulo de prueba."""`
    - `E`

## M8 — frontera de prompts sin local_commit_msg
- `test_versioned_corpus_still_mirrors_production`: **FALLA**
    - `>       assert build.check_versioned(DESTINATION, notices=notices) == []`
    - `E       AssertionError: assert ['commit-diff... constructor'] == []`
    - `E`

