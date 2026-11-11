# Brief: local_extract: aviso de valor cruzado entre claves (cross_filled_keys, #650)

## Problem

`local_extract` reparte a veces las filas de una tabla entre las claves pedidas casi por posición:
`licensed_user_limits` recibe la fila «Custom domains» de la clave pedida `custom_domain_limits`
(#586). El valor sale sin aviso. El detector estricto probado el 2026-11-10
(`.sdd/changes/extract-cross-fill-and-routing/detector.py`) dio 1 aviso en falso por pasada en el
conjunto a ciegas: `price` = `39`, fila propia «Retail cost (USD)» (sinónimo) y el mismo `39` en la
fila de `noise_level`.

## Desired outcome

Un aviso determinista en `_local_delegate.cross_filled_keys` cuando el valor de una clave solo está
en la fila de otra clave pedida, con 0 avisos en falso sobre un conjunto medido y los cruces del
#586 detectados. Solo aviso: el valor no cambia.

## In scope

- Detector nuevo (`src/local_delegate/cross_fill.py`) y su llamada en `local_extract`.
- Conjunto de medición como test parametrizado: los casos y respuestas reales del 2026-11-10 más 25
  tablas nuevas con respuestas escritas a mano.
- Aviso en los catálogos es/en, frase en la descripción de la tool, CHANGELOG y wiki.

## Out of scope

- El detector de tablas y el enrutado a `long` (otro agente, otra parte de `server.py`).
- El prompt de `local_extract` (no se toca).
- Poner a null o corregir el valor.

## Constraints and risks

- Heurística con riesgo de falsos positivos: puerta de medición propia (0 falsos positivos).
- `server.py` en CRLF; los catálogos y el CHANGELOG en LF.

## Open questions

- Ninguna que cambie la spec.

## Log

<!-- L1 is the original request, verbatim. -->

- L1 2026-11-11 Original request, verbatim:

  > Encargo: parte «aviso de valor cruzado» del issue público #650 de local-delegate (`gh issue view 650 -R ZahiriNatZuke/local-delegate`; mira también el #586 cerrado y sus comentarios). SDD `standard` (heurística con riesgo de falsos positivos: lleva puerta propia de medición), slug `extract-cross-filled-warning`. Rama `feat/extract-cross-filled-warning`. Otro agente amplía en paralelo el detector de tablas y el enrutado a `long` (otra parte de `server.py`): no toques eso.
  >
  > Problema: el modelo reparte las filas de una tabla entre las claves pedidas casi por posición (p. ej. `licensed_user_limits` recibe la fila de dominios). Propuesta del board: aviso determinista en `_local_delegate.cross_filled_keys` cuando el valor de la clave A aparece literal en una fila/línea de la fuente cuya etiqueta coincide en palabras con OTRA clave pedida B y no con A. Solo aviso, nunca poner null.
  >
  > Diseño a evaluar (decide tú con datos): avisar solo si el valor aparece en la fila de B y en ninguna otra fila/línea de la fuente (ocurrencia única) [...]; normalizar etiquetas [...] e ignorar valores triviales [...]. Puerta de medición obligatoria [...]: 0 falsos positivos en el conjunto y que detecte los cruces del #586. Deja el conjunto como test parametrizado. Documenta el campo en la descripción de la tool `local_extract` (en inglés, una frase) y en el CHANGELOG. No cambies el prompt.
- L2 2026-11-11 Detector, conjunto y test hechos; puerta pasada (0 falsos positivos); PR abierto,
  sin mezclar. Queda: prueba en vivo opcional de la sesión principal.
