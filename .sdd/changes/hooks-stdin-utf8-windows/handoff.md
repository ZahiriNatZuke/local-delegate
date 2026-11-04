# Handoff: Hooks de la entrega por settings leen y escriben UTF-8 en Windows

## Current state

- SDD status: closed (PR de cierre `chore/close-sdd-2026-11-04`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `1ae287be` (PR #560)

## What changed

- `hook_common.utf8_stdio()`: reconfigura stdin/stdout a UTF-8 al empezar el `main()` de cada hook de la entrega por settings (en Windows el `python` del PATH abría las tuberías en cp1252).
- El hook de lectura registra `reason: "no_file"` cuando no encuentra el fichero; la medición deja esas filas fuera del recuento de lecturas (ajuste de la revisión independiente).
- Tests de shell y subagente que discriminan el arreglo (ajuste de la revisión independiente).

## Decisions

- `install.py` no cambia: el comando sigue siendo `python "<script>"`; `update` recopia los scripts.
- El test con `StringIO` queda como guarda de no regresión (no discrimina el arreglo; F1 aceptado).

## Next action

- Ninguna. Tras `update`, los hooks instalados ya llevan el arreglo.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
