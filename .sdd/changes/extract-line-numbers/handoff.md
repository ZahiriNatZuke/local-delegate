# Handoff: local_extract numera las líneas con path para campos de ubicación (#568)

## Current state

- SDD status: closed (PR de cierre `chore/close-sdd-2026-11-04-tarde`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `d4a3bb1f` (PR #573, 2026-11-04T16:42:22Z)

## What changed

- `local_extract` con `path` numera las líneas del fichero (reutiliza `_number_lines` y `_numbered_code_pieces` del #460) cuando algún campo pide una ubicación (`lines`/`lineas`/`lineno` o `line` con calificador, incluidos `heading_line`/`section_line`); el texto en línea nunca se numera.
- El prefijo `N| ` se quita de los demás campos; las líneas citadas se comprueban y las dudosas salen en `lines_unverified`; `[inicio, fin]` se trata como rango.
- En ficheros Markdown cada trozo lleva un esquema de encabezados con su línea real, descontado del presupuesto del trozo.
- Ajustes de la revisión independiente: campos de cantidad (`lines_added`, `total_lines`) no activan la numeración; con cita explícita no se buscan rangos sueltos; la ubicación se une por programa desde los parciales (sin depender del reduce); el aviso de líneas se suma a otros avisos.
- Skill `local-delegation` (es/en) con la aclaración nueva.

## Decisions

- El esquema de encabezados va solo al prompt, no al recibo (gastaría contexto de Claude).
- La comprobación de líneas es por palabras del elemento: es un aviso conservador, no una prueba de exactitud.
- Riesgo residual aceptado: una llamada única puede pasar de `max_chars` (mismo criterio que #460); el hook y el aviso del mod siguen sin la aclaración (el mod exige reconstrucción).

## Next action

- Ninguna para este cambio. Si se quiere, llevar la aclaración al hook y al aviso del mod en un cambio aparte.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
