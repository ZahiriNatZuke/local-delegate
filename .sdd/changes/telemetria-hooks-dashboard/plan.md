# Implementation plan: El dashboard lee la telemetria de los hooks

## Approach

**Agregar en Python, pintar en JS, y no afirmar de más.**

- **El agregado es una función pura** (`_aggregate_hooks`), separada del endpoint. Es la convención
  del módulo —las cuentas viven en el servidor, una sola implementación— y además hace que todo el
  criterio se pruebe sin montar un cliente HTTP.
- **Se reutiliza `_read_file_cached`** en vez de escribir otro lector: el log de hooks es otro
  JSONL escrito por procesos que pueden morir a media línea, exactamente el caso para el que esa
  función ya está probada.
- **El mismo rango que el resto del panel.** Una tarjeta con otro periodo se leería como una
  contradicción de los KPIs de arriba.
- **La tarjeta se esconde en vez de enseñar ceros.** Es la decisión de diseño más importante del
  change: un cero leído de un fichero inexistente afirma algo falso.
- **La categoría se escapa** porque es el único texto de la página que no controla el daemon. El
  resto interpola directo, y eso está bien: sus datos son propios.

## Ordered tasks

1. **La variable de configuración**
   - Ficheros: `config.py`
   - Requisitos: REQ-003
   - Verificación: `HOOK_TELEMETRY_LOG` es `None` sin la variable.
   - Rollback: revertir.

2. **El agregado y el endpoint**
   - Ficheros: `web/metrics.py`
   - Requisitos: REQ-001 a REQ-006, REQ-010
   - Verificación: tests de agregado; e2e contra el log real de la máquina.
   - Rollback: revertir; el panel deja de pedir `/api/hooks` y la tarjeta no aparece.

3. **La tarjeta y su JS**
   - Ficheros: `web/metrics.py` (HTML y `<script>`)
   - Requisitos: REQ-007, REQ-008, REQ-009
   - Verificación: tests que **ejecutan** `renderHooks` y `escHooks` con node.
   - Rollback: revertir.

4. **Documentación**
   - Ficheros: `docs/wiki/Savings-and-metrics.md`, `CHANGELOG.md`
   - Requisitos: REQ-008 (la frontera, escrita también fuera del código)

## Test strategy

- **Unit (Python):** el agregado, por casos — sugeridas, campo ausente, vacío, agrupaciones,
  orden, categoría ausente.
- **Integración (Python):** el endpoint con `TestClient`, incluyendo rango, línea corrupta y no
  filtración de contenido.
- **JS ejecutado de verdad con node**, no grep: `escHooks` con entradas maliciosas y `renderHooks`
  con cuatro escenarios sobre un DOM mínimo. Sigue el patrón de la paridad de `acct()`.
- **End-to-end:** el endpoint contra el log real de la máquina (1817 eventos).
- **Verificación al revés:** mutantes sobre el agregado, el endpoint y el JS. Incluye
  explícitamente el mutante que **quita la llamada al escapado**, porque probar `escHooks` aislada
  no lo cazaría — error ya cometido dos veces en esta misma sesión.
- **Secretos:** un test comprueba que un campo de contenido inyectado en el log no sale por el
  endpoint.

## Migration and compatibility

Aditivo. Sin la variable de entorno, el endpoint responde `enabled: false` y la tarjeta no
aparece: el panel se ve exactamente igual que antes.

## Plan review

- [x] Cada requisito mapea a tarea y verificación (tabla de `spec.md`).
- [x] Nada destructivo: solo se lee un fichero.
- [x] Sin dependencias nuevas; `node` solo para tests, y se saltan si falta.
- [x] Sin trabajo ajeno: no se toca lo que los hooks registran ni el piloto A/B.
