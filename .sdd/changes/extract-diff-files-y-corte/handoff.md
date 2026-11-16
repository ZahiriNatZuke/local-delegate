# Handoff: local_extract: ficheros de un diff por programa y respuesta de líneas cortada (#665, #666)

## Current state

- SDD status: closed; PR #676 en verde, sin mezclar
- Last completed gate: memory
- Current revision: rama del worktree sobre b4669c85

## What changed

- #665: un campo que solo pide los ficheros de un diff y sus líneas lo responde el programa
  (`line_check.asks_for_diff_files` + `diff_file_ranges`); `_local_delegate.diff_files` lo dice y
  `model_error` lleva el fallo del modelo cuando lo hay.
- #666: la llamada única cortada con campos de líneas se rehace troceada; su fila de uso se pliega
  en la del rehecho; el error cortado dice `max_tokens`; `lines_unverified` mira también lo cortado.

## Decisions

- La hipótesis de #665 (fusión que se queda con el primero) era falsa: la unión ya concatenaba.
  El fallo era del modelo; la solución es determinista, no un prompt.
- Solo plurales de fichero cuentan; «modificados» sí, porque en un diff todos lo están.
- No se rehace una respuesta cortada sin campos de líneas: sus valores compiten entre trozos.

## Next action

- Tras la mezcla, prueba en vivo con `test-window` de `local_extract` sobre un `.patch` real y un
  Markdown grande con un campo de líneas.

## Memory

- Canonical note: ninguna nueva; lo durable está en este expediente y en el CHANGELOG.
- Indexes updated: no
