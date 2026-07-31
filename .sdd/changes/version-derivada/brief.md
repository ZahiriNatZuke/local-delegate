# Brief: __version__ deja de ser un literal clavado y sale de la metadata del paquete

## Problem

`src/local_delegate/__init__.py:12` declara `__version__ = "0.10.0"` como literal, y
`scripts/bump_version.py` no lo toca: sube la versión en `pyproject.toml`, en las dos de
`server.json` y en `uv.lock`, pero ignora ese atributo. Con la 0.19.0 publicada, el paquete
anuncia públicamente una versión **nueve releases desfasada**.

Dentro del repo no engaña a nadie —nadie lo lee; el servidor saca la suya de
`importlib.metadata` (`server.py:43-50`) y los checks de la suya (`checks.py:422-431`)—, pero
`local_delegate.__version__` es la convención que un consumidor externo consulta, y hoy miente.

Es la clase de defecto que este repo persigue: **dos fuentes para el mismo dato**, y una de las
dos no está atada a nada.

## Desired outcome

`local_delegate.__version__` coincide siempre con la versión declarada en `pyproject.toml`, sin
que nadie tenga que acordarse de bumpearla, y un test lo obliga.

## In scope

- Derivar `__version__` de la metadata del paquete instalado.
- Un test que ate `__version__` a `pyproject.toml` y que falle si vuelve a ser un literal.

## Out of scope

- Unificar `server._get_version()` y `checks._installed_version()`. Son dos accesores a la
  **misma** fuente con contratos distintos a propósito (`"0.0.0"` frente a `None`), y esa
  diferencia está documentada en sus docstrings.
- Añadir `__init__.py` a la lista de sitios que bumpea `bump_version.py`: sería una **quinta**
  declaración coordinada, o sea más sitios donde mentir, justo lo contrario de lo que se busca.

## Constraints and risks

- `__init__.py` no puede levantar excepción al importarse: un checkout sin instalar
  (`PackageNotFoundError`) debe seguir importando el paquete.
- El test compara con `pyproject.toml`. Si el editable está desincronizado (bump sin
  `uv sync`/`uv run`), fallaría por una causa distinta a la que dice — el mensaje del assert
  tiene que distinguir los dos casos.

## Open questions

- Ninguna. Derivar o borrar era la única decisión, y se resuelve en la spec.
