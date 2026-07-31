# Implementation plan: El JS del panel se prueba ejecutandolo

## Approach

**Ejecutar el JS real con node, sin tocar el panel.**

Las funciones se recortan del `HTML` por su cabecera —el mismo ayudante que usa el test de
paridad— y se corren en un programa `.mjs` con las dependencias mínimas. El módulo no cambia ni
una línea del dashboard: si hubiera que reescribir el código para poder probarlo, el test dejaría
de probar lo que se sirve.

Dos decisiones que no se derivan del repo:

1. **Fijar `TZ` a una zona con offset** (`America/Havana`) en vez de usar la del que ejecuta. Con
   `TZ=UTC` —lo habitual en un runner— un `localDayKey` escrito con `toISOString()` pasaría en
   verde. El test tiene que poder distinguir local de UTC, y para eso los dos no pueden coincidir.
2. **Elegir por riesgo, no por cobertura.** Se prueban las funciones que deciden qué se pide y
   cómo se agrupa; no se persigue tocar las 40.

## Ordered tasks

1. **El ayudante y los tests de rango**
   - Ficheros: `tests/test_dashboard_js.py`
   - Requisitos: REQ-001 a REQ-005, REQ-010
   - Verificación: mutantes sobre `computeRange`.
   - Rollback: borrar el módulo.

2. **Agrupación por día y agregados**
   - Requisitos: REQ-006, REQ-007, REQ-008
   - Verificación: mutantes de `toISOString`, orden y filtrado de ceros.

3. **Formato**
   - Requisitos: REQ-009
   - Verificación: mutante que mueve una frontera.

4. **CHANGELOG**

## Test strategy

- **Ejecución real con node.** Nada de grep.
- **Verificación al revés, y es la parte importante del change:** diez mutantes que reproducen los
  defectos clásicos de estas funciones —día en UTC, off-by-one en el preset, el rango
  personalizado cortando el último día, `agg` sin filtrar ceros o al revés, `fmtHace` pasándose
  una frontera, `byDay` sin ordenar o reventando con una fecha ilegible—.
- **`pytest.skip` sin node**, como el test de paridad.
- **Secretos:** no aplica.

## Migration and compatibility

Ninguna: solo se añaden tests. `metrics.py` no se toca.

## Plan review

- [x] Cada requisito mapea a un test y a un mutante donde aplica.
- [x] Nada destructivo.
- [x] Sin dependencias nuevas: node ya lo exige el CI.
- [x] Sin trabajo ajeno: no se toca el panel ni se mete Playwright.
