# Specification: Acotar el SDK mcp por debajo del major 2 y cerrar el punto ciego de resolucion libre

## Summary

Una instalación nueva de `local-delegate-mcp` desde PyPI, sin pines manuales, arranca y completa
el handshake MCP aunque el SDK `mcp` tenga publicado un major incompatible. El repositorio
comprueba esa propiedad por sí solo en cada cambio, en vez de depender de que un usuario tropiece
con el fallo en otra máquina.

## Requirements

- **REQ-001:** `pyproject.toml` acota `mcp` por debajo del major 2, conservando el mínimo actual.
  La restricción lleva un comentario que explica **por qué** existe (convención del repositorio).
- **REQ-002:** Instalado el paquete con **resolución libre** (sin `uv.lock`, tomando las versiones
  más altas admisibles), `import local_delegate.server` no lanza `ModuleNotFoundError`.
- **REQ-003:** En esas mismas condiciones, el server responde un handshake `initialize` por stdio
  **sin necesidad de un backend OpenAI-compatible vivo**.
- **REQ-004:** El CI ejecuta REQ-002 y REQ-003 en cada PR y en cada push a `main`, sobre el
  artefacto construido, no sobre el árbol de fuentes con el lock aplicado.
- **REQ-005:** Se demuestra que la comprobación de REQ-004 **falla** si se retira el techo. Un
  check que nunca ha fallado no es evidencia de nada.
- **REQ-006:** La versión pasa a **0.12.2**, coherente en los cuatro sitios que exige el proyecto
  (`pyproject.toml`, las dos de `server.json`, `uv.lock`), aplicada con `scripts/bump_version.py`.
- **REQ-007:** `CHANGELOG.md` describe el fallo en términos de su síntoma observable
  (`MCP error -32000` en el cliente) para que quien lo sufra lo reconozca.
- **REQ-008:** El check nuevo **no** se añade a los checks requeridos del ruleset hasta comprobar
  que publica su resultado en un PR real.
- **REQ-009:** La suite existente pasa contra la versión de `mcp` que quede fijada en el lock tras
  regenerarlo, sea 1.28.1 u otra 1.x.

## Acceptance scenarios

### Scenario: instalación nueva con el SDK 2.x disponible

- **Given** `mcp` 2.0.0 publicado como latest en PyPI
- **When** un usuario ejecuta `uvx local-delegate-mcp` sin `--with` ni pines
- **Then** el proceso arranca, responde `initialize` y no muere con `-32000 Connection closed`

### Scenario: el CI detecta el próximo major incompatible

- **Given** una dependencia con un major nuevo que rompe el import
- **When** corre el CI del repositorio
- **Then** el job de resolución libre falla y nombra el import que rompió

### Scenario: demostración de que el check muerde

- **Given** la rama del fix, con el techo aplicado
- **When** se retira el techo temporalmente y se corre el job
- **Then** el job falla; al reponer el techo, pasa

## Edge cases and failure behavior

- **Sin red o PyPI degradado:** el job de resolución libre depende de la red por definición. Un
  fallo de red no debe leerse como una regresión de dependencia: el mensaje tiene que permitir
  distinguirlos.
- **El backend no está vivo:** es el caso normal en CI. El handshake debe completarse igual; si el
  server exigiera el backend para arrancar, REQ-003 es inalcanzable y hay que reabrir la spec.
- **`uv lock --check` en el CI:** ya existe y debe seguir pasando tras regenerar el lock.
- **Instalaciones ya rotas:** el workaround `--with "mcp<2"` sigue siendo válido y no entra en
  conflicto con el techo. No se rompe a quien ya lo aplicó.

## Non-functional requirements

- **Compatibilidad:** no se altera el comportamiento del paquete. Solo cambia el rango admisible
  de una dependencia.
- **Operabilidad:** el fallo actual es mudo desde el cliente (`-32000` sin causa). El `CHANGELOG`
  debe dejar rastro de dónde mirar el traceback real (`Server stderr` del log del cliente).
- **Seguridad:** sin secretos nuevos. El job de CI no necesita credenciales.
- **Reversibilidad:** el techo se retira en una línea el día que se migre a 2.x.

## Non-goals

- Migrar a `mcp.server.mcpserver` y la API 2.x. Es un cambio SDD propio.
- Poner techo a las otras cinco dependencias directas. Se anota como seguimiento; hacerlo aquí
  mezclaría un arreglo urgente con una política de dependencias que merece su discusión.
- Cambiar el modo en que el daemon de Windows se actualiza (no está afectado).
- Declarar la versión real del server en `serverInfo` (hoy reporta la del SDK). Es un defecto real
  y separado; se anota para el backlog.

## Traceability

| Requisito | Trabajo planificado | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | `pyproject.toml` | diff + comentario presente |
| REQ-002, REQ-003 | script de comprobación | ejecución local y en CI |
| REQ-004 | job en `ci.yml` | run del PR |
| REQ-005 | prueba negativa deliberada | run en rojo, con su enlace |
| REQ-006 | `scripts/bump_version.py 0.12.2` | `bump_version.py --check` |
| REQ-007 | `CHANGELOG.md` | diff |
| REQ-008 | no tocar el ruleset | ausencia de cambios en los checks requeridos |
| REQ-009 | `uv run pytest -q` | salida de la suite |
