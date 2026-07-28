"""Comprueba que el paquete **instalado** arranca y responde un handshake MCP.

Por qué existe: el resto del CI instala desde `uv.lock`, y el lock es justo lo que nos ciega. El
2026-07-28 el SDK `mcp` publicó 2.0.0 —que elimina `mcp.server.fastmcp`— y `local-delegate-mcp`
declaraba `mcp>=1.2` sin techo. Toda instalación nueva por `uvx` moría en el import, mientras el
CI seguía verde porque el lock fijaba una 1.x. El fallo llegó por un usuario en otra máquina.

Este script se ejecuta con el intérprete de un entorno donde el paquete se instaló **resolviendo
dependencias libremente**, sin lock. Levanta el server por stdio, le manda `initialize` y exige una
respuesta con `serverInfo`.

El server se lanza contra un backend inexistente **a propósito**: arrancar y responder el handshake
no debe depender de que haya un endpoint OpenAI-compatible vivo, y en CI no lo hay.

Códigos de salida distintos para que un fallo de red no se lea como una regresión de dependencia:

    0  el handshake respondió
    1  el proceso murió en el import  -> regresión de dependencia (lo que este check vigila)
    2  arrancó pero no dio un handshake válido
    3  se quedó colgado
    4  no se pudo ni lanzar el proceso
"""

import json
import os
import subprocess
import sys
import tempfile

TIMEOUT_S = 90

PETICION = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "check-install-handshake", "version": "1"},
    },
}


def _entorno() -> dict:
    env = dict(os.environ)
    # El dashboard pediría un puerto que en CI no interesa (y en local ya está ocupado por el daemon).
    env["LOCAL_DELEGATE_WEB"] = "0"
    # Sin esto intentaría levantar llama-swap, que no existe en el runner.
    env["LOCAL_DELEGATE_AUTOSTART"] = "0"
    # Puerto muerto a propósito: el handshake no debe depender del backend.
    env["LOCAL_DELEGATE_BASE_URL"] = "http://127.0.0.1:59999/v1"
    return env


def main() -> int:
    # cwd fuera del repositorio: si se ejecutara desde la raíz, un `src/` en el path podría hacer
    # que se importe el árbol de fuentes en vez del paquete instalado, que es lo que se quiere probar.
    with tempfile.TemporaryDirectory() as cwd:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "local_delegate"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_entorno(),
                cwd=cwd,
                text=True,
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"FALLO: no se pudo lanzar el proceso: {exc}")
            return 4

        try:
            salida, error = proc.communicate(json.dumps(PETICION) + "\n", timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            print(f"FALLO: el server no respondió el handshake en {TIMEOUT_S}s.")
            return 3

    error = error or ""

    # Un ModuleNotFoundError/ImportError al arrancar es la firma de un major incompatible de una
    # dependencia. Se distingue del resto porque es el único caso que este check existe para cazar.
    if "ModuleNotFoundError" in error or "ImportError" in error:
        print("FALLO: el paquete instalado no importa. Una dependencia rompió su API.")
        print("Suele ser un major nuevo sin techo en `pyproject.toml`.")
        print("--- stderr ---")
        print(error.strip()[-2000:])
        return 1

    for linea in (salida or "").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            mensaje = json.loads(linea)
        except json.JSONDecodeError:
            continue
        info = mensaje.get("result", {}).get("serverInfo")
        if info:
            print(f"OK: handshake respondido por {info.get('name')} (SDK {info.get('version')}).")
            return 0

    print("FALLO: el proceso arrancó pero no devolvió un handshake válido.")
    print(f"returncode: {proc.returncode}")
    print("--- stdout ---")
    print((salida or "(vacío)").strip()[:2000])
    print("--- stderr ---")
    print((error or "(vacío)").strip()[-2000:])
    return 2


if __name__ == "__main__":
    sys.exit(main())
