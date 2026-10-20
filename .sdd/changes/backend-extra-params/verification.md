# Verification: Parámetros extra por petición al backend (reasoning effort y extra body)

## Environment

- Revision:
- Relevant runtime and tool versions:

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | | | |

## Quality checks

- [ ] Project-native tests pass.
- [ ] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes.
- [ ] No unrelated changes are present.

## Deviations and residual risk

- Record skipped checks, known limitations, and why the evidence is still sufficient or not.


## Desviaciones durante la implementación

### Guarda de REQ-014 (b): excepción de `local_delegate.model` (lotes L0 y A1)

- `tests/test_tool_signatures.py` exime el par `("local_delegate", "model")`. `model` es una clave
  reservada (REQ-005), pero ese argumento existe en `main` desde antes de este cambio (elige el
  modelo explícito, que no lleva parámetros de rol, REQ-013); quitarlo rompería a los clientes y el
  assert (a) de la instantánea. La excepción es por (tool, parámetro): el mismo nombre en otra tool
  sí dispara la guarda. Desde A1 (T3, paso 7) la guarda lee `backend_params.ALLOWED_KEYS |
  backend_params.RESERVED_KEYS` en vez de una copia literal.

### Decisiones del lote A1 (reglas puras: T3, T4 y T5)

1. El test `test_every_warning_code_has_text_in_es_and_en` del plan se llama
   `test_every_warning_code_has_text_in_both_languages`: el detector de nombres en español
   marcaba el nombre del plan.
2. Léxico del detector: 13 palabras más a inglés (entrada 15 del README del léxico); ver abajo.
3. El tope de 2048 tiene una sola copia: `backend_params.MAX_OVERRIDE_CHARS` toma
   `config.BACKEND_PARAMS_OVERRIDE_MAX_CHARS`.
4. `to_body`: `overrides` lleva siempre `temperature` y `max_tokens` (los de la tool si el rol no
   los cambia); `extra` va en el orden del catálogo; `reasoning_budget_tokens` solo con el
   razonamiento encendido y permitido; `reasoning_effort` siempre que esté configurado, también con
   `thinking_allowed=False`; `enable_thinking=true` sin presupuesto no manda nada.
5. Gramática de la variable: un trozo sin `.` avisa con `role=""` y como clave la parte izquierda;
   en una clave repetida decide la última aparición aunque sea la inválida; lo que va tras `=` nunca
   entra en un aviso.
6. Números: `nan`, `inf` y `1_000` como texto son `bad_type`; `1e400` es `bad_type` en clave entera
   y `out_of_range` en decimal; una clave decimal acepta un entero y una entera no acepta un
   decimal (`top_k: 20.0`).
7. La clase `Warning` tapa el builtin dentro del módulo; se conserva el nombre del plan (ruff no lo
   marca).
8. Los códigos `file_*` y `context_*` aún no tienen productor (llegan en tareas posteriores): el
   test de textos los construye a mano.

### Léxico del detector de nombres tocado fuera de lo que cada lote poseía

- `scripts/data/spanish_lexicon.json` y su README no estaban en la lista de ficheros de ningún
  lote, pero `tests/test_detect_spanish_names.py::test_repo_has_no_spanish_name_outside_the_exception_list`
  exige 0 palabras sin clasificar. L0 añadió 14 (entrada 13), E 6 (entrada 14: `rechazados` a
  español y 5 a inglés) y A1 13 más (entrada 15, todas a inglés), clasificadas a mano. Al rebasar
  se unieron las listas (ordenadas y sin duplicados).
