# Specification: __version__ deja de ser un literal clavado y sale de la metadata del paquete

## Summary

El paquete deja de declarar su versión a mano. `local_delegate.__version__` pasa a ser un dato
**derivado** de la metadata del paquete instalado —la misma fuente que ya usan el servidor MCP y
los checks del doctor—, y un test impide que vuelva a convertirse en un literal que nadie bumpea.

**Decisión: derivar, no borrar.** Borrarlo también acabaría con la mentira, pero `__version__` es
la convención pública que un consumidor externo consulta y no cuesta nada mantenerla correcta;
derivarlo la conserva **y** elimina la duplicación, que es lo que se busca. Añadirlo a
`bump_version.py` se descarta por lo contrario: convertiría cuatro sitios coordinados en cinco.

## Requirements

- **REQ-001:** `local_delegate.__version__` es igual a la versión declarada en
  `pyproject.toml [project].version` cuando el paquete está instalado.
- **REQ-002:** Importar `local_delegate` no levanta excepción aunque la metadata del paquete no
  esté disponible.
- **REQ-003:** Existe un test que falla si `__version__` deja de seguir a `pyproject.toml`, y su
  mensaje de fallo distingue «alguien clavó un literal» de «el editable está desincronizado».
- **REQ-004:** `__version__` sigue siendo un `str` y sigue exportado por el paquete.

## Acceptance scenarios

### Scenario: el atributo público dice la verdad

- **Given** el paquete instalado en la versión que declara `pyproject.toml`
- **When** se lee `local_delegate.__version__`
- **Then** su valor es exactamente esa versión

### Scenario: alguien vuelve a clavar un literal

- **Given** `__init__.py` modificado para declarar una versión fija distinta de la real
- **When** se corre la suite
- **Then** el test nuevo falla, y su mensaje señala `__init__.py` como el sitio a mirar

### Scenario: el paquete no está instalado

- **Given** un intérprete sin la metadata de `local-delegate-mcp`
- **When** se importa `local_delegate`
- **Then** el import termina sin excepción y `__version__` es un `str`

## Edge cases and failure behavior

- **Metadata ausente o rota:** se reutiliza el contrato ya existente de `server._get_version()`,
  que devuelve `"0.0.0"`. No se inventa un contrato nuevo ni se propaga `PackageNotFoundError`.
- **Editable desincronizado:** el test puede fallar sin que `__init__.py` tenga la culpa (bump de
  `pyproject.toml` sin reinstalar). El assert debe decirlo, o mandará a mirar el fichero
  equivocado — el error que esta sesión persigue de forma explícita.

## Non-functional requirements

- **Sin coste de arranque nuevo:** no se añaden importaciones que `__init__.py` no arrastre ya.
- **Compatibilidad:** el atributo mantiene nombre, tipo y visibilidad; ningún consumidor externo
  se rompe.

## Non-goals

- Unificar los dos accesores de versión (`server._get_version` y `checks._installed_version`).
- Que `bump_version.py` conozca `__init__.py`.
- Tocar `server.json`, `uv.lock` o el flujo de release.

## Traceability

| Requisito | Trabajo planificado | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | Tarea 1 | `verification.md` — test nuevo en verde |
| REQ-002 | Tarea 1 | `verification.md` — contrato de `_get_version()` |
| REQ-003 | Tarea 2 | `verification.md` — mutante del literal |
| REQ-004 | Tarea 1 | `verification.md` — suite completa |
