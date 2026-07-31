# Handoff: __version__ deja de ser un literal clavado y sale de la metadata del paquete

## Current state

- Estado SDD: `verifying` → pasa a `result-review` y `closing` con el CI del PR en verde.
- Último gate aprobado: `quality`.
- Revisión base: `3b20fb3`; rama `fix/version-derivada`.

## What changed

- `src/local_delegate/__init__.py`: `__version__` pasa de literal `"0.10.0"` a
  `_get_version()`, la misma función que el servidor MCP usa para declararse en `initialize`.
- `tests/test_release_metadata.py`: test nuevo que lo ata a `pyproject.toml`, con un `skip`
  explícito para el caso «el editable está desincronizado».
- `CHANGELOG.md`: entrada en `Unreleased`.

## Decisions

- **Derivar, no borrar.** Las dos opciones matan la mentira; derivar conserva además el atributo
  público que consulta quien importa el paquete, y cuesta una línea.
- **No se añade `__init__.py` a `bump_version.py`.** Eso convertiría cuatro declaraciones
  coordinadas en cinco. El objetivo era tener **menos** sitios que bumpear, no más.
- **Se reutiliza `server._get_version()` en vez de escribir un lector nuevo.** No añade
  importaciones (`__init__.py` ya importa `server`), no duplica la política de fallo, y garantiza
  que los dos canales públicos del paquete —el atributo y el handshake MCP— no puedan discrepar.
- **El test se salta solo si la metadata instalada no coincide con `pyproject.toml`.** Un fallo
  ahí acusaría a `__init__.py` de un problema del entorno; el `skip` separa las dos causas.

## Next action

Ninguna para este change. Siguiente punto del backlog: la autenticación del 9393.

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` (se borra el punto al cerrar).
- Índices actualizados: al cierre de la sesión.
