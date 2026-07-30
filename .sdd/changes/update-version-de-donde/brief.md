# Brief: update dice de donde saco la version publicada y como saltarse la cache

## Problem

Justo después de publicar una release, `local-delegate update` anuncia como «última» la versión
**anterior**. Se esquiva con `--version X.Y.Z`, pero el caso por defecto es el que falla y es
justo el momento en que uno lo usa.

**El pendiente estaba mal diagnosticado, y hay que replantearlo antes de tocar nada.** El backlog
decía que la causa es consultar el JSON de PyPI y que había que pasar al índice simple. **Las dos
cosas son falsas:** `latest_version()` (`update.py:259-280`) ya consulta el índice simple
—`https://pypi.org/simple/<pkg>/` con `Accept: application/vnd.pypi.simple.v1+json`— y lleva el
porqué escrito desde que se portó del bash.

### Lo que se midió en esta sesión

| Endpoint | `cache-control` |
|---|---|
| `pypi.org/simple/local-delegate-mcp/` (el que usamos) | `max-age=600, public` |
| `pypi.org/pypi/local-delegate-mcp/json` | `max-age=900, public` |

O sea que **el índice simple es el más fresco de los dos**, y cambiar de endpoint —que era el
arreglo propuesto— habría **empeorado** el síntoma. Queda descartado con dato, no con opinión.

Otros datos de la sonda, útiles para acotar el alcance:

- **No existe header `Age`** en la respuesta, así que no se puede reportar «esta respuesta tiene N
  segundos». Sí hay `X-Cache` (`MISS, MISS, HIT`) y `x-pypi-last-serial`, pero ninguno de los dos
  dice, por sí solo y sin una referencia previa, si lo servido está desfasado.
- El workflow `publish.yml` tarda **~40 s** de principio a fin (medido en las tres releases del
  2026-07-30: 0.15.0, 0.16.0 y 0.17.0). O sea que buena parte de la ventana en la que `update`
  «se equivoca» puede ser sencillamente el rato en que **la publicación todavía no ha terminado**.

### Un segundo defecto en la misma línea, encontrado leyendo

`update.py:589-591` imprime `Última versión publicada: {version}` **también cuando el usuario pasó
`--version`** — y ahí esa versión no es «la última publicada», es la que pidió él. El mensaje
afirma algo que no comprobó. Es el mismo problema de fondo: la línea no dice de dónde salió el
dato.

## Desired outcome

`update` deja de afirmar cosas que no comprobó y, cuando el síntoma aparece, **lo explica en el
momento**:

- La línea dice **de dónde** salió la versión: del índice simple de PyPI, o del `--version` que
  pasó el usuario.
- Si la versión instalada es **más nueva** que la que anuncia PyPI —que es exactamente lo que se
  ve al acabar de publicar—, `update` lo señala y recuerda `--version X.Y.Z`.
- El código deja escrito el resultado de la medición, para que nadie vuelva a proponer el JSON.

## In scope

- El mensaje de `run_update` sobre la versión, en sus tres casos: la que pidió el usuario, la que
  se consultó, y la que no se pudo consultar.
- La detección de «instalada más nueva que la publicada», reusando `checks._compare_versions`
  —que existe desde el change `doctor-version-publicada`— en vez de escribir otra comparación.
- Dejar en `latest_version()` el dato medido (600 s vs 900 s) junto al porqué que ya está escrito.
- Corregir el pendiente en el backlog del vault: la causa que afirmaba era falsa.

## Out of scope

- **Cambiar de endpoint.** Medido y descartado: el que usamos es el más fresco.
- **Reintentar o esperar** a que PyPI se refresque. Un comando que se cuelga esperando a un CDN es
  peor que uno que dice lo que ve.
- **Reportar la edad de la respuesta.** No hay header `Age`; construirla a partir de `X-Cache` y
  `x-pypi-last-serial` daría una cifra que no significa lo que parece.
- **Que `doctor` cambie.** Su comprobación nueva ya degrada bien y no afirma nada de más.

## Constraints and risks

- **La causa raíz sigue sin poder aislarse sin publicar.** Distinguir «PyPI sirvió caché stale» de
  «la publicación aún no había terminado» exige medir durante una publicación real, y publicar
  requiere confirmación explícita del usuario. Por eso el alcance es el que el propio backlog
  anticipó: que `update` **diga lo que sabe** en vez de adivinar.
- **Riesgo de sobre-ingeniería.** La tentación es añadir reintentos, cache-busters o un flag de
  frescura. Nada de eso es fiable contra un CDN ajeno, y todo se paga en complejidad permanente.
- **No duplicar la comparación de versiones.** `checks._compare_versions` ya existe y está probado;
  una segunda implementación en `update` sería la clase de verdad duplicada que ya costó caro aquí.
- **`run_update` imprime a través de `out`**, que los tests doblan. Cualquier mensaje nuevo tiene
  que salir por ahí y no por `print`, o dejará de ser verificable.

## Open questions

- Ninguna que bloquee. La pregunta de fondo —¿caché de PyPI o publicación sin terminar?— queda
  **abierta a propósito** y se podrá zanjar en la próxima publicación real, precisamente porque
  este cambio hace que `update` deje constancia de lo que vio.
