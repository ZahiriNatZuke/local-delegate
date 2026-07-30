# Verification: El header del dashboard usa el favicon canonico y se regenera la captura

Change **lite**.

## Environment

- **Revision:** rama `fix/marca-header-dashboard`, sobre `main` en `6b5a856`.
- **Runtime:** Windows 11, Python 3.11 (uv), Playwright + Chromium para la captura, `node` para
  el `--check` del JS del dashboard.

## El defecto

`web/metrics.py` tenía un SVG **dibujado a mano** dentro de `<span class="mark">` del header: un
chip verde con degradado y chevrones. La marca canónica del proyecto es otra —el corchete con el
chevrón de `resources/brand/favicon.svg`— y es la que ya servían `/favicon.svg` y la landing.

O sea que el panel enseñaba **una marca en su cabecera y otra en la pestaña del navegador**. Al
unificar la marca se actualizó el fichero canónico y el header se quedó atrás, precisamente
porque estaba escrito aparte. El comentario de `_load_favicon` (`metrics.py:533-535`) ya avisaba
de que el icono «NO se escribe aquí»: la regla se había aplicado al endpoint y no al HTML.

## El arreglo

El HTML lleva un marcador `__BRAND_MARK__` y `render_index()` inyecta el mismo `FAVICON` que se
sirve en `/favicon.svg`. No es que ahora coincidan: es que **no pueden diferir**, porque son el
mismo string.

El contenedor pasa a `aria-hidden="true"`, que oculta el subárbol entero al lector de pantalla
—incluido el `aria-label` del propio SVG—; el nombre ya lo dice `.brand-name` justo al lado.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| El header usa la marca canónica | test nuevo + inspección de la captura | ✅ | `test_el_header_del_dashboard_lleva_la_marca_canonica` |
| No pueden volver a separarse | inyección desde el mismo fichero | ✅ | `render_index()`; el test falla si se quita |
| Un solo `<svg>` en el contenedor | aserción sobre el HTML renderizado | ✅ | si alguien escribe otro al lado, se estrella |
| Captura del README al día | regenerada desde el repo | ✅ | `docs/assets/dashboard.png`, badge `v0.17.0` |
| Documentación | CHANGELOG + wiki | ✅ | `Unreleased/Fixed`, `Savings-and-metrics.md` |

### Verificado al revés

Quitado el `.replace("__BRAND_MARK__", FAVICON.strip())` de `render_index`:

```
FAILED tests/test_site.py::test_el_header_del_dashboard_lleva_la_marca_canonica
1 failed, 22 passed
```

## La captura del README

Regenerada con `scripts/dev/capture_dashboard.py --url http://127.0.0.1:9494/`.

**Servida desde el repo, no desde el daemon instalado**, que es el paso que se olvida: el script
deja pasar `/api/status` sin mockear a propósito (para que la versión y el catálogo sean reales),
así que capturar contra el daemon del 9393 habría dado el HTML del paquete instalado —sin el
cambio— y su badge de versión.

Detalle que costó dos intentos y conviene dejar escrito: **`local-delegate serve --port 9494` no
sirve para esto.** Es un daemon singleton y el lock lo tiene el daemon del 9393, así que responde
`lock ocupado pero no responde un daemon en 127.0.0.1:9494` y no arranca. Lo que funciona es
montar solo la app web:

```python
import uvicorn
from local_delegate.web import metrics
uvicorn.run(metrics.app, host="127.0.0.1", port=9494, log_level="warning")
```

Comprobado en la imagen resultante: el header lleva el corchete-chevrón de la marca única y el
badge dice `v0.17.0`. 390 eventos de ejemplo, 6 gráficos, indicador «EN CURSO».

Tras capturar, el proceso del 9494 se cerró y **el daemon real siguió intacto**: `/api/daemon`
responde `0.17.0 · pid 5900`, el mismo de antes.

## Quality checks

- [x] Project-native tests pass — **417 passed, 1 skipped** (416 antes).
- [x] Lint y formato limpios; `extract_dashboard_js.py` + `node --check` exit 0.
- [x] Secret scanning — sin cambios de dependencias ni de configuración; el único binario que
      entra es la captura, generada con datos de ejemplo deterministas que **no** contienen
      actividad real (rutas, proyectos ni horarios del usuario).
- [x] No unrelated changes.

## Deviations and residual risk

Ninguno funcional: es un cambio de presentación cubierto por un test que falla si se separan otra
vez. La captura seguirá siendo un artefacto que se regenera a mano —`docs/wiki/Publishing.md:89`
ya obliga a hacerlo cuando cambia algo visible del dashboard— y eso sigue en el backlog como
pendiente propio.
