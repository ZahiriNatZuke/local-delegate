#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Bash|PowerShell) para local-delegate.

Existe porque cerrar un camino no cierra los de al lado. El hook de `Read` puede bloquear la
lectura completa de un documento grande, pero `cat informe.md` hace exactamente lo mismo y no
pasa por ahí: la conducta se mueve al comando de shell, la adopción medida sube y no se ahorra un
solo token. La regla se declara sobre la **superficie de lectura**, no sobre una tool.

**Falso negativo antes que falso positivo.** Solo se reconocen formas simples e inequívocas de
volcar un fichero entero: `cat X`, `type X`, `more X`, `Get-Content X`, `gc X` y
`head X` sin recorte. Cualquier otra cosa —una tubería, una redirección, dos comandos encadenados,
una sustitución, varios ficheros, o un flag que ya acota la lectura— **no se bloquea**, y se
registra para tener el denominador. Bloquear un comando mal parseado no es un consejo malo: es
impedir algo que el usuario pidió, y se apaga el primer día.

Se apaga igual que el de lectura: `LD_HOOK_READ_BLOCK=0`, un backend que no responde, o el
interruptor general `LD_HOOK_ENABLED=0`. Sin dependencias (stdlib únicamente).
"""

from __future__ import annotations

import json
import os
import shlex
import sys

from hook_common import (
    backend_available,
    block_state,
    context_of,
    cooled_model,
    deny,
    hook_text,
    new_id,
    path_digest,
    record,
    record_block,
    summary_model,
)
from suggest_delegate_read import (
    PROSE_EXTENSIONS,
    block_on,
    extension_of,
    is_enabled,
)

#: Verbos que vuelcan un fichero entero. El valor es cuántas palabras ocupa el verbo.
VERBS = {
    "cat": 1,
    "type": 1,
    "more": 1,
    "get-content": 1,
    "gc": 1,
    "head": 1,
}

#: Cualquiera de estos convierte el comando en algo que este hook no entiende, y lo que no se
#: entiende no se bloquea.
METACHARACTERS = ("|", ">", "<", "&", ";", "`", "$(", "&&", "||", "\n")

#: Flags que ya acotan la lectura: quien los usa sabe qué trozo quiere, igual que un `offset`.
BOUNDING_FLAGS = {
    "-n",
    "-c",
    "-totalcount",
    "-tail",
    "-first",
    "-last",
    "-head",
    "-skip",
}


def split_words(command: str) -> list[str] | None:
    """Las palabras del comando, o `None` si no se puede leer con seguridad."""
    if any(meta in command for meta in METACHARACTERS):
        return None
    try:
        # `posix=False` conserva las comillas, que es lo que hace PowerShell; se quitan después.
        words = shlex.split(command, posix=False)
    except ValueError:
        return None
    return [p.strip("\"'") for p in words if p.strip()] or None


def whole_dump_path(command: str) -> str | None:
    """La ruta que este comando vuelca entera, o `None` si no es uno de esos comandos.

    Es deliberadamente estrecho. Todo lo que no encaje exactamente en «verbo + una ruta» sale por
    `None`, que es el lado que deja pasar la lectura.
    """
    words = split_words(command)
    if not words:
        return None

    lowered = [p.lower() for p in words]
    for verb, length in VERBS.items():
        if " ".join(lowered[:length]) == verb:
            rest = words[length:]
            break
    else:
        return None

    if len(rest) != 1:
        # Ni cero (un `cat` que lee de la entrada estándar) ni dos o más (varios ficheros, o un
        # flag). Con un flag que acota, además, la lectura ya es intencionada.
        return None
    if rest[0].lower() in BOUNDING_FLAGS or rest[0].startswith("-"):
        return None
    return rest[0]


def main() -> None:
    if not is_enabled():
        return

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not command.strip():
        return

    common = {
        "category": "shell",
        "route": "shell",
        "block": block_state(),
        **context_of(payload, __file__),
    }

    path = whole_dump_path(command)
    if path is None:
        # Se cuenta igual: sin el denominador no se sabe cuánta lectura se va por aquí, y esa era
        # justo la pregunta que la cuarta medición no pudo responder.
        record("PreToolUse", suggested=False, reason="not_a_dump", **common)
        return

    # Absoluta con el `cwd` de la sesión (revisión del plan, B2): `cat docs/x.md` trae una ruta
    # relativa, y el daemon —otro proceso, otro directorio— la resolvería contra el suyo. Con la
    # relativa, la huella de la nota no casaba con la de la delegación y el bloqueo no se contaba
    # como aceptado.
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(str(payload.get("cwd") or os.getcwd()), path))

    ext = extension_of(path)
    try:
        suggest_kb = float(os.environ.get("LD_HOOK_READ_SUGGEST_KB", "8"))
        size_kb = os.path.getsize(path) / 1024
    except (OSError, ValueError):
        record("PreToolUse", suggested=False, ext=ext, reason="no_file", **common)
        return

    common = {**common, "ext": ext, "size_kb": round(size_kb, 1), "path_sha": path_digest(path)}

    if ext not in PROSE_EXTENSIONS:
        record("PreToolUse", suggested=False, reason="not_prose", **common)
        return
    if size_kb <= suggest_kb:
        record("PreToolUse", suggested=False, reason="small", **common)
        return
    if not block_on():
        record("PreToolUse", suggested=False, reason="block_off", **common)
        return
    if not backend_available():
        record("PreToolUse", suggested=False, reason="backend_missing", **common)
        return
    if cooled_model(summary_model(int(size_kb * 1024))):
        record("PreToolUse", suggested=False, reason="model_cooled", **common)
        return

    block_id = new_id()
    record_block(block_id, path)
    # La ruta que se ofrece es la absoluta: con la relativa, el daemon la resolvería contra su
    # propio directorio y no encontraría el fichero.
    deny(
        "PreToolUse",
        hook_text("shell.block", size_kb=f"{size_kb:.0f}", path=path),
        reason="large_prose",
        id=block_id,
        **common,
    )


if __name__ == "__main__":
    main()
