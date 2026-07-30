# Specification: El header del dashboard usa el favicon canonico y se regenera la captura

Change **lite**: un defecto de presentación, acotado, con una causa clara y un arreglo de dos
líneas. Sin ceremonia; los requisitos caben en cinco.

## Summary

El icono del header del dashboard **es** el favicon canónico, no una copia parecida, y no puede
volver a separarse de él. La captura del README refleja el panel real.

## Requirements

- **REQ-001:** El icono del `<span class="mark">` del header sale de
  `resources/brand/favicon.svg`, el mismo fichero que sirve `/favicon.svg` y que usa la landing.
- **REQ-002:** No se puede volver a escribir un SVG a mano en ese sitio sin que la suite falle.
- **REQ-003:** El icono no se anuncia al lector de pantalla: el nombre ya lo dice `.brand-name`
  justo al lado y repetirlo sería ruido.
- **REQ-004:** `docs/assets/dashboard.png` se regenera desde **el dashboard del repo**, con la
  versión y el catálogo reales, sin exponer actividad real del usuario.
- **REQ-005:** `CHANGELOG.md` (`Unreleased`) y la wiki lo documentan.

## Acceptance scenarios

### Scenario: el panel y su pestaña enseñan la misma marca

- **Given** el dashboard servido
- **When** se carga `/`
- **Then** el SVG del header es el mismo que devuelve `/favicon.svg`.

### Scenario: alguien vuelve a escribir un icono a mano

- **Given** un `<svg>` añadido dentro del contenedor de marca
- **When** corre la suite
- **Then** falla, porque en ese contenedor tiene que haber exactamente uno.

## Edge cases and failure behavior

| Caso | Comportamiento |
|---|---|
| El recurso del favicon no se puede leer | `_load_favicon` ya devuelve un SVG vacío; el panel sigue funcionando, sin icono. Un icono ausente no tumba el dashboard |
| Queda el marcador sin sustituir | el test lo detecta: `__BRAND_MARK__` no puede aparecer en la página renderizada |

## Non-functional requirements

- **Accesibilidad:** el contenedor va `aria-hidden`, que oculta el subárbol entero —incluido el
  `aria-label` del SVG— sin tener que modificar el fichero canónico.
- **Privacidad:** la captura se genera con datos de ejemplo deterministas; no publica rutas,
  proyectos ni horarios reales del usuario.
- **Sin dependencias nuevas.** Playwright ya era una herramienta de desarrollo, no del paquete.

## Non-goals

- Rediseñar la marca. El fichero canónico no se toca.
- Automatizar la regeneración de la captura: sigue siendo manual y sigue en el backlog.
- Tocar la landing, que ya usaba el fichero correcto.

## Traceability

| Requisito | Trabajo | Evidencia |
|---|---|---|
| REQ-001, REQ-002 | `__BRAND_MARK__` + inyección en `render_index` | `test_el_header_del_dashboard_lleva_la_marca_canonica`, verificado al revés |
| REQ-003 | `aria-hidden="true"` en el contenedor | revisión del HTML |
| REQ-004 | `capture_dashboard.py` contra el 9494 del repo | la imagen, con badge `v0.17.0` |
| REQ-005 | CHANGELOG + `Savings-and-metrics.md` | diff |
