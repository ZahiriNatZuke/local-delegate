"""codex_hooks.py — the Codex delivery of local-delegate: user hooks in ``~/.codex/hooks.json`` (#669).

Codex CLI 0.169.0 (``openai/codex``, tag ``rust-v0.169.0``) reads, for its user layer,
``<CODEX_HOME>/hooks.json`` (``codex-rs/hooks/src/engine/discovery.rs``, ``load_hooks_json``) in
the format ``codex_plugin.check_hooks_file`` checks. This module owns two handlers in it:

- ``UserPromptSubmit`` → ``codex-prompt``: a delegation hint for a clearly mechanical prompt.
- ``SubagentStart`` → ``codex-subagent-start``: the reminder for every subagent.

Not covered here: the calls to our MCP tools and their attribution to a Codex session (next step
of #669), reads, shell commands and ``apply_patch`` (#670).

Codex only runs a handler the user approved in ``/hooks``. The approval is stored under the key
``"<path>:<event>:<group>:<handler>"`` (``codex-rs/hooks/src/lib.rs``, ``hook_key``) with a hash
of event, matcher and handler. Hence three rules:

- our groups go in the first empty group of their event (the hole an ``uninstall`` left) or at its
  end and, once there, are rewritten **in place**;
- a group of ours that goes away becomes ``{"hooks": []}`` while other groups follow it: Codex
  still counts it in the index (``append_hook_events`` enumerates the groups) and loads nothing,
  so a user's group behind it keeps its key; at the end of the list it is dropped;
- the command carries no version: the ``uv tool`` interpreter keeps its path on upgrade.

Codex runs the command through ``cmd.exe /C "<command>"`` on Windows and ``$SHELL -lc`` elsewhere
(``engine/command_runner.rs``); exit code 2 blocks, any other non-zero code is a failure that does
not (``events/pre_tool_use.rs``). ``local_delegate.hook`` never exits with 2.

Codex reads the file with ``fs::read_to_string`` + ``serde_json::from_str``: a UTF-8 BOM makes it
reject the whole file, so a file with one is never written and ``doctor`` warns.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import secrets
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

HOOKS_FILE_NAME = "hooks.json"
#: In `LOG_DIR`: `{hook name: UTC time}` of the last dispatch of each Codex hook.
SEEN_FILE_NAME = "codex-hooks-seen.json"
TIMEOUT_S = 30
HOOK_MODULE = "local_delegate.hook"


@dataclass(frozen=True)
class HookSpec:
    name: str
    event: str
    matcher: str | None = None


SPECS: tuple[HookSpec, ...] = (
    HookSpec("codex-prompt", "UserPromptSubmit"),
    HookSpec("codex-subagent-start", "SubagentStart"),
)
NAMES = frozenset(spec.name for spec in SPECS)

#: `hook_event_key_label` of `codex-rs/hooks/src/lib.rs`, for the events we use.
EVENT_LABELS = {"UserPromptSubmit": "user_prompt_submit", "SubagentStart": "subagent_start"}

#: The tail of every command of ours, whatever the interpreter in front of it.
#: Anchored at the start: one interpreter (quoted or bare) and nothing else in front, so a wrapper
#: of the user's that ends the same way is not taken for ours.
_OURS = re.compile(
    r"\s*(?P<python>\"[^\"]*\"|'[^']*'|[^\s\"']+)"
    r"\s+-I\s+-m\s+local_delegate\.hook\s+(?P<name>codex-[a-z][a-z-]{0,40})\s*"
)

#: The handler keys Codex runs instead of `command` on Windows: a handler with one is the user's.
WINDOWS_KEYS = frozenset({"commandWindows", "command_windows"})

#: A group that holds nothing: Codex counts it in the index and loads no handler.
EMPTY_GROUP: dict = {"hooks": []}


# --- The entries --------------------------------------------------------------------------------
def command(python: str, name: str, platform: str | None = None) -> str:
    """The command line of hook ``name``: the interpreter quoted for the shell Codex uses."""
    if (platform or sys.platform) == "win32":
        exe = '"' + python.replace("\\", "/").replace('"', "") + '"'
    else:
        exe = shlex.quote(python)
    return f"{exe} -I -m {HOOK_MODULE} {name}"


def handler(python: str, name: str, platform: str | None = None) -> dict:
    return {"type": "command", "command": command(python, name, platform), "timeout": TIMEOUT_S}


def group(spec: HookSpec, python: str, platform: str | None = None) -> dict:
    data: dict = {}
    if spec.matcher is not None:
        data["matcher"] = spec.matcher
    data["hooks"] = [handler(python, spec.name, platform)]
    return data


def entries(python: str, platform: str | None = None) -> dict[str, list[dict]]:
    """`{event: [group]}` of our hooks, as they go in `hooks.json`."""
    result: dict[str, list[dict]] = {}
    for spec in SPECS:
        result.setdefault(spec.event, []).append(group(spec, python, platform))
    return result


def our_name(candidate: object) -> str | None:
    """The hook name when ``candidate`` is a group of ours, else ``None``.

    Ours means exactly one ``command`` handler, no ``commandWindows`` (Codex would run that one on
    Windows) and a command ending in ``-I -m local_delegate.hook codex-<name>``. A handler of ours
    inside a group with others is the user's arrangement: it is left alone.
    """
    if not isinstance(candidate, dict):
        return None
    handlers = candidate.get("hooks")
    if not isinstance(handlers, list) or len(handlers) != 1:
        return None
    only = handlers[0]
    # `command_windows` too: Codex reads that spelling as well (`codex_plugin.HANDLER_FIELDS`).
    if not isinstance(only, dict) or only.get("type") != "command" or WINDOWS_KEYS & set(only):
        return None
    text = only.get("command")
    match = _OURS.fullmatch(text) if isinstance(text, str) else None
    return match.group("name") if match else None


def python_of(candidate: dict) -> str:
    """The interpreter of a group of ours, unquoted (what `command` put in front)."""
    text = candidate["hooks"][0]["command"]
    head = _OURS.fullmatch(text).group("python")
    if len(head) >= 2 and head[0] == head[-1] and head[0] in "\"'":
        head = head[1:-1]
    return head


# --- Merge and strip ----------------------------------------------------------------------------
class RejectedFile(ValueError):
    """Codex would reject `hooks.json` as it is: writing ours into it would load nothing."""


def _hooks_table(data: dict) -> dict:
    from . import codex_plugin

    findings = codex_plugin.check_hooks_file(data)
    if codex_plugin.rejected(findings):
        raise RejectedFile(
            ", ".join(f.where for f in findings if f.effect == codex_plugin.REJECTED)
        )
    if not isinstance(data.get("hooks"), dict):
        data["hooks"] = {}
    return data["hooks"]


def _vacate(groups: list, index: int) -> None:
    groups[index] = dict(EMPTY_GROUP)


def _trim(groups: list, vacated: set[int]) -> None:
    """Drops the groups this pass vacated from the end of the list (nothing behind them moves)."""
    while groups and (len(groups) - 1) in vacated:
        vacated.discard(len(groups) - 1)
        groups.pop()


def merge(data: dict, python: str, platform: str | None = None) -> tuple[dict, list[str]]:
    """Our groups in ``data`` (``hooks.json`` parsed): ``(data, names written or rewritten)``.

    Raises `RejectedFile` when Codex would reject the file. Pure: depends only on its arguments,
    as `install.update_config_json` requires.
    """
    hooks = _hooks_table(data)
    wanted = {spec.name: spec for spec in SPECS}
    placed: set[str] = set()
    changed: list[str] = []
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        vacated: set[int] = set()
        for index, candidate in enumerate(groups):
            name = our_name(candidate)
            if name is None:
                continue
            spec = wanted.get(name)
            if spec is None or spec.event != event or name in placed:
                _vacate(groups, index)
                vacated.add(index)
                changed.append(name)
                continue
            placed.add(name)
            fresh = group(spec, python, platform)
            if candidate != fresh:
                groups[index] = fresh
                changed.append(name)
        if vacated:
            _trim(groups, vacated)
            if not groups:
                hooks.pop(event)
    for spec in SPECS:
        if spec.name in placed:
            continue
        groups = hooks.setdefault(spec.event, [])
        fresh = group(spec, python, platform)
        # The hole an earlier `uninstall` left: same index again, so no holes pile up and the old
        # approval (same key, same hash) holds again, without local-delegate writing any.
        hole = next((i for i, g in enumerate(groups) if g == EMPTY_GROUP), None)
        if hole is None:
            groups.append(fresh)
        else:
            groups[hole] = fresh
        changed.append(spec.name)
    return data, changed


def strip(data: dict) -> tuple[dict, int]:
    """``data`` without our groups: ``(data, how many)``. Never moves a group of someone else."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data, 0
    removed = 0
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        vacated: set[int] = set()
        for index, candidate in enumerate(groups):
            if our_name(candidate) is not None:
                _vacate(groups, index)
                vacated.add(index)
                removed += 1
        if vacated:
            _trim(groups, vacated)
            if not groups:
                hooks.pop(event)
    return data, removed


def is_empty(data: dict) -> bool:
    """Nothing left worth a file: no keys, or only an empty `hooks`."""
    return all(key == "hooks" for key in data) and not data.get("hooks")


def has_bom(raw: bytes) -> bool:
    return raw.startswith(codecs.BOM_UTF8)


# --- What `doctor` reads ------------------------------------------------------------------------
@dataclass
class Found:
    name: str
    event: str
    group_index: int
    group: dict


@dataclass
class Inspection:
    """What `doctor` needs of `hooks.json`, `config.toml` and the dispatch marker. Only reads."""

    path: Path
    exists: bool = False
    error: str | None = None  # unreadable: the check is `unknown`
    rejected: str | None = None  # Codex would reject the whole file (`bom` or the keys)
    found: list[Found] = field(default_factory=list)
    toml_events: bool = False
    trusted: set[str] = field(default_factory=set)
    seen: dict[str, str] = field(default_factory=dict)


def hook_key(path: Path, event: str, group_index: int, handler_index: int = 0) -> str:
    """The key under which Codex keeps the approval of a handler (`hook_key` of `lib.rs`)."""
    return f"{path}:{EVENT_LABELS[event]}:{group_index}:{handler_index}"


def _toml_hooks(codex_dir: Path) -> tuple[bool, set[str]]:
    """(does `[hooks]` hold event groups, keys with a `trusted_hash` in `[hooks.state]`)."""
    import tomllib

    try:
        data = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return False, set()
    table = data.get("hooks")
    if not isinstance(table, dict):
        return False, set()
    events = any(key != "state" and value for key, value in table.items())
    state = table.get("state")
    trusted = set()
    if isinstance(state, dict):
        for key, value in state.items():
            if isinstance(value, dict) and isinstance(value.get("trusted_hash"), str):
                trusted.add(key)
    return events, trusted


def read_seen(log_dir: Path) -> dict[str, str]:
    try:
        data = json.loads((log_dir / SEEN_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in NAMES and isinstance(v, str)}


def inspect(codex_dir: Path, log_dir: Path) -> Inspection:
    """Reads `hooks.json`, `config.toml` and the dispatch marker. Never writes, never raises."""
    from . import codex_plugin

    path = codex_dir / HOOKS_FILE_NAME
    result = Inspection(path=path)
    result.toml_events, trusted = _toml_hooks(codex_dir)
    result.seen = read_seen(log_dir)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return result
    except OSError as exc:
        result.exists = True
        result.error = str(exc.strerror or exc)
        return result
    result.exists = True
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        result.error = type(exc).__name__
        return result
    if not isinstance(data, dict):
        result.rejected = "$"
        return result
    hooks = data.get("hooks")
    for event, groups in hooks.items() if isinstance(hooks, dict) else ():
        for index, candidate in enumerate(groups if isinstance(groups, list) else ()):
            name = our_name(candidate)
            if name is not None:
                result.found.append(Found(name, event, index, candidate))
    if has_bom(raw):
        result.rejected = "BOM"
    else:
        findings = codex_plugin.check_hooks_file(data)
        if codex_plugin.rejected(findings):
            result.rejected = ", ".join(
                f.where for f in findings if f.effect == codex_plugin.REJECTED
            )
    folded = {key.casefold() for key in trusted} if sys.platform == "win32" else trusted
    for item in result.found:
        if item.event not in EVENT_LABELS:
            continue
        key = hook_key(path, item.event, item.group_index)
        if (key.casefold() if sys.platform == "win32" else key) in folded:
            result.trusted.add(item.name)
    return result


# --- The handlers (run by `hook_entry` inside the net of `local_delegate.hook`) ----------------
def _mark_seen(name: str) -> None:
    """Best-effort: `{name: UTC time}` of the last dispatch, nothing from the payload."""
    try:
        from .read_switch import log_dir

        target = log_dir() / SEEN_FILE_NAME
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current = {k: v for k, v in current.items() if k in NAMES}
        current[name] = datetime.now(UTC).isoformat(timespec="seconds")
        target.parent.mkdir(parents=True, exist_ok=True)
        # A temporary of its own: several subagents may start at the same moment.
        tmp = target.with_name(f"{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        tmp.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")
        tmp.replace(target)
    except Exception:
        # Observation only: a lost marker never breaks the hook.
        pass


def _payload() -> dict | None:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except (OSError, ValueError, AttributeError):
        return None
    return data if isinstance(data, dict) else None


def _emit(event: str, text: str) -> None:
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
            ensure_ascii=False,
        )
    )


def run(name: str, load_hook_module: Callable[[str], ModuleType]) -> None:
    """Runs Codex hook ``name``. Raises on a bug: `hook_entry` logs it and exits 0.

    ``load_hook_module`` is `hook_entry._load_hook_module`, passed in so this module
    never imports `hook_entry`, which imports this one.
    """
    _mark_seen(name)
    payload = _payload()
    if payload is None:
        return
    common = load_hook_module("hook_common")
    if not common.enabled() or common.backend_down():
        return
    if name == "codex-prompt":
        prompt_rules = load_hook_module("suggest_delegate_prompt")
        prompt = str(payload.get("prompt") or "")
        if prompt_rules.is_system_event(prompt):
            return
        category = prompt_rules.classify(prompt)
        if category is not None:
            _emit(
                "UserPromptSubmit", common.hook_text("codex.prompt.mechanical", category=category)
            )
    elif name == "codex-subagent-start":
        _emit("SubagentStart", common.hook_text("codex.subagent.start"))
