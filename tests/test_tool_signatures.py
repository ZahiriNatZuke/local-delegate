"""REQ-014 (SDD `backend-extra-params`, T2): el modelo frontera no puede fijar nada.

Los parámetros de rol los pone quien configura la máquina, nunca quien llama a la tool. Dos asserts
independientes:

- **(a) Instantánea**: nombres, orden y tipos de los parámetros de las 11 tools MCP, tomados de
  `main` (`f2dd267`) en `tests/fixtures/tool_signatures.json`. Un argumento nuevo la rompe.
- **(b) Guarda permanente**: ningún parámetro se llama como una clave permitida (REQ-004), una
  reservada (REQ-005), `role`, `backend_params` o `extra_body`, ni empieza por `reasoning`. No
  depende de la instantánea: actualizarla no la apaga.

Las claves salen de `backend_params.ALLOWED_KEYS | backend_params.RESERVED_KEYS` (T3, paso 7);
`tests/test_backend_params_rules.py` comprueba que son las de la spec.

Para regenerar la instantánea (solo si el cambio de firma es a propósito):
`uv run python tests/test_tool_signatures.py`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from pathlib import Path

from local_delegate import backend_params, server

SNAPSHOT = Path(__file__).parent / "fixtures" / "tool_signatures.json"

#: REQ-004 y REQ-005: la regla única de `backend_params` (T3, paso 7). La guarda mira el catálogo
#: del producto, no una copia: una clave que se añada allí queda prohibida aquí sin tocar el test.
ALLOWED_KEYS = frozenset(backend_params.ALLOWED_KEYS)
RESERVED_KEYS = backend_params.RESERVED_KEYS
#: REQ-014 (b): los nombres que, además de las claves, quedan prohibidos.
EXTRA_FORBIDDEN = frozenset({"role", "backend_params", "extra_body"})
FORBIDDEN_PREFIX = "reasoning"
#: El único parámetro de hoy que coincide con una clave reservada: `local_delegate(model=…)` elige
#: el modelo (lo explícito no lleva parámetros de rol, REQ-013) y existe desde antes de este
#: cambio. Quitarlo rompería a los clientes (assert a). La excepción es por (tool, parámetro): el
#: mismo nombre en otra tool sí dispara la guarda.
PRE_EXISTING = frozenset({("local_delegate", "model")})


def current_signatures() -> dict[str, list[list[str]]]:
    """Las tools registradas en el servidor MCP, con `[nombre, tipo]` de cada parámetro en orden.

    El tipo es la anotación tal como está escrita (`server.py` usa `from __future__ import
    annotations`, así que es texto y no depende de la versión de Python).
    """
    tools = asyncio.run(server.mcp.list_tools())
    signatures = {}
    for tool in tools:
        parameters = inspect.signature(getattr(server, tool.name)).parameters.values()
        signatures[tool.name] = [[p.name, str(p.annotation)] for p in parameters]
    return dict(sorted(signatures.items()))


def test_tool_parameters_match_snapshot():
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    current = current_signatures()
    assert len(expected) == 11, "la instantánea de f2dd267 tiene las 11 tools"
    assert current == expected, (
        "los parámetros de las tools MCP no son los de la instantánea: si añadiste un argumento a "
        "propósito, actualiza la instantánea (`uv run python tests/test_tool_signatures.py`)"
    )


def test_no_tool_parameter_is_a_backend_param():
    forbidden = ALLOWED_KEYS | RESERVED_KEYS | EXTRA_FORBIDDEN
    offenders = [
        (tool, name)
        for tool, parameters in current_signatures().items()
        for name, _type in parameters
        if (name in forbidden or name.startswith(FORBIDDEN_PREFIX))
        and (tool, name) not in PRE_EXISTING
    ]
    assert offenders == [], f"una tool deja fijar parámetros del backend: {offenders}"


def test_the_guard_has_the_keys_of_the_spec():
    """Guarda de la guarda: 21 permitidas (REQ-004) y 27 reservadas (REQ-005), sin cruce."""
    assert len(ALLOWED_KEYS) == 21
    assert len(RESERVED_KEYS) == 27
    assert not ALLOWED_KEYS & RESERVED_KEYS


if __name__ == "__main__":
    SNAPSHOT.write_text(
        json.dumps(current_signatures(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    sys.exit(0)
