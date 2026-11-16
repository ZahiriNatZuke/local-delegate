#!/usr/bin/env python3
"""Checks the Codex hooks of `install`/`uninstall` against a real Codex (issue #669, REQ-010).

Usage: ``python scripts/dev/codex_hooks_live.py [<scratch dir>]`` with ``codex`` on the PATH.

Everything happens under a temporary ``CODEX_HOME``: the real ``~/.codex`` is never read by Codex
here nor written by `install`, and the script prints the hashes of its ``config.toml`` and
``hooks.json`` before and after to show it. It asks ``codex app-server`` for ``hooks/list`` (what
``/hooks`` shows) after each step:

1. a user's ``hooks.json`` with a group of their own, then ``install`` twice (the second writes
   nothing);
2. a second group of the user's behind ours, then ``uninstall``: the user's keeps its key;
3. ``install`` again: ours goes back to its index;
4. a file with a UTF-8 BOM: Codex rejects it and ``install`` refuses to write it.

It also compares the key `codex_hooks.hook_key` computes (what `doctor` counts as approved) with
the key Codex lists. It does not approve anything: approval stays with the person, in ``/hooks``.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

LIST_TIMEOUT_S = 40
START_WAIT_S = 3
USER_BASH = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo user-bash"}]}
USER_PROMPT = {"hooks": [{"type": "command", "command": "echo user-prompt"}]}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"


def hooks_list(codex_home: Path, cwd: Path) -> dict:
    """`hooks/list` of a fresh `codex app-server`, killed before returning."""
    exe = shutil.which("codex")
    if exe is None:
        raise SystemExit("codex is not on the PATH")
    proc = subprocess.Popen(
        [exe, "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=dict(os.environ, CODEX_HOME=str(codex_home)),
        cwd=cwd,
        text=True,
        encoding="utf-8",
    )
    lines: list[str] = []
    threading.Thread(target=lambda: lines.extend(proc.stdout), daemon=True).start()

    def send(message: dict) -> None:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "probe", "version": "0"}},
            }
        )
        time.sleep(START_WAIT_S)
        send({"method": "initialized"})
        send({"id": 2, "method": "hooks/list", "params": {"cwds": [str(cwd)]}})
        deadline = time.time() + LIST_TIMEOUT_S
        while time.time() < deadline:
            for line in lines.copy():  # the reader thread keeps appending
                if '"id":2' in line:
                    return json.loads(line).get("result", {}).get("data", [{}])[0]
            time.sleep(0.5)
        return {"errors": ["no answer to hooks/list"]}
    finally:
        proc.kill()
        proc.wait(timeout=10)


def show(title: str, entry: dict) -> list[dict]:
    print(f"\n== {title}")
    hooks = entry.get("hooks", [])
    for hook in hooks:
        print(f"  {hook.get('key')}  trust={hook.get('trustStatus')}  cmd={hook.get('command')}")
    print("  warnings:", entry.get("warnings"))
    print("  errors:", entry.get("errors"))
    return hooks


def main() -> int:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="ld669-"))
    # The install writes nothing of its own data here, but just in case: never the real log dir.
    os.environ["LOCAL_DELEGATE_LOG_DIR"] = str(scratch / "data")
    from local_delegate import claude_plugin, codex_hooks, install

    real = [Path.home() / ".codex" / "config.toml", Path.home() / ".codex" / "hooks.json"]
    before = {str(path): digest(path) for path in real}

    # A fresh HOME each run: Codex leaves read-only files under `.codex/.tmp`.
    scratch.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="home-", dir=scratch))
    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True)
    cwd = scratch / "cwd"
    cwd.mkdir(exist_ok=True)
    path = codex_dir / codex_hooks.HOOKS_FILE_NAME
    path.write_text(json.dumps({"hooks": {"PreToolUse": [USER_BASH]}}, indent=2) + "\n", "utf-8")
    ld_bin = claude_plugin.LdBin(sys.executable, None)

    def options() -> install.Options:
        return install.Options(
            home=home,
            components={"hooks"},
            targets={"codex"},
            python_exe="python",
            use_cli=False,
            write_language=False,
            claude_ld_bin=ld_bin,
        )

    failures: list[str] = []

    def expect(condition: bool, what: str) -> None:
        print(("  OK   " if condition else "  FAIL ") + what)
        if not condition:
            failures.append(what)

    print("install 1 ->", install.apply(install.plan_install(options()), dry_run=False))
    first = path.read_bytes()
    print("install 2 ->", install.apply(install.plan_install(options()), dry_run=False))
    expect(path.read_bytes() == first, "the second install writes nothing")
    entry = hooks_list(codex_dir, cwd)
    hooks = show("after install", entry)
    listed = {hook.get("key") for hook in hooks}
    expect(not entry.get("errors") and not entry.get("warnings"), "the file loads cleanly")
    user_bash = f"{path}:pre_tool_use:0:0"  # `EVENT_LABELS` only knows our events
    expect(user_bash in listed, f"the user's group keeps its key {user_bash}")
    for event in ("UserPromptSubmit", "SubagentStart"):
        ours = codex_hooks.hook_key(path, event, 0)
        expect(ours in listed, f"Codex lists our key {ours}")
    expect(all(hook.get("trustStatus") == "untrusted" for hook in hooks), "everything is untrusted")

    data = json.loads(path.read_text("utf-8"))
    data["hooks"]["UserPromptSubmit"].append(USER_PROMPT)
    path.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
    user_key = codex_hooks.hook_key(path, "UserPromptSubmit", 1)
    print("uninstall ->", install.apply(install.plan_uninstall(options()), dry_run=False))
    entry = hooks_list(codex_dir, cwd)
    hooks = show("after uninstall, with a group of the user's behind ours", entry)
    keys = {hook.get("key") for hook in hooks}
    expect(user_key in keys, f"the user's group keeps its key {user_key}")
    expect(not entry.get("errors") and not entry.get("warnings"), "the hole loads cleanly")
    expect(
        not any("local_delegate.hook" in str(hook.get("command")) for hook in hooks),
        "none of ours left",
    )

    print("install 3 ->", install.apply(install.plan_install(options()), dry_run=False))
    hooks = show("after installing again", hooks_list(codex_dir, cwd))
    keys = {hook.get("key") for hook in hooks}
    expect(codex_hooks.hook_key(path, "UserPromptSubmit", 0) in keys, "ours is back at index 0")
    expect(user_key in keys, "the user's group still has its key")

    path.write_bytes(codecs.BOM_UTF8 + path.read_bytes())
    with_bom = path.read_bytes()
    entry = hooks_list(codex_dir, cwd)
    hooks = show("a hooks.json with a BOM", entry)
    expect(not hooks, "Codex loads no hook of a file with a BOM")
    expect(bool(entry.get("warnings") or entry.get("errors")), "and Codex says so")
    code = install.apply(install.plan_install(options()), dry_run=False)
    expect(
        code == 0 and path.read_bytes() == with_bom,
        "install leaves it as it was, says why and does not fail",
    )

    after = {str(p): digest(p) for p in real}
    print("\nreal ~/.codex before:", before)
    print("real ~/.codex after: ", after)
    expect(before == after, "the real ~/.codex did not change")
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
