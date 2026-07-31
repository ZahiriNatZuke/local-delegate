# Brief: Los PNG de la marca quedan atados al favicon.svg

## Problem

`site/apple-touch-icon.png` y `site/favicon-32x32.png` salen de `site/icon.src.html`, que **carga**
`favicon.svg` en vez de redibujar la marca — o sea, el diseño ya evitaba la tercera copia.

Lo que faltaba es lo otro: **nada obligaba a regenerarlos cuando el SVG cambia**. Los tests de
`test_site.py` comprobaban que existen, que la cabecera es la de un PNG y que están declarados en
el HTML con el `sizes` correcto. Ninguno miraba si su **contenido** seguía correspondiéndose con
el icono. El propio repo lo llamaba «riesgo aceptado» en `test_captura.py:16`.

El síntoma sería silencioso: la landing serviría un icono viejo mientras el dashboard sirve el
nuevo, y nada fallaría.

## Desired outcome

Tocar `favicon.svg` sin regenerar los PNG **rompe el PR**, y regenerarlos es un comando.

## In scope

- Un script que regenere los dos PNG y escriba un manifiesto con la procedencia.
- Tests que comparen el SVG actual con el registrado y los PNG con los suyos.
- Actualizar el procedimiento documentado en `icon.src.html`.

## Out of scope

- **Rasterizar dentro del CI para comparar píxeles.** Era lo que el pendiente daba por necesario
  («atarlo de verdad exige rasterizar dentro del CI»). Metería un navegador en el pipeline por un
  riesgo que se cubre con un hash.
- `og-image.png`: ya tiene su fuente versionada y su test; no sale del SVG.

## Constraints and risks

- **El manifiesto no puede actualizarse a mano**, o el check se cumpliría sin que nadie regenerara
  nada. Lo escribe el script que captura, igual que el de la captura del README.
- **Playwright no es dependencia del proyecto** y `uv sync` lo desinstala. El script tiene que
  fallar con un mensaje que diga cómo instalarlo, no con un `ImportError` crudo.
- **Comparar por hash no compara píxeles.** Si alguien regenera con otro navegador o versión, el
  PNG puede diferir sin que la marca cambie. Es ruido tolerable: obliga a commitear el PNG nuevo,
  no a cambiar el icono.

## Open questions

- Ninguna. La decisión de fondo —procedencia en vez de rasterizado— se resuelve en la spec.
