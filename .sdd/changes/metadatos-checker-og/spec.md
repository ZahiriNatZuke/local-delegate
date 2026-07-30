# Cerrar los avisos del checker de OpenGraph en la landing

Modo **lite**. Continuación directa de `marca-open-graph`: aquella dejó los metadatos sociales
completos, y un checker externo (72/100) señala lo que faltó.

## Origen

Un analizador de OpenGraph público sobre `https://zahirinatzuke.github.io/local-delegate`. Sus
siete avisos, cada uno con veredicto propio — el informe **no se acepta entero**:

| # | Aviso | Veredicto |
|---|---|---|
| 1 | `og:description` de 213 caracteres | **Válido.** Medido: 213. `description` (104) y `twitter:description` (149) sí están en rango. |
| 2 | Falta `apple-touch-icon` | **Válido.** iOS no usa SVG; sin PNG hace una captura de la página. |
| 3 | Falta favicon `.ico`/`.png` | **Válido el arreglo, no el argumento.** La doc de Google dice que acepta «cualquier formato válido» y no excluye SVG, así que su «Google won't display it» no tiene respaldo. Un PNG cubre a todos igual y cuesta nada. |
| 4 | Falta `twitter:site` | **Válido.** La cuenta existe: `@ZahiriNatZuke`. |
| 5 | Canonical distinto de la URL | **Falso positivo.** Se analizó `…/local-delegate` sin barra; GitHub Pages responde `301` a `…/local-delegate/`, que es exactamente lo que declara el canonical. Comprobado. **No se toca.** |
| 6 | Sin datos estructurados (JSON-LD) | **Válido**, y con un tipo mejor que el `WebPage` genérico que sugiere. |
| 7 | Falta web app manifest | **Válido con matices.** Esto no es una PWA; se añade un manifest honesto (`display: browser`), no uno que finja una app instalable. |

**Lo que no se copia del informe:** todos sus snippets usan rutas absolutas
(`/apple-touch-icon.png`, `/favicon.ico`, `/site.webmanifest`). Esto es un GitHub Pages **de
proyecto**: la raíz del dominio es `zahirinatzuke.github.io`, que no pertenece a este repo.
Comprobado — `https://zahirinatzuke.github.io/favicon.ico` da 404. Todo va relativo, como el
`favicon.svg` que ya funciona.

## Requisitos

- **REQ-001:** `og:description` baja a 110–160 caracteres **reutilizando la cadena de
  `twitter:description`**, que ya está en rango (149): dos textos que dicen lo mismo pasan a ser uno.
- **REQ-002:** La landing sirve `apple-touch-icon.png` (180×180) y `favicon-32x32.png`,
  **derivados del SVG canónico**, no dibujados aparte.
- **REQ-003:** Los dos PNG llevan fondo sólido: la marca es solo trazo y iOS compone la
  transparencia sobre negro.
- **REQ-004:** La página declara `twitter:site` y `twitter:creator` con `@ZahiriNatZuke`.
- **REQ-005:** La página declara un JSON-LD de tipo `SoftwareApplication` —es un programa gratuito
  y de código abierto, no una `WebPage` anónima— que parsea como JSON válido.
- **REQ-006:** La página declara un `site.webmanifest` con los iconos, el `theme-color` que ya usa
  y `display: browser`.
- **REQ-007:** Ninguna ruta nueva es absoluta.
- **REQ-008:** El número de versión sigue sin escribirse a mano: si el JSON-LD lo declara, va por
  el marcador `__LD_VERSION__` que sustituye `build_site.py`.

## Escenarios de aceptación

### Escenario: el enlace se comparte en iOS y en X

- **Dado** un iPhone que añade la página a la pantalla de inicio
- **Cuando** iOS busca el icono
- **Entonces** encuentra `apple-touch-icon.png` de 180×180 con fondo sólido, y no hace una captura

### Escenario: el checker se vuelve a pasar

- **Dado** el informe de siete avisos
- **Cuando** se analiza la página publicada otra vez
- **Entonces** quedan cerrados los seis reales y sigue abierto solo el del canonical, que es un
  falso positivo documentado

## Comportamiento en los bordes

- Si GitHub Pages no sirviera `site.webmanifest` con un `Content-Type` JSON, el fichero pasa a
  llamarse `manifest.json`. Se comprueba en producción, no se supone.
- Los PNG derivan del SVG: si alguien cambia la marca y no los regenera, quedan viejos. El
  procedimiento va escrito en el fichero fuente, como ya se hizo con `og-image.png`.

## No funcionales

- Sin dependencias nuevas: los PNG se rasterizan con Playwright, que es el procedimiento ya
  documentado para `og-image.png`, y todo lo demás es stdlib.
- Nada de red en tiempo de carga: los ficheros nuevos son locales, como el resto del sitio.

## Fuera de alcance

- El `canonical` (aviso 5): es correcto.
- Un `.ico`. Con el PNG declarado el aviso se cierra, y un formato contenedor más es superficie
  que mantener sin nadie que la pida.
- Convertir la landing en PWA: sin service worker, sin `display: standalone`.
- El dashboard: estos ficheros son de la landing. La marca canónica sigue siendo una sola.

## Trazabilidad

- REQ-001 · REQ-004 · REQ-005 · REQ-006 · REQ-007 → `site/index.html` + `tests/test_site.py`
- REQ-002 · REQ-003 → `site/icon.src.html` → `site/apple-touch-icon.png`, `site/favicon-32x32.png`
- REQ-006 → `site/site.webmanifest`
- REQ-008 → `scripts/build_site.py` (ya sustituye el marcador) + test existente de versiones
