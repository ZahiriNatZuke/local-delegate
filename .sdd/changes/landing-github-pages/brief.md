# Brief: La landing vive en el repo y se publica en GitHub Pages

> **Traza reconstruida a posteriori (2026-07-31).** El trabajo se hizo y se mergeó el 2026-07-30
> con el PR **#65** (`19a84ee`), pero los artefactos SDD se crearon con `sdd start` y **nunca se
> rellenaron**: se commitearon en plantilla. No se perdió nada — comprobado con
> `git show 19a84ee:.sdd/changes/landing-github-pages/spec.md`, que ya salía vacío.
>
> Lo que sigue se reconstruye desde el **diff mergeado, el cuerpo del commit y verificación
> fresca por ejecución**, no desde la memoria de aquella sesión. Los gates `spec` y `plan` se
> aprueban como **registro fiel de lo entregado**, no como documentos que guiaron el trabajo,
> porque no lo guiaron.

## Problema

El proyecto no tenía ninguna página que explicara qué hace y por qué. El README sirve a quien ya
llegó al repositorio; no sirve para compartir un enlace ni para que alguien entienda la propuesta
antes de decidir si le interesa.

## Resultado deseado

Una página en español e inglés, dentro del repositorio, que se despliegue sola en cada push a
`main` que la toque, y que no pueda anunciar una versión falsa.

## En alcance

- La página (`site/index.html`), bilingüe y autónoma.
- El despliegue automático a GitHub Pages (`.github/workflows/pages.yml`).
- La sustitución de la versión en tiempo de build (`scripts/build_site.py`).

## Fuera de alcance

- Publicar `docs/`, que guarda la wiki, las recipes y `plans/`.
- Dominio propio, analítica, formularios o cualquier recurso de terceros.

## Restricciones y riesgos

- **El número de versión ya vive en cuatro sitios** (`pyproject.toml`, `server.json` dos veces y
  `uv.lock`), y el histórico dice cómo acaba: en la 0.8.1 el lock se quedó en 0.7.0. Una quinta
  copia escrita a mano mentiría, y dentro del propio prototipo ya llegó a mentir con la primera
  release.
- Servir el directorio equivocado publicaría documentación interna sin que nadie lo haya decidido.

## Preguntas abiertas

Ninguna pendiente. Las dos que había —qué directorio se publica y cómo llega la versión a la
página— se resolvieron dentro del propio cambio y quedan registradas como decisiones en
`handoff.md`.
