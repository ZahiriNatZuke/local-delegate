# Higiene de CodeQL (plan §1.4)

Lote corto entre el cierre del frente A y B0: deja en 0 las 16 alertas abiertas de code scanning
de `main` (dc971f4) **arreglando el código**, sin descartar ninguna. Rama `sdd/codeql-hygiene`.

Evidencias en `evidence/codeql-hygiene/`: `pytest-full.log`, `collect.txt`, `targeted.txt`,
`ruff.txt`, `detector.txt`/`detector.json` y `mutant.log`.

## Alerta → cambio → por qué no cambia el comportamiento

Las líneas de la columna «cambio» son las del working tree tras el lote.

| Alerta | Regla | Sitio en dc971f4 | Cambio | Por qué el comportamiento es el mismo |
|---|---|---|---|---|
| 93 | py/stack-trace-exposure | `web/metrics.py:964` | `web/metrics.py:975-982`: el 502 de `POST /api/llamaswap/watch` responde un texto fijo por familia (`WATCH_LIMIT`, `WATCH_REJECTED`, `WATCH_UNREACHABLE`, `metrics.py:85-89`) y el detalle va a `logger.warning` (logger nuevo del módulo, `metrics.py:80`). `llamaswap_api.py:94`: subclase `TooManyWatches(QueryError)` para el tope de vigías (`:623`). | Es el único cambio visible que el plan admite: mismo 502 y misma clave `error`, con otro texto. `TooManyWatches` es `QueryError`, así que todos los `except QueryError` siguen igual; solo sirve para que el CLI siga diciendo «tope de vigías» sin copiar el texto de la excepción. |
| 103 | py/empty-except | `server.py:864` | `server.py:860`: `with suppress(Exception):` alrededor de `rec.update(_slowness_fields(...))`. | Traga el mismo tipo (`Exception`) que antes; el comentario de encima ya da el motivo (REQ-028). |
| 116 | py/empty-except | `server.py:873` | `server.py:879`: `with suppress(Exception):` con comentario. | Igual tipo tragado; el evento ya está escrito. |
| 106 | py/empty-except | `server.py:4515` | `server.py:4529`: `with suppress(Exception):` con comentario. | Igual tipo tragado; el informe sale sin la línea, como antes. |
| 105 | py/empty-except | `residency.py:1063` | `residency.py:1064`: `contextlib.suppress(FileNotFoundError)` con comentario. | Mismo tipo (`FileNotFoundError`); el `raise` sigue relanzando el original. |
| 113 | py/empty-except | `resources/hooks/hook_common.py:261` | `hook_common.py:260`: `contextlib.suppress(OSError, ValueError, KeyError, TypeError)` con comentario. Solo stdlib (`import contextlib`), sin imports de `local_delegate`. | Mismos cuatro tipos; el `return` dentro del `with` sale igual que dentro del `try`. |
| 102 | py/empty-except | `tests/fake_llama_server.py:134` | `fake_llama_server.py:135`: `contextlib.suppress(KeyboardInterrupt)` dentro del `try/finally`. | Mismo tipo; el `finally` sigue cerrando el socket. |
| 118, 119 | py/unused-global-variable | `topology.py:509-510` | `topology.py:480-492`: `_cache` pasa a ser una instancia de `_Cache` (`entry`, `version`); `snapshot()` y `_forget()` ya no usan `global`. | Mismos valores y mismas transiciones bajo el mismo `_lock`; `_forget()` sigue sin reiniciar la versión. Nadie fuera del módulo lee `_cache`/`_version` (grep). |
| 115 | py/unused-global-variable | `server.py:596` | `server.py:566-574`: `_pace_state` → `_pace_cache = _PaceCache()` con `entry`; `_pace_references()` sin `global`. | Misma clave de origen y misma resiembra; nadie fuera del módulo lo leía. |
| 95 | py/unused-global-variable | `server.py:1443` | `server.py:1431-1438`: `_turn_version` es un `_TurnVersion` con `value`; `_reset_turn` y `_on_snapshot_seen` escriben `.value`. `tests/test_affinity.py:455` parchea `server._turn_version.value`. | Misma comparación «solo hacia delante» bajo `_turn_lock`. El único lector externo era ese `monkeypatch`, adaptado. |
| 101 | py/catch-base-exception | `tests/test_turn.py:261` | `except Exception` (y `self.error: Exception \| None`). | Las funciones del hilo (`Turn.request`) solo lanzan `Exception` (`AbandonedWait` incluida); `KeyboardInterrupt` solo llega al hilo principal y ningún hilo llama `sys.exit` ni `pytest.fail/skip` (grep en los tres ficheros). |
| 100 | py/catch-base-exception | `tests/test_turn_daemon.py:119` | Igual. | Igual motivo. |
| 99 | py/catch-base-exception | `tests/test_affinity.py:210` | Igual. | Igual motivo. |
| 98 | py/import-and-import-from | `tests/test_slowness.py:18` | Fuera `from backend_mock import chat_response, llama_timings`; se usan como `backend_mock.chat_response`/`backend_mock.llama_timings`. | Mismas funciones del mismo módulo. |
| 50 | py/mixed-returns | `server.py:1249` | `server.py:1380`: `raise AssertionError(...)` al final de `_post_chat`, tras el comentario que explica por qué no se llega. | El final era inalcanzable (medido; lo vigila `tests/test_post_chat_paths.py`, que exige un `ChatResult` en todos los caminos). Ahora no hay `return None` implícito. |

## Endpoints hermanos

Se buscó `str(e)`/`str(exc)`/`{e}` dentro de un `JSONResponse` en todo `src/` (`web/metrics.py`,
`daemon.py`, `server.py`): **no hay otro**. Los demás `except` de `metrics.py` no meten la
excepción en la respuesta; `GET /api/backend/stats` pasa la excepción a `failures.detail`, que solo
usa su **tipo** (`type(e).__name__`) y su código HTTP, no su texto. Sin cambios ahí.

## Efecto en el CLI

`local-delegate residency` contra el daemon mostraba el texto del 502 («ya hay 4 vigías
abiertas»). Ahora muestra el texto fijo de su familia (`WATCH_LIMIT` para el tope). Se ajustó
`tests/test_residency_cli.py::test_without_a_watch_it_does_not_write_unless_now` (lanza
`TooManyWatches` y comprueba `WATCH_LIMIT` y que el texto de la excepción **no** sale); el resto
del test (no escribe a ciegas, `--now` sí escribe) no cambia.

## Tests y control positivo

- Nuevo `tests/test_metrics.py::test_llamaswap_watch_502_does_not_expose_the_exception`
  (3 casos: `QueryError`, `TooManyWatches`, `ConnectError`): la respuesta no contiene un marcador
  único del texto de la excepción, trae el mensaje fijo de su familia, y la guarda comprueba que el
  marcador sí llegó al log.
- `test_llamaswap_watch_that_cannot_open_is_502` ahora exige `{"error": WATCH_REJECTED}`.
- Mutante (`mutant.log`): `{"error": message}` → `{"error": str(e) or message}`. Fallan los 4
  tests por el assert esperado: los tres nuevos en `assert secret not in r.text` y el del 401 en
  la igualdad del mensaje. Fichero restaurado (sha256 igual al de antes).

## Resultados

- Suite completa: 2 620 recogidos; 2 618 passed, 2 skipped, 0 failed.
- `ruff check .` limpio; `ruff format --check .`: 197 ficheros ya formateados.
- Detector con la lista: 0 fuera de la lista y 0 palabras sin clasificar. Se añadieron al léxico
  `caplog` y `expose` (en), que solo aparecen en el test nuevo.
- Fines de línea conservados (`git ls-files --eol`): `server.py` y `web/metrics.py` en CRLF, el
  resto en LF.

## Pendiente fuera de este lote

Que CodeQL lo confirme: tras el PR, `gh api repos/…/code-scanning/alerts?state=open` en `main` debe
dar 0 y `gh pr checks` sin alertas nuevas.
