# Specification: Cerrar las 10 alertas abiertas de CodeQL: 6 arreglos y 4 descartes

## Summary

Tras este cambio, `gh api repos/ZahiriNatZuke/local-delegate/code-scanning/alerts?state=open`
devuelve una lista vacía en `main`, con seis alertas cerradas porque el código mejoró y cuatro
descartadas con motivo escrito y verificable. Ningún fichero de la superficie expuesta del paquete
(daemon HTTP, token, lectura de ficheros, hooks) cambia de comportamiento.

## Requirements

- **REQ-001:** El script de extracción del JS del dashboard reconoce etiquetas `<script>` sin
  distinguir mayúsculas de minúsculas, y sigue extrayendo exactamente el mismo bloque inline que
  extraía antes (el que no lleva `src=`).
- **REQ-002:** Los tres `except` que hoy solo hacen `pass` explican en el propio bloque por qué
  tragarse el error es lo correcto ahí, en un comentario dentro del `except`.
- **REQ-003:** El test de deshabilitado de tipografías web comprueba la ausencia y presencia de la
  URL de Google Fonts de forma que distinga una URL real de una subcadena suelta, y sigue fallando
  si el dashboard deja de respetar `WEB_FONTS=False`.
- **REQ-004:** El test de concurrencia del semáforo comprueba, además del pico, que al terminar
  todos los hilos no queda ninguno activo, leyendo el estado compartido bajo su lock.
- **REQ-005:** Las cuatro alertas que son falsos positivos (#19, #13, #11, #12) quedan cerradas en
  GitHub con `dismissed_reason` y un comentario que explica por qué la herramienta se equivoca, y
  esto ocurre solo después de que la PR de los arreglos esté mergeada.
- **REQ-006:** La suite de tests del proyecto y el CI completo pasan en verde con los cambios.

## Acceptance scenarios

### Scenario: el escaneo siguiente queda limpio

- **Given** la rama `fix/codeql-alertas-abiertas` mergeada en `main` y los cuatro descartes aplicados
- **When** se consulta `gh api .../code-scanning/alerts?state=open`
- **Then** la respuesta es una lista vacía

### Scenario: el script de extracción no cambia lo que extrae

- **Given** el `metrics.HTML` actual, que usa `<script>` en minúsculas
- **When** se ejecuta `uv run python scripts/extract_dashboard_js.py` antes y después del cambio
- **Then** el fichero producido es byte a byte idéntico, y `node --check` pasa sobre él

### Scenario: los tests reforzados siguen pudiendo fallar

- **Given** los tests reescritos de `test_metrics.py` y `test_core.py`
- **When** se introduce a mano el defecto que cada uno dice cubrir (dashboard que ignora
  `WEB_FONTS=False`; semáforo que deja hilos activos o permite pico > 2)
- **Then** el test correspondiente falla, y falla por esa razón y no por otra

## Edge cases and failure behavior

- **`re.IGNORECASE` y el negative lookahead:** al ignorar mayúsculas, el `(?![^>]*src=)` también
  excluirá `SRC=`. Es el comportamiento correcto y más estricto; hay que confirmar que no descarta
  el bloque inline que sí queremos.
- **Si un descarte se aplicara antes del merge**, la alerta cerrada podría reabrirse al siguiente
  escaneo si el código cambiara. Por eso REQ-005 fija el orden.
- **Si CodeQL sigue marcando #1 o #18 tras reescribir los tests**, el arreglo no se fuerza: se
  documenta y se descartan como falso positivo, igual que los otros cuatro. Reescribir un test
  hasta que la herramienta calle sería empeorarlo.

## Non-functional requirements

- **Seguridad:** ninguna de las diez alertas está en la superficie expuesta; el cambio no debe
  ampliar esa superficie ni tocar el manejo del token, la autenticación del daemon ni el
  saneamiento de rutas.
- **Compatibilidad:** sin cambios de API pública, de CLI ni de formato de datos. No procede bump de
  versión ni entrada de changelog de usuario.
- **Trazabilidad:** cada descarte lleva comentario en GitHub que remite al razonamiento, de modo que
  quien vea la alerta cerrada dentro de seis meses entienda por qué.

## Non-goals

- No se cambia la suite de queries de CodeQL.
- No se refactorizan los imports perezosos de `ctypes`.
- No se convierte `except BaseException` del canario de macOS en `except Exception`.
- No se publica release: el cambio no altera comportamiento de usuario.

## Traceability

| Requisito | Alerta | Fichero | Verificación |
|-----------|--------|---------|--------------|
| REQ-001 | #20 | `scripts/extract_dashboard_js.py` | diff byte a byte de la salida + `node --check` |
| REQ-002 | #17, #15, #3 | `hook_common.py`, `daemon.py`, `server.py` | inspección + suite verde |
| REQ-003 | #1 | `tests/test_metrics.py` | mutante: dashboard que ignora `WEB_FONTS=False` |
| REQ-004 | #18 | `tests/test_core.py` | mutante: hilo que no libera el semáforo |
| REQ-005 | #19, #13, #11, #12 | GitHub API | `gh api ...?state=open` devuelve `[]` |
| REQ-006 | todas | — | `uv run pytest` + `gh run list` completo tras el push |
