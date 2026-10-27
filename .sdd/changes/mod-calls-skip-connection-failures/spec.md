# El contador del mod no cuenta los fallos de conexión (issue #436)

Modo: lite.

## Qué pasa

Con el backend inalcanzable (DNS que no resuelve), la banda del mod muestra `○ CAÍDO` y aun así el
contador de delegaciones sube con cada intento: 17 contadas, 2 reales. La banda pinta
`total.calls` de `/api/stats?session=<id>`, que cuenta **todos** los eventos, también los
`ok: false`. Además `_accounting` (y su espejo JS `acct`) apunta `backend_calls = chunks or 1`
también en los fallos de conexión, cuando la petición no llegó al backend.

## Decisión

- `total.calls` del servidor **no cambia**: son intentos, y el panel lo usa como denominador del
  porcentaje de errores (`errors / calls`). Cambiarlo movería cifras del panel y del histórico.
- La banda del mod cuenta como delegaciones las que respondieron (`total.calls - total.errors`) y
  enseña los fallidos aparte: `2 delegaciones · 15 fallidas · …`. Todos los fallos van a
  «fallidas», no solo los de conexión: una delegación que falló (por carga, por el modelo) tampoco
  le ahorró nada a quien la pidió; contarla como delegación es el mismo engaño.
- Un fallo con `connection_failure` no gasta `backend_calls`: cuenta solo las llamadas que
  `chunks` diga que se hicieron antes de perder la conexión (una troceada que cae en el trozo 3
  conserva 2). Los demás fallos (`capacity_or_load`, 5xx, timeout, errores del modelo) siguen
  contando sus llamadas: la petición llegó y el backend la gastó.
- `/api/stats` gana `total.connection_failures` (cuántos de `errors` no llegaron al backend).

## Criterios de aceptación

1. Log con 2 éxitos, 14 fallos `dns`, 1 fallo `dns` troceado con `chunks: 2` y 1 `capacity_or_load`:
   `total.calls` 18, `errors` 16, `connection_failures` 15, `backend_calls` 5.
2. La banda (barra, línea y Desktop, es/en) dice `2 delegaciones · 15 fallidas` con 17 intentos y
   15 errores; con solo fallos, `0 delegaciones · 1 fallida`; sin errores, igual que antes.
3. `_accounting` y `acct` coinciden también en los fallos de conexión (test de paridad).
4. El panel muestra «llamadas reales» 0 cuando todas fallaron por conexión (antes `||` caía a
   `calls`).

## Fuera

El punto 3 del issue (cortar los reintentos con el backend caído: circuit breaker / respuesta
inmediata) no entra aquí: es comportamiento del servidor y de los hooks, merece su cambio.

## Verificación

- `tests/test_metrics_session_filter.py::test_connection_failures_spend_no_backend_call` (por
  `/api/stats?session=`, el camino del mod) y casos nuevos en la paridad Python/JS.
- `mod/status.test.ts`: tres tests nuevos y un caso más en el de Desktop.
- Control positivo: sin el arreglo fallan los 4 del mod (`17 delegaciones`) y los 2 de Python;
  con un mutante que solo devuelve `backend_calls = chunks or 1` fallan la paridad y
  `assert 19 == 5`.
