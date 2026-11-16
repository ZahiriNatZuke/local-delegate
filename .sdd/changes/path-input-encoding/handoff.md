# Handoff: Lectura con path: ficheros que no son UTF-8 y falsos «datos inventados» con m²/m³ (#672)

## Current state

- SDD status: verificando; las puertas quality, conformance y memory se pasan con el CI en verde
- Last completed gate: plan
- Current revision: rama `fix/path-input-encoding`

## What changed

- `server._decode_input_file`: UTF-8 estricto, UTF-16 con BOM, cp1252 y Latin-1; la codificación queda en `_INPUT_ENCODING`.
- Las seis tools de texto con `path` avisan delante de la respuesta; `local_extract` en `_local_delegate.warning` e `input_encoding`, también en sus errores.
- `grounding.check` compara en NFC y la revisión de idioma solo juzga letras.

## Decisions

- ContextVar en lugar de cambiar la firma de `_read_input` (seis llamadas y una decena de tests); `_read_input` la reinicia en cada lectura.
- Sin detección estadística de codificaciones: cp1252 cubre la salida de las herramientas de Windows; el aviso pide convertir si sale raro.
- El aviso va delante (como el de truncado) y nunca delante de un `[local-delegate error]`.

## Next action

- Esperar el CI del PR y cerrar las puertas.

## Memory

- Canonical note: este handoff y el Log del brief
- Indexes updated: ninguno
