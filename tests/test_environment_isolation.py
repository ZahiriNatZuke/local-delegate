"""La suite no puede depender del entorno de quien la corre.

El defecto que cierran estos tests: `tests/test_daemon.py` daba cuatro `401 == 200` en cualquier
máquina con `LOCAL_DELEGATE_WEB_TOKEN` definida —o sea, en cualquiera con el daemon instalado— y
en CI nunca se veía porque allí esa variable no existe. El fallo parecía del cambio que estuvieras
haciendo en ese momento.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from conftest import SUITE_LANGUAGE

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
    # Y una que se lee al llamar, no al importar: entra en el inventario por la lectura de arranque
    # de `config.py`. Si faltara, la suite heredaria el idioma de commit de la maquina y los tests
    # del prompt de `local_commit_msg` y de los corpus pasarian o fallarian segun quien los corra.
    assert "LOCAL_DELEGATE_COMMIT_LANGUAGE" in config.ENVIRONMENT_VARIABLES
    # Las dos del idioma (REQ-019, REQ-028): la primera la lee `hook_common.resolve_language` con el
    # entorno inyectado, y la segunda se lee al llamar. Sin registro, la suite heredaria el idioma
    # de quien la corre.
    assert "LOCAL_DELEGATE_LANG" in config.ENVIRONMENT_VARIABLES
    assert "LOCAL_DELEGATE_OUTPUT_LANGUAGE" in config.ENVIRONMENT_VARIABLES


#: Las que la suite fija a propósito en vez de quitarlas (REQ-043), con el valor que deben tener.
def _pinned_by_the_suite(tmp_path: Path) -> dict[str, str]:
    return {"LOCAL_DELEGATE_LANG": SUITE_LANGUAGE, "LOCAL_DELEGATE_LOG_DIR": str(tmp_path)}


def test_the_suite_runs_without_package_variables_defined(tmp_path):
    """Ninguna variable que lea `config` puede estar definida mientras corre la suite...

    ...salvo las que la propia suite fija (REQ-043): el idioma, para que los asserts en español
    valgan en cualquier máquina, y el directorio de datos, para que un hook lanzado como subproceso
    no lea el `language.json` real del usuario. Esas tienen que valer exactamente lo fijado.
    """
    pinned = _pinned_by_the_suite(tmp_path)
    defined = sorted(n for n in config.ENVIRONMENT_VARIABLES if n in os.environ and n not in pinned)
    assert defined == [], (
        f"El entorno de esta máquina se está colando en la suite: {defined}. "
        "La fixture `env_without_package_variables` de conftest.py debería haberlas quitado."
    )
    assert {n: os.environ.get(n) for n in pinned} == pinned


def _variables_read_by_hooks() -> dict[str, set[str]]:
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
                # `env.get("LOCAL_DELEGATE_LANG")` de `resolve_language`, que recibe el entorno
                # inyectado: solo cuenta con nuestro prefijo, que filtra los `.get` de otra cosa.
                is_injected_env_get = (
                    node.func.attr == "get" and isinstance(target, ast.Name) and target.id == "env"
                )
                if (is_environ_get or is_getenv or is_injected_env_get) and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        names.add(first.value)
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
    # Y ve la variable de idioma, que `resolve_language` lee del entorno INYECTADO (`env.get`).
    assert "LOCAL_DELEGATE_LANG" in per_file.get("hook_common.py", set()), per_file

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


def test_hooks_never_name_a_retired_name():
    """REQ-010: desde la 0.38.0 los hooks leen solo los nombres nuevos y ni detectan los viejos.

    Ninguna constante de texto de un hook (variables, rutas, docstrings) puede ser el nombre viejo
    de una variable o un interruptor del registro: si lo fuera, el hook lo estaría leyendo, o
    prometiendo en su documentación algo que ya no hace. Los nombres viejos salen del registro, no
    de una lista a mano.
    """
    from local_delegate import deprecations

    old_names = {e.old for e in deprecations.env_vars() + deprecations.switch_files()}
    # Control positivo: el registro trae los tres nombres que leían los hooks.
    assert len(old_names & {e.old for e in deprecations.switch_files()}) == 1
    assert len(old_names) >= 3, old_names

    hooks = Path(config.__file__).parent / "resources" / "hooks"
    found = {
        f"{file.name}:{node.lineno}:{node.value}"
        for file in sorted(hooks.glob("*.py"))
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(old in node.value for old in old_names)
    }
    assert found == set(), f"un hook nombra un nombre retirado: {sorted(found)}"

    # Y lee los nuevos directamente (control de que el escáner ve las lecturas del bloqueo).
    read = set().union(*_variables_read_by_hooks().values())
    assert {"LD_HOOK_READ_BLOCK", "LD_HOOK_READ_SWITCH_FILE"} <= read, sorted(read)


# --- REQ-018 y plan D7: el idioma del sistema se lee en UN solo sitio ------------------------------

#: Las únicas funciones que pueden mirar el idioma del sistema: la regla y sus dos piezas.
_LANGUAGE_WHITELIST = {
    "hook_common.py": {"resolve_language", "_system_language", "_windows_ui_language"}
}
_SYSTEM_LANGUAGE_VARIABLES = re.compile(r"^(LANG|LANGUAGE|LC_[A-Z]+)$")
_SYSTEM_LANGUAGE_APIS = {
    "GetUserDefaultUILanguage",
    "getlocale",
    "getdefaultlocale",
    "windows_locale",
}


def _system_language_reads(root: Path) -> list[tuple[str, str, int, bool]]:
    """(fichero, qué, línea, dentro de la lista blanca) de cada lectura del idioma del sistema."""
    found = []
    for file in sorted(root.rglob("*.py")):
        if "vendor" in file.parts or "__pycache__" in file.parts:
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"))
        allowed = _LANGUAGE_WHITELIST.get(file.name, set())
        inside: dict[int, bool] = {}
        for func in ast.walk(tree):
            if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef) and func.name in allowed:
                for child in ast.walk(func):
                    inside[id(child)] = True
        for node in ast.walk(tree):
            what = None
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _SYSTEM_LANGUAGE_VARIABLES.match(node.value)
            ):
                what = node.value
            elif isinstance(node, ast.Attribute) and node.attr in _SYSTEM_LANGUAGE_APIS:
                what = node.attr
            if what:
                rel = file.relative_to(root).as_posix()
                found.append((rel, what, node.lineno, inside.get(id(node), False)))
    return found


def test_only_resolve_language_reads_the_system_language():
    """Ningún código del paquete ni de los hooks lee `LANG`, `LC_*`, `LANGUAGE` o la API de idioma
    de Windows fuera de `hook_common.resolve_language` y sus dos piezas.

    Una segunda lectura sería una segunda regla: el CLI y el daemon podrían discrepar del hook, y
    en Windows `LANG` lo pone Git Bash (`en_US.UTF-8`) aunque la interfaz esté en español.
    """
    reads = _system_language_reads(Path(config.__file__).parent)
    # Control: el escáner ve las lecturas legítimas; si no viera ninguna, pasaría en vacío.
    whitelisted = {what for _file, what, _line, ok in reads if ok}
    assert {"LANG", "LC_ALL", "LANGUAGE", "GetUserDefaultUILanguage"} <= whitelisted, whitelisted
    outside = [f"{file}:{line} {what}" for file, what, line, ok in reads if not ok]
    assert outside == [], (
        f"Lecturas del idioma del sistema fuera de `hook_common.resolve_language`: {outside}. "
        "Usa `i18n.current()` (paquete) o `hook_common.resolve_language` (hooks)."
    )
