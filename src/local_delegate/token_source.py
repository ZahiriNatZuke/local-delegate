"""De dónde saca sus credenciales un proceso que no hereda el entorno del usuario.

Dos credenciales: la clave del backend (`LOCAL_DELEGATE_API_KEY`) y el token del puerto del daemon
(`LOCAL_DELEGATE_WEB_TOKEN`). El orden es el mismo para todos los consumidores: primero el entorno
del proceso y, si falta, la fuente del sistema. El valor nunca se registra ni se imprime: quien
llama solo lo pone en una cabecera.

**Windows**: el registro (`HKCU\\Environment`), solo para el token. Existe por Claude Desktop: no
pasa su entorno a los MCP que arranca (solo una lista fija de variables del sistema más el `env`
literal de la entrada) y no expande `${VAR}` en `claude_desktop_config.json` (medido el
2026-10-21, `research-r5`). El puente que lanza Desktop no ve, por tanto, la variable, y escribir
el token en la config es justo lo que se quiere evitar. Las variables de usuario viven en el
registro, que es también de donde las toma el daemon al arrancar desde su tarea programada:
leerlas de ahí da el mismo valor que el daemon sin que nadie lo copie a ningún sitio. Para el
puente el registro va **antes** que el entorno (ver `web_token`).

**macOS**: el Llavero, con `security find-generic-password` (issue #409). La decisión 11 del plan
dejaba esto solo en Windows con la premisa «en macOS no hay daemon local»; no se cumple en la
topología Remote-backend (Mac → PC), donde la Mac tiene su LaunchAgent y su MCP stdio. Ahí el MCP
solo veía la clave si heredaba el entorno de un shell: Claude Desktop abierto desde el Dock, o una
sesión de Code cuyo entorno de login no se pudo resolver, arrancaban sin ella y el backend daba
401 en silencio. El Llavero es el análogo de `HKCU\\Environment`: la clave no se copia a ningún
sitio. Servicios: `local-delegate-remote` (el que ya documentaba la wiki) y
`local-delegate-web-token`.

La consulta al Llavero vive en `keychain` (hoja sin imports del paquete, para que `config` la use
sin ciclo): solo si falta la variable, en diferido (nunca al importar), con tope de tiempo —un
Llavero bloqueado puede dejar a `security` esperando un diálogo, y colgar el MCP es peor que un
401— y una sola vez por proceso, también cuando no hay nada.

**Linux**: solo el entorno del proceso.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

from . import config, keychain

TOKEN_VARIABLE = "LOCAL_DELEGATE_WEB_TOKEN"
API_KEY_VARIABLE = "LOCAL_DELEGATE_API_KEY"
_ENVIRONMENT_KEY = "Environment"

#: Servicio del Llavero de cada credencial (cuenta: el usuario, como en `-a "$USER"`). La consulta
#: vive en `keychain`, una hoja sin imports del paquete que `config` también usa sin ciclo.
KEYCHAIN_SERVICES = {
    API_KEY_VARIABLE: keychain.API_KEY_SERVICE,
    TOKEN_VARIABLE: keychain.WEB_TOKEN_SERVICE,
}

SOURCE_ENVIRONMENT = keychain.SOURCE_ENVIRONMENT
SOURCE_KEYCHAIN = keychain.SOURCE_KEYCHAIN
is_macos = keychain.is_macos
read_keychain = keychain.read


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


def _environment_raw(name: str) -> str:
    return config.API_KEY if name == API_KEY_VARIABLE else config.WEB_TOKEN


def environment_value(name: str) -> str:
    """Lo que trae el entorno del proceso para `name`, o cadena vacía si no trae nada usable.

    En blanco o una referencia `${VAR}` sin expandir cuentan como ausente (`keychain.usable`).
    """
    return keychain.usable(_environment_raw(name))


def resolve(name: str) -> tuple[str, str | None]:
    """`(valor, fuente)` de la credencial `name`: entorno del proceso y, si falta, el Llavero.

    La fuente es `SOURCE_ENVIRONMENT`, `SOURCE_KEYCHAIN` o `None` (cadena vacía: no hay). El
    registro de Windows no entra aquí: solo lo usa el puente, por `web_token`.
    """
    return keychain.credential(_environment_raw(name), KEYCHAIN_SERVICES[name])


def api_key() -> str:
    """La clave del backend, o cadena vacía (lo mismo que pone `config.auth_headers`)."""
    return resolve(API_KEY_VARIABLE)[0]


def daemon_token() -> str:
    """El token del puerto tal como lo usan el propio daemon y sus clientes internos."""
    return resolve(TOKEN_VARIABLE)[0]


def web_token() -> str:
    """El token del puerto del daemon para el puente de Desktop.

    En Windows, primero el registro y luego el entorno: el registro es la fuente que no caduca (un
    proceso lanzado antes de rotar el token hereda el valor viejo, mientras que el registro ya tiene
    el nuevo). En el resto, el orden común: entorno y, en macOS, el Llavero. Cadena vacía si no hay
    token en ningún sitio (daemon sin token, o variable sin poner).
    """
    if sys.platform == "win32":
        return read_user_environment(TOKEN_VARIABLE) or config.WEB_TOKEN
    return daemon_token()
