"""De dónde saca el token del puerto un proceso que no hereda el entorno del usuario.

Existe por Claude Desktop: no pasa su entorno a los MCP que arranca (solo una lista fija de
variables del sistema más el `env` literal de la entrada) y no expande `${VAR}` en
`claude_desktop_config.json` (medido el 2026-10-21, `research-r5`). El puente que lanza Desktop
no ve, por tanto, `LOCAL_DELEGATE_WEB_TOKEN`, y escribir el token en la config es justo lo que se
quiere evitar. En Windows las variables de usuario viven en `HKCU\\Environment`, que es también de
donde las toma el daemon al arrancar desde su tarea programada: leerlas de ahí da el mismo valor
que el daemon sin que nadie lo copie a ningún sitio.

Solo Windows (decisión 11 del plan): en macOS y Linux no hay daemon local para el chat de Desktop,
así que fuera de Windows esto se queda en el entorno del proceso.

El valor nunca se registra ni se imprime: quien llama solo lo pone en una cabecera.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

from . import config

TOKEN_VARIABLE = "LOCAL_DELEGATE_WEB_TOKEN"
_ENVIRONMENT_KEY = "Environment"


def _winreg() -> ModuleType:
    # Import diferido y por función: `winreg` solo existe en Windows, y así la suite puede
    # sustituir el registro entero sin tocar el real.
    return importlib.import_module("winreg")


def read_user_environment(name: str) -> str | None:
    """La variable de usuario `name` tal como está en el registro, o `None` si no hay.

    `None` también fuera de Windows y cuando el valor está vacío: una variable en blanco es el
    mismo «no hay token» que una ausente, y tratarla como token daría un 401 engañoso.
    """
    if sys.platform != "win32":
        return None
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ENVIRONMENT_KEY) as key:
            value, kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if not isinstance(value, str):
        return None
    if kind == winreg.REG_EXPAND_SZ:
        value = winreg.ExpandEnvironmentStrings(value)
    return value.strip() or None


def web_token() -> str:
    """El token del puerto del daemon: primero el registro, luego el entorno del proceso.

    El registro va primero porque es la fuente que no caduca: un proceso lanzado antes de rotar
    el token hereda el valor viejo, mientras que el registro ya tiene el nuevo. Cadena vacía si
    no hay token en ningún sitio (daemon sin token, o variable sin poner).
    """
    return read_user_environment(TOKEN_VARIABLE) or config.WEB_TOKEN
