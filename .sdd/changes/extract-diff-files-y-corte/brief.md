# Brief: local_extract: ficheros de un diff por programa y respuesta de líneas cortada (#665, #666)

Nivel SDD: `lite`. Disparador: arreglo con riesgo de regresión en `local_extract` (dos issues,
contrato de `_local_delegate` ampliado con `diff_files` y un error nuevo), sin migración ni datos.

## Problem

- #665: `local_extract(path=<diff grande>, fields=["ficheros_con_lineas"])` devolvía solo el primer
  fichero (`package.json: líneas 1-21`), sin aviso.
- #666: con un campo de líneas sobre un Markdown de decenas de KB (una sola llamada del rol `long`),
  la salida se cortaba por `max_tokens`: error «respuesta no parseable como JSON» y las líneas
  inventadas de la parte legible sin comprobar.

## Desired outcome

- Un campo que solo pide los ficheros de un diff y sus líneas trae todos los ficheros, por programa.
- Una respuesta de líneas cortada se rehace troceada; si sigue sin JSON, el error nombra
  `max_tokens` y las líneas que no casan van a `lines_unverified`.

## In scope

- `src/local_delegate/server.py` (`local_extract`), `src/local_delegate/line_check.py`
  (`asks_for_diff_files`), i18n es/en, tests, CHANGELOG y `docs/wiki/Tools.md`.

## Out of scope

- Otros campos de líneas sobre diffs (`hunks_con_lineas`): siguen siendo del modelo.
- Respuestas cortadas sin campos de líneas: no se rehacen (sus valores compiten, no se suman).
- Subir versión; ficheros de Codex.

## Constraints and risks

- Sin backend real (401 desde agentes): todo se prueba con `_run_chat` doblado.
- La llamada rehecha escribe una fila de uso más (una por llamada real al backend).

## Open questions

- Ninguna que cambie la especificación.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-16 Original request, verbatim:

  > Resolver #665 (local_extract sobre un .patch grande devuelve solo el primer fichero) y #666 (campo de líneas sobre Markdown grande devuelve JSON truncado por max_tokens y líneas inventadas)

- L2 2026-11-16 Reproducido con backend doblado; hipótesis de #665 (fusión que se queda con el
  primero) refutada: la unión concatena bien, el modelo nombra el primer fichero de cada trozo.
  #666 confirmado: la llamada única cortada no se reintentaba. Arreglo y tests hechos; falta PR.
