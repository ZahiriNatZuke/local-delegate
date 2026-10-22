"""install_state.py — what `install` wrote, so `doctor`, `update` and `uninstall` stop guessing.

REQ-007 (SDD claude-plugin-and-mods). One JSON file, ``install-state.json``, in the installer's
data directory, with the **same write rule as** ``language.json`` (``install.data_dir_for``): with a
simulated HOME it is only written when ``LOCAL_DELEGATE_LOG_DIR`` chose the directory.

Shape::

    {
      "schema": 1,
      "claude_delivery": "plugin" | "settings",
      "claude_delivery_explicit": true,            # optional, see below
      "version": "<package version that wrote it>",
      "updated_at": "<ISO 8601>",
      "pieces": {"plugin": {"at": "…", …}, "marketplace": {…}, "desktop_entry": {…}}
    }

``claude_delivery_explicit`` is only there when the user asked for ``--claude-delivery settings``:
``update`` then leaves the settings delivery alone instead of migrating it (REQ-008 a is for old
installs, not for a choice). Any other ``install`` takes it out. It is optional on purpose, so the
states written before it read the same and ``schema`` stays at 1.

``pieces`` lists only what ``install`` itself wrote, with its date. A piece that existed before
and is not listed here is not ours, and nobody deletes it.

A missing or unreadable file reads as ``None`` ("unknown"), never as an empty state: an empty state
would say "install wrote nothing", which is a claim, and a wrong one after an upgrade from 0.39.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import install

STATE_FILE = "install-state.json"
SCHEMA_VERSION = 1
#: Optional: present (and ``true``) only after ``install --claude-delivery settings``.
EXPLICIT_FIELD = "claude_delivery_explicit"


def now_iso() -> str:
    """Current UTC time, to the second, with a ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def path(home: Path, data_dir: Path | None = None) -> Path | None:
    """Where the state lives for ``home``, or ``None`` if it must not be touched."""
    directory = install.data_dir_for(home, data_dir)
    return directory / STATE_FILE if directory is not None else None


def load(home: Path, data_dir: Path | None = None) -> dict | None:
    """The stored state, or ``None`` when it is unknown (no file, unreadable, not an object)."""
    target = path(home, data_dir)
    if target is None:
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save(home: Path, state: dict, data_dir: Path | None = None) -> Path | None:
    """Writes ``state`` atomically; returns the path, or ``None`` if the rule says not to write."""
    target = path(home, data_dir)
    if target is None:
        return None
    write_json_atomic(target, state)
    return target


def write_json_atomic(target: Path, data: dict) -> None:
    """Writes ``data`` as UTF-8 JSON with LF endings, through a temporary file and a rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    os.replace(tmp, target)


def new_state(delivery: str, version: str, *, now: str | None = None) -> dict:
    """A fresh state with no pieces."""
    return {
        "schema": SCHEMA_VERSION,
        "claude_delivery": delivery,
        "version": version,
        "updated_at": now or now_iso(),
        "pieces": {},
    }


def delivery(state: dict | None) -> str | None:
    """The Claude Code delivery the state records, or ``None`` if unknown."""
    if not isinstance(state, dict):
        return None
    value = state.get("claude_delivery")
    return value if isinstance(value, str) else None


def delivery_explicit(state: dict | None) -> bool:
    """True when the user chose the settings delivery with ``--claude-delivery settings``."""
    return isinstance(state, dict) and state.get(EXPLICIT_FIELD) is True


def with_delivery_explicit(state: dict, explicit: bool) -> dict:
    """A copy of ``state`` with the mark of an explicit settings choice set or taken out."""
    new = dict(state)
    if explicit:
        new[EXPLICIT_FIELD] = True
    else:
        new.pop(EXPLICIT_FIELD, None)
    return new


def piece(state: dict | None, name: str) -> dict | None:
    """The record of a piece ``install`` wrote, or ``None`` if the state does not list it."""
    if not isinstance(state, dict):
        return None
    pieces = state.get("pieces")
    entry = pieces.get(name) if isinstance(pieces, dict) else None
    return entry if isinstance(entry, dict) else None


def with_piece(state: dict, name: str, /, *, now: str | None = None, **details: object) -> dict:
    """A copy of ``state`` that lists ``name`` as written by ``install`` now."""
    pieces = dict(state.get("pieces") or {})
    pieces[name] = {"at": now or now_iso(), **details}
    return {**state, "pieces": pieces}


def without_piece(state: dict, name: str) -> dict:
    """A copy of ``state`` that no longer lists ``name``."""
    pieces = dict(state.get("pieces") or {})
    pieces.pop(name, None)
    return {**state, "pieces": pieces}
