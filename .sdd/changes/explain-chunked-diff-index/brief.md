# Brief: local_explain_code sobre un diff troceado: índice completo y líneas del patch (#582)

## Problem

`local_explain_code(path=<diff unificado de ~95 KB, 32 ficheros>, question="Lista los ficheros del
diff con el rango de líneas de cada uno dentro del patch")` devolvió 5 de 32 ficheros, un rango
242–257 para un fichero que está en 1–23, y no avisó del troceado.

Causa (comprobada con un diff sintético de 32 ficheros): la numeración `N| ` de cada trozo es
correcta (offset absoluto). El 242–257 es exactamente `+242,16` de una cabecera `@@ -a,b +242,16 @@`:
el modelo citó las líneas del fichero nuevo que da el hunk, no las del patch. Los 27 ficheros que
faltan vienen de los prompts: el map pide «una viñeta por cada función, clase o método», el
inventario de definiciones de primer nivel está vacío en un diff (sus líneas empiezan por
`+`/`-`/espacio) y el reduce ordena «no enumeres sus partes». Y el único aviso de troceado era el
recibo, que depende de `FEEDBACK_ENABLED`.

## Desired outcome

Con un diff troceado, el índice de ficheros con sus líneas en el patch es completo y exacto
(por programa), los prompts distinguen líneas del patch de cabeceras `@@`, y toda respuesta
troceada lo dice.

## In scope

- `local_explain_code` con `path` (numerado), contenido diff unificado, llamada troceada y única.
- Aviso de troceado en toda respuesta troceada de `local_explain_code`.

## Out of scope

- Responder sin modelo cuando la pregunta es solo un índice (detectarlo exige heurística de idioma).
- Otras tools (`local_summarize`, `local_extract`), zonas de los PR #579 y #581.

## Constraints and risks

- `server.py` en CRLF; tests existentes intactos; sin diff, los prompts byte a byte iguales salvo el
  aviso de troceado (que sí cambia la salida troceada de todo `local_explain_code`).

## Open questions

- Ninguna.

## Log

- L1 2026-11-04 Original request, verbatim:

  > Tarea: issue #582 — `local_explain_code` sobre un diff grande devuelve un índice parcial con
  > rangos desplazados, sin avisar del troceado. [...] Arreglo esperado (ajústalo con evidencia):
  > 1. Si los números se desplazan, corrígelo (numeración con el offset real en todos los caminos,
  > incluidos diffs). 2. Que una respuesta construida desde trozos lo diga siempre en
  > `_local_delegate` (troceado, nº de trozos) y que el reduce no tire trozos en preguntas de
  > enumeración. 3. Para diffs unificados (`diff --git`), valora una ruta determinista: el índice
  > de ficheros con sus rangos de línea en el patch se puede sacar sin modelo [...]
