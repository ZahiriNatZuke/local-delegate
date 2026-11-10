# Handoff: local_extract: aviso de valor cruzado entre claves y subida al rol long en tablas (#586)

## Current state

- SDD status: `implementing`; la sesión coordinadora pasa a `verifying` y aprueba `quality`,
  `conformance` y `memory` con la CLI.
- Last completed gate: `plan`.
- Current revision: PR #643 mezclado en `main` (`da15a6f6`), dentro de la release 0.51.0 (PR #653).

## What changed

- T1, T2, T3, T5, T6, T7 y T8 hechas; T4 y el commit del aviso, `[-]` (D11).
- Prueba en vivo (REQ-038) pasada el 2026-11-10 (`verification.md`, «Prueba en vivo (REQ-038),
  resultado»); #586 cerrado con el comentario de abajo y seguimiento público #650; revisión de
  resultado en `review.md`.

## Decisions

- El motivo del rol viaja por una `ContextVar` (filas que la operación escribe desde su hilo) y por
  `cancellation.Token.role_reason` (filas de `_log_stopped`, que escribe el middleware fuera de ese
  contexto). El decorador `_role_reason_scope` abre y cierra el ámbito de la `ContextVar`; el
  cuerpo sigue dentro de `local_extract`.
- `ruff` salta `.sdd/changes/extract-cross-fill-and-routing` (`extend-exclude` + `force-exclude`)
  para no reescribir el detector congelado.

## Next action

- Puertas y estado `closed`. En el tablero, la tarjeta «mandar al rol long las tablas y los extract
  con muchos campos parecidos (#586)» sigue en «Por hacer»: pasarla a «Hecho» (la parte de muchos
  campos no se hace, D1) y dejar la del aviso enlazada al #650.
- Los borradores de abajo ya se publicaron (#586 y #650); quedan como registro.

### Borrador del comentario de cierre del #586 (T8, REQ-039)

> **Queda fuera de este cierre el caso que abrió el issue** (la página de 33 KB, que ya iba al rol
> `long`, con el valor de una fila que nadie pidió) **y el aviso de valor cruzado**: los dos siguen
> en #<seguimiento>.
>
> Lo que sí entra en la <versión>: `local_extract` manda al modelo de contexto largo una entrada
> pequeña que trae una tabla HTML o Markdown, también con un solo campo. Medido por la propia tool:
> el modelo mecánico contestaba con el valor de otra fila en 8 de las 16 tablas pequeñas (y en 7 de
> 8 claves pedidas solas); el largo, en 0 de esas 8, sin fallar ninguna de las 44 claves de las
> limpias. En la prueba en vivo: <cifras de `outputs/live-score.json`>. La respuesta lo dice en
> `_local_delegate.role_reason` y el log en `role_reason: "table"`.
>
> Lo que cuesta: mediana de inferencia de 2,9 s frente a 0,84 s; de 10 a 13 s más si el modelo
> largo no estaba cargado; el respaldo pasa a ser el modelo de `code`. Se apaga con
> `LOCAL_DELEGATE_EXTRACT_TABLE_LONG=0`.
>
> Límites: CSV, TSV, tablas GFM sin tuberías externas, el separador `|-|-|` y las rejillas de
> `<div>` no se ven y siguen en el modelo mecánico.

### Borrador del issue público de seguimiento (T8, REQ-039)

Título: `local_extract: valor de otra fila en una página grande (rol long), aviso de valor cruzado y tablas que la regla no ve`

- **El caso del #586**: página HTML de unos 33 KB, ya en el rol `long`, con el valor de una fila
  que nadie pidió. No se reprodujo con páginas inventadas de 6,6 y 29 KB. Criterio de reapertura:
  una entrada inventada que lo reproduzca.
- **El aviso de valor cruzado**: un detector estricto (valor de la clave igual a la celda de la
  fila de otra clave pedida) dio 1 aviso en falso en cada pasada de un conjunto escrito a ciegas:
  número repetido en dos filas, con la fila propia de etiqueta sinónima (una clave `price` con
  valor `39`, fila «Retail cost (USD)», y el mismo `39` en la fila de otra clave pedida). Vuelve a
  diseño con su propia puerta.
- **Tablas que la regla no ve**: un CSV en el que el modelo mecánico rellenó una celda vacía con la
  celda vecina de su fila (no pedida), y otro CSV ambiguo (el valor es a la vez un trozo de la
  celda propia y la celda entera de otra fila).

Tarjetas del tablero: una para este seguimiento y otra para el #630 (`local_summarize`), buscando
antes si ya existen.

## Memory

- Canonical note: pendiente (la escribe la sesión coordinadora al cerrar).
- Indexes updated: no.
