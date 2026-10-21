"""Banco de pruebas con `claude -p` (SDD subagente-lector-local, spec v2).

Lo comparten el control instalado (tarea 4) y el experimento de adopción (tarea 5). Todo lo que
aquí parece exceso de cuidado salió de una revisión adversarial que encontró la forma de que el
experimento midiera el entorno en vez del producto (`review.md`):

- **Entorno por `--settings`, no por variables del proceso.** El bloque `env` del
  `settings.json` del usuario pisaría a las del proceso; `--settings` tiene más precedencia. Y el
  control de precedencia al inicio de cada tanda lo comprueba en vez de suponerlo.
- **El interruptor global de apagado nunca se toca**: afecta a las sesiones del usuario y dispara
  el criterio de retirada del bloqueo. Se aísla con `LD_HOOK_READ_SWITCH_FILE` a una ruta que no
  existe.
- **Telemetría propia de cada corrida**, para atribuir cada evento a su corrida sin cruces.
- **La evidencia sale del transcript**, nunca de lo que el modelo diga que hizo.

El formato del transcript es interno de Claude Code y cambia entre versiones: si falta algo que
se espera, se lanza `FormatoDesconocido` en vez de devolver ceros.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
TOOL_PRINCIPAL = "mcp__local-delegate__local_summarize"
LOCAL_PREFIX = "mcp__local-delegate__local_"
#: Resultado de Bash por encima del cual contar como «volcado» si el comando nombra el fichero.
DUMP_THRESHOLD = 2048
#: Marcas del texto de los bloqueos de nuestros hooks (Read y Shell), en los dos idiomas de
#: `hook_common.HOOK_TEXTS` (`read.block` y `shell.block`).
BLOCK_MARKERS = (
    "y es prosa",
    "de prosa al contexto",
    "and it is prose",
    "of prose into the context",
)


class UnknownFormat(RuntimeError):
    """El transcript o la salida de `claude -p` no tienen la forma que se espera."""


@dataclass
class Run:
    session_id: str
    result: str
    cost_usd: float
    start: str
    end: str
    error: str = ""
    model_usage: dict = field(default_factory=dict)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def project_dir(cwd: Path) -> Path:
    """Dónde guarda Claude Code los transcripts de una sesión lanzada en `cwd`."""
    return PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def write_settings(dest: Path, env: dict[str, str]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"env": env}, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def batch_env(telemetry: Path, switch: Path, *, hooks: bool = True) -> dict[str, str]:
    return {
        "LD_HOOK_TELEMETRY_LOG": str(telemetry),
        "LD_HOOK_READ_BLOCK": "1",
        "LD_HOOK_READ_SWITCH_FILE": str(switch),
        "LD_HOOK_ENABLED": "1" if hooks else "0",
    }


def run(
    prompt: str,
    cwd: Path,
    settings: Path,
    *,
    model: str = "opus",
    max_turns: int = 12,
    timeout_s: int = 900,
) -> Run:
    """Una sesión nueva de `claude -p`. No reintenta: eso lo decide quien llama."""
    start = now()
    argv = [
        "claude",
        "-p",
        "--model",
        model,
        "--settings",
        str(settings),
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        str(max_turns),
        prompt,
    ]
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Run("", "", 0.0, start, now(), error="timeout")
    final = None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            final = event
    if final is None:
        return Run("", "", 0.0, start, now(), error=f"sin resultado: {proc.stderr[-300:]}")
    return Run(
        session_id=str(final.get("session_id") or ""),
        result=str(final.get("result") or ""),
        cost_usd=float(final.get("total_cost_usd") or 0.0),
        start=start,
        end=now(),
        error="api" if final.get("is_error") else "",
        model_usage=final.get("modelUsage") or {},
    )


def read_transcript(cwd: Path, session_id: str, *, wait_s: float = 5.0) -> list[dict]:
    path = project_dir(cwd) / f"{session_id}.jsonl"
    limit = time.monotonic() + wait_s
    while not path.is_file() and time.monotonic() < limit:
        time.sleep(0.2)
    if not path.is_file():
        raise UnknownFormat(f"no aparece el transcript de la sesión {session_id}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _same_path(a: str, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(str(b)))
    except (TypeError, ValueError):
        return False


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
    return ""


def analyze(events: list[dict], file: Path) -> dict:
    """Qué hizo el hilo principal con `fichero`, leído del transcript (nunca del informe)."""
    deferred = None
    usages: dict[str, dict] = {}
    results: dict[str, dict] = {}
    for event in events:
        if event.get("isSidechain"):
            continue
        attached = event.get("attachment")
        if isinstance(attached, dict) and attached.get("type") == "deferred_tools_delta":
            # Es un DELTA: llegan varios y cada uno añade o quita nombres. Quedarse con el último
            # daba «no diferidas» en el control instalado (tarea 4) con las tools ahí.
            deferred = (deferred or set()) | set(attached.get("addedNames") or [])
            deferred -= set(attached.get("removedNames") or [])
        content = (event.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_use":
                usages[block["id"]] = block
            elif block.get("type") == "tool_result":
                results[block.get("tool_use_id", "")] = block
    if deferred is None:
        raise UnknownFormat("el transcript no trae `deferred_tools_delta`")

    output = {
        "deferred_tools": TOOL_PRINCIPAL in deferred,
        "read_full": False,
        "read_ranges": 0,
        "bash_dump": False,
        "local_with_path": [],
        "toolsearch": False,
        "blocked": False,
    }
    for uid, usage in usages.items():
        name, entry = usage.get("name", ""), usage.get("input") or {}
        result = results.get(uid) or {}
        result_text = _text(result.get("content"))
        if result.get("is_error") and any(m in result_text for m in BLOCK_MARKERS):
            output["blocked"] = True
            continue  # una lectura denegada no metió nada en el contexto
        if name == "ToolSearch":
            output["toolsearch"] = True
        elif name == "Read" and _same_path(str(entry.get("file_path", "")), file):
            if entry.get("offset") is not None or entry.get("limit") is not None:
                output["read_ranges"] += 1
            else:
                output["read_full"] = True
        elif name in ("Bash", "PowerShell"):
            command = str(entry.get("command", ""))
            if file.name in command and len(result_text) > DUMP_THRESHOLD:
                output["bash_dump"] = True
        elif (
            name.startswith(LOCAL_PREFIX)
            and _same_path(str(entry.get("path", "")), file)
            and not result.get("is_error")
        ):
            output["local_with_path"].append(name)
    output["content_in_context"] = (
        output["read_full"] or output["read_ranges"] > 0 or output["bash_dump"]
    )
    return output


def telemetry_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def valid_run(telemetry: list[dict], session_id: str) -> bool:
    """El hook de prompt deja un evento en TODO prompt: si no está, con el bloqueo encendido, la
    corrida no corrió con los hooks que se querían medir."""
    from local_delegate import legacy_names

    # El estado del bloqueo en el formato viejo (`bloqueo: encendido`) o el nuevo (`block: on`).
    return any(
        e.get("event") == "UserPromptSubmit"
        and e.get("session_id") == session_id
        and legacy_names.normalize("hook_telemetry", e).get("block") == "on"
        for e in telemetry
    )


def note_window(dest: Path, batch: str, runs: list[Run]) -> None:
    """Ventana de la tanda (+10 min: los modelos quedan calientes) y sus sesiones, para excluirlas.

    `destino` es el fichero nuevo (`excluded-windows.json`): si aún no existe, se parte del de antes
    que tenga al lado (`ventanas-excluidas.json`, que no se reescribe), con sus claves traducidas.
    Se escribe siempre en el formato nuevo.
    """
    from local_delegate import legacy_names

    old_name = legacy_names.EXCLUDED_WINDOWS_FILE_NAMES[0]
    source = dest if dest.is_file() else dest.with_name(old_name)
    data: dict = {"sessions": [], "windows": []}
    if source.is_file():
        data = legacy_names.normalize_excluded_windows(
            json.loads(source.read_text(encoding="utf-8"))
        )
    valid_ones = [c for c in runs if c.start]
    if not valid_ones:
        return
    end = datetime.fromisoformat(max(c.end for c in valid_ones)).timestamp() + 600
    data.setdefault("windows", []).append(
        {
            "batch": batch,
            "start": min(c.start for c in valid_ones),
            "end": datetime.fromtimestamp(end, UTC).isoformat(timespec="seconds"),
        }
    )
    known = {s["session_id"] for s in data.setdefault("sessions", [])}
    for c in valid_ones:
        if c.session_id and c.session_id not in known:
            data["sessions"].append(
                {"session_id": c.session_id, "start": c.start, "end": c.end, "reason": batch}
            )
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def confirm(runs: int, cost_per_run: float, *, yes: bool) -> bool:
    print(
        f"Se van a lanzar {runs} corridas de `claude -p` (~{cost_per_run:.2f} USD de "
        f"lista cada una, ~{runs * cost_per_run:.0f} USD en total) contra tu cuota."
    )
    if yes:
        return True
    try:
        return input("¿Seguir? [s/N]: ").strip().lower() in {"s", "si", "sí", "y", "yes"}
    except EOFError:
        return False


def precedence_control(bench: Path, prose_file: Path, switch: Path) -> bool:
    """Con `LD_HOOK_ENABLED=0` por `--settings`, el `Read` completo de prosa grande NO se deniega.

    Si se deniega, el `env` del usuario manda sobre `--settings` y nada de lo que sigue mediría la
    variante que dice: la tanda aborta, no reintenta.
    """
    settings = write_settings(
        bench / "settings-precedence.json",
        batch_env(bench / "telemetry-precedence.jsonl", switch, hooks=False),
    )
    run_result = run(
        f"Lee entero el fichero {prose_file} con la tool Read (sin offset ni limit) y dime "
        "solo su primera línea.",
        bench,
        settings,
        max_turns=4,
    )
    if run_result.error or not run_result.session_id:
        return False
    seen = analyze(read_transcript(bench, run_result.session_id), prose_file)
    return seen["read_full"] and not seen["blocked"]
