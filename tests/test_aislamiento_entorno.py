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


def _variables_que_leen_los_hooks() -> dict[str, set[str]]:
    """Escanea `resources/hooks/*.py` y devuelve, por fichero, las variables que consulta.

    Que lo cuente el programa y no una lista a mano: contar sitios a ojo ya salió mal una vez en
    este repo —14 variables contadas, 34 reales—, y aquí el coste de que se escape una es que la
    suite vuelva a heredar el entorno de quien la corre.

    Solo cuentan las variables NUESTRAS. Un hook también consulta las del sistema operativo
    —`LOCALAPPDATA`, `XDG_DATA_HOME`— para saber dónde vive el directorio de datos, y esas ni se
    declaran ni se limpian: quitarlas durante la suite rompería justo lo que se quiere probar.
    """
    hooks = Path(config.__file__).parent / "resources" / "hooks"
    nuestras = ("LD_HOOK_", "LOCAL_DELEGATE_")
    encontradas: dict[str, set[str]] = {}
    for archivo in sorted(hooks.glob("*.py")):
        nombres: set[str] = set()
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            # os.environ.get("X") / os.getenv("X")
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute):
                objetivo = nodo.func.value
                es_environ_get = (
                    nodo.func.attr == "get"
                    and isinstance(objetivo, ast.Attribute)
                    and objetivo.attr == "environ"
                )
                es_getenv = nodo.func.attr == "getenv"
                if (es_environ_get or es_getenv) and nodo.args:
                    primero = nodo.args[0]
                    if isinstance(primero, ast.Constant) and isinstance(primero.value, str):
                        nombres.add(primero.value)
            # os.environ["X"]
            if (
                isinstance(nodo, ast.Subscript)
                and isinstance(nodo.value, ast.Attribute)
                and nodo.value.attr == "environ"
                and isinstance(nodo.slice, ast.Constant)
                and isinstance(nodo.slice.value, str)
            ):
                nombres.add(nodo.slice.value)
        propias = {n for n in nombres if n.startswith(nuestras)}
        if propias:
            encontradas[archivo.name] = propias
    return encontradas


def test_toda_variable_que_lean_los_hooks_esta_declarada_en_config():
    """REQ-022: los hooks leen con `os.environ` porque no pueden importar el paquete.

    Son stdlib pura y corren fuera de él, así que la lectura tiene que ser directa — pero el
    inventario del que se alimenta el aislamiento de la suite se construye mirando SOLO a
    `config.py`. Una variable que exista para el hook y no esté reflejada aquí es invisible para
    el guardián, y por esa rendija los tests vuelven a heredar lo que haya en la máquina.
    """
    por_archivo = _variables_que_leen_los_hooks()
    # Control positivo: si el escáner dejara de encontrar nada, este test pasaría en vacío. El
    # umbral baja de 3 a 2 al retirarse `output_stats.py`, que era el tercer fichero que leía
    # variables propias; sigue cazando un escáner que devuelva vacío o casi.
    assert len(por_archivo) >= 2, f"el escáner no encontró casi nada: {por_archivo}"

    sin_declarar = {
        f"{archivo}:{nombre}"
        for archivo, nombres in por_archivo.items()
        for nombre in nombres
        if nombre not in config.VARIABLES_DE_ENTORNO
    }
    assert sin_declarar == set(), (
        f"Estas variables las leen los hooks y no constan en `config.py`: {sorted(sin_declarar)}. "
        "Decláralas allí con los helpers `_env*`, aunque el hook siga leyéndolas por su cuenta."
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
