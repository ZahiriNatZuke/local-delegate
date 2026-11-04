# Specification: local_extract: marcadores de sin dato a null y cuentas de listas vacías

## Summary

`local_extract` (issue #586) no devuelve como dato un marcador de «sin dato» (`"N/A"`,
`"desconocido"`, `"-"`, cadena vacía…): lo convierte a `null`, lo lista en `missing_keys` y avisa.
El prompt pide `null` para lo que no está, prohíbe rellenar una clave con el contenido de otra y
recuerda que una lista vacía tiene 0 elementos. Si la entrada es un objeto JSON y una clave pedida
es la cuenta de una lista de primer nivel (`number_of_comments` ↔ `comments`), el programa cuenta
la lista y corrige la cifra del modelo, con aviso.

## Requirements

- **REQ-001** — Un valor de primer nivel que es una cadena cuyo texto (sin espacios alrededor, sin
  mayúsculas, sin punto final) es un marcador de sin dato de la lista cerrada `_NO_DATA_MARKERS`
  (`n/a`, `n.a.`, `n/d`, `s/d`, `null`, `undefined`, `unknown`, `desconocido`, `no disponible`,
  `not available`, `no consta`, `no especificado`, `not specified`, `unspecified`, `no mencionado`,
  `not mentioned`, `not found`, `no encontrado`, `no aplica`, `not applicable`, `sin datos`,
  `no data`, `sin información`, `no information`, `-`, `--`, `—`, `?`, `...`, `…`, cadena vacía o
  solo espacios, y las variantes femeninas o sin tilde de los anteriores, `sin dato`, `---`, `–`)
  se devuelve como `null`. Riesgo asumido: `unknown`, `undefined`, `-`, `?` o `""` pueden ser un
  valor real en algún contexto (tipos de TypeScript); su texto no se pierde (`placeholder_keys`).
  - Request: "normaliza en servidor los marcadores de «sin dato» (N/A, n/a, none, null, unknown, -, cadena vacía, «no disponible», «no consta», etc.) a null"
  - Verify: test tests/test_extract_placeholder_values.py
- **REQ-002** — Esa clave entra en `_local_delegate.missing_keys` (orden de la petición), su valor
  original queda en `_local_delegate.placeholder_keys` (`{clave: valor}`) y `warning` lleva un aviso
  es/en propio (`mcp.warning.extract_placeholder_keys`); el aviso de claves omitidas sigue nombrando
  solo las que el modelo omitió.
  - Request: "para que entren en missing_keys"
  - Verify: test tests/test_extract_placeholder_values.py
- **REQ-003** — Valores legítimos no se tocan: `"none"`/`"ninguno"` (respuesta «cero elementos»),
  `"NA"`, `"."`, `0`, `false`, listas y objetos (aunque contengan marcadores), y textos que solo contienen
  un marcador (`"N/A en Windows"`).
  - Request: "no conviertas valores legítimos"
  - Verify: test tests/test_extract_placeholder_values.py
- **REQ-004** — En la extracción troceada, al rellenar desde los parciales (#473) un null o un
  marcador del reduce, se salta un marcador de sin dato y se toma el siguiente valor real.
  - Request: derived: el relleno desde parciales tomaría un "N/A" de un trozo antes que el dato real de otro
  - Verify: test tests/test_extract_placeholder_values.py
- **REQ-005** — APLAZADO (escalado a la sesión principal): el refuerzo del prompt de sistema de
  `local_extract` (null para la clave sin dato, no rellenar una clave con otra, lista vacía = 0).
  Implementado y retirado: cambiar ese prompt rompe la red del corpus congelado
  (`tests/test_corpus.py`: `test_versioned_corpus_still_mirrors_production`,
  `test_retouched_reference_that_is_still_valid_is_caught_by_the_watch`,
  `test_affinity_check_is_ok_with_any_environment_language[None|en]`), que exige declarar una
  frontera en `scripts/build_corpus.py::PROMPT_BOUNDARIES` y cambiar los conjuntos fijos de esos
  tests, más las fixtures `tests/fixtures/request_bodies/extract_schema*.json`. La regla de la
  jornada prohíbe modificar tests existentes sin decisión.
  - Request: "refuerza el prompt de extracción: campo sin dato → null; no rellenar un campo con contenido de otro; una lista vacía cuenta 0"
  - Verify: review .sdd/changes/extract-placeholder-values/verification.md
- **REQ-006** — Si la entrada entera es un objeto JSON y una clave pedida tiene forma de cuenta
  (`number_of_X`, `num_X`, `count_of_X`, `count_X`, `X_count`, también camelCase) y exactamente una
  clave de primer nivel del JSON coincide con `X` (o `X` + `s`, con la forma de `_key_shape`) y su
  valor es una lista, y el JSON no trae ya en primer nivel una clave con la forma de la pedida
  (página de una lista más larga), el valor devuelto es `len(lista)` (un BOM inicial se ignora; un
  JSON que no se puede leer, incluido un entero de más de 4300 dígitos, no se recuenta); si el modelo dio otra cosa, queda en
  `_local_delegate.recounted_keys` (`{clave: {"model": v, "count": n, "source": X}}`) con aviso
  es/en, y la clave sale de `missing_keys`. Si no se cumple todo, no se toca nada.
  - Request: "Si ves una guarda programática razonable para el caso «cuenta de una lista vacía», valórala, pero no inventes heurísticas frágiles"
  - Verify: test tests/test_extract_placeholder_values.py
- **REQ-007** — Los tests existentes y sus fixtures siguen pasando sin cambios (solo se añaden una
  excepción de texto en `tests/data/uncatalogued_exceptions.json` y palabras inglesas al léxico
  `scripts/data/spanish_lexicon.json`, que es el procedimiento de esos guardianes).
  - Request: "los tests existentes intactos"
  - Verify: cmd bash ~/.claude/scripts/pesado.sh pytest -n 2
- **REQ-008** — CHANGELOG `[Unreleased]` → Fixed con (#586).
  - Request: derived: regla de release del repo
  - Verify: review CHANGELOG.md

## Acceptance scenarios

### Scenario: el JSON del issue

- **Given** un JSON con `"comments": []`, `"reviews"` con 2 entradas y un modelo que responde
  `{"review_verdict": "N/A", "number_of_comments": 2, "number_of_reviews": 2}`
- **When** se llama a `local_extract`
- **Then** `review_verdict` es `null` y está en `missing_keys`, `number_of_comments` es `0` con
  `recounted_keys`, y `number_of_reviews` queda en `2` sin aviso

## Edge cases and failure behavior

- Respuesta no JSON o que no es objeto: igual que hoy (error en `_local_delegate`).
- Clave pedida `_local_delegate`: fuera de la normalización, como hoy.
- Entrada que no es JSON, JSON que es una lista, o dos claves que encajan con la cuenta: sin recuento.
- Un aviso anterior (truncado, nulls troceados) conserva su texto exacto (#455); los nuevos se
  añaden detrás con `; `.

## Non-functional requirements

- Determinista, sin llamadas extra al modelo; una sola `json.loads` de la entrada (ya en memoria).

## Non-goals

- Detectar que un texto libre es un resumen de otro campo (comentarios = resumen del cuerpo): queda
  al prompt; una comparación de similitud sería frágil.
- Marcadores dentro de listas u objetos anidados.
