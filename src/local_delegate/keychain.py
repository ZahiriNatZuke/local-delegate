"""Lectura de credenciales del Llavero de macOS (issue #409). Hoja: no importa nada del paquete.

Es hoja a propósito: la usan `config` (para `auth_headers` y `web_auth_headers`) y `token_source`
(que importa `config`), y si viviera en cualquiera de los dos habría un ciclo de imports.

`credential(valor_del_entorno, servicio)` aplica el orden común a todos los consumidores: primero
lo que trae el entorno del proceso y, si falta, el Llavero. Un valor en blanco o una referencia
`${VAR}` que el cliente no expandió cuentan como ausentes: Claude Code pasa `${VAR}` tal cual si
no tiene la variable (`review-spec.md` §13), que es la entrada que escribe
`install --api-key-env`, y tomarla por clave taparía el Llavero con un 401 seguro.

La consulta es `/usr/bin/security find-generic-password -a <usuario> -s <servicio> -w`: solo en
macOS, solo si falta la variable, en diferido (nunca al importar), con tope de tiempo —un Llavero
bloqueado puede dejar a `security` esperando un diálogo, y colgar el MCP es peor que un 401— y una
sola vez por proceso, también cuando no hay nada. El valor nunca se registra ni se imprime.
"""

from __future__ import annotations

import getpass
import re
import subprocess
import sys
import threading

#: Servicio de la clave del backend (el que ya documentaba la wiki).
API_KEY_SERVICE = "local-delegate-remote"
#: Servicio del token del puerto del daemon.
WEB_TOKEN_SERVICE = "local-delegate-web-token"
#: Servicio del token del puerto del daemon de la OTRA máquina (la del backend), para su turno.
REMOTE_WEB_TOKEN_SERVICE = "local-delegate-remote-web-token"
#: Ruta absoluta: launchd da a las apps gráficas un PATH mínimo y no se depende de él.
SECURITY_COMMAND: tuple[str, ...] = ("/usr/bin/security",)
#: Tope de la consulta. Un Llavero desbloqueado responde en milisegundos.
TIMEOUT_SECONDS = 3.0

SOURCE_ENVIRONMENT = "environment"
SOURCE_KEYCHAIN = "keychain"

_UNEXPANDED_REFERENCE = re.compile(
    r"^\s*(?:\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}|\{env:[A-Za-z_][A-Za-z0-9_]*\})\s*$"
)

# Servicio → valor (o `None`, «no hay»). Una consulta por proceso: un MCP stdio pide la cabecera
# en cada llamada, y lanzar `security` cada vez sería lento y, con el Llavero bloqueado, un
# diálogo detrás de otro.
_CACHE: dict[str, str | None] = {}
_LOCK = threading.Lock()


def is_macos() -> bool:
    return sys.platform == "darwin"


def usable(raw: str | None) -> str:
    """`raw` si sirve como credencial; cadena vacía si está en blanco o es `${VAR}` sin expandir."""
    if not raw or not raw.strip() or _UNEXPANDED_REFERENCE.match(raw):
        return ""
    return raw


def _query(service: str) -> str | None:
    try:
        account = getpass.getuser()
    except Exception:  # sin usuario resoluble no hay cuenta que pedir
        return None
    argv = [*SECURITY_COMMAND, "find-generic-password", "-a", account, "-s", service, "-w"]
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        # No arranca, no termina a tiempo (Llavero bloqueado) o argumentos inválidos: «no hay».
        # No se registra nada: no aporta y así ningún camino puede acabar escribiendo la salida.
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def read(service: str) -> str | None:
    """El valor del servicio en el Llavero de macOS, o `None`. Una consulta por proceso."""
    if not is_macos():
        return None
    with _LOCK:
        if service not in _CACHE:
            _CACHE[service] = _query(service)
        return _CACHE[service]


def credential(environment: str | None, service: str) -> tuple[str, str | None]:
    """`(valor, fuente)`: el del entorno si sirve y, si no, el del Llavero; `("", None)` si no hay."""
    value = usable(environment)
    if value:
        return value, SOURCE_ENVIRONMENT
    stored = read(service)
    if stored:
        return stored, SOURCE_KEYCHAIN
    return "", None
