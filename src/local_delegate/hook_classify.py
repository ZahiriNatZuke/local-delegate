"""`hook classify`'s answer, in a module that imports nothing of the hook machinery.

`hook_entry` (the CLI and the daemon's `POST /api/hook/classify`) and `codex_reads` (the Codex read
hook) both need it. It lives here so that `codex_reads` does not import `hook_entry`, which imports
`codex_hooks`, which imports `codex_reads`: that cycle is what CodeQL's `py/cyclic-import` flagged.
`hook_entry.classify_text` stays, as a lazy wrapper of this one.
"""

from __future__ import annotations


def classify_text(payload: object, environ) -> str:
    """La respuesta de `hook classify`, el JSON tal cual sale por stdout (sin el salto final).

    La única implementación: la usan el CLI (con `os.environ`) y el endpoint del daemon
    `POST /api/hook/classify` (con el entorno que manda el mod, `CLASSIFY_ENV`). No lee
    `os.environ` cuando le pasan otro entorno ni lo toca: el daemon atiende peticiones a la vez.
    Importa el clasificador como módulo del paquete, sin tocar `sys.path` (en el daemon, el
    `sys.path` es de todos).
    """
    import json

    from . import read_switch
    from .resources.hooks import hook_common, read_classifier

    if not isinstance(payload, dict):
        payload = {}
    if read_switch.enabled(environ=environ):
        state = hook_common.block_state(environ)
    else:
        state = "inactive"
    if state == "on" and hook_common.backend_down(environ):
        # Corte por backend inalcanzable (issue #436): el mod de lectura solo actúa con `on`, así
        # que con este valor deja pasar la lectura sin resumir ni avisar, igual que con el bloqueo
        # apagado. Sin tocar el mod: la condición vive aquí, en una sola implementación.
        state = "backend_down"
    return json.dumps(read_classifier.classify(payload, state, environ), ensure_ascii=False)
