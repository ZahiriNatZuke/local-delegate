# Brief: Sube el Chart.js vendorizado a 4.5.1

## Problem

El vigilante del vendorizado (change `vigilante-vendorizado`, PR #39) avisó en su primera corrida de
lo que ya se sabía: **Chart.js está en 4.4.1 y la última publicada es 4.5.1**, dos minors de atraso.
Se dejó fuera de aquel cambio a propósito —el vigilante tenía que estrenarse con una versión de
estado conocido— y quedó anotado como su primer encargo.

El aviso vive en un job **verde**, que es exactamente el mecanismo por el que nadie se enteró del
atraso la primera vez. Atenderlo ahora es también comprobar que el proceso sirve para algo.

## Desired outcome

El vendorizado en 4.5.1, con la procedencia verificada, el manifiesto al día y el vigilante diciendo
**«está al día»** sin ningún aviso. El dashboard pinta igual que antes.

## In scope

- Sustituir `chart.umd.min.js` y `chart.js-LICENSE.md` por los de 4.5.1.
- Actualizar `vendor.json`: versión, origen, hash, bytes y nota de procedencia.
- Verificar el dashboard **antes y después**, a ojo y no solo por tests.
- Corregir lo que la actualización destape.

## Out of scope

- Tocar el vigilante en sí, salvo lo que la subida destape.
- **Publicar a PyPI**: es decisión aparte, del usuario.
- Cambiar cómo se sirve Chart.js o cómo lo usa el dashboard.

## Constraints and risks

- **La procedencia hay que establecerla, no suponerla.** Un CDN puede transformar lo que sirve: es
  literalmente lo que pasó con 4.4.1 y el banner de jsDelivr.
- **Riesgo real de regresión visual**: un minor de una librería de gráficos puede cambiar cómo
  pinta, y los tests no lo verían — solo comprueban que el fichero se sirve.
- El blob **no** puede pasar por ninguna normalización de finales de línea (`.gitattributes`).

## Open questions

Ninguna abierta. Resueltas al ejecutar:

- **¿De dónde bajarlo?** Del **tarball oficial de npm**, no de un CDN. Se comparó además con
  jsDelivr y son idénticos byte a byte, así que la procedencia queda por dos caminos independientes.
- **¿4.5.1 tiene CVEs?** No: OSV.dev devuelve cero.
- **¿Cambia la licencia?** Sigue MIT; cambia el rango de años del copyright, así que el fichero de
  licencia se actualiza también.
