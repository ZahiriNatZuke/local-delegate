# Specification: local_summarize troceado: reintentar una vez las secciones que faltan y nombrarlas en el aviso (#691)

Nivel `lite`: toca el camino troceado de `local_summarize` (una llamada más al backend, riesgo
medio según el arreglo R5 de `.sdd/changes/text-tools-common-cause/research.md`).

## Summary

Cuando un resumen troceado sale sin alguna sección (el modelo la omitió o la dejó sin contenido),
el servidor la vuelve a pedir **una vez**, agrupada con las demás que faltan, y la pone en su
sitio. Lo que siga faltando ya no se rellena con «(sin resumir)» en el cuerpo: sale **una sola
vez**, en el aviso, con sus títulos.

## Requirements

- **REQ-001** — En el camino troceado (`reduce="concat"`), si tras unir los parciales faltan
  secciones o quedaron vacías (sin contar las vacías en el propio documento), se hace **una**
  llamada más al backend con solo esas secciones; nunca más de una.
  - Request: "reintentar UNA vez, por programa, las secciones que faltan"
  - Verify: test tests/test_summarize_retry_missing_sections.py
- **REQ-002** — Lo que el reintento resume entra en su sitio (orden del documento) y deja de
  contar como faltante.
  - Request: "reintentar UNA vez, por programa, las secciones que faltan"
  - Verify: test tests/test_summarize_retry_missing_sections.py
- **REQ-003** — Lo que sigue faltando tras el reintento no aparece en el cuerpo (ni título ni
  «(sin resumir)»); el aviso lo cuenta y nombra cada título **una vez**.
  - Request: "si siguen faltando nombrarlas una sola vez en el aviso"
  - Verify: test tests/test_summarize_retry_missing_sections.py
- **REQ-004** — Sin secciones que falten no hay reintento; si el reintento falla en el backend,
  se devuelve el resumen de antes (con el aviso de REQ-003), no un error.
  - Request: derived: el reintento es opcional y no puede empeorar la respuesta
  - Verify: test tests/test_summarize_retry_missing_sections.py
- **REQ-005** — El reintento va en la misma operación: un único evento de log, con el paso
  contado en `steps` (`kind: "retry"`).
  - Request: derived: el panel y el log cuentan operaciones, no llamadas sueltas
  - Verify: test tests/test_summarize_retry_missing_sections.py

## Acceptance scenarios

### Scenario: la sección vuelve vacía la primera vez y bien la segunda

- **Given** un Markdown que se trocea en varias partes y un backend que omite 2 secciones
- **When** se llama a `local_summarize(path=…)`
- **Then** hay una llamada de reintento con esas 2 secciones, salen resumidas en su sitio, y no
  hay «(sin resumir)» ni aviso de secciones sin resumir

### Scenario: falla dos veces

- **Given** el mismo documento y un backend que también las omite en el reintento
- **When** se llama a `local_summarize(path=…)`
- **Then** hay un solo reintento, el cuerpo no tiene «(sin resumir)» ni esos títulos, y el aviso
  cuenta 2 secciones sin resumir y nombra cada título una vez

## Edge cases and failure behavior

- El material de las secciones a reintentar no cabe en un trozo: se piden las que caben, en
  orden; las demás quedan nombradas en el aviso.
- El reintento cortado por `length`: lo que traiga con contenido entra; cuenta como llamada
  truncada como cualquier otro paso.
- Sin tiempo según el presupuesto de la llamada (#596): no se reintenta.

## Non-functional requirements

- Prompt del map intacto (sin cambios de prompt). Llamada simple (sin trocear) intacta byte a
  byte: sigue con su marcador «(sin resumir)» y sus tests.

## Non-goals

- `local_extract`, `codex_reads.py` y el camino de una sola llamada.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
