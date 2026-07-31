# Result review: Cerrar los avisos del checker de OpenGraph en la landing

## Verdict

`conforms`

## Cómo se revisó

Revisión fresca del 2026-07-31, **contra la página publicada**, no contra el árbol de trabajo ni
contra el acta de verificación original. El trabajo se mergeó con el PR **#68** (`78737cd`) y
GitHub Pages lo desplegó ese mismo día; el deploy vigente es el de `chore(release): 0.17.0` (#71),
posterior, y ninguno de los PR #73–#84 tocó `site/`.

Esto importa porque los dos riesgos que el acta original dejó **explícitamente abiertos** solo se
podían cerrar en producción. Los dos quedan cerrados abajo.

## Comparación contra la especificación

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | `og:description` mide **149** caracteres (era 213) y es **la misma cadena** que `twitter:description`; `description` sigue en 104. Medido sobre el HTML servido. |
| REQ-002 | sí | sí | Los dos PNG responden `200 image/png`, y su cabecera **IHDR** dice `180x180` y `32x32`, que es exactamente lo que declaran los `sizes` de la página. |
| REQ-003 | sí | sí | **`color_type=2`** en las dos cabeceras IHDR: color verdadero **sin canal alfa**. No hay transparencia que iOS pueda componer sobre negro. Dato más fuerte que la inspección visual del acta original. |
| REQ-004 | sí | sí | `twitter:site` y `twitter:creator`, ambos `@ZahiriNatZuke`. |
| REQ-005 | sí | sí | El bloque `application/ld+json` parsea con `json.loads`; `@type` = `SoftwareApplication` y `url` = la base del sitio con barra. |
| REQ-006 | sí | sí | `site.webmanifest` responde `200` con `display: browser`, `theme_color: #0D1A1D` y sus tres iconos, los tres servidos. |
| REQ-007 | sí | sí | Búsqueda de `href`/`src` que empiecen por `/` sobre el HTML publicado: **ninguna**. Las absolutas que hay son las `og:image`/`twitter:image`/`canonical`, que la especificación de OpenGraph exige absolutas. |
| REQ-008 | sí | sí | El JSON-LD publicado trae `softwareVersion: "0.17.0"`, o sea el marcador `__LD_VERSION__` sustituido por `build_site.py`. Cero marcadores sobreviven en la página. |

## Los dos riesgos que el acta dejó abiertos, ya cerrados

1. **El `Content-Type` del manifest en GitHub Pages.** El acta avisaba de que, si allí no se
   sirviera como JSON, habría que renombrar el fichero a `manifest.json`. **Se sirve como
   `application/manifest+json; charset=utf-8`**, así que no hay que renombrar nada.

2. **Volver a pasar el checker.** Se comprobaron sus siete avisos uno a uno contra la página
   publicada: los seis reales están cerrados y el séptimo —el del `canonical`— sigue siendo el
   falso positivo documentado. Confirmado de nuevo por ejecución: `…/local-delegate` **sin** barra
   responde `301` hacia `…/local-delegate/`, que es literalmente lo que declara el `canonical`.

## Hallazgos

Ninguno bloqueante. Dos observaciones, ninguna imputable a este cambio:

- **Los PNG pueden quedarse viejos** si alguien edita la marca y no los regenera. Ya estaba
  registrado como riesgo residual aceptado; el procedimiento vive dentro de `icon.src.html`.
  Es la misma clase de deuda que la captura del README, que sí se ataca aparte.
- El deploy de Pages solo corre cuando se toca `site/`, así que el `softwareVersion` de la página
  refleja la versión del **último despliegue**, no la última publicada en PyPI. Hoy coinciden.

## Seguimiento requerido

Ninguno. El cambio conforma con la especificación y no deja trabajo pendiente.
