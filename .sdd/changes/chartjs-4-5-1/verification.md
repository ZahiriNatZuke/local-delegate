# Verification: Sube el Chart.js vendorizado a 4.5.1

## Environment

- Revision: rama `feat/chartjs-4-5-1`, sacada de `main` (`f7897a6`), worktree
  `D:\Projects\local-delegate-vendor`.
- Relevant runtime and tool versions: Python 3.11 del worktree, Node 20 para `node --check`,
  Chromium vía Playwright para la comprobación visual del dashboard.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| Procedencia verificada, no supuesta | Bajar el tarball oficial de npm y comparar su `package/dist/chart.umd.min.js` con lo que sirve jsDelivr | OK | Los dos: **208 522 bytes**, `sha256 48444a82d4edcb5bec0f1965faacdde18d9c17db3063d042abada2f705c9f54a`. Idénticos byte a byte |
| Sin vulnerabilidades conocidas | Consulta a OSV.dev por `chart.js` 4.5.1 | OK | **cero** vulnerabilidades |
| Licencia revisada | Diff de `LICENSE.md` del tarball contra el vendorizado | Cambia | Sigue **MIT**; solo cambia el copyright de `2014-2022` a `2014-2024`. Se actualiza el fichero |
| Manifiesto al día y vigilante conforme | `python scripts/check_vendor.py` | OK | «Integridad: OK», «OSV no conoce ninguna para `chart.js` 4.5.1», «Versión: está al día». **exit 0 y sin un solo AVISO** |
| Sin regresión visual en el dashboard | Levantar el panel con datos y mirarlo, antes y después | OK | 4.4.1: 6 instancias de Chart, 5 canvas pintados, 0 errores de consola. 4.5.1: **6 instancias, los mismos 5 canvas, 0 errores**. Capturas a página completa de ambos |
| El blob no se normaliza | El `-text` de `.gitattributes` cubre los ficheros nuevos | OK | `test_gitattributes_protege_el_vendorizado_de_la_normalizacion` sigue verde; el patrón es del directorio, no del fichero |

## Quality checks

- [x] Project-native tests pass. `pytest -q`: **256 pasan**.
- [x] Lint, formatting, type checking, and build checks pass where applicable. `ruff check .`,
      `ruff format --check .` y `extract_dashboard_js.py` + `node --check`.
- [x] Secret scanning passes. `gitleaks` del pre-commit y el job `secrets`.
- [x] No unrelated changes are present. El blob, la licencia, el manifiesto, dos tests que clavaban
      la versión, el CHANGELOG y el procedimiento de la wiki.

## Lo que destapó la actualización

**Dos sitios seguían clavando la versión a mano**, y solo se ven cuando actualizas:

1. `tests/test_metrics.py` afirmaba `"Chart.js v4.4.1" in r.text`.
2. Los tests de versión del vigilante pasaban `"4.4.1"` y `"4.5.1"` literales a npm simulado.

Los dos fallaron al subir, los dos eran el problema que `vendor.json` vino a resolver, y los dos
pasan ahora a **leer la versión del manifiesto**. El del vigilante usa además `MUY_POSTERIOR`
(`99.0.0`) para el caso «hay una más nueva», que así no vuelve a envejecer nunca.

También se mejoró el **procedimiento documentado**, que se escribió de memoria y se probó aquí por
primera vez: ahora manda bajar del **tarball de npm** en vez de un CDN, extrae también la licencia
—que nadie habría pensado en mirar— y avisa de la caché de 24 h.

## Deviations and residual risk

- **La comprobación visual necesitó recarga forzada.** El endpoint sirve el JS con
  `Cache-Control: public, max-age=86400`, así que el navegador seguía enseñando 4.4.1 con el
  servidor ya sirviendo los bytes de 4.5.1: `window.Chart.version` decía `4.4.1`. Es un despiste con
  cara de bug — anotado en la wiki. Afecta también al usuario que actualice: verá los gráficos
  viejos hasta un día después.
- **El canvas `spark` sale con cero píxeles pintados en las dos versiones.** No es una regresión de
  esta subida: es idéntico antes y después, y responde a que el rango «Hoy» tiene pocos eventos. Se
  deja como está; mirarlo sería otro cambio.
- **La comprobación visual se hizo con datos sintéticos** (420 eventos generados) y en un solo
  navegador. Cubre que los seis gráficos pintan y que no hay errores, no una revisión de píxeles.
- **No se publica a PyPI.** Esto queda en `Unreleased`; publicar es decisión del usuario.
