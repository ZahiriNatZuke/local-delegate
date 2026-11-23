# Handoff: local_extract: nombres de campo de ficheros y hunks de un diff por programa, sin null silencioso (#665)

## Current state

- SDD status: result-review (spec, plan y quality aprobadas)
- Last completed gate: quality
- Current revision: rama `fix/extract-diff-files-names`

## What changed

- `line_check`: `asks_for_diff_hunks`, `diff_file_hunks` (y `diff_file_ranges` encima), recuento
  `changed/modified` delante de un plural de ficheros ya no anula el campo de líneas.
- `local_extract`: sufijo `.patch`/`.diff` como diff, valor de hunks por programa, avisos
  `extract_diff_unparsed` y `extract_diff_null_hint` (es+en).

## Decisions

- `hunks_with_lines` a secas sigue siendo del modelo (test existente del #676).
- Formato de hunks: `ruta: primera-última (hunks: a-b, c-d)`; sin hunks (binario), solo el rango.

## Next action

- Revisión de dos jueces (`review.md`) y puerta `conformance` en la sesión principal; prueba en
  vivo tras integrar en el PR conjunto.

## Memory

- Canonical note: ninguna nueva; el diagnóstico va en el comentario del issue #665.
- Indexes updated: no
