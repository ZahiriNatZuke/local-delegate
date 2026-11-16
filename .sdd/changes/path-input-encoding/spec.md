# Specification: Lectura con path: ficheros que no son UTF-8 y falsos «datos inventados» con m²/m³ (#672)

## Summary

Un `path` que no es UTF-8 se lee con sus caracteres y la tool avisa de cómo lo leyó; la revisión de
datos inventados de `local_summarize` no marca como inventado lo que el fichero sí contiene.

## Requirements

- **REQ-001** — Un `path` UTF-8 válido se lee igual que antes (finales de línea normalizados a `\n`) y no lleva aviso.
  - Request: derived: no romper lo que ya funciona
  - Verify: test tests/test_input_encoding.py::test_a_utf8_file_reads_as_before_and_carries_no_encoding
- **REQ-002** — Un `path` que no es UTF-8 se decodifica como Windows-1252, o Latin-1 si trae bytes que Windows-1252 no define, sin U+FFFD; uno con BOM de UTF-16 se lee como UTF-16.
  - Request: "detectar/decodificar la codificación (o avisar claramente)"
  - Verify: test tests/test_input_encoding.py (lector)
- **REQ-003** — Las seis tools que leen `path` de texto (summarize, extract, explain_code, lint_summary, commit_msg, translate) avisan con `[local-delegate warning: …]` cuando el fichero no era UTF-8; extract en `_local_delegate.warning` y `input_encoding`; un error conserva su prefijo al principio.
  - Request: "Comprueba si el mismo lector de ficheros afecta a otras tools con `path` … y cubre la combinación"
  - Verify: test tests/test_input_encoding.py (una prueba por tool)
- **REQ-004** — La revisión de #630 no marca `m²`/`m³` del fichero de la repro como inventados, compara en NFC y solo juzga letras.
  - Request: "que el control de «datos inventados» no marque como inventado lo que sí está en el fichero por un problema de decodificación o normalización Unicode"
  - Verify: test tests/test_input_encoding.py::test_summarize_of_the_issue_warns_of_the_encoding_and_not_of_invented_data
- **REQ-005** — CHANGELOG (Unreleased), `docs/wiki/Tools.md` y los catálogos es/en lo dicen.
  - Request: derived: regla de release del repo
  - Verify: review CHANGELOG.md, docs/wiki/Tools.md, test_i18n_parity

## Acceptance scenarios

### Scenario: repro del issue

- **Given** un fichero Latin-1 con `m³/ha` y `m²` y tildes
- **When** se llama a `local_summarize(path=…, focus="volumen y área")` y el modelo copia `m²`/`m³`
- **Then** la respuesta empieza con el aviso de codificación y no trae el aviso de datos inventados

## Edge cases and failure behavior

- Bytes 0x81, 0x8D, 0x8F, 0x90, 0x9D: Latin-1 (decodifica cualquier byte).
- BOM de UTF-16 con cuerpo roto: lo de antes (UTF-8 con reemplazo), sin aviso.
- Texto en línea (`text=`) tras un `path` Latin-1: sin aviso (el estado se reinicia en cada lectura).

## Non-functional requirements

- Sin dependencias nuevas; lectura lineal; sin expresiones regulares nuevas sobre la entrada.

## Non-goals

- Adivinar otras codificaciones (cp1251, Shift-JIS).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
