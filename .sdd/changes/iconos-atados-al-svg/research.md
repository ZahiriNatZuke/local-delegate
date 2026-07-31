# Research: Los PNG de la marca quedan atados al favicon.svg

## Current behavior

- `site/icon.src.html` **carga** `favicon.svg` (`<img src="favicon.svg">`) y lo compone sobre el
  fondo sólido que iOS necesita. No redibuja la marca: eso ya estaba bien resuelto.
- `site/favicon.svg` y `src/local_delegate/resources/brand/favicon.svg` son **idénticos**, y hay un
  test que los compara byte a byte (`test_el_favicon_de_la_landing_es_el_mismo_del_dashboard`).
- Lo que cubría `test_site.py` sobre los PNG: que existen, que la cabecera IHDR dice el tamaño que
  declara el `<link sizes>`, y que se publican en el build. **Nada sobre su contenido.**
- El procedimiento de regeneración estaba escrito **en un comentario** de `icon.src.html`: levantar
  `http.server`, abrir la página y capturar el viewport a cada tamaño, a mano.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `scripts/dev/capture_icons.py` | — (nuevo) | Regenera y escribe el manifiesto | molde: `capture_dashboard.py` |
| `site/icons.json` | — (nuevo) | La procedencia de los PNG | molde: `docs/assets/dashboard.json` |
| `tests/test_site.py` | Cubre existencia y tamaños | Añade tres tests de procedencia | `test_site.py:346-360` |
| `site/icon.src.html` | Fuente y procedimiento manual | El procedimiento pasa a ser un comando | comentario del fichero |
| `site/*.png` | Los iconos | Regenerados por el script | — |

## Existing conventions

- **El manifiesto lo escribe quien captura, nunca el bump ni una persona.** Está escrito en
  `docs/assets/dashboard.json`: *«Lo escribe `scripts/dev/capture_dashboard.py` al capturar, NUNCA
  a mano… si lo actualizara quien sube la versión, el check se cumpliría sin que nadie regenerara
  la imagen»*. Este change replica ese razonamiento tal cual.
- **Los scripts de `scripts/dev/` no son dependencias del proyecto** y avisan de qué instalar.
- **Los artefactos binarios se atan por un fichero revisable**: `og-image.png` tiene
  `og-image.src.html` y su test.
- **Los tests de conjunto se comparan por igualdad, no por inclusión** (`JOBS_ESPERADOS` en
  `ci_gate`, las páginas de la wiki), para que añadir algo y olvidarlo no pase desapercibido.

## Dependencies and integrations

- `playwright` (chromium) solo para el script, no para la suite ni el CI.
- El resto es stdlib: `http.server`, `hashlib`, `json`.

## Risks and unknowns

- **Confirmado por ejecución:** el script regenera los dos PNG y el manifiesto; los tres tests
  pasan; los tres mutantes (SVG tocado, PNG tocado a mano, icono no declarado) fallan.
- **Confirmado, y conviene saberlo:** los PNG regenerados **no son byte a byte los anteriores**
  (1669→2116 y 424→488 bytes). Los originales se capturaron con otro navegador o versión. La marca
  es la misma; lo que cambia es la codificación del PNG.
- **Limitación asumida:** el hash detecta «este PNG no salió de este SVG», no «este PNG dibuja otra
  cosa». Regenerar con otro chromium producirá un PNG distinto y habrá que commitearlo. Es ruido
  tolerable frente a meter un navegador en el CI.
