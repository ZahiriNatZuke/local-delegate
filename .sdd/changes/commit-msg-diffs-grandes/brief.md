# Brief: local_commit_msg deja de truncar diffs grandes

## Problem

Reportado desde la Mac, usando el MCP en una sesión de trabajo real: para un diff de 71 000 chars
la tool devolvió `docs: update angular agents documentation` cuando el cambio era un refactor de
`paycorr-core`. El cliente lo describió como «inservible para este cambio».

Reproducido aquí por ejecución con `git diff 6a7959e HEAD` (164 585 chars, 44 archivos): la tool
procesa 20 027 chars —siete archivos, **todos de `.sdd/`**— y devuelve `chore: update GitHub
Actions pages artifact version`. Como `git diff` sale ordenado por ruta, lo que se descarta es
justo `src/` y `tests/`.

`local_commit_msg` era la única tool de reducción que seguía truncando: `local_summarize` y
`local_lint_summary` ya leen entero y bajan a `_chat_map_reduce`.

## Desired outcome

El diff entra completo y el mensaje refleja el cambio real, no el primer archivo por orden
alfabético de rutas. Y quien llama la tool puede ver sobre cuánto se redactó.

## In scope

- Que `local_commit_msg` procese el diff entero, partiéndolo por archivo.
- Que el paso que redacta el mensaje reciba el inventario completo del diff.
- Que el troceado entienda diffs, que hoy no los distingue de prosa.

## Out of scope

- Filtrar el ruido del diff (lockfiles, generados, líneas de contexto sin cambiar).
- Cambiar el modelo del rol `code` ni sus topes de `max_chars`.
- Tocar el resto de tools.

## Constraints and risks

- El coste sube de 1 llamada a N+1; es el trato que ya aceptaron las otras dos tools.
- La calidad del mensaje con N parciales no se puede verificar con mocks: hace falta el backend
  real, y la API key está cifrada con DPAPI, así que la corrida la tiene que lanzar el usuario.
- El daemon de esta máquina sale del paquete de `uv tool`, no del venv del repo.

## Open questions

Ninguna abierta. La que había —si el modelo de código produce un mensaje decente con muchos
parciales— se resolvió midiendo: la respuesta fue que no, y de ahí salieron las tareas 6 y 7.
