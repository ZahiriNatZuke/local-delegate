# Brief (modo lite): el amarillo del botón de idioma es color de UI, no de ruta

## Problema

En la paleta de la landing el amarillo tiene **un solo significado**, escrito en el propio CSS:
`--local: #E8B500;  /* amarillo de señal: la vía que se toma */`. El selector de idioma lo usaba
como color del estado activo. Elegir idioma no es tomar una ruta.

Es la misma mezcla que el PR #67 corrigió en el titular, en otra superficie que entonces no se
contó.

## Resultado deseado

El idioma activo se distingue con un recurso de UI, no con un token semántico.

## En alcance

La regla `.lang button[aria-pressed="true"]` y un test que la ate.

## Fuera de alcance

Los 14 usos de `--local` que sí son de ruta, el CTA, el anillo de foco y el subrayado de enlaces.

## Restricciones y riesgos

- El sitio tiene **dos temas** y `--ink` se invierte entre ellos: cualquier color elegido tiene que
  funcionar en los dos sin literales pegados.
- El estado activo no puede dejar de distinguirse del inactivo.
