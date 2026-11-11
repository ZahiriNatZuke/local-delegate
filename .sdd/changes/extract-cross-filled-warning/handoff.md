# Handoff: local_extract: aviso de valor cruzado entre claves (cross_filled_keys, #650)

## Current state

- SDD cerrado; PR abierto desde `feat/extract-cross-filled-warning`, sin mezclar.

## What changed

- `src/local_delegate/cross_fill.py` (detector), llamada y aviso en `local_extract`, clave
  `mcp.warning.extract_cross_filled_keys` en es/en, CHANGELOG, wiki, léxico de nombres.
- Conjunto de medición en `tests/data/cross_fill/` y `tests/test_extract_cross_fill.py`.

## Decisions

- Coincidencia estricta y ocurrencia única antes que cobertura: 0 falsos positivos medidos en 169
  respuestas, 72 cruces detectados; los cruces con valores repetidos, empates u otro idioma no avisan.
- Solo aviso: el valor no cambia.

## Next action

- Mezclar el PR cuando el CI esté verde (lo decide la sesión principal). Puede chocar en el texto
  de la descripción de `local_extract` con el cambio paralelo del detector de tablas.
- El #650 sigue abierto por sus otras dos partes.

## Memory

- Canonical note: la escribe la sesión principal si lo ve útil (sin secretos ni datos personales).
