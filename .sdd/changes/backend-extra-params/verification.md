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

### Decisiones del lote A2 (fichero y resolución: T6 y T7)

1. **Dos códigos nuevos**, `file_busy` (el cerrojo no se libera en `LOCK_TIMEOUT` = 10 s) y
   `file_write_failed` (un `OSError` al escribir), con su texto es/en en `common.json`.
   `set_value`/`unset`/`reset` devuelven `(ok, code, warnings)` como pide el plan y no lanzan; sin
   estos dos códigos habrían tenido que dejar escapar `filelock.Timeout` y `OSError` hacia la CLI.
   `test_backend_params_i18n.py` (de A1) gana esos dos avisos en su lista de todos los códigos.
   `write(mutator)` sí deja pasar los dos errores: es la pieza de bajo nivel.
2. **Un rechazo lleva su aviso**: además del código, `warnings` trae `Warning(rol, clave, código)`
   para que la CLI (lote B) nombre rol y clave sin el valor.
3. **`set` nunca pisa un fichero que `load` ignoraría entero** (JSON roto, `version` ≠ 1, > 64 KB):
   devuelve el código `file_*` y no lo toca, como `test_windows._Locked`, que niega la escritura si
   el fichero existente es ilegible. Así no se pierde a ciegas una edición a mano.
4. **`reset` con el razonamiento encendido** (`test_reset_budget_rejected_while_thinking_on`):
   `reset` vacía el rol entero, `enable_thinking` incluido, así que no deja razonamiento sin
   presupuesto. Se implementa lo que piden el plan (paso 4 y la revisión P4) tal cual: se rechaza
   `reset <rol>` y `reset` global si algún rol que vaciaría tiene en el fichero
   `enable_thinking: true` **con** `reasoning_budget_tokens`; antes hay que hacer
   `unset <rol> enable_thinking`. Si se prefiere que `reset` lo vacíe todo sin preguntar, basta con
   quitar la primera vuelta de `reset.mutate` y ese test: es una decisión de producto para la CLI.
5. **`test_same_size_rewrite_is_seen` va en dos casos, `[set|in_place]`**. Con `set` el fichero
   se reemplaza con `os.replace` y cambia el `st_ino` (también en NTFS), así que el mutante que
   pide el plan (`st_mtime` en vez de `st_mtime_ns` y sin `st_size`, pero con `st_ino`) **no** lo
   haría fallar. El caso `in_place` reescribe el mismo fichero (mismo inodo, mismo tamaño) y fija
   la `mtime` 100 ns después con `os.utime(ns=…)`; a fechas actuales el `float` de `st_mtime` no
   distingue 100 ns. Con el mutante falla en el assert del valor (`20 == 30`); lo mismo para T7
   en `test_ctx_size_cache_sees_rewrite` (`4096 != 8000`).
6. **`write` no vacía la caché**: la invalidación depende solo de la clave
   `(st_mtime_ns, st_size, st_ino)` + valor crudo de la variable. Si el fichero cambia mientras se
   lee, el resultado no se cachea.
7. **`report()`**: una entrada por rol en el orden de `ROLES` y, solo si hay, una última con
   `role == ""` para los avisos que no son de ningún rol (fichero roto, variable larga, trozo sin
   rol, rol desconocido). `effective(rol).warnings` = los del rol + esos generales; un rol
   desconocido da valores vacíos.
8. **`unset` acepta cualquier clave** (también una que el catálogo rechaza) para poder limpiar una
   edición a mano; una clave ausente no es error. El rol sí se valida.
9. **`model_context_size`**: un valor de `--ctx-size`/`-c` que no es un entero positivo (`${CTX}`,
   `0`, `-5`) da el estimado; `llamaswap_config` importa ahora `config` (no hay ciclo). El código y
   los comentarios nuevos van en inglés, aunque el resto de `llamaswap_config.py` sigue en español.
10. En `tests/test_backend_params_file.py` se fija `model_context_size` a 32768 en todos los tests
    para que el aviso de contexto no dependa de la config de llama-swap de la máquina; los tests
    de contexto lo fijan a 8192.

### Decisiones del lote C1 (fusión en el embudo: T10)

1. **Dónde se fusiona**: `_RoleParams.apply` en `_call_model`, sobre el dict nuevo
   `{"model": model, **payload}`; el `payload` compartido no se toca. `temperature` y `max_tokens`
   se sustituyen en su sitio; las demás claves que devuelve `to_body` van al final y **nunca**
   pisan una clave que ya esté en el cuerpo (capa 3), además del `assert` de `to_body`.
2. **`_role_params_for` devuelve `None`** con modelo explícito, sin rol o si el rol no tiene ningún
   valor efectivo, aunque tenga avisos (p. ej. `enable_thinking` sin presupuesto y nada más): los
   avisos se ven en `show`, `doctor` y `local_status` (`report()`), no en cada llamada. Con `None`
   el cuerpo es el de hoy byte a byte.
3. En `_chat` la resolución va **dentro** del `try` que cierra la entrada en vuelo, para que un
   fallo inesperado al leer el fichero no deje la entrada colgada. En `_chat_chunked` y
   `_chat_map_reduce` se resuelve al crear `_CurrentModel`, como dice el plan.
4. `_RoleParams` ya lleva `probed`, `rejected`, `reasoning_skipped` (C2), `reasoning_chars` (D) y
   un `threading.Lock`; en C1 nadie los usa. `budget` solo tiene valor con el razonamiento
   encendido.
5. **Tests de más respecto a la lista del plan**: `test_vision_role_params_reach_image_call`
   (paso 7: la imagen lleva los parámetros de `vision` y no los de otro rol) y un caso `range` en
   `test_bad_keys_dropped_rest_applied` (REQ-007, `top_p: 1.5`). `test_reserved_key_never_reaches_body`
   recorre **todas** las claves de `RESERVED_KEYS`, por fichero y por variable.
6. `test_params_survive_fallback_and_later_chunks` usa `local_explain_code` troceado (map/reduce,
   rol `code`, `LOCAL_DELEGATE_MAX_CHARS_CODE=3000`) con el modelo de `code` caído: el respaldo es
   el de `long`, y `long` tiene su propio `top_k: 5` configurado para probar que el rol del
   respaldo no se cuela en la operación de `code`.
7. **Controles positivos** (mutante → test → assert que dispara):
   - `"top_k": 0` siempre en `_call_model` → `test_body_matches_main[simple-no_file]`, assert de
     igualdad del cuerpo («el cuerpo 0 no es el de f2dd267»);
   - `_CurrentModel.call` resuelve con `self.role` → `test_params_survive_fallback_and_later_chunks`,
     `assert body.get("top_k") == 33` en el índice 2 (primer trozo tras el salto);
   - `_role_params_for` sin mirar `explicit` → `test_explicit_model_carries_no_params`, igualdad
     con la fixture (sobra `top_k: 20`);
   - `apply` sin sustituir `temperature`/`max_tokens` → `test_role_temperature_overrides_tool[local_classify]`,
     `[0.0] == [0.5]`;
   - `_chat` pasa `role_params=None` → `test_thinking_on_classify_sums_budget`, `16 == 16 + 512`;
   - resolución cacheada por proceso → `test_file_change_applies_next_operation`,
     `[20, 20, 20] == [20, 30, None]`;
   - `local_describe_image` con rol `mechanical` → `test_vision_role_params_reach_image_call`,
     `99 == 7`;
   - en `backend_params.py` (mutantes temporales, no cambios): `apply_thinking_rule` apagado →
     `test_thinking_without_budget_body_has_no_template_kwargs[file]`, assert del aviso;
     `enable_thinking: false` sin mandar nada → `test_thinking_off_sends_false_and_keeps_max_tokens`,
     `KeyError: 'chat_template_kwargs'`; validación de valores apagada →
     `test_bad_keys_dropped_rest_applied[range]`, `assert 'top_p' not in body`; `key_problem` sin
     `reserved_key` → `test_reserved_key_never_reaches_body[cache_prompt-file]`, en el assert del
     **código** del aviso (`unknown_key` en vez de `reserved_key`): la clave no llega al cuerpo de
     todos modos, porque la filtran tres capas (`key_problem`, `_catalog_order` y el filtro de
     `to_body`); un mutante de una sola capa no puede hacer fallar los asserts del cuerpo.
8. `backend_params.py` no se toca.

### Decisiones del lote B (CLI y `doctor`: T8 y T9)

1. **La desviación 4 del lote A2 queda resuelta por la decisión 12 del usuario** (`brief.md`):
   `reset` ya no se rechaza con el razonamiento encendido. Se quitó la primera vuelta de
   `reset.mutate` en `backend_params.py` (el único cambio del lote en ese módulo) y el test
   `test_reset_budget_rejected_while_thinking_on` pasa a `test_reset_empties_role_with_thinking_on`
   (`[role|all]`), que comprueba que el rol queda vacío; con el bloqueo repuesto como mutante falla
   en `assert bp.reset(...) == (True, None, [])`.
2. **Textos de rechazo propios de la CLI**: los de `common.json` describen lo que hace una tool con
   una entrada mala («se quita»), no una orden rechazada. `cli.json` lleva
   `cli.backend_params.refused.<código>` para `unknown_role`, `unknown_key`, `reserved_key`,
   `deferred_key`, `bad_type` y `out_of_range`, y dos para `thinking_without_budget` según la orden
   (`thinking_set`: «antes, `set <rol> reasoning_budget_tokens <n>`»; `thinking_unset`: «antes,
   `unset <rol> enable_thinking`»). Los `file_*` usan el texto común, que ya se lee como rechazo.
   Nombran rol y clave, nunca el valor.
3. **Códigos de salida**: rechazo → 2 (como `test-window`), con el motivo en stderr y nada en
   stdout; éxito → 0, con la línea de confirmación en stdout (sin el valor) y los avisos de contexto
   de `set` en stderr.
4. **Forma de `show --json`**: `{"file": ruta, "roles": [{"role", "params": [{"key", "value",
   "source"}], "warnings": [{"code", "key"}]}]}`, con los cuatro roles siempre y una última entrada
   `role == ""` solo si hay avisos generales (la de `report()`). `value` va con su tipo JSON
   (`true`, `20`, `0.1`).
5. **`show` en texto**: primero `Fichero: <ruta>`; luego solo los roles con valores o avisos, cada
   uno con `clave = valor  (fichero|variable)` y sus avisos; sin nada, «sin parámetros». Los
   booleanos se escriben `on`/`off`, como en `set` (`doctor.format_param_value`, que reutiliza la
   CLI).
6. **`doctor`**: las líneas salen justo después de las de idioma y con su misma columna. Hay líneas
   si algún rol tiene valores o avisos, o si `LOCAL_DELEGATE_BACKEND_PARAMS` está definida en esta
   shell (aunque sus entradas se descarten); definida pero vacía cuenta como no definida. Las
   claves que vienen de la variable llevan la marca `(variable)`.
7. **Fuera de los ficheros del lote**: `tests/test_cli_english.py` gana las cinco rutas de ayuda de
   `backend-params` en `HELP_PATHS` (así la ayuda nueva entra en los tests de idioma), y
   `tests/test_doctor_backend_params.py` importa `_stub_environment` de `tests/test_doctor.py`.
8. **Léxico del detector**: ninguna entrada nueva. La única palabra que marcó (`bpsub`, una
   variable) se renombró a `commands`; la entrada 17 queda libre.
9. Tests de más sobre los del plan: `test_show_text_rows` y
   `test_doctor_lines_with_only_the_variable_and_nothing_valid`. El de «salida idéntica a la de
   hoy» compara `doctor` con y sin las líneas nuevas y además exige la costura de hoy (líneas de
   idioma, una línea en blanco, la leyenda): sin ella, un `print()` de más en el sitio de la llamada
   sobrevivía como mutante.

### Léxico del detector de nombres tocado fuera de lo que cada lote poseía

- `scripts/data/spanish_lexicon.json` y su README no estaban en la lista de ficheros de ningún
  lote, pero `tests/test_detect_spanish_names.py::test_repo_has_no_spanish_name_outside_the_exception_list`
  exige 0 palabras sin clasificar. L0 añadió 14 (entrada 13), E 6 (entrada 14: `rechazados` a
  español y 5 a inglés), A1 13 más (entrada 15, todas a inglés) y A2 9 más (entrada 16, todas a
  inglés), clasificadas a mano. Al rebasar se unieron las listas (ordenadas y sin duplicados).
  C1 añadió 1 (entrada 18: `survive`, a inglés); B ninguna (la entrada 17 queda libre).
