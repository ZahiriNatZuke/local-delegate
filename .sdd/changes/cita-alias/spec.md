# Specification: El verificador de citas acepta un alias o una constante del nombre citado (#616)

## Summary

`line_check.check` deja de marcar como falsa una cita cuya línea usa un alias del nombre que la
respuesta cita: una constante cuyo valor es ese nombre (`READ_SUMMARY_TOOL = 'local_summarize'`),
una variable asignada a él (`summarize_fn = readSummarize`) o un `import … as`. Una cita en una línea sin el
nombre ni ninguno de sus alias sigue avisando.

Evidencia: issue #616; `line_check.py` `check` (l. 467) solo busca, como palabra entera, los
nombres y palabras de la línea de la respuesta en la ventana de la cita (`TOLERANCE = 1`).

## Requirements

- **REQ-001** — Una cita de la línea que usa una constante o una variable cuyo valor es el nombre
  citado (con o sin comillas, con anotación de tipo opcional) o un alias de `import … as` no se
  marca.
  - Request: "no debe acusar de falsa una cita que nombra lo que la línea hace mediante un alias o una constante"
  - Verify: test `test_a_citation_through_an_alias_holds` (repro del #616, Python con anotación, `import as`)
- **REQ-002** — Una cita a una línea sin el nombre ni ningún alias suyo sigue marcándose, y una
  comparación (`==`, `!=`, `<=`, `>=`) o una expresión más larga (`x = f(nombre)`) no crea alias.
  - Request: "sin dejar pasar citas falsas de verdad"
  - Verify: test `test_an_alias_does_not_cover_a_wrong_citation`, `test_a_comparison_or_a_call_is_not_an_alias`
- **REQ-003** — Los casos de revisión existentes (`CORRECT` y `WRONG`) dan lo mismo.
  - Request: derived: sin regresiones
  - Verify: test `test_the_review_cases` y `test_at_most_two_false_warnings_and_every_real_error` sin cambios
- **REQ-004** — La búsqueda de alias es lineal en el tamaño del fichero (sin retroceso catastrófico).
  - Request: derived: el verificador corre sobre ficheros grandes del usuario
  - Verify: test `test_the_alias_search_is_linear`

## Acceptance scenarios

### Scenario: la constante del #616

- **Given** un fichero con `const TOOL = 'local_summarize'` y una llamada `call(SERVER, TOOL, {})`
- **When** la respuesta dice que `local_summarize` se invoca en la línea de la llamada
- **Then** no hay aviso para esa línea

### Scenario: cita equivocada

- **Given** el mismo fichero
- **When** la respuesta cita una línea sin `local_summarize` ni `TOOL`
- **Then** esa línea se marca

## Edge cases and failure behavior

- Solo un nivel de alias (no transitivo). Un alias corto o común (`_COMMON`) no cuenta.

## Non-functional requirements

- Funciones puras sobre cadenas, como el resto del módulo; sin dependencias.

## Non-goals

- Seguir alias entre ficheros, o entender llamadas indirectas (`getattr`, tablas de despacho).
- La lista de apariciones exactas de la pregunta (no cambia).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
