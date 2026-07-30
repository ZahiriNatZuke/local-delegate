# Implementation plan: El header del dashboard usa el favicon canonico y se regenera la captura

Change **lite**. Tres tareas cortas.

## Approach

**Inyectar en vez de sincronizar.** La alternativa obvia —copiar el SVG canónico dentro del HTML y
poner un test que compare las dos copias— deja dos copias vivas y confía en que nadie edite una
sola. Ya pasó exactamente eso: el comentario de `_load_favicon` (`metrics.py:533-535`) declaraba
que el icono «NO se escribe aquí», y aun así el header tenía el suyo.

`HTML` ya usa un marcador (`__WEB_FONTS__`) que `render_index()` sustituye, así que hay un patrón
establecido: se añade `__BRAND_MARK__` y se sustituye por el mismo `FAVICON` que sirve el endpoint.
No hay dos copias que puedan divergir; hay una.

## Ordered tasks

1. **Sustituir el SVG a mano por el marcador**
   - Ficheros: `src/local_delegate/web/metrics.py` (`HTML` y `render_index`).
   - Requisitos: REQ-001, REQ-003.
   - Verificación: test nuevo, verificado al revés.
   - Rollback: dos líneas.

2. **El test que impide la reincidencia**
   - Ficheros: `tests/test_site.py`, junto a los otros tests de marca.
   - Requisitos: REQ-002.
   - Verificación: comprueba tres cosas —el canónico aparece, el marcador no queda sin sustituir,
     y hay **un solo** `<svg>` en el contenedor—. Verificado al revés quitando la inyección.

3. **Captura del README y documentación**
   - Ficheros: `docs/assets/dashboard.png`, `CHANGELOG.md`,
     `docs/wiki/Savings-and-metrics.md`.
   - Requisitos: REQ-004, REQ-005.
   - Verificación: inspección visual de la imagen (marca nueva, badge `v0.17.0`) y diff.
   - **Ojo:** hay que servir el dashboard **del repo**, no el daemon instalado, porque el script
     deja pasar `/api/status` sin mockear a propósito.

## Test strategy

- Unit: el test de `test_site.py`, obligatoriamente verificado al revés.
- Los cuatro pasos del CI con `.`, incluido `extract_dashboard_js.py` + `node --check`, porque se
  toca el fichero que contiene el JS del dashboard.
- Manual: inspección de la captura generada.

## Migration and compatibility

Cambio puramente visual. Sin dependencias nuevas, sin API tocada, sin formatos ni rutas nuevas.

## Plan review

Change **lite**: sin revisión adversarial separada. El riesgo es bajo y acotado —un cambio de
presentación con test propio y rollback de dos líneas— y la verificación al revés cubre lo único
que podría fallar en silencio: que el test no probara nada.

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
