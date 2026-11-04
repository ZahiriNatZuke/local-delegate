# Specification: local_summarize corta el resumen a mitad de frase con el max_words por defecto (#580)

## Summary

`local_summarize` con el `max_words` por defecto (150) devuelve resúmenes cortados a mitad de
palabra. Causa, con evidencia: la llamada única (camino plano, sin estructura) y el map/reduce piden
`max_tokens = 2 * max_words + 64` (364 con 150). Medido el 2026-11-04 contra el backend real
(ventana de prueba `w-20261104T174214Z`, gemma4-26b-a4b y gemma3-4b, salida en español): el modelo
gasta **1,46–1,67 tokens por palabra** (Markdown con backticks y negritas sube la cuenta) y se pasa
del presupuesto de palabras hasta **1,49×** (224 palabras para 150 pedidas). Juntos, 150 palabras
pedidas pueden necesitar ~2,5 tokens por palabra pedida: 364 no llega. En el log del mes, todos los
cortes de `local_summarize` plano acaban justo en 2w+64 (364, 464, 564, 664 tokens).

El resumen por secciones ya usa 3 tokens por palabra más títulos y colchón; no se toca.

## Requirements

- **REQ-001** — La llamada única de `local_summarize` pide `max_tokens = 3 * max_words + 64` (514
  con 150): margen medido sobre datos reales, el mismo factor que el resumen por secciones.
  - Request: "margen de tokens suficiente sobre `max_words` medido con datos reales"
  - Verify: test tests/test_summarize_word_budget.py
- **REQ-002** — El map/reduce de `local_summarize` usa el mismo tope en el map, el reagrupado y el
  reduce. `_chat_map_reduce` sin `max_tokens_for` sigue con 2w+64 (otras tools y tests).
  - Request: "¿Afecta también al resumen por secciones, al map/reduce…?"
  - Verify: test tests/test_summarize_word_budget.py
- **REQ-003** — Si la llamada única acaba en `finish_reason: length`, la salida se recorta en el
  último final de frase completo (o la última línea completa), sin dejar un título, una etiqueta
  `**…:**` o una línea que termina en `:` colgando, ni un bloque de código o marcado inline abierto.
  - Request: "recortar la salida en el último final de frase completo (sin perder estructura Markdown, sin dejar listas o bloques abiertos)"
  - Verify: test tests/test_summarize_word_budget.py
- **REQ-004** — Tras recortar, el aviso conserva «salida truncada por max_tokens» y añade que se
  recortó hasta la última frase completa (es y en). Si no hay dónde recortar, la salida y el aviso
  quedan como hoy.
  - Request: "conservar el aviso de truncado con texto que diga que se recortó"
  - Verify: test tests/test_summarize_word_budget.py
- **REQ-005** — Las llamadas que acaban en `stop` devuelven exactamente lo mismo que hoy; el
  contrato de `max_words` no cambia; los tests existentes pasan sin tocarlos.
  - Request: "No cambies el contrato de `max_words` ni la salida de las llamadas que hoy acaban bien."
  - Verify: test tests/test_summarize_word_budget.py

## Acceptance scenarios

### Scenario: corte a mitad de frase

- **Given** un backend que devuelve dos frases y media con `finish_reason: length`
- **When** se llama `local_summarize(text=…)` con el `max_words` por defecto
- **Then** la petición lleva `max_tokens: 514`, la salida acaba en la segunda frase y el aviso dice
  que se recortó

### Scenario: lista abierta

- **Given** una salida `Intro.\n\n**Puntos:**\n* uno.\n* dos a medi`
- **Then** queda `Intro.\n\n**Puntos:**\n* uno.` (la lista cerrada en su último elemento completo)

## Edge cases and failure behavior

- Sin ningún final de frase ni línea completa: se devuelve tal cual con el aviso de hoy.
- Un punto dentro de `código inline` o de un bloque ``` no cuenta como final.
- Un reintento con orden de acortar se descarta: duplicaría la latencia (decenas de segundos con
  el rol `long`) justo en los casos largos, y con el margen nuevo el corte pasa a ser raro.

## Non-functional requirements

- Sin cambio de coste en el caso normal: el tope solo limita, no alarga lo que el modelo escribe.

## Non-goals

- Resumen por secciones, `local_describe_image` (2w+64, 0 cortes en 3 meses de log), lint, commit,
  explain_code y extract, que tienen sus propios topes.
- Recortar la salida final del map/reduce (su aviso cuenta llamadas cortadas, no solo la final).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
