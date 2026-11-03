# Brief: local_summarize: no sacar secciones de las cadenas de un fichero de código

## Problem

Issue #539: `local_summarize(path=<.mjs de ~6,9 KB>)` con un template literal que contiene un
Markdown (`## Specs`, `## Tasks`, una línea `campo: ${variable}` seguida de `---`) devolvió un
resumen cuyos encabezados son las líneas de esa cadena, sin aviso. Causa raíz en nuestro código:
por encima de 6000 caracteres el rol es `long` y `sections.detect` busca títulos Markdown en el
texto entero, también en un fichero de código; toma `## Specs` (ATX) y `campo: ${variable}` + `---`
(setext) como secciones, se las pasa al modelo como «secciones en orden» y `sections.complete`
inserta las que el modelo no ponga. El modelo solo copia la estructura que le damos.

## Desired outcome

Un fichero de código (por extensión) no se resume por secciones Markdown, y si un título del
resumen copia literalmente una línea de una cadena del fuente, la respuesta lo avisa.

## In scope

- Saltar el resumen estructurado cuando `path` tiene extensión de código.
- Guarda determinista de salida con aviso `[local-delegate warning: …]`.

## Out of scope

- Cambiar los prompts del sistema de `local_summarize`.
- Cambiar `sections.detect` para texto en línea (un acento grave suelto en prosa Markdown haría
  perder secciones a documentos reales).

## Constraints and risks

- Los tests existentes no se tocan; un .md real no debe dar aviso (falsos positivos).

## Open questions

- Ninguna.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-03 Original request, verbatim:

  > Issue #539: local_summarize sobre un .mjs con Markdown en template literals promociona las líneas de las cadenas a encabezados del resumen, sin aviso
