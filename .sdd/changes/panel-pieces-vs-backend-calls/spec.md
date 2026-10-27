# Especificación (modo lite): el panel separa trozos y llamadas al backend

Issue #454: en una delegación troceada, «En curso» muestra «Trozo n/3» y la actividad «4×».

## Premisa, reproducida

- `_inflight_start(..., chunks=len(pieces))` guarda TROZOS; `_log_event(..., chunks=calls)` guarda
  LLAMADAS (map, reduce, regroup, reintentos) en `_chat_chunked` y `_chat_map_reduce`.
- Con el `src` de `main`, los tests nuevos dan: evento sin `pieces` (`KeyError`), la llamada del
  reduce ve la entrada en vuelo sin fase («Trozo 3/3»), la fila de actividad pinta `4×`.

## Qué

1. Log: campo nuevo `pieces` (trozos anunciados) en los eventos troceados de `_chat_chunked` y
   `_chat_map_reduce`. `chunks` no cambia (= llamadas); su renombrado a `backend_calls` queda fuera.
2. Actividad: con `pieces`, el chip es `3 +1` (o `3×` si no hubo llamadas extra) con el título
   «3 trozos · 4 llamadas al backend»; sin `pieces`, como antes. El diálogo de la fila añade
   «Trozos» y «Llamadas al backend». El cálculo de coste no cambia.
3. En curso: `_inflight_phase(entry_id, phase)` (best-effort) con `map` (por defecto, ausencia),
   `reduce` (reduce y regroup) y `retry` (trozo que se vuelve a partir: en `_chat_chunked` y, tras
   el #455, en `_map_parts` del map/reduce, por salida cortada o desborde de contexto). `_inflight_progress` vuelve a `map` al pasar de trozo. `inflight_snapshot`
   copia `phase`. El panel pinta «Combinando {total} trozos…» y «Reintentando trozo {n}/{total}».

## Criterios de aceptación

1. Evento troceado con `pieces` == nº de trozos y `chunks` == nº de llamadas, en los dos caminos.
2. La llamada del reduce ve `phase: "reduce"`; las del map, ninguna.
3. Las llamadas de los medios trozos ven `phase: "retry"` (en los dos caminos); el trozo siguiente
   vuelve a no tener fase.
4. Un evento sin trocear no lleva ni `chunks` ni `pieces`.
5. Chip `3 +1` con su título, `3×` sin extra, `4×` con el título viejo para eventos sin `pieces`.
6. «En curso» pinta las tres fases con i18n es+en.

## Fuera de alcance

- Renombrar `chunks` a `backend_calls` (más adelante, con alias de lectura).
- La fase en la banda del mod: lee `chunk/chunks` y sigue funcionando sin cambios (ignora `phase`).
