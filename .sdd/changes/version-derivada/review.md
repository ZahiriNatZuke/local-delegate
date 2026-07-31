# Result review: __version__ deja de ser un literal clavado y sale de la metadata del paquete

## Verdict

`conforms`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 — `__version__` == `pyproject.toml` | Sí, `__init__.py:17` | Sí | Vía `server._get_version()`; el test corrió sin saltarse |
| REQ-002 — importar no levanta sin metadata | Sí, heredado | Por contrato | `server.py:43-50` devuelve `"0.0.0"`; no se ejerció por ejecución (ver desviaciones) |
| REQ-003 — test que ata y distingue las dos causas | Sí, `test_release_metadata.py` | Sí, con mutante | Cayó solo él, con el mensaje que apunta a `__init__.py` |
| REQ-004 — sigue `str` y exportado | Sí | Sí | `__all__` intacto; suite completa en verde |

## Findings

- **Ninguno bloqueante.**
- *Menor, informativo:* el repo mantiene **dos** accesores a la misma fuente
  (`server._get_version()` con reserva `"0.0.0"` y `checks._installed_version()` con `None`). No
  es duplicación de dato —los dos leen `importlib.metadata`— sino dos contratos distintos a
  propósito, documentados en sus docstrings. Se dejó explícitamente fuera de alcance en `spec.md`
  y no se toca.
- *Menor, informativo:* `bump_version.py` sigue diciendo «cuatro sitios» y sigue siendo cierto:
  este change no añade un quinto, lo quita de la ecuación.

## Required follow-up

- Ninguno para cerrar. El CI del PR es la última comprobación pendiente y es la de siempre.
