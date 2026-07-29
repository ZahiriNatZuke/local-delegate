# Handoff: Sube el Chart.js vendorizado a 4.5.1

## Current state

- SDD status: `closed` (modo **lite**). Los cinco gates aprobados.
- Last completed gate: `memory`.
- Current revision: **PR #41 mergeado** en `main` con squash. Los 12 checks en verde, Windows
  incluido. En `Unreleased`: **no publicado en PyPI**.

## What changed

Chart.js pasa de **4.4.1 a 4.5.1**: el blob, su licencia y el manifiesto. Más lo que la subida
destapó: dos tests que clavaban la versión y el procedimiento documentado, que se estrenaba.

| Fichero | Qué |
| --- | --- |
| `resources/vendor/chart.umd.min.js` | 4.5.1, del tarball de npm. 208 522 bytes, `sha256 48444a82…f54a` |
| `resources/vendor/chart.js-LICENSE.md` | sigue MIT; cambia el copyright a `2014-2024` |
| `resources/vendor/vendor.json` | versión, `source`, hash, bytes y la nota de procedencia reescrita |
| `tests/test_metrics.py` | el assert de la versión la **lee del manifiesto** en vez de clavarla |
| `tests/test_vendor.py` | `VERSION_VENDORIZADA` (del manifiesto) y `MUY_POSTERIOR` en vez de números |
| `docs/wiki/Repo-hardening.md` | el procedimiento corregido con lo aprendido al ejecutarlo |
| `CHANGELOG.md` | entrada en `Unreleased` |

## Decisions

- **Se baja del TARBALL OFICIAL de npm, no de un CDN.** Es el cambio de criterio del procedimiento.
  Un CDN puede transformar lo que sirve y de hecho lo hace; el tarball es la fuente canónica.
  jsDelivr pasa a ser la **segunda** fuente, para confirmar: los dos dan el mismo hash.
- **El banner de jsDelivr es intermitente.** Se lo puso a la 4.4.1 y **no** a la 4.5.1. Que no sea
  sistemático es lo que lo hace traicionero, y por eso sigue documentado aunque esta vez no saliera.
  No confundirlo con el banner legítimo de Chart.js, que empieza por `/*!` y sí es parte del fichero.
- **La verificación visual es obligatoria en este cambio, no un extra.** Ningún test del repo ve una
  regresión de una librería de gráficos. Se hace con **línea base antes de tocar nada**; sin ella un
  fallo no se puede atribuir.
- **Los tests no clavan la versión: la leen del manifiesto.** Y para el caso «hay una más nueva» se
  usa `99.0.0`, que no envejece.

## Lo que costó una hora y no debería costarla otra vez

**La caché de 24 h del endpoint.** Tras cambiar el blob, `window.Chart.version` seguía diciendo
`4.4.1` con el servidor sirviendo ya los 208 522 bytes nuevos: el endpoint manda
`Cache-Control: public, max-age=86400`. Tiene cara de «la actualización no se aplicó» y no lo es.
Hace falta recarga forzada. Vale también para el usuario que actualice el paquete.

## Next action

Nada dentro de este change. Fuera de él: **publicar**, que es decisión del usuario. Hasta entonces
esto vive en `Unreleased` y no le llega a nadie que instale desde PyPI.

## Memory

- Canonical note: `projects/local-delegate/vigilante-vendorizado.md` en el vault, actualizada con la
  subida y con lo que enseñó.
- Indexes updated: sí. El `backlog.md` cierra el pendiente de subir a 4.5.1, y la memoria de
  proyecto de Claude Code lleva el puntero al día.
