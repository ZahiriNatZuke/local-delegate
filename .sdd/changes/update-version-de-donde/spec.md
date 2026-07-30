# Specification: update dice de donde saco la version publicada y como saltarse la cache

## Summary

`local-delegate update` deja de afirmar cosas que no comprobó. La línea de la versión dice **de
dónde** salió el dato, y cuando aparece el síntoma conocido —justo después de publicar, PyPI
anuncia todavía la versión anterior— el comando **lo señala en el momento** y recuerda `--version`,
en vez de dejar al usuario preguntándose por qué su release no aparece.

No cambia de dónde se consulta: medido en esta sesión, el índice simple (`max-age=600`) es más
fresco que el JSON (`max-age=900`), así que el arreglo que proponía el backlog habría empeorado el
síntoma.

## Requirements

### La línea dice de dónde salió el dato

- **REQ-001:** Cuando el usuario pasa `--version X.Y.Z`, la salida **no** afirma que esa sea la
  última publicada: dice que es la versión que él pidió.
- **REQ-002:** Cuando la versión se consultó, la salida nombra la fuente (el índice simple de
  PyPI) y advierte de que se sirve con caché.
- **REQ-003:** Cuando no se pudo consultar, se conserva el comportamiento actual: se avisa con el
  motivo y **se sigue** sin tocar los pines. No es un error.
- **REQ-004:** Todos los mensajes salen por el `out` de `run_update`, nunca por `print`, para que
  sigan siendo verificables desde los tests.

### El síntoma se detecta y se explica

- **REQ-005:** Si la versión **instalada** es más nueva que la que anuncia PyPI, `update` lo dice
  explícitamente: es la firma exacta de una publicación que aún no se ha propagado.
- **REQ-006:** En ese caso, el mensaje recuerda `--version X.Y.Z` como la salida inmediata, con la
  versión instalada ya sustituida en el texto (no un placeholder).
- **REQ-007:** El aviso **no** cambia el exit code ni el plan de acciones: `update` sigue haciendo
  exactamente lo que hacía. Es información, no un cambio de comportamiento.
- **REQ-008:** La comparación reusa `checks._compare_versions`; no se escribe una segunda
  implementación de «qué versión es mayor».

### Que nadie vuelva a proponer el JSON

- **REQ-009:** `latest_version()` deja escrito el dato medido —índice simple `max-age=600` frente
  a JSON `max-age=900`— junto al porqué que ya tenía, para que la comparación no haya que
  rehacerla.
- **REQ-010:** El `CHANGELOG.md` recoge el cambio bajo `Unreleased`, respetando su CRLF.
- **REQ-011:** Los mensajes no usan caracteres fuera de cp1252.

## Acceptance scenarios

### Scenario AC-1: acabas de publicar

- **Given** una instalación en `0.17.0` y un PyPI que todavía anuncia `0.16.0`
- **When** se ejecuta `local-delegate update`
- **Then** la salida dice que la instalada es más nueva que la publicada, nombra las dos
  versiones y recuerda `--version 0.17.0`; el exit code y las acciones planificadas son los
  mismos que sin el aviso

### Scenario AC-2: versión pedida a mano

- **Given** `local-delegate update --version 0.17.0`
- **When** corre el comando
- **Then** la salida atribuye la versión al usuario y **no** contiene la frase que afirma que es
  la última publicada

### Scenario AC-3: caso normal

- **Given** una instalación al día y PyPI respondiendo
- **When** se ejecuta `local-delegate update`
- **Then** la línea de la versión nombra el índice simple de PyPI como fuente, y no aparece
  ningún aviso de desfase

### Scenario AC-4: sin red

- **Given** que la consulta a PyPI falla
- **When** se ejecuta `local-delegate update`
- **Then** se avisa con el motivo, no se tocan los pines, el resto del comando sigue igual y no
  aparece el aviso de desfase (no hay con qué comparar)

## Edge cases and failure behavior

- **Versión instalada desconocida** (`importlib.metadata` sin metadatos): no hay comparación
  posible, así que no se emite el aviso de desfase. Se calla, no se inventa.
- **Versiones no comparables** (`_compare_versions` devuelve `None`): igual, sin aviso.
- **Instalada igual o más vieja que la publicada:** es el caso normal; sin aviso de desfase.
- **`--version` y desfase a la vez:** con `--version` no se consulta PyPI, así que no hay nada que
  comparar y no se emite el aviso.

## Non-functional requirements

- **Sin peticiones nuevas:** el número de llamadas a PyPI por ejecución no cambia (sigue siendo
  una, o cero con `--version`).
- **Sin dependencias nuevas.**
- **Compatibilidad:** no cambian flags, exit codes ni el plan de acciones. Lo único que cambia es
  el texto de la salida.
- **Operabilidad:** el objetivo es que la próxima publicación real deje **evidencia en pantalla**
  de si el desfase ocurrió, que es lo que permitirá zanjar la causa raíz sin adivinar.

## Non-goals

- Cambiar de endpoint (medido y descartado).
- Reintentar, esperar o forzar el refresco de la caché de PyPI.
- Reportar la edad de la respuesta: no hay header `Age` y derivarla sería inventar una cifra.
- Tocar el check `cli.published` de `doctor`, que ya degrada correctamente.

## Traceability

| Requisito | Trabajo previsto | Evidencia |
|---|---|---|
| REQ-001..REQ-004 | Mensajes de la versión en `run_update` | tests que aseveran sobre `out` |
| REQ-005..REQ-008 | Detección de desfase reusando `checks._compare_versions` | tests de los cuatro desenlaces |
| REQ-009 | Comentario de `latest_version()` | revisión del diff |
| REQ-010, REQ-011 | CHANGELOG y encoding | revisión del diff y `.encode("cp1252")` |
