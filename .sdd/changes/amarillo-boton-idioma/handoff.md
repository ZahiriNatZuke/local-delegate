# Handoff: el amarillo del botón de idioma es color de UI, no de ruta

## Estado actual

- SDD status: `closed`
- Último gate completado: `memory`
- Revisión: rama `fix/amarillo-boton-idioma` sobre `main` en `b5c51ef`.

## Qué cambió

El botón del idioma activo se marca **invirtiendo** (`--ink` de fondo, `--paper` de texto) en vez
de con el amarillo de la vía local. Un test ata la regla.

## Decisiones que no se deducen del código

1. **La inversión no se eligió por estética, sino porque se resuelve sola en los dos temas.**
   `--ink` y `--paper` se intercambian juntos entre claro y oscuro, así que el texto contrasta con
   su fondo por construcción — sin el literal que hacía falta antes.

2. **El `color` duplicado NO era residuo, y esto es lo que más fácil se pierde.** `--ink` vale
   `#0D1A1D` en claro pero `#E4EBE8` en oscuro. El `#0D1A1D` literal existía para que el texto no
   saliera casi blanco sobre el amarillo. Quien vea un duplicado parecido en el futuro: antes de
   borrarlo, mirar si el token cambia entre temas.

3. **Solo se corrigió una de las cuatro superficies de UI que usan el token, y a propósito.** El
   CTA es literalmente la vía que se toma; el anillo de foco y el subrayado de enlaces usan el
   amarillo como acento interactivo, un rol consistente en todo el sitio. Están nombradas en
   `verification.md` por si algún día se decide lo contrario.

## Siguiente acción

Ninguna. Con esto se cierra el punto 9 del plan de la sesión; quedan la fase 3 del SDK y la
decisión de publicar.

## Memoria

- Nota canónica: pendiente de escribir con la jornada del 2026-07-31.
- Sin secretos ni datos personales.
