# Brief: Lectura con path: ficheros que no son UTF-8 y falsos «datos inventados» con m²/m³ (#672)

## Problem

`server._read_input` leía todo `path` como UTF-8 con `errors="replace"`. Un fichero Latin-1 (salida
de `pdftotext -layout` en Windows) perdía `²`, `³` y tildes como U+FFFD sin aviso, y la revisión de
#630 (`grounding.check`) tomaba por inventados los `m²`/`m³` que el resumen copiaba del fichero.
Además `grounding._foreign_words` juzgaba `²` como si fuera una letra (el patrón `[^\W\d_]` acepta
los dígitos que no son decimales) y comparaba sin normalizar la forma Unicode.

## Desired outcome

El fichero se decodifica bien (o con la mejor suposición) y la tool lo dice; la revisión de datos
inventados no marca lo que sí está en el fichero.

## In scope

- Lector común de `path` de las seis tools de texto y su aviso en cada una.
- `grounding.check`: NFC en ambos lados y solo letras en la revisión de idioma.
- CHANGELOG, `docs/wiki/Tools.md`, catálogos es/en.

## Out of scope

- Detección estadística de otras codificaciones (cp1251, Shift-JIS): se avisa y se pide convertir.
- `local_describe_image` (lee bytes) y el troceado de `local_extract`.

## Constraints and risks

- Un fichero UTF-8 debe leerse byte a byte igual que antes (mismos finales de línea, BOM incluido).
- Un error del backend conserva `[local-delegate error]` al principio.

## Open questions

- Ninguna.

## Log

- L1 2026-11-16 Original request, verbatim:

  > **#672**: `local_summarize` con `path` no avisa de ficheros Latin-1 y da falso positivo de «datos inventados» con `m²`/`m³`. Léelo con `gh issue view 672 --comments`. Esperado: detectar/decodificar la codificación (o avisar claramente) y que el control de «datos inventados» no marque como inventado lo que sí está en el fichero por un problema de decodificación o normalización Unicode. Comprueba si el mismo lector de ficheros afecta a otras tools con `path` (extract, explain_code, lint_summary, translate) y cubre la combinación, no solo la función.

- L2 2026-11-16 Implementado y verificado en local; PR abierto. Queda el CI y cerrar las puertas.
