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


def test_the_variable_inventory_is_not_empty():
    """Control positivo de los otros dos: sin esto, un inventario roto los dejaría pasar en vacío.

    Si `_READ_VARIABLES` dejara de alimentarse, `ENVIRONMENT_VARIABLES` quedaría vacío y tanto la
    fixture de aislamiento como el test de abajo pasarían sin haber comprobado absolutamente nada.
    """
    assert len(config.ENVIRONMENT_VARIABLES) > 20
    # Dos que tienen que estar sí o sí: la que causó el defecto y la de la telemetría de hooks.
    assert "LOCAL_DELEGATE_WEB_TOKEN" in config.ENVIRONMENT_VARIABLES
    assert "LD_HOOK_TELEMETRY_LOG" in config.ENVIRONMENT_VARIABLES


def test_the_suite_runs_without_package_variables_defined():
    """Ninguna variable que lea `config` puede estar definida mientras corre la suite."""
    defined = sorted(n for n in config.ENVIRONMENT_VARIABLES if n in os.environ)
    assert defined == [], (
        f"El entorno de esta máquina se está colando en la suite: {defined}. "
        "La fixture `env_without_package_variables` de conftest.py debería haberlas quitado."
    )


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _variables_read_by_hooks(with_alias: bool = True) -> dict[str, set[str]]:
    """Escanea `resources/hooks/*.py` y devuelve, por fichero, las variables que consulta.

    Que lo cuente el programa y no una lista a mano: contar sitios a ojo ya salió mal una vez en
    este repo —14 variables contadas, 34 reales—, y aquí el coste de que se escape una es que la
    suite vuelva a heredar el entorno de quien la corre.

    Solo cuentan las variables NUESTRAS. Un hook también consulta las del sistema operativo
    —`LOCALAPPDATA`, `XDG_DATA_HOME`— para saber dónde vive el directorio de datos, y esas ni se
    declaran ni se limpian: quitarlas durante la suite rompería justo lo que se quiere probar.
    """
    hooks = Path(config.__file__).parent / "resources" / "hooks"
    ours = ("LD_HOOK_", "LOCAL_DELEGATE_")
    found: dict[str, set[str]] = {}
    for file in sorted(hooks.glob("*.py")):
        names: set[str] = set()
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            # os.environ.get("X") / os.getenv("X")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = node.func.value
                is_environ_get = (
                    node.func.attr == "get"
                    and isinstance(target, ast.Attribute)
                    and target.attr == "environ"
                )
                is_getenv = node.func.attr == "getenv"
                if (is_environ_get or is_getenv) and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        names.add(first.value)
            # env_alias("NUEVA", "VIEJA") de hook_common: las dos se leen (REQ-002)
            if with_alias and isinstance(node, ast.Call) and _call_name(node) == "env_alias":
                for arg in node.args[:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        names.add(arg.value)
            # os.environ["X"]
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                names.add(node.slice.value)
        own = {n for n in names if n.startswith(ours)}
        if own:
            found[file.name] = own
    return found


def test_every_variable_the_hooks_read_is_declared_in_config():
    """REQ-022: los hooks leen con `os.environ` porque no pueden importar el paquete.

    Son stdlib pura y corren fuera de él, así que la lectura tiene que ser directa — pero el
    inventario del que se alimenta el aislamiento de la suite se construye mirando SOLO a
    `config.py`. Una variable que exista para el hook y no esté reflejada aquí es invisible para
    el guardián, y por esa rendija los tests vuelven a heredar lo que haya en la máquina.
    """
    per_file = _variables_read_by_hooks()
    # Control positivo: si el escáner dejara de encontrar nada, este test pasaría en vacío. El
    # umbral baja de 3 a 2 al retirarse `output_stats.py`, que era el tercer fichero que leía
    # variables propias; sigue cazando un escáner que devuelva vacío o casi.
    assert len(per_file) >= 2, f"el escáner no encontró casi nada: {per_file}"

    undeclared = {
        f"{file}:{name}"
        for file, names in per_file.items()
        for name in names
        if name not in config.ENVIRONMENT_VARIABLES
    }
    assert undeclared == set(), (
        f"Estas variables las leen los hooks y no constan en `config.py`: {sorted(undeclared)}. "
        "Decláralas allí con los helpers `_env*`, aunque el hook siga leyéndolas por su cuenta."
    )


def test_config_only_reads_the_environment_through_the_registered_door():
    """`os.environ` solo se toca dentro de `_read`, que es quien alimenta el inventario.

    Sin esta guarda, una lectura directa nueva (`os.environ.get("LOCAL_DELEGATE_LO_QUE_SEA")`)
    quedaría fuera de `ENVIRONMENT_VARIABLES` y la suite volvería a heredar el entorno por esa
    rendija — que es exactamente como llegó hasta aquí el caso de `LOCAL_DELEGATE_WEB_TOKEN`.
    """
    source = Path(config.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    def touches_env(node: ast.AST) -> bool:
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Attribute)
                and child.attr in {"environ", "getenv"}
                and isinstance(child.value, ast.Name)
                and child.value.id == "os"
            ):
                return True
        return False

    culprits = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name != "_read" and touches_env(node)
    ]
    culprits += [
        f"nivel de módulo (línea {node.lineno})"
        for node in tree.body
        if not isinstance(node, ast.FunctionDef | ast.ClassDef) and touches_env(node)
    ]
    assert culprits == [], (
        f"Estas lecturas se saltan `_read` y no entran en el inventario: {culprits}. "
        "Usa `_read`/`_env`/`_env_int`/`_env_flag`/`_env_float` en vez de `os.environ` directo."
    )


def test_hooks_read_renamed_names_only_through_env_alias():
    """REQ-002: una variable renombrada se lee por `hook_common.env_alias`, nunca directa.

    Una lectura directa (`os.environ["LD_HOOK_READ_BLOQUEAR"]`) se saltaría el alias: el nombre
    nuevo no ganaría y el viejo no quedaría anotado para el aviso.
    """
    from local_delegate import deprecations

    # Solo variables: el interruptor viejo (`switch_file`) es un fichero, no se lee del entorno.
    renamed = {
        n
        for kind, old, new in deprecations.hook_names()
        if kind == "env_var"
        for n in (old, new)
        if n
    }
    # Control positivo: el registro trae las dos variables de hooks y el escáner de alias las ve.
    assert {"LD_HOOK_READ_BLOQUEAR", "LD_HOOK_READ_BLOCK"} <= renamed
    via_alias = set().union(*_variables_read_by_hooks().values())
    assert renamed <= via_alias, sorted(renamed - via_alias)

    direct = {
        f"{file}:{name}"
        for file, names in _variables_read_by_hooks(with_alias=False).items()
        for name in names
        if name in renamed
    }
    assert direct == set(), f"lectura directa de un nombre renombrado: {sorted(direct)}"
