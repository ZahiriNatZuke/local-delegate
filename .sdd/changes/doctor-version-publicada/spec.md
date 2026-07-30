# Specification: doctor compara la version instalada contra la publicada en PyPI

## Summary

`local-delegate doctor` gana una comprobación más en el grupo *Entorno*: compara la versión del
paquete instalado con la última publicada en PyPI y avisa cuando la instalación se ha quedado
atrás. Hoy ese caso pasa el diagnóstico en silencio — con el CLI en 0.16.0 y la 0.17.0 publicada,
`doctor` decía «todo a punto».

La consulta se hace **en toda ejecución de `doctor`**, con timeout corto, y degrada a «no se pudo
comprobar» si no hay red. A cambio, `install` y `update` —que corren el mismo registro— **siguen
sin salir a internet**.

## Requirements

### El check nuevo

- **REQ-001:** El registro `checks.CHECKS` incluye una comprobación más, con `id` `cli.published`
  y `group` `entorno`, colocada inmediatamente después de `cli.path`.
- **REQ-002:** Su `probe` compara la versión instalada (`checks._installed_version()`) con la
  última publicada en PyPI y devuelve: `WARN` si la instalada es **menor** (con `fix_hint` no
  vacío); `OK` si son **iguales**; `OK` si la instalada es **mayor**, diciéndolo en el detalle; y
  `UNKNOWN` si no se pudo saber la versión instalada, si no se pudo consultar PyPI o si la
  consulta está deshabilitada — en los tres casos con el motivo en el detalle.
- **REQ-003:** La comparación es numérica por componentes, no alfabética: `0.9.0` es **menor** que
  `0.11.0`.
- **REQ-004:** El `probe` **nunca lanza**: cualquier fallo de red, de parseo o de metadatos se
  traduce a `UNKNOWN`. El `try` de `run_all` es la última red, no la primera.
- **REQ-005:** El `probe` **no escribe** nada, como el resto del registro.
- **REQ-006:** El detalle y el `fix_hint` no usan caracteres fuera de cp1252.

### De dónde sale el dato

- **REQ-007:** La última versión publicada se obtiene llamando a `update.latest_version()`, sin
  reimplementar la consulta ni el criterio de ordenación. Sigue habiendo **una sola** definición
  de «cuál es la última publicada».
- **REQ-008:** `checks.Context` gana un colaborador inyectable para esa consulta, con un default
  que llama al módulo real; doblarlo hace el probe determinista **sin salir a la red**.
- **REQ-009:** El default consulta con un timeout corto y explícito, definido como constante del
  módulo.

### Quién NO sale a la red

- **REQ-010:** El reporte final de `install` (`cli.py`, `run_all(..., groups=_SCAFFOLD_GROUPS)`)
  **no consulta PyPI**: inyecta el colaborador que no toca la red, y la comprobación aparece en su
  salida como `[ -- ]` con un motivo que lo dice.
- **REQ-011:** `update` (`update.py`, `run_all(ctx)`) tampoco consulta PyPI **a través del check**:
  ya lo hace por su cuenta con `latest_version()`, y una segunda llamada en el mismo comando sería
  una consulta duplicada.
- **REQ-012:** `doctor` sí consulta, en toda ejecución, con o sin `--online`. El flag `--online`
  conserva su significado actual —comparar las versiones del **backend** contra GitHub— y no
  gobierna esta comprobación.

### Coherencia del registro

- **REQ-013:** Los cuatro sitios de `checks.py` que dicen el tamaño del registro pasan a decir
  «trece»; el test que los compara contra `len(CHECKS)` sigue verde.
- **REQ-014:** El `CHANGELOG.md` recoge el cambio bajo `Unreleased`, respetando su terminador de
  línea CRLF.
- **REQ-015:** Si la documentación publicada (README o wiki) describe la salida de `doctor` o la
  lista de comprobaciones, se actualiza en el mismo cambio.

## Acceptance scenarios

### Scenario AC-1: instalación vieja — el caso que motivó el cambio

- **Given** un CLI instalado en `0.16.0` y `0.17.0` publicada en PyPI
- **When** se ejecuta `local-delegate doctor` sin flags
- **Then** en el grupo *Entorno* aparece una línea `[WARN]` que nombra las dos versiones, debajo
  la línea `arréglalo con: <comando>`, y el resultado final cuenta ese aviso (exit code 1)

### Scenario AC-2: al día

- **Given** un CLI instalado en la misma versión que la última publicada
- **When** se ejecuta `local-delegate doctor`
- **Then** la línea es `[ OK ]` y no aporta ningún aviso al exit code

### Scenario AC-3: repo por delante de lo publicado

- **Given** un CLI instalado desde el repo en una versión **mayor** que la última publicada
- **When** se ejecuta `local-delegate doctor`
- **Then** la línea es `[ OK ]` y el detalle dice que esa versión aún no está publicada

### Scenario AC-4: sin red

- **Given** que la consulta a PyPI falla (sin red, timeout o respuesta ilegible)
- **When** se ejecuta `local-delegate doctor`
- **Then** la línea es `[ -- ]` con el motivo, el diagnóstico no se cae, el resto de las
  comprobaciones se imprimen igual, y ese `[ -- ]` no cuenta para el exit code

### Scenario AC-5: `install` no sale a internet

- **Given** un `local-delegate install` cualquiera
- **When** termina e imprime el reporte del andamiaje
- **Then** no se ha hecho ninguna petición a PyPI, y la línea de la comprobación nueva es `[ -- ]`
  con un motivo que lo explica

### Scenario AC-6: `update` no duplica la consulta

- **Given** un `local-delegate update`
- **When** corre su diagnóstico interno
- **Then** PyPI se consulta **una sola vez** en todo el comando —la que ya hacía
  `latest_version()`— y no una por el check

## Edge cases and failure behavior

- **Versión instalada ilegible o ausente** (`importlib.metadata` sin metadatos): `UNKNOWN`, nunca
  `MISSING`. Regla 2 del módulo: lo que no se pudo comprobar no es una falta.
- **PyPI responde pero sin versiones utilizables:** `latest_version()` ya devuelve
  `(None, motivo)`; el probe lo pasa a `UNKNOWN` con ese motivo.
- **Sin red:** el coste tope de `doctor` sube por el timeout de la constante, no más.
- **Versión instalada con sufijo** (`0.17.1.dev3`): la clave de comparación numérica la ordena
  por delante de `0.17.1`, lo que da `OK` («aún no publicada»), que es la respuesta correcta para
  una instalación de desarrollo.

## Non-functional requirements

- **Rendimiento:** medido por ejecución antes de especificar, dos consultas seguidas al índice
  simple de PyPI tardaron 0.08 s y 0.07 s. El sobrecoste de `doctor` con red es despreciable; sin
  red queda acotado por el timeout.
- **Compatibilidad:** no cambia la semántica de ningún flag existente ni el formato de la salida
  del resto de las comprobaciones. Corre en los tres sistemas del CI.
- **Privacidad:** la petición es la misma que ya hace `update` (índice simple de PyPI, sin
  credenciales ni datos del usuario).
- **Robustez:** ninguna ruta de fallo puede tumbar el diagnóstico, que es justo lo que uno ejecuta
  cuando algo va mal.

## Non-goals

- Arreglar la caché de PyPI que hace que `update` anuncie la versión anterior justo tras publicar
  (pendiente aparte).
- Que algún comando **actualice** el CLI; aquí solo se diagnostica y se sugiere.
- Cambiar el significado de `--online`.
- Comprobar versiones de dependencias distintas del propio paquete.

## Traceability

| Requisito | Trabajo previsto | Evidencia |
|---|---|---|
| REQ-001, REQ-013 | Entrada nueva en `CHECKS` y los cuatro textos del tamaño | test del registro y del tamaño |
| REQ-002..REQ-006 | `_probe_published` en `checks.py` | tests por cada estado + test de no-escritura |
| REQ-007..REQ-009 | Colaborador `latest_release` en `Context` y su default | test con colaborador doblado |
| REQ-010, REQ-011 | Inyección en `cli.py` y `update.py` | tests que fallan si se toca la red |
| REQ-012 | `doctor.py` sin cambios en `--online` | test de `doctor` sin flags |
| REQ-014, REQ-015 | CHANGELOG y documentación | revisión del diff |
