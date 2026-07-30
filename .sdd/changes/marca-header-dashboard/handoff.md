# Handoff: El header del dashboard usa el favicon canonico y se regenera la captura

## Current state

- **SDD status:** `closing` → cerrado con este documento. Change **lite**.
- **Last completed gate:** los cinco aprobados.
- **Current revision:** mergeado en `main` como `ca7e0bd` (PR #74, squash), 12 checks del PR en
  verde y CI completo de `main` verificado después (CI, CodeQL, Vendor audit).
- **Sin publicar.** Vive en `Unreleased`, junto al change C.

## What changed

El header del dashboard tenía un **SVG dibujado a mano** —chip verde con degradado y chevrones—
mientras la marca del proyecto es el corchete con el chevrón de `resources/brand/favicon.svg`. El
panel enseñaba una marca en su cabecera y otra en la pestaña del navegador.

Ahora el HTML lleva `__BRAND_MARK__` y `render_index()` inyecta el mismo `FAVICON` que se sirve en
`/favicon.svg`. Captura del README regenerada; `CHANGELOG` y `docs/wiki/Savings-and-metrics.md`
actualizados.

## Decisions

1. **Inyectar, no sincronizar.** La alternativa era copiar el SVG en el HTML y poner un test que
   comparara las copias. Se descartó: eso es lo que había, y falló. Con una sola fuente no hay nada
   que sincronizar.
2. **`aria-hidden` en el contenedor, no un SVG modificado.** Oculta el subárbol entero —incluido el
   `aria-label` del fichero canónico— sin tener que editar el fichero, que se usa en tres sitios.
   El nombre lo dice `.brand-name` justo al lado.
3. **El test exige un solo `<svg>`** dentro del contenedor, no solo que el canónico esté presente:
   sin eso, alguien podría añadir otro al lado y el test seguiría verde.

## Lo que enseñó

- **Declarar una fuente única en un comentario no basta si queda una copia viva en otro sitio.** El
  comentario de `_load_favicon` decía «NO se escribe aquí» y aun así había un icono escrito ahí
  mismo, 370 líneas más abajo. La regla se había aplicado al endpoint y a la landing, pero no al
  HTML del propio panel.
- **`local-delegate serve --port 9494` no sirve para capturar el README.** Es un daemon singleton y
  el lock lo tiene el daemon del 9393: responde `lock ocupado pero no responde un daemon en
  127.0.0.1:9494` y no arranca, aunque el puerto esté libre. Hay que montar solo `metrics.app` con
  uvicorn. Esto se suma al gotcha ya conocido de servir **desde el repo**, porque el script deja
  pasar `/api/status` sin mockear a propósito.

## Next action

Nada pendiente de este change. La regeneración de la captura sigue siendo manual y sigue en el
backlog como pendiente propio.

## Memory

- **Canonical note:** `projects/local-delegate/jornada-2026-07-30-el-tercer-verbo.md` (sección de
  la marca), más el gotcha del `serve` singleton anotado en `projects/local-delegate/backlog.md`.
- **Indexes updated:** puntero propio en la memoria de Claude Code del proyecto.
