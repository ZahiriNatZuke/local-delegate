# Especificación: Marca única y metadatos sociales en la landing

> **Reconstruida a posteriori el 2026-07-31** desde el diff mergeado del PR **#67** (`fcf462b`) y
> el cuerpo de su commit. Ver la nota completa en `brief.md`.

## Resumen

El proyecto tiene **un** icono, que vive en un solo fichero y del que todo lo demás es copia
verificada; y su página se comparte con imagen, título y descripción propios.

## Requisitos

- **REQ-001:** El icono de marca vive en **un solo fichero canónico**
  (`src/local_delegate/resources/brand/favicon.svg`). La copia de la landing es **idéntica byte a
  byte**, y algo lo comprueba.
- **REQ-002:** El dashboard **lee** el icono de ese recurso en vez de tenerlo escrito inline.
- **REQ-003:** El fichero canónico **viaja en el wheel**.
- **REQ-004:** La página declara los metadatos sociales completos: `og:url`, `og:site_name`,
  `og:locale` con el inglés como alternativo, `og:image` con medidas y texto alternativo,
  `canonical`, `theme-color` y `twitter:card` de tipo `summary_large_image`.
- **REQ-005:** Existe una imagen social de **1200×630**, y sus medidas reales coinciden con las
  que declaran los metadatos.
- **REQ-006:** Lo que se versiona de la imagen es **el HTML que la genera**, con el procedimiento
  dentro, porque un PNG no se puede revisar en un diff.
- **REQ-007:** Los ficheros `*.src.html` **no se publican**: son la fuente revisable de un
  artefacto, no páginas del sitio.
- **REQ-008:** El titular **no resalta «la nube» con el amarillo de la vía local**. En esa paleta
  el amarillo significa «la vía que se toma», y el titular dice que lo mecánico no tiene por qué
  ir a la nube.

## Escenarios de aceptación

### Escenario: alguien comparte el enlace

- **Dado** el sitio publicado
- **Cuando** se pega su URL en una red social
- **Entonces** aparece con imagen grande, título y descripción propios, y no como un enlace pelado

### Escenario: alguien edita la marca en un solo sitio

- **Dado** el icono canónico y su copia en la landing
- **Cuando** se cambia uno de los dos y no el otro
- **Entonces** un test falla, porque los compara byte a byte

## Comportamiento en los bordes

- **Sin `twitter:card=summary_large_image` la imagen se recorta a un cuadrado diminuto**, así que
  declarar la imagen no basta.
- Si el PNG y los metadatos se separan, un test que lee la **cabecera del PNG** lo caza.

## No funcionales

- **Accesibilidad:** el color del resalte del titular mantiene contraste suficiente para texto
  sobre el papel en los dos temas (4,4:1 en claro, 7,1:1 en oscuro).
- **Coherencia semántica:** el amarillo conserva un solo significado en toda la paleta.

## No objetivos

- Los PNG derivados, el manifest y el JSON-LD (van en `metadatos-checker-og`).
- Rediseñar la paleta.

## Trazabilidad

- REQ-001 · REQ-002 · REQ-003 → `src/local_delegate/resources/brand/favicon.svg`,
  `site/favicon.svg`, `src/local_delegate/web/metrics.py` + `tests/test_site.py`
- REQ-004 · REQ-008 → `site/index.html` + `tests/test_site.py`
- REQ-005 · REQ-006 → `site/og-image.png`, `site/og-image.src.html` + `tests/test_site.py`
- REQ-007 → `scripts/build_site.py`
