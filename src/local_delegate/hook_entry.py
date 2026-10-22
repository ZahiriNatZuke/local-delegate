"""`hook <nombre>`: los hooks de la entrega por plugin, en proceso y sin cargar el servidor (REQ-003).

El plugin declara cada hook como `<python del entorno de uv tool> -I -m local_delegate.hook <nombre>`
(vía B de T0, `evidence/T0.md`); `local-delegate hook <nombre>` llega aquí por el mismo camino. Lo
que corre es **el mismo script** de `resources/hooks/` que usa la entrega por settings, ejecutado en
este proceso con `runpy` y con su ruta empaquetada como `__file__`: así la huella de telemetría
(`hook_common.version_de`) es idéntica en las dos entregas y la serie de la ventana P-4 no se corta.

Tres reglas, y las tres existen porque Claude Code bloquea el prompt o la tool con el código 2:

- un nombre desconocido sale con 0 y sin texto (un plugin más nuevo que el paquete);
- cualquier fallo sale con 0 y deja una línea en `LOG_DIR/hook-failures.jsonl`, solo con el tipo;
- `local_delegate.hook` envuelve todo esto y sale siempre con 0.

Con la capa «activo» del hook de lectura apagada, `read`, `mcp-read` y `shell` salen después de
importar solo `read_switch`: en la entrega por plugin esas entradas van siempre declaradas.

Dos subcomandos más no son hooks de `hooks.json`: los llama el mod de lectura por `$.process.run`
(plan, Ola 5, «Contrato de `hook classify`»):

- `hook classify`: stdin, la entrada de un hook `PreToolUse` (`tool_name`, `tool_input`, `cwd`,
  `session_id`); stdout, `{"kind", "path", "scope", "bytes", "range", "via", "read_switch"}` de
  `read_classifier.classify`. `hook classify --list-tools` da la lista JSON de tools que pueden
  leer o escribir (`mcp__*` es un prefijo).
- `hook record-read`: stdin, la salida de `classify` más `decision` y `session_id`; escribe en la
  telemetría de los hooks la misma línea que habría escrito el hook de esa vía, más `decision` y
  `source: "mod"` (`hook_common.MOD_DECISIONS`). No escribe nada en stdout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Nombre del hook → (script de `resources/hooks/`, ¿depende de la capa «activo» de lectura?).
#: Es el contrato con `hooks.json` del plugin (decisión 2 del plan).
HOOKS: dict[str, tuple[str, bool]] = {
    "prompt": ("suggest_delegate_prompt.py", False),
    "record-call": ("record_call.py", False),
    "read": ("suggest_delegate_read.py", True),
    "mcp-read": ("suggest_delegate_read.py", True),
    "shell": ("suggest_delegate_shell.py", True),
}

#: Subcomandos del mod de lectura (no son hooks de `hooks.json`). Salen con 0 pase lo que pase.
COMMANDS = ("classify", "record-read")

#: Opción de `classify` que lista las tools en vez de clasificar.
LIST_TOOLS_FLAG = "--list-tools"

#: Log de fallos de los hooks, en `LOG_DIR`. Una línea por fallo: hora, hook y tipo de excepción.
FAILURE_LOG = "hook-failures.jsonl"

#: Tope del log de fallos: pasado este tamaño no se escribe más (un hook roto en bucle no llena
#: el disco; con una línea ya se sabe que falla).
FAILURE_LOG_MAX_BYTES = 256 * 1024


def hooks_dir() -> Path:
    """La carpeta de los scripts empaquetados (la misma que copia la entrega por settings)."""
    return Path(__file__).resolve().parent / "resources" / "hooks"


def _utf8_streams() -> None:
    """stdin y stdout en UTF-8: con `-I` Python ignora `PYTHONUTF8` y `PYTHONIOENCODING`, y en una
    tubería de Windows saldría cp1252. Claude Code manda y espera UTF-8; un carácter fuera de esa
    tabla tumbaba el aviso entero."""
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            continue  # un flujo ya leído o cerrado: se queda como estaba


def _run_script(script: Path, args: list[str]) -> None:
    """Corre el script como `__main__`, como lo correría `python <script> <args>`."""
    import runpy

    saved_argv, saved_path = sys.argv, list(sys.path)
    sys.argv = [str(script), *args]
    # Los scripts importan `hook_common` (y `shell`, `suggest_delegate_read`) como módulos sueltos.
    sys.path.insert(0, str(script.parent))
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
    finally:
        sys.argv, sys.path[:] = saved_argv, saved_path


def _load_hook_module(name: str):
    """Un módulo suelto de `resources/hooks/` (como lo importan los scripts entre sí)."""
    import importlib

    folder = str(hooks_dir())
    if folder not in sys.path:
        sys.path.insert(0, folder)
    return importlib.import_module(name)


def _classify(args: list[str]) -> None:
    import json

    classifier = _load_hook_module("read_classifier")
    if LIST_TOOLS_FLAG in args:
        print(json.dumps(classifier.list_tools()))
        return
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    from . import read_switch

    if read_switch.enabled(environ=os.environ):
        state = _load_hook_module("hook_common").block_state()
    else:
        state = "inactive"
    print(json.dumps(classifier.classify(payload, state), ensure_ascii=False))


def _record_read() -> None:
    import json

    entry = json.load(sys.stdin)
    if not isinstance(entry, dict):
        return
    via = str(entry.get("via") or "")
    script = "suggest_delegate_shell" if via.startswith("shell_") else "suggest_delegate_read"
    _load_hook_module(script).record_decision(entry)


def _log_failure(name: str, exc: BaseException) -> None:
    """Best-effort: ni rutas ni mensajes, que pueden llevar contenido del usuario; solo el tipo."""
    try:
        import json
        from datetime import UTC, datetime

        from .read_switch import log_dir

        target = log_dir() / FAILURE_LOG
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > FAILURE_LOG_MAX_BYTES:
            return
        line = {"ts": datetime.now(UTC).isoformat(), "hook": name, "error": type(exc).__name__}
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(line) + "\n")
    except Exception:
        # un hook nunca lanza; perder la línea es el mal menor
        pass


def main(argv: list[str]) -> int:
    """Despacha un hook. Devuelve siempre 0 y no lanza (salvo `KeyboardInterrupt` del todo)."""
    name = argv[0] if argv else ""
    if name in COMMANDS:
        try:
            _utf8_streams()
            if name == "classify":
                _classify(argv[1:])
            else:
                _record_read()
        except (Exception, SystemExit) as exc:
            _log_failure(name, exc)
        return 0
    entry = HOOKS.get(name)
    if entry is None:
        return 0
    script, gated = entry
    try:
        args: list[str] = []
        if gated:
            from . import read_switch

            if not read_switch.enabled(environ=os.environ):
                return 0
            # El script mira `--enabled` o la variable; la capa ya está decidida aquí.
            args = [read_switch.ENABLED_FLAG]
        _utf8_streams()
        _run_script(hooks_dir() / script, args)
    except (Exception, SystemExit) as exc:  # incluye SystemExit(2): nunca bloquear
        _log_failure(name, exc)
    return 0
