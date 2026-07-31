# Especificación: La landing vive en el repo y se publica en GitHub Pages

> **Reconstruida a posteriori el 2026-07-31** desde el diff mergeado del PR **#65** (`19a84ee`),
> el cuerpo de su commit y los tests que lo acompañan. Ver la nota completa en `brief.md`.

## Resumen

El proyecto publica una página propia, bilingüe y autónoma, que se despliega sola cuando cambia y
que no puede anunciar un número de versión que no sea el real.

## Requisitos

- **REQ-001:** El repositorio contiene una página (`site/index.html`) que explica qué hace el
  proyecto y por qué, en **español e inglés**, con las **mismas claves** en los dos idiomas.
- **REQ-002:** La página se publica en GitHub Pages **automáticamente** en cada push a `main` que
  toque lo que la afecta, y también a mano por `workflow_dispatch`.
- **REQ-003:** El número de versión **no se escribe a mano** en la página: se declara con el
  marcador `__LD_VERSION__`, que `scripts/build_site.py` sustituye por lo que diga
  `pyproject.toml`.
- **REQ-004:** Si un marcador sobrevive al build, el despliegue **falla** en vez de publicar una
  página rota (`build_site.py --check`).
- **REQ-005:** La página es un documento completo **sin recursos externos**: nada de CDNs, fuentes
  remotas ni scripts de terceros.
- **REQ-006:** Se publica `site/` y **no** `docs/`.

## Escenarios de aceptación

### Escenario: alguien empuja un cambio de la página a `main`

- **Dado** un push a `main` que toca `site/`, `pyproject.toml`, `build_site.py` o el propio workflow
- **Cuando** corre `pages.yml`
- **Entonces** se construye el sitio con la versión sustituida y se despliega, y si algún marcador
  sobrevive el trabajo falla antes de publicar

### Escenario: alguien mira el pie de la página

- **Dado** el sitio publicado
- **Cuando** se lee el número de versión que anuncia
- **Entonces** es el que declara `pyproject.toml`, porque no hay ninguna otra forma de que llegue ahí

## Comportamiento en los bordes

- **Un marcador sin sustituir no se publica:** `--check` recorre la salida del build y termina en
  error si encuentra alguno.
- **Una versión literal escrita a mano se caza en los tests**, con lookaround para no confundir un
  `127.0.0.1` con un `X.Y.Z`.

## No funcionales

- **Autonomía:** sin recursos de terceros, por la misma razón que Chart.js está vendorizado — una
  página que depende de un CDN depende de que ese CDN siga ahí y de lo que sirva.
- **Privacidad:** sin analítica ni cookies, así que no hay nada que declarar.

## No objetivos

- Publicar `docs/` (wiki, recipes y `plans/`) en una URL pública.
- Dominio propio, PWA, formularios o backend.

## Trazabilidad

- REQ-001 · REQ-005 → `site/index.html` + `tests/test_site.py`
- REQ-002 · REQ-006 → `.github/workflows/pages.yml`
- REQ-003 · REQ-004 → `scripts/build_site.py` + `tests/test_site.py`
