"""Quién pidió cada delegación: modelo, hilo y esfuerzo de quien llama (coste-api-y-cuota).

Tres preguntas, y las reglas que varios consumidores necesitan, en un solo sitio:

- **Al momento** (REQ-002, REQ-003): el hook `record_call.py` deja una nota por `tool_use_id`
  con `agent_id`, `agent_type`, `effort` y `transcript_path`; `resolve_call` la lee y busca el
  modelo en la cola del transcript que señala la nota. `current_call` lo hace una vez por
  petición y lo memoriza en el dict que el middleware pone en `clients`.
- **El relleno a posteriori** (REQ-005): la clave de cada línea del log (`file_keys`) y
  los `attribution-AAAAMM.json` (`read_backfill`, `write_backfill`), donde una entrada solo se
  sustituye por otra de cruce mejor. Los `atribucion-AAAAMM.json` de una versión anterior se
  leen mientras no exista el nuevo y siembran el nuevo una sola vez; nunca se reescriben.
- **Lo que no cuenta** (REQ-007) y **cuánto viven los transcripts** (enmienda 1):
  `exclusion_reason` y `cleanup_period_days`.

Solo stdlib. La nota la escribe un hook que no puede importar este módulo, así que su formato vive
en dos sitios y lo ata un test de ida y vuelta (`tests/test_attribution.py`).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from . import clients, legacy_names, pricing
from .resources.hooks import hook_common

#: Una nota de más de diez minutos ya no cuenta (REQ-003).
NOTE_TTL_S = hook_common.NOTE_TTL_S

#: Cuánto del final del transcript se lee como mucho, y en cuánto tiempo (REQ-003).
TAIL_BYTES = 256 * 1024
BUDGET_S = 0.050

#: Clientes que no son Claude: sus delegaciones cuentan como uso, pero no se valoran (REQ-007).
NON_CLAUDE_CLIENTS = {"codex-mcp-client": "no es Claude"}

#: El cliente `mcp` es el de los scripts del repo: lo que hace es una prueba (test-windows-out-of-metrics).
TEST_CLIENTS = {"mcp": "pruebas"}

#: Clientes cuyas delegaciones no se valoran, con el rótulo del tramo `excluido` (REQ-007). Se
#: conserva como unión de los dos de arriba; la regla vive en `exclusion_reason` y `test_reason`.
EXCLUDED_CLIENTS = {**NON_CLAUDE_CLIENTS, **TEST_CLIENTS}

#: Orden de los cruces del relleno: una entrada solo se sustituye por otra de rango MAYOR (REQ-005).
MATCH_RANK = {"exact": 2, "window": 1, "window+path": 1, "ambiguous": 0, "no_match": 0}

#: `cleanupPeriodDays` por defecto de Claude Code (enmienda 1).
DEFAULT_CLEANUP_DAYS = 30

_BACKFILL_VERSION = 1


# --- Al momento ---------------------------------------------------------------------------------


def _valid_id(tool_use_id: object) -> bool:
    return isinstance(tool_use_id, str) and bool(hook_common.TOOL_USE_ID_PATTERN.match(tool_use_id))


def read_note(tool_use_id: str, *, directory: Path | None = None) -> dict | None:
    """La nota que dejó el hook para ese `tool_use_id`, o `None`. Nunca lanza.

    Una nota ilegible, a medias o de otro id cuenta como «sin nota».
    """
    if not _valid_id(tool_use_id):
        return None
    # Sin directorio explícito, el nombre nuevo y luego el viejo (REQ-012): un hook
    # `anotar_llamada.py` de una versión anterior sigue escribiendo en `local-delegate-llamadas/`.
    bases = (
        [directory]
        if directory is not None
        else [hook_common.call_notes_dir(), hook_common.legacy_call_notes_dir()]
    )
    for base in bases:
        try:
            note = json.loads((base / f"{tool_use_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(note, dict) and note.get("tool_use_id") == tool_use_id:
            return note
    return None


def _projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def _safe_path(path: Path, root: Path) -> Path | None:
    """La ruta resuelta si cuelga de `root` y acaba en `.jsonl`; si no, `None`.

    La nota vive en un temporal que cualquier proceso local puede escribir: sin esta comprobación,
    el daemon abriría el fichero que le dijeran.
    """
    try:
        resolved = path.resolve()
        if resolved.suffix != ".jsonl" or not resolved.is_relative_to(root.resolve()):
            return None
        return resolved
    except (OSError, ValueError, RuntimeError):
        return None


def _transcript_de(note: dict, root: Path) -> Path | None:
    """El transcript donde está el `tool_use`: el del subagente si la nota trae `agent_id`.

    La nota de un subagente trae el `transcript_path` del PRINCIPAL (medido); el suyo es
    `<sesión>/subagents/agent-<agent_id>.jsonl`.
    """
    raw_path = note.get("transcript_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    principal = _safe_path(Path(raw_path), root)
    if principal is None:
        return None
    agent = note.get("agent_id")
    if not agent:
        return principal
    if not isinstance(agent, str):
        return None
    return _safe_path(principal.with_suffix("") / "subagents" / f"agent-{agent}.jsonl", root)


def _model_from_line(line: bytes, tool_use_id: str) -> str | None:
    """`message.model` si la línea es la del `tool_use` con ese id; si no, `None`."""
    try:
        data = json.loads(line)
        message = data.get("message") if isinstance(data, dict) else None
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if not isinstance(content, list):
            return None
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("id") == tool_use_id
            ):
                model = message.get("model")
                return model if isinstance(model, str) and model else None
    except (ValueError, TypeError):
        return None
    return None


def _find_model(
    path: Path, tool_use_id: str, *, clock: Callable[[], float], opener: Callable[..., Any]
) -> str | None:
    """Busca la línea del `tool_use` de atrás adelante en la cola del transcript.

    Lee como mucho `TAIL_BYTES` y corta al pasar `BUDGET_S` medido con `clock`. Lo que no
    encuentra lo cierra el relleno a posteriori.
    """
    start = clock()
    needle = tool_use_id.encode("ascii")
    try:
        with opener(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            offset = max(0, size - TAIL_BYTES)
            stream.seek(offset)
            tail = stream.read(size - offset)
    except (OSError, ValueError):
        return None
    lines = tail.split(b"\n")
    if offset > 0:
        lines = lines[1:]  # la primera está cortada por la mitad
    for line in reversed(lines):
        if clock() - start > BUDGET_S:
            return None
        if needle not in line:
            continue
        model = _model_from_line(line, tool_use_id)
        if model:
            return model
    return None


def _supports_effort(model: str) -> bool:
    try:
        entry = pricing.entry(model)
    except Exception:
        return True
    return True if entry is None else bool(entry.get("supports_effort", True))


def resolve_call(
    tool_use_id: str | None,
    *,
    notes: Path | None = None,
    now: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    opener: Callable[..., Any] = open,
    projects: Path | None = None,
) -> dict:
    """Los campos `caller_*` de una llamada (REQ-003); `{}` si no hay nota vigente.

    `notes` es el directorio de notas (por defecto, el del hook) y `projects` la raíz de la que
    tiene que colgar el transcript (por defecto, `~/.claude/projects`). Nunca devuelve el id de
    sesión ni nada más del transcript que el modelo.
    """
    if not tool_use_id or not _valid_id(tool_use_id):
        return {}
    note = read_note(tool_use_id, directory=notes)
    if note is None:
        return {}
    instant = time.time() if now is None else now
    try:
        if instant - float(note["ts"]) > NOTE_TTL_S:
            return {}
    except (KeyError, TypeError, ValueError):
        return {}

    agent = note.get("agent_id")
    r: dict = {"caller_kind": "subagent" if agent else "main", "caller_src": "hook"}
    entry_type = note.get("agent_type")
    if agent and isinstance(entry_type, str) and entry_type:
        r["caller_agent_type"] = entry_type
    effort = note.get("effort")
    if isinstance(effort, str) and effort:
        r["caller_effort"] = effort

    path = _transcript_de(note, projects or _projects_root())
    model = _find_model(path, tool_use_id, clock=clock, opener=opener) if path is not None else None
    if model:
        r["caller_model"] = pricing.normalize_id(model)
        r["caller_src"] = "hook+transcript"
        if "caller_effort" not in r and not _supports_effort(r["caller_model"]):
            r["caller_effort"] = "n/a"  # Haiku 4.5: no admite esfuerzo y no es un dato que falte
    return r


def current_call() -> dict:
    """La atribución de la petición en curso, resuelta UNA vez por petición; `{}` fuera de una.

    Se memoriza en el dict que el middleware pone por petición (`clients.request_memory`),
    nunca en el módulo: en el daemon un dict del módulo crecería sin límite.
    """
    tool_use_id = clients.current_tool_use_id()
    if not tool_use_id:
        return {}
    memo = clients.request_memory()
    if memo is not None and tool_use_id in memo:
        return memo[tool_use_id]
    result = resolve_call(tool_use_id)
    if memo is not None:
        memo[tool_use_id] = result
    return result


# --- Relleno a posteriori (REQ-005) -------------------------------------------------------------


def file_keys(rows: Iterable[dict]) -> list[str]:
    """La clave de cada línea del log, en el orden del fichero ENTERO.

    `tool_use_id` si la línea lo trae; si no, `ts|tool|ordinal`, con `ordinal` la posición de la
    línea entre las de su misma `(ts, tool)`. El log solo crece por el final, así que una línea
    nueva no cambia la clave de las anteriores. `(ts, tool)` sola repite: `ts` va en segundos y dos
    subagentes llaman a la vez a la misma tool.
    """
    seen: dict[tuple[str, str], int] = {}
    keys: list[str] = []
    for row in rows:
        tool_use_id = row.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id:
            keys.append(tool_use_id)
            continue
        pair = (str(row.get("ts", "")), str(row.get("tool", "")))
        ordinal = seen.get(pair, 0)
        seen[pair] = ordinal + 1
        keys.append(f"{pair[0]}|{pair[1]}|{ordinal}")
    return keys


def backfill_path(log_dir: Path, month: str) -> Path:
    """`attribution-AAAAMM.json` junto al log: el único que se escribe (REQ-005)."""
    return Path(log_dir) / f"{legacy_names.ATTRIBUTION_FILE_PREFIXES[1]}{month}.json"


def legacy_backfill_path(log_dir: Path, month: str) -> Path:
    """`atribucion-AAAAMM.json`, el de una versión anterior: solo se lee (REQ-006)."""
    return Path(log_dir) / f"{legacy_names.ATTRIBUTION_FILE_PREFIXES[0]}{month}.json"


def _load_entries(path: Path) -> dict[str, dict] | None:
    """Las entradas de un fichero del relleno, ya en el formato nuevo; `None` si no existe.

    Un fichero que existe pero no se lee cuenta como vacío: así no se siembra desde el viejo
    encima de un nuevo dañado.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    entries = legacy_names.read_key(data, "entries", "entradas") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {
        k: legacy_names.normalize("attribution", v)
        for k, v in entries.items()
        if isinstance(v, dict)
    }


def read_backfill(log_dir: Path, month: str) -> dict[str, dict]:
    """Las entradas del relleno de ese mes (`{clave: entrada}`); `{}` si no hay o no se lee.

    Lee `attribution-AAAAMM.json`. Mientras no exista, lee el `atribucion-AAAAMM.json` de una
    versión anterior, traducido al formato nuevo (REQ-006). En cuanto existe el nuevo, el viejo ya
    no se lee: lo que tenía entró en el nuevo al sembrarlo, una sola vez (`write_backfill`).
    """
    entries = _load_entries(backfill_path(log_dir, month))
    if entries is None:
        entries = _load_entries(legacy_backfill_path(log_dir, month))
    return entries or {}


def _rank(entry: dict) -> int:
    return MATCH_RANK.get(str(entry.get("match")), -1)


def write_backfill(log_dir: Path, month: str, entries: dict[str, dict]) -> dict[str, dict]:
    """Funde `entries` con lo que ya hay y lo escribe de forma atómica. Devuelve el resultado.

    Una entrada existente no se borra nunca, y solo la sustituye otra de cruce MEJOR
    (`exact` > `window` = `window+path` > `ambiguous` = `no_match`). Si aún no existe
    `attribution-AAAAMM.json`, «lo que ya hay» es el `atribucion-AAAAMM.json` viejo: el nuevo se
    siembra desde él, con la misma regla, y el viejo queda intacto (REQ-006). Se escribe siempre
    en el formato nuevo, también si `entries` llega con claves o valores viejos.
    """
    merged = read_backfill(log_dir, month)
    for key, new_entry in entries.items():
        new_entry = legacy_names.normalize("attribution", new_entry)
        old_entry = merged.get(key)
        if old_entry is None or _rank(new_entry) > _rank(old_entry):
            merged[key] = new_entry
    target = backfill_path(log_dir, month)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(dir=target.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {"version": _BACKFILL_VERSION, "entries": merged},
                stream,
                ensure_ascii=False,
                sort_keys=True,
            )
        os.replace(temporal, target)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            # Limpieza de mejor esfuerzo: si el temporal ya no está o no se puede borrar, se
            # ignora para que el `raise` de abajo propague el error original y no este.
            pass
        raise
    return merged


# --- Lo que no cuenta y cuánto viven los transcripts ---------------------------------------------


def test_reason(row: dict, backfill_entry: dict | None = None) -> str | None:
    """`"pruebas"` si la fila es una prueba, o `None`. Es la ÚNICA regla de «esto es una prueba»
    (test-windows-out-of-metrics, REQ-004): la aplican el panel entero, `local_status`, el coste, el
    recálculo y los medidores de `scripts/`.

    Es una prueba si la pidió el cliente `mcp` de los scripts, si es de un transcript de banco
    (`bench` en `backfill_entry` o, si no se pasa, en la propia fila ya fundida), o si `fundir` le
    estampó `test_window` porque su `ts` cae en una ventana de prueba.
    """
    reason = TEST_CLIENTS.get(str(row.get("client") or ""))
    if reason:
        return reason
    bench = backfill_entry.get("bench") if isinstance(backfill_entry, dict) else row.get("bench")
    if bench or row.get("test_window"):
        return "pruebas"
    return None


def exclusion_reason(row: dict, backfill_entry: dict | None = None) -> str | None:
    """El motivo por el que la delegación no se valora (REQ-007), o `None` si cuenta.

    `no es Claude` (Codex) o `pruebas` (`test_reason`). Las de Codex sí cuentan como uso en el
    panel: solo el coste las deja fuera.
    """
    return NON_CLAUDE_CLIENTS.get(str(row.get("client") or "")) or test_reason(row, backfill_entry)


def cleanup_period_days(claude_dir: Path) -> int:
    """`H`: `cleanupPeriodDays` de `claude_dir/settings.json`, o 30 si falta o no es un entero
    positivo (enmienda 1)."""
    try:
        data = json.loads((Path(claude_dir) / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_CLEANUP_DAYS
    value = data.get("cleanupPeriodDays") if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return DEFAULT_CLEANUP_DAYS
    return value
