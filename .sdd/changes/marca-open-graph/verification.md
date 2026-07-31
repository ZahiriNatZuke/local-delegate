# Verificación: Marca única y metadatos sociales en la landing

> **Verificación fresca del 2026-07-31**, contra el sitio **publicado** y el árbol de `main`. No
> reproduce el acta original porque no hubo: la traza se commiteó en plantilla (ver `brief.md`).

## Entorno

- Revisión del trabajo: PR **#67**, `fcf462b`, mergeado el 2026-07-30. Publicado en la **0.17.0**.
- `main` en `b8c43cd`; sitio servido por GitHub Pages.
- Windows 11, Python 3.13 (`uv`), `curl` para las comprobaciones HTTP.

## Evidencia

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001 | SHA-256 de `src/local_delegate/resources/brand/favicon.svg` y `site/favicon.svg` | **idénticos**: `8b26059aa8c1d5059953…` los dos |
| REQ-002 | `metrics.py` | `_load_favicon()` lee `resources/brand/favicon.svg` del paquete; el comentario de la línea 533 deja escrito que el icono **no se escribe ahí** |
| REQ-003 | El recurso en el wheel | comprobado en su día al implementar; el dashboard sirve el icono en una instalación real |
| REQ-004 | Etiquetas del HTML publicado | los doce `og:*` presentes (`type`, `site_name`, `locale`, `locale:alternate`, `url`, `title`, `description`, `image`, `image:type`, `image:width`, `image:height`, `image:alt`), `canonical`, `theme-color` `#0D1A1D` y `twitter:card` = `summary_large_image` |
| REQ-005 | Cabecera **IHDR** de la `og-image.png` publicada | `1200x630`, exactamente lo que declaran `og:image:width` y `og:image:height` |
| REQ-006 | `site/og-image.src.html` | versionado, con el procedimiento dentro |
| REQ-007 | `build_site.py --out` y el sitio publicado | el build no copia ningún `*.src.html`; `…/og-image.src.html` responde **404** en producción |
| REQ-008 | Test que ata las dos mitades del titular | pasa (dentro de los 23 de `test_site.py`) |

## Comprobaciones de calidad

- [x] `uv run pytest tests/test_site.py -q` → **23 pasan**.
- [x] Sin dependencias nuevas.
- [x] Secretos: ninguno en juego.
- [x] Sin cambios ajenos: el diff toca `site/`, el recurso de marca, `metrics.py`,
      `build_site.py`, `tests/test_site.py` y el `CHANGELOG`.

## Desviaciones y riesgo residual

- **La traza se rellenó a posteriori.** Es la desviación de proceso que este cierre documenta.
- **La misma mezcla del amarillo sobrevive en otro sitio.** Este cambio la corrigió en el
  **titular**; el **botón de idioma activo** sigue usando `--local` como color de estado. No es
  una regresión de este cambio —ya estaba— pero sí queda dicho aquí: se ataca en su propio cambio.
- **La `og-image.png` puede quedarse vieja** si alguien cambia el diseño y no la regenera desde
  `og-image.src.html`. Mismo riesgo aceptado que los PNG de marca y que la captura del README.
