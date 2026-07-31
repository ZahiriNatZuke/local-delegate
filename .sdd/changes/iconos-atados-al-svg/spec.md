# Specification: Los PNG de la marca quedan atados al favicon.svg

## Summary

Los PNG de la marca declaran de qué `favicon.svg` salieron, y la suite lo comprueba. Tocar el
icono sin regenerarlos rompe el PR; regenerarlos es un comando.

**Decisión de fondo: se ata por procedencia, no rasterizando en el CI.** El pendiente daba por
necesario meter un navegador en el pipeline. Un hash del SVG de origen cubre el fallo real —los
PNG se quedan viejos— sin esa dependencia.

## Requirements

- **REQ-001:** Existe un manifiesto con el sha256 del SVG con el que se generaron los PNG.
- **REQ-002:** Un test falla si el `favicon.svg` actual no es ese.
- **REQ-003:** El manifiesto registra el sha256, el tamaño en bytes y el lado de cada PNG, y un
  test los compara con los ficheros en disco.
- **REQ-004:** El manifiesto cubre **todos** los PNG de la marca, comparados por conjuntos iguales.
- **REQ-005:** Un script regenera los PNG y escribe el manifiesto en un solo comando.
- **REQ-006:** Sin playwright, el script falla diciendo cómo instalarlo, no con un `ImportError`.
- **REQ-007:** El script no deja el servidor de ficheros escuchando al terminar.

## Acceptance scenarios

### Scenario: alguien cambia el icono y no regenera

- **Given** `site/favicon.svg` modificado
- **When** corre la suite
- **Then** falla, diciendo el comando exacto para regenerar

### Scenario: alguien regenera por fuera del script

- **Given** un PNG sustituido a mano (el sha del SVG sigue cuadrando)
- **When** corre la suite
- **Then** falla el test que compara cada PNG con su hash registrado

### Scenario: se añade un icono nuevo y no se declara

- **Given** un PNG más en `site/` que no está en el manifiesto
- **When** corre la suite
- **Then** falla el test de conjuntos

## Edge cases and failure behavior

- **`og-image.png` no cuenta:** no sale del SVG y ya tiene su propio par fuente/test. Se excluye
  explícitamente del conjunto.
- **Regenerar con otro navegador** produce PNG distintos aunque la marca sea la misma. El test
  fallará y habrá que commitear los nuevos: correcto, aunque ruidoso.

## Non-functional requirements

- **Sin dependencias nuevas del proyecto ni del CI**: playwright vive solo en el script.
- **El manifiesto es revisable**: JSON con un bloque `_acerca_de` que dice quién lo escribe y por
  qué no se toca a mano.

## Non-goals

- Comparar píxeles o rasterizar en el CI.
- Tocar `og-image.png`.
- Generar más tamaños de icono de los que la landing declara.

## Traceability

| Requisito | Trabajo | Evidencia |
| --- | --- | --- |
| REQ-001 | `capture_icons.py` | `site/icons.json` generado |
| REQ-002 | `test_los_png_se_generaron_con_el_favicon_svg_actual` | mutante: SVG tocado |
| REQ-003 | `test_el_manifiesto_describe_los_png_que_hay_en_disco` | mutante: PNG tocado |
| REQ-004 | `test_el_manifiesto_cubre_todos_los_png_de_la_marca` | mutante: icono quitado |
| REQ-005 | `capture_icons.py` | ejecutado: dos PNG y el manifiesto |
| REQ-006 | `capture_icons.py` | revisión del `except ImportError` |
| REQ-007 | `capture_icons.py` | `shutdown()`/`server_close()` en el `finally` |
