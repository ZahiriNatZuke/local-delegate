# Especificación (modo lite): el map/reduce reintenta los parciales cortados por max_tokens

Issue #455. Con el log de octubre, `local_explain_code` cortó algún parcial del map en 15 de 15
delegaciones troceadas (50 parciales); la tarjeta del backlog «local_lint_summary corta pasos
intermedios en logs muy grandes» (10 de 12) es el mismo defecto en el reagrupado.

## Premisas, reproducidas

- `_map_piece` solo parte y reintenta ante desborde de contexto; un paso que sale por `length`
  se acepta cortado (`_one` suma `truncated_calls`). Con el `src` de `main`, los tests nuevos de
  map y reagrupado acaban con el aviso «salida truncada…» y ningún paso reintentado.
- El map de `local_explain_code` va con el tope común `2·350+64 = 764` tokens: con trozos de
  ~12 000 caracteres las notas se cortaban en ~3 100-3 200 caracteres (~4,2 por token).
- El aviso no dice qué trozo se perdió.

## Qué

1. Map: si un paso sale por `length`, profundidad < 2 y el trozo es partible (mayor que
   `CHUNK_MIN_CHARS`, `_split` da ≥ 2), se descarta ese parcial y se reintenta partido, como
   `_chat_chunked`. El paso descartado no cuenta en `truncated_calls` y en `steps` lleva
   `"retried": true` (clave opcional; los demás pasos conservan su formato).
2. Reagrupado: igual, partiendo el grupo en dos. El reduce final no se parte.
3. `local_explain_code`: tope propio del map, `max(764, min(len(trozo) // 8, CHUNK_MAX_TOKENS))`.
4. Si queda algún parcial cortado, el aviso (y `report["truncated_pieces"]` en `local_extract`)
   dice el número de trozo y, si el texto aparece una sola vez en la entrada, sus líneas.

## Criterios de aceptación

1. Map con `length` que se arregla partiendo → resultado sin aviso, `finish_reason` `stop`, pasos
   `retried`.
2. Profundidad agotada → aviso con «trozos afectados: N (líneas a-b)», líneas correctas.
3. Trozo no partible → como antes (truncado + aviso, una llamada).
4. Reagrupado con `length` → se parte y reagrupa; sin aviso.
5. Reduce con `length` → no se parte; aviso sin trozos.
6. `local_explain_code` usa su tope nuevo en el map.
7. `local_extract` sigue devolviendo el objeto con `_local_delegate.truncated/warning`; el aviso
   nombra el trozo.
