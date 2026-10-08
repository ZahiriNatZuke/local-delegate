# Panel: coste, cuota e imágenes como dashboard (SDD ligero)

## Qué

Rehacer la presentación de las tres tarjetas que trajo el PR #232 en
`src/local_delegate/web/metrics.py` («Equivalente a precio de API», «Cuota de la suscripción» e
«Imágenes») y dos defectos de la barra superior y del espaciado. Solo presentación: ni el cálculo
(`_accounting` y su espejo JS, `valoracion`, `cuota`) ni las APIs cambian.

## Por qué

El usuario las rechazó: un dashboard no lleva párrafos (la de coste tenía un titular y nueve), el
texto no usaba la tipografía de las demás tarjetas, la cuota sin calibrar ocupaba una tarjeta para
decir que no hay dato, no había hueco entre la tarjeta de coste y las de abajo y, en modo oscuro,
el icono del calendario de los `<input type=date>` salía negro e invisible.

## Criterios de aceptación

1. El cuerpo de las tres tarjetas no lleva párrafos: cifras con la forma de los KPIs (etiqueta,
   valor en mono, pista corta) y, en la de coste, la tabla modelo/hilo/esfuerzo/casos/T/cota/
   estimación, que depende del rango elegido.
2. Todo el texto que salía en las tarjetas está en un diálogo de información, abierto con el
   botón ⓘ de la cabecera, accesible con teclado y cerrable con Esc.
3. Las cifras usan las mismas fuentes y tokens que los KPIs de arriba.
4. La cuota sin calibrar no se pinta; su explicación está en el diálogo. Calibrada, se presenta
   como medidor por ventana.
5. Las imágenes van como cifras; sin imágenes en el rango, la tarjeta no se pinta.
6. El hueco entre la tarjeta de coste y la fila de abajo es el mismo que entre el resto (16 px).
7. Los controles nativos (calendario, lista del `<select>`) se ven en claro y en oscuro.
8. Tests del panel y suite completa en verde; capturas antes/después en claro y oscuro.
