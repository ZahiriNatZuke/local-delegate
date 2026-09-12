#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Bash|PowerShell) para local-delegate.

Existe porque cerrar un camino no cierra los de al lado. El hook de `Read` puede bloquear la
lectura completa de un documento grande, pero `cat informe.md` hace exactamente lo mismo y no
pasa por ahí: la conducta se mueve al comando de shell, la adopción medida sube y no se ahorra un
solo token. La regla se declara sobre la **superficie de lectura**, no sobre una tool.

**Falso negativo antes que falso positivo.** Solo se reconocen formas simples e inequívocas de
volcar un fichero entero: `cat X`, `type X`, `more X`, `Get-Content X`, `gc X`, `rtk read X` y
`head X` sin recorte. Cualquier otra cosa —una tubería, una redirección, dos comandos encadenados,
una sustitución, varios ficheros, o un flag que ya acota la lectura— **no se bloquea**, y se
registra para tener el denominador. Bloquear un comando mal parseado no es un consejo malo: es
impedir algo que el usuario pidió, y se apaga el primer día.

Se apaga igual que el de lectura: `LD_HOOK_READ_BLOQUEAR=0`, un backend que no responde, o el
interruptor general `LD_HOOK_ENABLED=0`. Sin dependencias (stdlib únicamente).
"""

from __future__ import annotations

import json
import os
import shlex
import sys

from hook_common import (
    anotar_bloqueo,
    backend_disponible,
    contexto_de,
    deny,
    nuevo_id,
    record,
)
from suggest_delegate_read import (
    EXTENSIONES_DE_PROSA,
    bloqueo_encendido,
    esta_encendido,
    extension_de,
)

#: Verbos que vuelcan un fichero entero. El valor es cuántas palabras ocupa el verbo.
VERBOS = {
    "cat": 1,
    "type": 1,
    "more": 1,
    "get-content": 1,
    "gc": 1,
    "head": 1,
    "rtk read": 2,
}

#: Cualquiera de estos convierte el comando en algo que este hook no entiende, y lo que no se
#: entiende no se bloquea.
METACARACTERES = ("|", ">", "<", "&", ";", "`", "$(", "&&", "||", "\n")

#: Flags que ya acotan la lectura: quien los usa sabe qué trozo quiere, igual que un `offset`.
FLAGS_QUE_ACOTAN = {
    "-n",
    "-c",
    "-totalcount",
    "-tail",
    "-first",
    "-last",
    "-head",
    "-skip",
}


def trocear(comando: str) -> list[str] | None:
    """Las palabras del comando, o `None` si no se puede leer con seguridad."""
    if any(meta in comando for meta in METACARACTERES):
        return None
    try:
        # `posix=False` conserva las comillas, que es lo que hace PowerShell; se quitan después.
        palabras = shlex.split(comando, posix=False)
    except ValueError:
        return None
    return [p.strip("\"'") for p in palabras if p.strip()] or None


def fichero_volcado_entero(comando: str) -> str | None:
    """La ruta que este comando vuelca entera, o `None` si no es uno de esos comandos.

    Es deliberadamente estrecho. Todo lo que no encaje exactamente en «verbo + una ruta» sale por
    `None`, que es el lado que deja pasar la lectura.
    """
    palabras = trocear(comando)
    if not palabras:
        return None

    minusculas = [p.lower() for p in palabras]
    for verbo, largo in VERBOS.items():
        if " ".join(minusculas[:largo]) == verbo:
            resto = palabras[largo:]
            break
    else:
        return None

    if len(resto) != 1:
        # Ni cero (un `cat` que lee de la entrada estándar) ni dos o más (varios ficheros, o un
        # flag). Con un flag que acota, además, la lectura ya es intencionada.
        return None
    if resto[0].lower() in FLAGS_QUE_ACOTAN or resto[0].startswith("-"):
        return None
    return resto[0]


def main() -> None:
    if not esta_encendido():
        return

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    comando = (payload.get("tool_input") or {}).get("command")
    if not isinstance(comando, str) or not comando.strip():
        return

    comun = {"category": "shell", "camino": "shell", **contexto_de(payload, __file__)}

    ruta = fichero_volcado_entero(comando)
    if ruta is None:
        # Se cuenta igual: sin el denominador no se sabe cuánta lectura se va por aquí, y esa era
        # justo la pregunta que la cuarta medición no pudo responder.
        record("PreToolUse", suggested=False, motivo="no_es_volcado", **comun)
        return

    ext = extension_de(ruta)
    try:
        suggest_kb = float(os.environ.get("LD_HOOK_READ_SUGGEST_KB", "8"))
        size_kb = os.path.getsize(ruta) / 1024
    except (OSError, ValueError):
        record("PreToolUse", suggested=False, ext=ext, motivo="sin_fichero", **comun)
        return

    comun = {**comun, "ext": ext, "size_kb": round(size_kb, 1)}

    if ext not in EXTENSIONES_DE_PROSA:
        record("PreToolUse", suggested=False, motivo="no_es_prosa", **comun)
        return
    if size_kb <= suggest_kb:
        record("PreToolUse", suggested=False, motivo="pequeno", **comun)
        return
    if not bloqueo_encendido():
        record("PreToolUse", suggested=False, motivo="bloqueo_apagado", **comun)
        return
    if not backend_disponible():
        record("PreToolUse", suggested=False, motivo="backend_ausente", **comun)
        return

    identificador = nuevo_id()
    anotar_bloqueo(identificador, ruta)
    deny(
        "PreToolUse",
        f"Este comando vuelca {size_kb:.0f} KB de prosa al contexto. Pasalo por una tool local "
        f'con `path="{ruta}"`: `local_summarize` para el contenido, `local_extract` para campos '
        "concretos.\n\n"
        "Si necesitas el texto literal, pide solo el trozo que te hace falta —`sed -n`, "
        "`head -n`, `Get-Content -TotalCount`— que no se bloquean.",
        motivo="prosa_grande",
        id=identificador,
        **comun,
    )


if __name__ == "__main__":
    main()
