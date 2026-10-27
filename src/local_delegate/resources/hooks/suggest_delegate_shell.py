#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Bash|PowerShell) para local-delegate.

Existe porque cerrar un camino no cierra los de al lado. El hook de `Read` puede bloquear la
lectura completa de un documento grande, pero `cat informe.md` hace exactamente lo mismo y no
pasa por ahí: la conducta se mueve al comando de shell, la adopción medida sube y no se ahorra un
solo token. La regla se declara sobre la **superficie de lectura**, no sobre una tool.

**Falso negativo antes que falso positivo.** Solo se bloquean formas simples e inequívocas de
volcar un fichero entero: `cat X`, `more X`, `Get-Content X` y, en PowerShell, `type X` y `gc X`.
Cualquier otra cosa —una tubería, una redirección, dos comandos encadenados, una sustitución,
varios ficheros, un flag, o `head X`, que solo saca diez líneas— **no se bloquea**, y se registra
con su vía y su alcance para tener el denominador. Bloquear un comando mal parseado no es un
consejo malo: es impedir algo que el usuario pidió, y se apaga el primer día.

Qué lee cada comando lo decide `read_classifier.py` (REQ-019), el mismo módulo que usa el mod de
lectura de la entrega por plugin: este hook no lleva reglas de lectura propias.

Se apaga igual que el de lectura: `LD_HOOK_READ_BLOCK=0`, un backend que no responde, o el
interruptor general `LD_HOOK_ENABLED=0`. Sin dependencias (stdlib únicamente).
"""

from __future__ import annotations

import json
import os
import sys

import read_classifier
from hook_common import (
    already_recorded,
    backend_available,
    backend_down,
    block_state,
    context_of,
    cooled_model,
    deny,
    hook_text,
    mod_decision_fields,
    mod_record_id,
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
    step_aside_for_read_mod,
)


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

    tool_name = str(payload.get("tool_name") or "")
    if step_aside_for_read_mod(payload, __file__, category="shell", route="shell"):
        return

    found = read_classifier.classify_shell(command, tool_name)
    access = read_classifier.primary(found)
    common = {
        "category": "shell",
        "route": "shell",
        "block": block_state(),
        **context_of(payload, __file__),
        "via": access.via if access else "none",
        "scope": access.scope if access else "unclassifiable",
    }

    path = read_classifier.simple_whole_dump(found)
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
    if backend_down():
        record("PreToolUse", suggested=False, reason="backend_down", **common)
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


def record_decision(entry: dict) -> None:
    """`hook record-read` de una vía de shell: la línea que habría escrito este hook, con la
    decisión del mod (`hook_common.mod_decision_fields`)."""
    # El mismo `id` por todas las vias del mod: una decision ya escrita no se escribe otra vez.
    record_id = mod_record_id(entry)
    if record_id and already_recorded(record_id):
        return
    path = entry.get("path") if isinstance(entry.get("path"), str) else None
    payload = {"session_id": entry.get("session_id")}
    fields: dict = {
        "category": "shell",
        "route": "shell",
        "block": block_state(),
        **context_of(payload, __file__),
        "via": str(entry.get("via") or "none"),
        "scope": str(entry.get("scope") or "unclassifiable"),
        **mod_decision_fields(entry.get("decision")),
    }
    if path:
        fields["ext"] = extension_of(path)
        if isinstance(entry.get("bytes"), int):
            fields["size_kb"] = round(entry["bytes"] / 1024, 1)
        fields["path_sha"] = path_digest(path)
    if fields.get("blocked") and path:
        fields["id"] = record_id or new_id()
        record_block(fields["id"], path)
    elif record_id:
        fields["id"] = record_id
    record("PreToolUse", **fields)


if __name__ == "__main__":
    main()
