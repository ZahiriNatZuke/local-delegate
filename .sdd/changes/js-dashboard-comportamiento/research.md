# Research: El JS del panel se prueba ejecutandolo

## Current behavior

- El `<script>` extraído son **674 líneas** con **40+ funciones**.
- **Una sola se ejecuta** en la suite: `acct()`, en `test_metrics.py:641`, comparándola con la
  implementación de Python.
- El resto de la cobertura del JS: `node --check` en `ci.yml` (parsea) y aserciones tipo
  `assert "fetch('/api/stats?'" in html` (el texto está).
- El PR #110 añadió dos tests que ejecutan `escHooks` y `renderHooks` con node sobre un DOM
  mínimo, o sea que el camino ya está abierto.

### Las funciones donde un fallo cambia lo que se ve

| Función | Qué decide | Por qué es delicada |
| --- | --- | --- |
| `computeRange` | Qué periodo se le pide al backend | Un fallo desplaza **todo** el panel, y el resultado sigue siendo coherente consigo mismo |
| `localDayKey` | La clave del día | Cruza la frontera UTC→local; su propio comentario avisa: *«no uses toISOString(): eso vuelve a UTC»* |
| `byDay` | Las barras del gráfico | Los eventos llegan **más recientes primero**, así que el orden lo pone ella |
| `agg` | Los donuts | Filtra ceros y ordena |
| `fmtHace` | El «hace X» | Cuatro tramos con fronteras exactas |

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `tests/test_dashboard_js.py` | — (nuevo) | 12 tests que ejecutan JS | — |
| `web/metrics.py` | El panel | **Sin cambios**: solo se lee su `HTML` | — |
| `ci.yml` | `node --check` | Sin cambios; los tests ya corren en la matriz | — |

## Existing conventions

- **`_extraer_funcion_js`**: recorta una función del `<script>` balanceando llaves. Ya existe en
  `test_metrics.py` y se replica aquí con el mismo criterio.
- **`pytest.skip` si no hay node**, igual que el test de paridad: la suite no puede exigir node
  para todo.
- **Los tests explican qué fallo real los motiva**, no qué línea ejecutan.

## Dependencies and integrations

- `node`, ya requerido por el CI y por el test de paridad.
- Ninguna dependencia de Python nueva.

## Risks and unknowns

- **Confirmado por ejecución:** los 12 tests pasan y 9 de 9 mutantes aplicables caen.
- **Confirmado, y costó un rato:** `subprocess.run(env={"TZ":…, "PATH":…})` **mata a node en
  Windows** con SIGABRT (exit 134). Necesita el entorno completo. El mismo programa corría bien
  desde bash con `env -i`, lo que despistaba.
- **Confirmado a base de mutante:** la primera versión del test de `byDay` **no probaba el
  orden**, porque los datos ya entraban ordenados. Quitar el `sort` del código no lo hacía fallar.
