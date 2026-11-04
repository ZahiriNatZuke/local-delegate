# Handoff: local_explain_code sobre un diff troceado: índice completo y líneas del patch (#582)

## Current state

- SDD status: closed (PR de cierre `chore/close-sdd-2026-11-04-tarde`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `cf1474d8` (PR #583)

## What changed

- `line_check.diff_file_ranges(content)`: `(inicio, fin, ruta)` por fichero de un diff unificado, en líneas del parche y sin modelo (sigue las cuentas de `@@`, corta en firma de `format-patch`, admite `diff -ru`/SVN y rutas citadas).
- `local_explain_code` con `path` y diff: el system aclara que los números de `@@` no son líneas del parche y lleva `_DIFF_NOTE`; al trocear, cada trozo recibe sus ficheros (máx. 20, reservados del presupuesto), el map da una viñeta por fichero y el reduce recibe el índice completo.
- La respuesta termina con el índice calculado por programa (50 ficheros, o 200 si la pregunta pide ficheros o líneas).
- Aviso de «respuesta construida a partir de N trozos» cuando el recibo está apagado (ajuste de la revisión independiente: con el recibo encendido no se repite).

## Decisions

- No se responde sin modelo cuando la pregunta es solo un índice: haría falta una heurística de idioma frágil; el índice exacto va siempre al final.
- La explicación troceada sin pregunta ni diff no lleva aviso: su salida está congelada por hash en un test existente que no se toca (REQ-005 restringido).
- Un hunk con cuentas que no casan (parche editado a mano) puede tragarse una cabecera `--- ` sin `diff --git`; se aceptó para no abrir ficheros falsos en diffs bien formados.

## Next action

- Ninguna. La prueba en vivo queda para cuando el daemon corra una versión que incluya `cf1474d8`.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
