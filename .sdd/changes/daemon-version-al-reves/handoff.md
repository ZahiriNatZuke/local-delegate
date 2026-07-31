# Handoff: El check del daemon compara versiones por desigualdad

## Current state

- SDD status: `closing`. Gates aprobados: `spec`, `quality`, `conformance`.
- Revision: rama `fix/daemon-version-al-reves` sobre `main` en `9d2c242`.
- Suite: **556 passed, 1 skipped**.

## What changed

`_probe_daemon` pasa de comparar con `!=` a comparar con `_compare_versions`, y distingue los dos
sentidos: daemon atrasado → reiniciar; instalación atrasada → comando de upgrade. Dos versiones no
ordenables avisan sin ofrecer arreglo.

Tres ficheros: `checks.py`, `tests/test_checks.py`, `CHANGELOG.md`.

## Decisions

- **`warn` en los tres sentidos**, para que el exit code de `doctor` no cambie para nadie.
- **Sin `fix_hint` cuando no se pueden ordenar**: sugerir uno de los dos podría ser el equivocado, y
  ese fue exactamente el defecto que se está arreglando.
- **No se toca `update`** para que actualice el CLI de `uv tool`: descartado con motivo escrito
  (hacerlo desde el propio entorno destruye la instalación en Windows). Este change arregla el
  **diagnóstico**, no el mecanismo.

## Next action

Merge del PR. Y luego, el asunto que el usuario levantó aparte: **el 401 del backend en `doctor`**.
`service.backend` prueba el backend **directamente**, y un shell interactivo no tiene
`LOCAL_DELEGATE_API_KEY` (vive cifrada con DPAPI en el launcher del daemon), así que siempre saldrá
`[ -- ]`. El daemon **sí** está autenticado y ya expone `/api/backend`: la vía sensata es que
`doctor` pregunte al daemon cuando esté arriba, y solo vaya directo si no lo está.

## Memory

- Canonical note: `projects/local-delegate/jornada-2026-07-31-la-0-18-0.md` (se le añade este fix).
- Indexes updated: pendiente al cerrar.
