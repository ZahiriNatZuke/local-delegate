#!/usr/bin/env python3
"""Hook UserPromptSubmit para recordar delegacion solo en intenciones mecanicas claras."""

from __future__ import annotations

import json
import re
import sys

from hook_common import emit, record

_CATEGORIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("summarize", re.compile(r"\b(resum|sintetiz|summary|summarize)\w*\b", re.I)),
    ("extract", re.compile(r"\b(extrae|extraer|extract|campos?|fields?)\b", re.I)),
    ("classify", re.compile(r"\b(clasific|etiquet|classif|label)\w*\b", re.I)),
    ("translate", re.compile(r"\b(traduc|translate)\w*\b", re.I)),
    ("lint", re.compile(r"\b(lint|pytest|test output|salida de (?:tests?|pruebas))\b", re.I)),
    ("boilerplate", re.compile(r"\b(boilerplate|esqueleto|scaffold)\w*\b", re.I)),
)
_HOST_ONLY = re.compile(
    r"\b(arquitect|diseñ|design|investig|research|multi[- ]?fuente|latest|actual(?:iza)?|"
    r"seguridad|security|credencial|secret|deploy|publica|borra|elimina|migraci)\w*\b",
    re.I,
)


def classify(prompt: str) -> str | None:
    if not prompt.strip() or _HOST_ONLY.search(prompt):
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
    category = classify(prompt)
    if category is None:
        record("UserPromptSubmit", suggested=False, prompt_chars=len(prompt))
        return
    context = (
        f"Oportunidad mecanica detectada ({category}). Antes de leer contenido grande, evalua "
        "usar la tool local_* especifica con path. Conserva en Claude cualquier parte que exija "
        "criterio, varias fuentes, tools externas o acciones de riesgo."
    )
    emit("UserPromptSubmit", context, category=category, prompt_chars=len(prompt))


if __name__ == "__main__":
    main()
