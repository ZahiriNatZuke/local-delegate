# Research: __version__ deja de ser un literal clavado y sale de la metadata del paquete

## Current behavior

- `src/local_delegate/__init__.py:12` → `__version__ = "0.10.0"`, literal.
- `pyproject.toml [project].version` → `0.19.0` (la publicada).
- `scripts/bump_version.py:2-19` dice explícitamente que la versión vive en **cuatro** sitios
  (`pyproject.toml`, las dos de `server.json`, `uv.lock`). `__init__.py` no está en la lista y el
  script no lo lee ni lo escribe: `read_versions()` (líneas 72-97) y `plan()` (110-144) solo
  tocan esos cuatro.
- Nadie lee `__version__` dentro del repo. Un grep sobre `src/`, `tests/` y `scripts/` no
  devuelve ningún consumidor.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `src/local_delegate/__init__.py` | Exporta `main` y declara `__version__` a mano | Pasa a derivarlo | `__init__.py:9-12` |
| `src/local_delegate/server.py` | `_get_version()` cachea `importlib.metadata.version("local-delegate-mcp")`, con `"0.0.0"` de reserva | Se reutiliza; no cambia | `server.py:43-50` |
| `src/local_delegate/checks.py` | `_installed_version()` lee lo mismo y devuelve `None` si no se puede | Sin cambios; contrato distinto a propósito | `checks.py:422-431` |
| `tests/test_release_metadata.py` | Ata `server.json` a `pyproject.toml` en cada PR | Recibe el test nuevo: es el módulo que existe para esto | `test_release_metadata.py:1-7` |
| `scripts/bump_version.py` | Bumpea los cuatro sitios | Sin cambios: el objetivo es que haya **menos** sitios que bumpear | `bump_version.py:2-19` |

## Existing conventions

- **Un dato que puede desfasarse se ata con un test que lo obligue.** El precedente es
  `test_el_docstring_dice_cuantos_checks_hay_de_verdad` (`tests/test_checks.py:902-922`): el
  docstring de `checks.py` no puede mentir sobre su propio tamaño porque el test lo compara con
  `len(checks.CHECKS)`. Se demostró vivo al añadir el check nº16 (falló con `KeyError: 16`).
- Los tests de coherencia entre metadatos de publicación viven en `tests/test_release_metadata.py`
  y leen `pyproject.toml` con `tomllib` (`_pyproject()`, líneas 18-20).
- Los docstrings de los tests explican **por qué** existen y qué fallo real los motivó.

## Dependencies and integrations

- `importlib.metadata`, de la biblioteca estándar. Ya importado por `server.py` y `checks.py`, así
  que derivar `__version__` de `server._get_version()` no añade ninguna importación nueva a la
  cadena que `__init__.py` ya arrastra con `from .server import main`.

## Risks and unknowns

- **Confirmado:** `bump_version.py` no toca `__init__.py`; nadie lee `__version__` dentro del repo.
- **Confirmado:** `server._get_version()` no levanta si el paquete no está instalado; devuelve
  `"0.0.0"`.
- **Asunción a validar por ejecución:** que un mutante que restaure el literal haga fallar el test
  nuevo, y con el mensaje que corresponde.
