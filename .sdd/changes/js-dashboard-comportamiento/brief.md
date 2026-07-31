# Brief: El JS del panel se prueba ejecutandolo

## Problem

El `<script>` inline del dashboard son **674 líneas** con más de 40 funciones, y hasta ahora la
suite **ejecutaba una sola**: la paridad de `acct()` con Python (`test_metrics.py:641`). El resto
se cubría con `node --check` —que solo dice que el fichero parsea— y *grep* sobre el HTML, que dice
que cierto texto está ahí.

Ninguna de las dos comprueba **qué hace** el código. Y dos de los cinco bugs de la 0.11.0 vivían
justo ahí.

El pendiente daba por hecho que automatizarlo pedía **Playwright en el CI**. No hace falta para lo
que más importa: las funciones que deciden qué se pide y cómo se agrupa son puras o casi puras, y
se ejecutan con node igual que `acct()`.

## Desired outcome

Las funciones del panel donde un fallo cambia lo que el usuario ve están probadas por ejecución, y
un defecto introducido a mano en ellas hace fallar la suite.

## In scope

- `computeRange` (los seis presets de rango).
- `localDayKey` y `byDay` (agrupación por día local).
- `agg` (lo que alimenta los donuts).
- `fmtHace` (el «hace X» del indicador).

## Out of scope

- **Playwright en el CI.** Instalar navegadores en el pipeline por lo que ya cubre node no
  compensa. El PR #110 dejó además el precedente de ejercitar render sobre un DOM mínimo.
- El render de los gráficos con Chart.js: es la librería, no nuestro código.
- CSS y aspecto visual.

## Constraints and risks

- **La zona horaria es el riesgo real de este change.** Si los tests corren con `TZ=UTC`, un
  `localDayKey` escrito con `toISOString()` pasaría en verde — precisamente el fallo que hay que
  cazar. Hay que fijar `TZ` a una zona con offset.
- `subprocess` con el entorno recortado **mata a node en Windows** (SIGABRT): necesita
  `SYSTEMROOT` y compañía. El entorno se hereda entero con `TZ` encima.
- Extraer funciones del HTML por su cabecera acopla los tests al texto del código; es el precio ya
  aceptado por el test de paridad, y el ayudante se reutiliza.

## Open questions

- Ninguna. Si algún día hace falta probar interacción real (clics, paginación en el DOM), ahí sí
  tocaría Playwright, y sería un change propio.
