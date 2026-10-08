# Handoff: Las pruebas fuera de las métricas: ventanas de prueba y una sola regla de exclusión en todo el panel

## Current state

Implementado de T0 a T8 y T10 en la rama `sdd/test-windows-out-of-metrics`. T9 (instalar, sembrar
y comprobar en la PC real) **preparado pero sin ejecutar**: el encargo prohibía tocar el `LOG_DIR`
real y el daemon, y el clasificador bloqueó leer ese directorio. Pasos exactos y script en
`evidencias/T9.md` y `evidencias/sembrar_T9.py`.

## What changed

- `src/local_delegate/test_windows.py` (nuevo): fichero `LOG_DIR/test-windows.json`, lectura
  tolerante y cacheada, `find` indexado, escritura atómica bajo `FileLock`.
- `atribucion.test_reason`: la única regla de «es una prueba»; `coste.fundir` estampa
  `test_window` en la copia.
- CLI `local-delegate test-window {start,stop,add,list}`.
- Panel: `_split_tests` en el servidor, `include_tests` en `/api/events`, `/api/stats` y
  `/api/hooks`; interruptor «Pruebas» con su ⓘ y punto de ventana abierta.
- `local_status` sin pruebas; check `metrics.test_windows` en `doctor`.
- `scripts/medir_enfriamiento.py` arranca de nuevo (`args.excluir`) y los dos medidores aplican las
  ventanas.
- CHANGELOG, README y wiki.

## Decisions

- D1-D7 aprobadas por el usuario el 2026-10-08 tal cual las recomienda el spec.
- `medir_enfriamiento.py` aplica solo las ventanas; `medir_adopcion.py`, la regla común entera
  (ver `evidencias/T7.md`).

## Next action

1. Ejecutar T9 en la PC (orden en `evidencias/T9.md`): instalar la rama, sembrar con
   `sembrar_T9.py`, anotar las cifras de `medir_adopcion.py` antes (`--include-tests`) y después, y
   comprobar `/api/stats`, `local_status` y `doctor` contra el daemon.
2. Medir P-4 a 30 días (2026-10-15) con `uv run python scripts/medir_enfriamiento.py --desde
   2026-09-15T19:26:41` (la ventana de P-4 ya irá en el fichero tras la siembra).

## Memory

Para persistir al cerrar: «antes de una prueba en vivo contra el MCP o el daemon,
`local-delegate test-window start --label …`, guardar el id que imprime; al acabar,
`local-delegate test-window stop <id>`». Y que `medir_enfriamiento.py` reventaba siempre desde #240
(`args.exclude`), arreglado aquí.
