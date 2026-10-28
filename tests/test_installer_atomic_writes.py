"""Writes to the user's live config files are atomic and keep what Claude Code wrote meanwhile.

Before, `_write_text` and `_write_json` did ``path.write_bytes``: truncate, then write. A crash
halfway left `~/.claude.json` cut (JSON that does not parse), a reader could see it truncated, and
whatever Claude Code saved between our read and our write was lost: `~/.claude.json` and
`~/.claude/settings.json` are rewritten by Claude Code while it runs.

The "Claude Code writes in between" moment is injected through `install._backup`, which runs after
the read and before the write both before and after the fix, so the same tests fail on the old
code for the reason they name.

Everything runs against a fake HOME (`tmp_path`).
"""

from __future__ import annotations

import codecs
import json
import os
from pathlib import Path

import pytest

from local_delegate import install as inst
from local_delegate import plugin_migration, update

CLAUDE_STATE = {"count": 7, "projects": {"D:/x": {"history": ["á"]}}}


def _opts(home: Path, **kw) -> inst.Options:
    base = dict(  # noqa: C408 — readable kwargs
        home=home,
        components={"mcp"},
        targets={"claude"},
        python_exe="python3",
        use_cli=False,  # never call the real `claude` binary from the suite
    )
    base.update(kw)
    return inst.Options(**base)


def _run(actions: list[inst.Action]) -> tuple[int, str]:
    lines: list[str] = []
    failures = inst.apply(
        actions, dry_run=False, out=lambda *a: lines.append(" ".join(map(str, a)))
    )
    return failures, "\n".join(lines)


def _mcp_actions(home: Path) -> list[inst.Action]:
    return [a for a in inst.plan_install(_opts(home)) if a.kind == "mcp"]


def _leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp"))


def _json_bytes(data: dict, *, bom: bool = False, crlf: bool = False) -> bytes:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    return (codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8")


def _claude_code_writes_on_backup(monkeypatch, path: Path, writes: list[bytes]) -> list[bytes]:
    """Each `_backup(path)` call first lets "Claude Code" save the next of `writes` there."""
    pending = list(writes)
    real_backup = inst._backup

    def _backup(target: Path) -> None:
        if target == path and pending:
            path.write_bytes(pending.pop(0))
        real_backup(target)

    monkeypatch.setattr(inst, "_backup", _backup)
    return pending


# --- Atomicity ---------------------------------------------------------------------------------
def test_a_crash_before_the_replace_leaves_claude_json_intact_and_no_temporary(
    tmp_path, monkeypatch
):
    path = tmp_path / ".claude.json"
    original = _json_bytes(CLAUDE_STATE)
    path.write_bytes(original)

    def _crash(src, dst):
        raise KeyboardInterrupt  # Ctrl+C right when the new content is ready

    monkeypatch.setattr(inst.os, "replace", _crash)
    with pytest.raises(KeyboardInterrupt):
        _run(_mcp_actions(tmp_path))

    assert path.read_bytes() == original, "the file was rewritten in place, not through a temp"
    assert _leftovers(tmp_path) == []


def test_a_reader_never_sees_claude_json_truncated(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    original = _json_bytes(CLAUDE_STATE)
    path.write_bytes(original)
    seen: dict[str, bytes] = {}
    real_replace = os.replace

    def _observe(src, dst):
        seen["target"] = Path(dst).read_bytes()
        seen["temp"] = Path(src).read_bytes()
        real_replace(src, dst)

    monkeypatch.setattr(inst.os, "replace", _observe)
    failures, out = _run(_mcp_actions(tmp_path))

    assert failures == 0, out
    assert seen, "the file was not written through a temporary + os.replace"
    assert seen["target"] == original, "the target changed before the replace"
    assert json.loads(seen["temp"])["mcpServers"][inst.SERVER_NAME]
    assert _leftovers(tmp_path) == []


def test_write_text_is_atomic_too(tmp_path, monkeypatch):
    claude_md = tmp_path / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True)
    claude_md.write_bytes(b"# Reglas\r\n")

    def _crash(src, dst):
        raise OSError("simulated: disk full")

    monkeypatch.setattr(inst.os, "replace", _crash)
    with pytest.raises(OSError, match="disk full"):
        inst._write_text(claude_md, "# Reglas\nnuevo\n")

    assert claude_md.read_bytes() == b"# Reglas\r\n"
    assert _leftovers(claude_md.parent) == []


# --- Windows: the target held open -------------------------------------------------------------
def test_a_target_held_open_is_retried_and_then_written(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    path.write_bytes(_json_bytes(CLAUDE_STATE))
    real_replace = os.replace
    calls = {"n": 0}

    def _busy_twice(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "simulated: in use")
        real_replace(src, dst)

    monkeypatch.setattr(inst.os, "replace", _busy_twice)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    failures, out = _run(_mcp_actions(tmp_path))

    assert failures == 0, out
    assert calls["n"] == 3
    assert inst.SERVER_NAME in json.loads(path.read_bytes())["mcpServers"]


def test_a_target_that_stays_locked_fails_the_action_and_leaves_no_temporary(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    original = _json_bytes(CLAUDE_STATE)
    path.write_bytes(original)

    def _locked(src, dst):
        raise PermissionError(13, "simulated: in use")

    monkeypatch.setattr(inst.os, "replace", _locked)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    failures, out = _run(_mcp_actions(tmp_path))

    assert failures == 1, out
    assert ".claude.json" in out and "simulated: in use" in out
    assert path.read_bytes() == original
    assert _leftovers(tmp_path) == []


# --- Claude Code writes between our read and our write -----------------------------------------
def test_what_claude_code_writes_in_between_in_claude_json_is_kept(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    path.write_bytes(_json_bytes(CLAUDE_STATE))
    newer = {**CLAUDE_STATE, "count": 8, "lastSession": "abc"}
    _claude_code_writes_on_backup(monkeypatch, path, [_json_bytes(newer)])

    failures, out = _run(_mcp_actions(tmp_path))

    assert failures == 0, out
    data = json.loads(path.read_bytes())
    assert data["lastSession"] == "abc", "what Claude Code wrote meanwhile was lost"
    assert data["count"] == 8
    assert inst.SERVER_NAME in data["mcpServers"]
    assert _leftovers(tmp_path) == []


def test_the_retry_keeps_the_bom_and_crlf_claude_code_wrote(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    path.write_bytes(_json_bytes(CLAUDE_STATE, bom=True, crlf=True))
    newer = {**CLAUDE_STATE, "lastSession": "abc"}
    _claude_code_writes_on_backup(monkeypatch, path, [_json_bytes(newer, bom=True, crlf=True)])

    failures, out = _run(_mcp_actions(tmp_path))

    assert failures == 0, out
    raw = path.read_bytes()
    assert raw.startswith(codecs.BOM_UTF8) and not raw[3:].startswith(codecs.BOM_UTF8)
    assert raw.count(b"\n") == raw.count(b"\r\n"), "line endings were changed"
    data = json.loads(raw.decode("utf-8-sig"))
    assert data["lastSession"] == "abc" and inst.SERVER_NAME in data["mcpServers"]


def test_a_file_that_keeps_changing_fails_the_action_without_writing(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    path.write_bytes(_json_bytes(CLAUDE_STATE))
    first = _json_bytes({**CLAUDE_STATE, "count": 8})
    second = _json_bytes({**CLAUDE_STATE, "count": 9})
    _claude_code_writes_on_backup(monkeypatch, path, [first, second])

    failures, out = _run(_mcp_actions(tmp_path))

    assert failures == 1, out
    assert ".claude.json" in out
    assert path.read_bytes() == second, "Claude Code's last write was overwritten"
    assert _leftovers(tmp_path) == []


def test_settings_hooks_keep_what_claude_code_wrote_in_between(tmp_path, monkeypatch):
    claude = tmp_path / ".claude"
    claude.mkdir()
    path = claude / "settings.json"
    path.write_bytes(_json_bytes({"model": "opus"}))
    _claude_code_writes_on_backup(
        monkeypatch, path, [_json_bytes({"model": "opus", "theme": "dark"})]
    )
    hooks_dst = claude / "hooks" / inst.HOOKS_SUBDIR
    entries = [("Stop", None, f'python3 "{hooks_dst / "x.py"}"')]

    inst._register_settings_hooks(claude, entries)

    data = json.loads(path.read_bytes())
    assert data["theme"] == "dark", "what Claude Code wrote meanwhile was lost"
    assert data["hooks"]["Stop"]


def test_plugin_migration_keeps_what_claude_code_wrote_in_between(tmp_path, monkeypatch):
    claude = tmp_path / ".claude"
    claude.mkdir()
    path = claude / "settings.json"
    hooks_dst = claude / "hooks" / inst.HOOKS_SUBDIR
    inst._register_settings_hooks(claude, [("Stop", None, f'python3 "{hooks_dst / "x.py"}"')])
    current = json.loads(path.read_bytes())
    _claude_code_writes_on_backup(monkeypatch, path, [_json_bytes({**current, "theme": "dark"})])

    removed = plugin_migration.remove_settings_hooks(claude)

    data = json.loads(path.read_bytes())
    assert removed == 1
    assert data["theme"] == "dark", "what Claude Code wrote meanwhile was lost"
    assert not data.get("hooks", {}).get("Stop")


def test_the_pin_keeps_what_claude_code_wrote_in_between(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    entry = {"command": "uvx", "args": ["--from", f"{update.PACKAGE}==0.42.0", "local-delegate"]}
    base = {**CLAUDE_STATE, "mcpServers": {inst.SERVER_NAME: entry}}
    path.write_bytes(_json_bytes(base))
    _claude_code_writes_on_backup(monkeypatch, path, [_json_bytes({**base, "lastSession": "z"})])

    actions = [a for a in update.plan_pin(update.Options(home=tmp_path), "0.43.0")]
    failures, out = _run([a for a in actions if a.target == path])

    assert failures == 0, out
    data = json.loads(path.read_bytes())
    assert data["lastSession"] == "z", "what Claude Code wrote meanwhile was lost"
    assert f"{update.PACKAGE}==0.43.0" in data["mcpServers"][inst.SERVER_NAME]["args"]
