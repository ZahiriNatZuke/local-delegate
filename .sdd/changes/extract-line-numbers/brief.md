# Brief: local_extract numera las líneas con path para campos de ubicación (#568)

## Problem

`local_extract(path=<Markdown ~1900 líneas>, fields=[..., "secciones_con_lineas"])` se trocea en 8
partes y devuelve todo `null`: el modelo nunca ve números de línea (igual que `local_explain_code`
antes de #460), así que un campo de localización no tiene respuesta posible.

## Desired outcome

Con `path` y algún campo que pida líneas, el modelo ve cada línea como `N| línea` con el número
absoluto del fichero (también en cada trozo), para Markdown recibe además el esquema de
encabezados con su línea (calculado por programa), y el servidor comprueba las líneas citadas.

## In scope

- Numeración con `path` cuando algún campo es de ubicación (criterio determinista por nombre).
- Esquema de encabezados Markdown en el prompt (acotado en tamaño).
- Comprobación en el servidor de las líneas citadas en los campos de ubicación.
- Quitar el prefijo `N| ` copiado en los valores de campos que no son de ubicación.
- Texto de la skill: decir que el nombre del campo debe pedir líneas.

## Out of scope

- Una tool nueva `local_locate`.
- Numerar `text=` en línea (no hay fichero al que remitir).
- Cambiar `local_explain_code`.

## Constraints and risks

- Sin regresiones: con campos que no son de ubicación, o con `text=`, todo queda byte a byte igual.
- `server.py` es CRLF; los JSON de i18n y la skill son LF.

## Open questions

- Ninguna que cambie la spec.

## Log

- L1 2026-11-04 Original request, verbatim:

  > Tu tarea: issue #568 — `local_extract` no puede localizar líneas en un Markdown grande [...]
  > Alcance: 1. Con `path`, `local_extract` numera las líneas que ve el modelo [...] 2. Para
  > Markdown [...] esquema de encabezados con su línea [...] 3. Si el modelo cita líneas,
  > compruébalas en el servidor como en #464 [...] 4. Revisa el texto de la skill/bloque [...]
