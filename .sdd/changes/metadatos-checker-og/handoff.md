# Handoff: Cerrar los avisos del checker de OpenGraph en la landing

## Estado actual

- SDD status: `closed`
- Último gate completado: `memory`
- Revisión: mergeado en `main` con el PR **#68** (`78737cd`), publicado por GitHub Pages y
  **verificado fresco en producción el 2026-07-31**. Salió al mundo con la **0.17.0**.

## Qué cambió

La landing cierra los seis avisos reales de un checker externo de OpenGraph, con el séptimo
descartado como falso positivo. Concretamente: `og:description` baja de 213 a 149 caracteres
reutilizando la cadena de `twitter:description` —dos textos que decían lo mismo pasan a ser uno—,
la página declara `apple-touch-icon.png` (180×180) y `favicon-32x32.png` derivados por
rasterización del SVG canónico, `twitter:site`/`twitter:creator`, un JSON-LD de tipo
`SoftwareApplication` y un `site.webmanifest` honesto.

## Decisiones que no se deducen del código

1. **El informe del checker no se aceptó entero.** De sus siete avisos, uno es un **falso
   positivo**: analizó `…/local-delegate` sin barra final, y GitHub Pages responde `301` hacia la
   versión con barra, que es exactamente lo que declara el `canonical`. No se toca, y por eso
   seguirá saliendo en cualquier análisis futuro. Otro aviso se atendió **con el argumento
   corregido**: se añade un favicon PNG, pero no porque «Google no muestre SVG» —la documentación
   de Google no excluye SVG—, sino porque un PNG cubre a todos los clientes y no cuesta nada.

2. **Ninguna ruta nueva es absoluta, al revés de lo que proponían todos los snippets del
   informe.** Esto es un GitHub Pages **de proyecto**: la raíz del dominio es
   `zahirinatzuke.github.io` y no pertenece a este repo — comprobado, `…/favicon.ico` da 404. Un
   `/apple-touch-icon.png` habría apuntado fuera del sitio.

3. **Esto no es una PWA y el manifest no finge que lo sea:** `display: browser`, sin service
   worker. Se añadió para cerrar el aviso, no para prometer una app instalable.

4. **Los PNG llevan fondo sólido a propósito** (`color_type=2`, sin canal alfa). La marca es solo
   trazo, y iOS compone la transparencia sobre negro.

5. **No se añadió un `.ico`.** Con el PNG declarado el aviso se cierra, y un formato contenedor
   más es superficie que mantener sin nadie que la pida.

6. **El número de versión sigue sin escribirse a mano.** El JSON-LD lo declara por el marcador
   `__LD_VERSION__` que sustituye `scripts/build_site.py`, al que hubo que enseñarle a reconocer
   también los `.webmanifest`.

## Riesgo residual aceptado

Los PNG derivan del SVG canónico y **nada obliga a regenerarlos** si alguien cambia la marca. El
procedimiento va escrito dentro de `icon.src.html`. Atarlo de verdad exigiría rasterizar dentro
del CI. Es la misma clase de deuda que la captura del README.

## Siguiente acción

Ninguna para este cambio. Los dos pendientes que dejó abiertos el acta de verificación
—el `Content-Type` del manifest en GitHub Pages y volver a pasar el checker— se cerraron en la
revisión de conformidad del 2026-07-31, los dos contra la página publicada.

## Memoria

- Nota canónica: `projects/local-delegate/jornada-2026-07-30-noche-socket-y-la-0-17-0.md`
  (la tanda que publicó la 0.17.0, con la landing y su marca dentro).
- Índices actualizados: la memoria de proyecto de Claude Code ya apunta a esa nota.
- Sin secretos ni datos personales: el único identificador es la cuenta pública `@ZahiriNatZuke`,
  que la propia página publica.
