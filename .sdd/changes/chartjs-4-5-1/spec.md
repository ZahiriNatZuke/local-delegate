# Specification: Sube el Chart.js vendorizado a 4.5.1

## Summary

El dashboard sirve Chart.js **4.5.1** en vez de 4.4.1, con su procedencia verificada y declarada, y
el vigilante del vendorizado deja de avisar de que hay una versión más nueva.

## Requirements

- **REQ-001:** El contenido de `resources/vendor/chart.umd.min.js` es el `dist/chart.umd.min.js` de
  **chart.js 4.5.1**, y su procedencia está **verificada contra la fuente canónica** (el tarball de
  npm), no supuesta a partir de un CDN.
- **REQ-002:** El manifiesto declara la versión, el origen, el hash y el tamaño nuevos, y su nota de
  procedencia describe lo que de verdad se observó al bajarlo.
- **REQ-003:** La licencia vendorizada corresponde a la versión vendorizada.
- **REQ-004:** `scripts/check_vendor.py` sale **verde y sin ningún aviso**.
- **REQ-005:** El dashboard sigue pintando sus gráficos, comprobado **mirándolo**, con una línea
  base tomada antes de tocar nada.

## Acceptance scenarios

### Scenario: el vigilante deja de avisar

- **Given** el vendorizado en 4.5.1 y npm publicando 4.5.1
- **When** corre `scripts/check_vendor.py`
- **Then** dice «está al día», no imprime ningún `AVISO` y sale con 0

### Scenario: el panel no se rompe

- **Given** el dashboard con datos y Chart.js 4.5.1
- **Then** pinta los mismos gráficos que con 4.4.1, sin errores de consola

## Edge cases and failure behavior

- **Si la procedencia no se puede establecer** (el tarball y el CDN no coinciden), el cambio se
  detiene: se vendoriza lo que se puede demostrar, no lo que parece.
- **Si 4.5.1 tuviera un CVE conocido**, no se sube: se estaría cambiando un problema por otro.
- **Si el dashboard se rompiera visualmente**, se revierte: la línea base previa existe justamente
  para poder atribuir el fallo.

## Non-functional requirements

- **Sin dependencias nuevas** y sin tocar el runtime: cambia un asset.
- El blob **no** puede pasar por normalización de finales de línea.

## Non-goals

- **No se publica a PyPI**: es decisión del usuario, aparte.
- **No se rediseña el vigilante**, salvo lo que la subida destape.
- **No se cambia** cómo se sirve Chart.js ni cómo lo usa el dashboard.

## Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | Tarea 1 del plan | Hash del tarball de npm igual al de jsDelivr, byte a byte |
| REQ-002 | Tarea 2 | El propio `vendor.json` |
| REQ-003 | Tarea 2 | Diff de `LICENSE.md`: sigue MIT, cambia el rango de años |
| REQ-004 | Tarea 2 | Ejecución real: «está al día», exit 0, sin avisos |
| REQ-005 | Tarea 3 | Instancias y canvas pintados antes y después, consola limpia, capturas |
