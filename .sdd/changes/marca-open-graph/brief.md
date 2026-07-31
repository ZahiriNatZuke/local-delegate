# Brief: Marca única y metadatos sociales en la landing

> **Traza reconstruida a posteriori (2026-07-31).** El trabajo se mergeó el 2026-07-30 con el PR
> **#67** (`fcf462b`), pero los artefactos SDD se crearon con `sdd start` y **nunca se
> rellenaron**: se commitearon en plantilla, igual que en `landing-github-pages`. Lo que sigue se
> reconstruye desde el diff mergeado, el cuerpo del commit y verificación fresca por ejecución.
> Los gates `spec` y `plan` se aprueban como **registro fiel de lo entregado**, no como documentos
> que guiaron el trabajo.

## Problema

Dos defectos que salieron juntos:

1. **La landing y el dashboard tenían dos iconos distintos:** un glifo amarillo en la página y un
   chip esmeralda en el panel. Y el amarillo es, literalmente, el color que el propio CSS de la
   landing declara como «de señal: rutas, no marca».
2. **La página tenía tres etiquetas `og:*` y ninguna de Twitter**, o sea que el enlace compartido
   salía sin imagen.

## Resultado deseado

Un icono único que viva en **un solo fichero**, y una página cuyo enlace compartido se vea como
debe en las redes.

## En alcance

- El icono canónico y su consumo desde la landing y el dashboard.
- Los metadatos sociales completos (`og:*` y `twitter:*`) y la imagen social.
- La corrección del amarillo en el titular.

## Fuera de alcance

- Los iconos PNG, el manifest y los datos estructurados: eso es `metadatos-checker-og`, el cambio
  siguiente.
- El resto de la paleta de la landing.

## Restricciones y riesgos

- **Un icono editado en un sitio y no en el otro es la misma verdad duplicada que este repo ya ha
  pagado varias veces.** Si hay dos copias, tiene que haber algo que las ate.
- Un PNG **no se puede revisar en un diff**: hace falta versionar algo que sí.

## Preguntas abiertas

Ninguna pendiente.
