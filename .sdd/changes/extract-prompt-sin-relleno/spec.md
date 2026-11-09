# Specification: local_extract: el prompt pide null y prohíbe rellenar con otra clave o fila

## Summary

`local_extract` (issue #586) pide al modelo, en todas sus llamadas (la única, cada trozo del map y
el reduce), `null` para lo que la entrada no trae y le prohíbe rellenar una clave con el dato de
otra clave o de otra fila. Antes solo el map decía «ponlo a null». Además, una lista vacía que el
schema obligó a escribir como la cadena `"[]"` vuelve como `[]`.

## Requirements

- **REQ-001** — El `system` de `local_extract` lleva, detrás del de siempre, la cláusula
  `_EXTRACT_NO_FILL_CLAUSE` («Si el contenido no trae el dato de una clave, pon null en vez de
  inventarlo, y no la rellenes con el dato de otra clave ni de otra fila de una tabla o lista.
  Sigue valiendo resumir, contar, clasificar o deducir lo que el contenido permite (por ejemplo,
  false si no menciona algo), y tomar lo que va dentro de una ruta o de un nombre.») en la
  llamada única, en cada trozo del map y en el reduce, también con la entrada numerada (#568).
  - Request: "El prompt de la llamada única (y el de los trozos, si lo hay) pide null para lo que la entrada no trae y prohíbe rellenar una clave con datos de otra clave o de otra fila"
  - Verify: test tests/test_extract_no_fill.py
- **REQ-002** — La frontera se declara en `scripts/build_corpus.py::PROMPT_BOUNDARIES` (`0.50.0`:
  `local_extract`); los corpus congelados siguen sin errores y lo dicen como aviso.
  - Request: "declara la frontera en `PROMPT_BOUNDARIES`"
  - Verify: test tests/test_corpus.py
- **REQ-003** — Los cuerpos congelados de `extract_schema` y `extract_schema_retry` siguen
  comparándose byte a byte, con el cambio declarado en `_CHANGED_SYSTEM_SUFFIX` de
  `tests/test_request_body_compat.py` (precedente: `_CHANGED_MAX_TOKENS` del #580); las fixtures
  no se regeneran (llevan anotado `f2dd267` y un test lo exige).
  - Request: "es el único caso en que se permite tocar tests existentes, y solo las fixtures de la petición" (ampliado por el orquestador: `_CHANGED_SYSTEM` como el #580 y las listas de fronteras de `test_corpus.py`)
  - Verify: test tests/test_request_body_compat.py
- **REQ-004** — Un valor de primer nivel que es, entero (sin espacios alrededor y con o sin el
  prefijo de línea), el texto `"[]"` vuelve como `[]`, con el texto original en
  `_local_delegate.decoded_keys` y sin aviso; cualquier otro texto (`"[1]"`, `"{}"`, `"none"`,
  y `"[ ]"`, la casilla sin marcar de Markdown) no se toca.
  - Request: "mira si el post-proceso puede normalizar una lista vacía en forma de cadena a `[]` o a null sin riesgo"
  - Verify: test tests/test_extract_no_fill.py

## Acceptance scenarios

### Scenario: tabla HTML sin el dato

- **Given** una tabla Standard/Enterprise sin fila de usuarios con licencia
- **When** se pide `licensed_user_limits`
- **Then** el modelo recibe la regla de no rellenar con otra fila y devuelve null

## Edge cases and failure behavior

- `"[]"` en un campo de recuento (`number_of_comments`) vuelve como `[]`, no como 0: `_recount_lists` (#591)
  no lo corrige, igual que antes no corregía el texto `"[]"`. Riesgo aceptado (revisión, juez A).
- Con la entrada numerada (#568), un `"12| []"` copiado con el prefijo también se decodifica.
- Entrada troceada: la regla va también en el map y en el reduce.

## Non-functional requirements

- Sin cambios de `max_tokens`, schema ni número de llamadas.

## Non-goals

- Medir la calidad con el backend real en esta rama: se hace en la prueba conjunta antes de la
  release con las 5 entradas de `scratchpad/live/rerun_after.md` (decisión del orquestador).
- Volver a un aviso por palabras sin respaldo (retirado en el #609).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
