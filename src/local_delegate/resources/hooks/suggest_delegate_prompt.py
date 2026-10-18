#!/usr/bin/env python3
"""Hook UserPromptSubmit para recordar delegacion solo en intenciones mecanicas claras."""

from __future__ import annotations

import json
import re
import sys

from hook_common import block_state, context_of, emit, hook_text, record

_CATEGORIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("summarize", re.compile(r"\b(resum|sintetiz|summary|summarize)\w*\b", re.IGNORECASE)),
    ("extract", re.compile(r"\b(extrae|extraer|extract|campos?|fields?)\b", re.IGNORECASE)),
    ("classify", re.compile(r"\b(clasific|etiquet|classif|label)\w*\b", re.IGNORECASE)),
    ("translate", re.compile(r"\b(traduc|translate)\w*\b", re.IGNORECASE)),
    (
        "lint",
        re.compile(r"\b(lint|pytest|test output|salida de (?:tests?|pruebas))\b", re.IGNORECASE),
    ),
    ("boilerplate", re.compile(r"\b(boilerplate|esqueleto|scaffold)\w*\b", re.IGNORECASE)),
)
_HOST_ONLY = re.compile(
    r"\b(arquitect|diseñ|design|investig|research|multi[- ]?fuente|latest|actual(?:iza)?|"
    r"seguridad|security|credencial|secret|deploy|publica|borra|elimina|migraci)\w*\b",
    re.IGNORECASE,
)


# Claude Code tambien dispara UserPromptSubmit con mensajes que NO escribio el usuario: el informe
# de un subagente, el aviso de que termino una tarea en segundo plano, un mensaje de otra sesion.
# El payload no trae ningun campo de origen (capturado el 2026-09-22 con Claude Code 2.1.280:
# solo cwd, hook_event_name, permission_mode, prompt_id, session_id y transcript_path); lo unico
# que los distingue es como empieza `prompt`. Sin este filtro, un informe que dice «summary»
# recibia el aviso de delegar, y cada uno contaba como un prompt mas en la telemetria.
_SYSTEM_EVENT = re.compile(
    r"\A\s*(?:Another Claude session sent a message:\s*)?"
    r"<(?:task-notification|agent-message|cross-session-message|system-reminder)\b"
)


def is_system_event(prompt: str) -> bool:
    return bool(_SYSTEM_EVENT.match(prompt))


def classify(prompt: str) -> str | None:
    if not prompt.strip() or is_system_event(prompt) or _HOST_ONLY.search(prompt):
        return None
    for category, pattern in _CATEGORIES:
        if pattern.search(prompt):
            return category
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    prompt = str(payload.get("prompt") or "")
    if is_system_event(prompt):
        # Ni aviso ni telemetria: no es un prompt, y contarlo inflaria el total del panel.
        return
    # Sesión, versión y estado del bloqueo en TODO evento, como los hooks de lectura: sin sesión
    # no se puede atribuir un evento a su corrida, y el banco de `scripts/` valida cada corrida por
    # aquí.
    common = {**context_of(payload, __file__), "block": block_state()}
    category = classify(prompt)
    if category is None:
        record("UserPromptSubmit", suggested=False, prompt_chars=len(prompt), **common)
        return
    context = hook_text("prompt.mechanical", category=category)
    emit("UserPromptSubmit", context, category=category, prompt_chars=len(prompt), **common)


if __name__ == "__main__":
    main()
