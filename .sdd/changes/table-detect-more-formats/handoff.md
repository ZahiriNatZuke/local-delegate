# Handoff: Detector de tablas: GFM sin tuberías externas, |-|-|, CSV, TSV y ARIA; local_summarize sube a long con tabla (#650)

## Current state

- SDD status: cerrado tras las puertas quality, conformance y memory
- Last completed gate: memory
- Current revision: rama `fix/table-detect-more-formats`, PR #658

## What changed

- `table_detect.table_format` nombra el formato (html, aria, markdown, csv, tsv); `has_table` es su sí o no.
- `local_extract`: `role_reason.format`. `local_summarize`: sube a long con tabla pequeña, aviso con el formato, `LOCAL_DELEGATE_SUMMARIZE_TABLE_LONG`.
- El aviso de cifras de #630 se queda en HTML, ARIA y Markdown.

## Decisions

- Rejillas de `<div>`: solo por rol ARIA; las clases maquetan páginas sin tabla.
- CSV/TSV: tres filas seguidas con el mismo número de separadores y sin pinta de prosa ni código; una coma entre dígitos no cuenta para el estilo; calibrado contra todo el árbol del repo.
- Las cifras de #630 no se abren con CSV/TSV: un log de CI con tabuladores traería de vuelta el ruido de los recuentos.
- El camino por secciones de summarize queda atado al tamaño.

## Next action

- Sesión principal: medir con el log de uso real cuántos `local_summarize` pequeños llevan tabla (volumen de subidas a long) y, si conviene, una prueba en vivo de latencia; no hay cambio de prompt.

## Memory

- Canonical note: este handoff; sin nota de vault propia (decisiones en el SDD y el PR)
- Indexes updated: ninguno
