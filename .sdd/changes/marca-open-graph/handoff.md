# Handoff: Marca única y metadatos sociales en la landing

## Estado actual

- SDD status: `closed`
- Último gate completado: `memory`
- Revisión: mergeado en `main` con el PR **#67** (`fcf462b`) el 2026-07-30, publicado en la
  **0.17.0**. Verificado fresco contra el sitio publicado el **2026-07-31**.

## Qué cambió

Hay **un** icono de marca —un corchete de terminal abrazando el chevron de delegación, «lo que
entra aquí se queda aquí»— y vive en un solo fichero:
`src/local_delegate/resources/brand/favicon.svg`. El dashboard lo lee de ahí en vez de tenerlo
inline, y la landing sirve una copia que un test compara **byte a byte**.

La página gana los metadatos sociales completos y una imagen social de 1200×630 que usa el
diagrama de conmutación que ya es la tesis de la página: la troncal baja entera y la rama a la
nube se queda a medias.

## Decisiones que no se deducen del código

1. **Dos copias del icono, atadas por un test.** No se puede tener una sola: el dashboard sirve
   desde el paquete y la landing desde GitHub Pages, que son dos despliegues distintos. Como
   eliminar la copia no es opción, se ata — «un icono editado en un sitio y no en el otro es la
   misma verdad duplicada que este repo ya ha pagado varias veces».

2. **De la imagen social se versiona el generador, no el artefacto.** Un PNG no se puede revisar
   en un diff; `og-image.src.html` sí, y lleva el procedimiento dentro. El PNG se comprueba
   leyendo su **cabecera**, para que no pueda separarse de lo que declaran los metadatos.

3. **Los `*.src.html` no se publican.** Son la fuente revisable de un artefacto, no páginas del
   sitio — el mismo criterio por el que se publica `site/` y no `docs/`.

4. **El titular deja de resaltar «la nube» con el amarillo de la vía local.** En esa paleta el
   amarillo tiene un solo significado y está escrito en el propio CSS: «amarillo de señal: la vía
   que se toma». El titular dice «lo mecánico no tiene por qué ir a la nube» y pintaba «ir a la
   nube» con ese amarillo, subrayado además con un trazo de 6 px: **señalaba como camino bueno
   justo lo que la frase niega**. La tarjeta social ya tenía la decisión tomada —allí «nube» va en
   el gris apagado de la rama que se escapa— y la landing hace ahora lo mismo. Se resalta solo
   «la nube» (no «ir a»), en un `--cloud-deep` nuevo con contraste suficiente en los dos temas
   (4,4:1 en claro, 7,1:1 en oscuro), y **sin subrayado**, porque el destacado es semántico y no
   un realce.

5. **`twitter:card=summary_large_image` no es cosmético:** sin él la imagen se recorta a un
   cuadrado diminuto.

## Lo que este cambio NO cubrió, y quedó vivo

**La misma mezcla del amarillo sobrevive en el botón de idioma**, que usa `--local` para su estado
`aria-pressed="true"`. Se corrigió el titular y no se contaron las demás superficies del mismo
token. Se ataca en su propio cambio.

## Deuda de proceso, dicha sin adornos

Los artefactos SDD **se commitearon en plantilla** y se rellenaron el 2026-07-31, después del
merge. Los gates `spec` y `plan` se aprobaron como registro fiel de lo entregado.

## Siguiente acción

El cambio del amarillo del botón de idioma.

## Memoria

- Nota canónica: `projects/local-delegate/jornada-2026-07-30-noche-socket-y-la-0-17-0.md`.
- Índices actualizados: la memoria de proyecto de Claude Code ya apunta a esa nota, y el backlog
  del vault ya registra el fleco del botón de idioma.
- Sin secretos ni datos personales.
