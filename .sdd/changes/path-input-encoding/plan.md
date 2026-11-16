# Implementation plan: Lectura con path: ficheros que no son UTF-8 y falsos «datos inventados» con m²/m³ (#672)

## Approach

`_decode_input_file` lee bytes y prueba UTF-8 estricto; con BOM de UTF-16, UTF-16; si no,
Windows-1252 y luego Latin-1. Normaliza finales de línea como hacía `read_text`. La codificación
usada (si no era UTF-8) queda en la ContextVar `_INPUT_ENCODING`, que `_read_input` reinicia en
cada llamada: así no cambia la firma de `_read_input` (seis llamadas y una decena de tests) y cada
tool añade el aviso con `_with_input_encoding_notice` en sus retornos (o en `_local_delegate` en
extract). En `grounding.check`, NFC en resumen y fuente; `_foreign_words` solo juzga caracteres que
son letras.

## Ordered tasks

- [x] T1 — Lector con decodificación y ContextVar (REQ-001, REQ-002)
  - Files or modules: src/local_delegate/server.py
  - Verification: tests del lector en tests/test_input_encoding.py
  - Depends on: none
- [x] T2 — Aviso en las seis tools (REQ-003)
  - Files or modules: src/local_delegate/server.py, resources/i18n/{es,en}/mcp.json
  - Verification: una prueba por tool
  - Depends on: T1
- [x] T3 — Revisión de #630 en NFC y solo letras (REQ-004)
  - Files or modules: src/local_delegate/grounding.py
  - Verification: tests de grounding y repro de punta a punta
  - Depends on: none
- [x] T4 — Documentación (REQ-005)
  - Files or modules: CHANGELOG.md, docs/wiki/Tools.md
  - Verification: revisión y paridad i18n
  - Depends on: T2

## Test strategy

- Unit: lector y `grounding.check`.
- Integration: cada tool con backend simulado (`backend_mock`) y fichero Latin-1 real en `tmp_path`.
- End-to-end or manual: no hace falta prueba en vivo; no cambia ningún prompt.
- Security and secret scanning: sin secretos; la entrada no confiable no pasa por expresiones nuevas.

## Migration and compatibility

- UTF-8 sin cambios. Un fichero no UTF-8 cambia de texto con U+FFFD a texto bien decodificado más aviso.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
