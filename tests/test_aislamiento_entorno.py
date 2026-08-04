"""La suite no puede depender del entorno de quien la corre.

El defecto que cierran estos tests: `tests/test_daemon.py` daba cuatro `401 == 200` en cualquier
máquina con `LOCAL_DELEGATE_WEB_TOKEN` definida —o sea, en cualquiera con el daemon instalado— y
en CI nunca se veía porque allí esa variable no existe. El fallo parecía del cambio que estuvieras
haciendo en ese momento.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from local_delegate import config


def test_el_inventario_de_variables_no_esta_vacio():
    """Control positivo de los otros dos: sin esto, un inventario roto los dejaría pasar en vacío.

    Si `_VARIABLES_LEIDAS` dejara de alimentarse, `VARIABLES_DE_ENTORNO` quedaría vacío y tanto la
    fixture de aislamiento como el test de abajo pasarían sin haber comprobado absolutamente nada.
    """
    assert len(config.VARIABLES_DE_ENTORNO) > 20
    # Dos que tienen que estar sí o sí: la que causó el defecto y la de la telemetría de hooks.
    assert "LOCAL_DELEGATE_WEB_TOKEN" in config.VARIABLES_DE_ENTORNO
    assert "LD_HOOK_TELEMETRY_LOG" in config.VARIABLES_DE_ENTORNO


def test_la_suite_corre_sin_variables_del_paquete_definidas():
    """Ninguna variable que lea `config` puede estar definida mientras corre la suite."""
    definidas = sorted(n for n in config.VARIABLES_DE_ENTORNO if n in os.environ)
    assert definidas == [], (
        f"El entorno de esta máquina se está colando en la suite: {definidas}. "
        "La fixture `entorno_sin_variables_del_paquete` de conftest.py debería haberlas quitado."
    )


def test_config_solo_lee_el_entorno_por_la_puerta_registrada():
    """`os.environ` solo se toca dentro de `_leer`, que es quien alimenta el inventario.

    Sin esta guarda, una lectura directa nueva (`os.environ.get("LOCAL_DELEGATE_LO_QUE_SEA")`)
    quedaría fuera de `VARIABLES_DE_ENTORNO` y la suite volvería a heredar el entorno por esa
    rendija — que es exactamente como llegó hasta aquí el caso de `LOCAL_DELEGATE_WEB_TOKEN`.
    """
    fuente = Path(config.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)

    def toca_el_entorno(nodo: ast.AST) -> bool:
        for hijo in ast.walk(nodo):
            if (
                isinstance(hijo, ast.Attribute)
                and hijo.attr in {"environ", "getenv"}
                and isinstance(hijo.value, ast.Name)
                and hijo.value.id == "os"
            ):
                return True
        return False

    culpables = [
        nodo.name
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.FunctionDef) and nodo.name != "_leer" and toca_el_entorno(nodo)
    ]
    culpables += [
        f"nivel de módulo (línea {nodo.lineno})"
        for nodo in arbol.body
        if not isinstance(nodo, ast.FunctionDef | ast.ClassDef) and toca_el_entorno(nodo)
    ]
    assert culpables == [], (
        f"Estas lecturas se saltan `_leer` y no entran en el inventario: {culpables}. "
        "Usa `_leer`/`_env`/`_env_int`/`_env_flag`/`_env_float` en vez de `os.environ` directo."
    )
