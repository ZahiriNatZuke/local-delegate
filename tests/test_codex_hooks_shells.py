"""Issue #718: the line of each Codex hook starts the interpreter in the shells Codex may use.

Codex runs a hook `command` with the shell of the session (`build_hooks_config` in
`core/src/session/mod.rs` → `Shell::derive_exec_args` in `core/src/shell.rs`):
`<pwsh> -NoProfile -Command <line>`, `<cmd> /c <line>` or `<bash> -c <line>`. On Windows the
default is PowerShell, where a line that starts with a quoted path is a `ParserError` and no
process starts. These tests run the generated line exactly that way, with a fake interpreter: a
venv whose `local_delegate.hook` only writes its `argv` to a marker file. A marker means the
interpreter started; its absence, that the shell never launched it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest
from completion_shells import find_shell, powershell_env, require_or_skip

from local_delegate import codex_hooks

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Codex shells on Windows")

TIMEOUT_S = 120
MARKER_VAR = "LD_FAKE_HOOK_MARKER"
FAKE_HOOK = (
    "import json, os, sys\n"
    "with open(os.environ['LD_FAKE_HOOK_MARKER'], 'w', encoding='utf-8') as f:\n"
    "    json.dump(sys.argv, f)\n"
)


def _fake_interpreter(folder: Path) -> str:
    """A venv in ``folder`` with a `local_delegate.hook` that writes its argv to the marker."""
    venv.EnvBuilder(symlinks=False).create(folder)
    package = folder / "Lib" / "site-packages" / "local_delegate"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "hook.py").write_text(FAKE_HOOK, "utf-8")
    exe = folder / "Scripts" / "python.exe"
    assert exe.is_file(), exe
    return str(exe)


@pytest.fixture(scope="module")
def safe_python(tmp_path_factory) -> str:
    return _fake_interpreter(tmp_path_factory.mktemp("safe") / "venv")


@pytest.fixture(scope="module")
def spaced_python(tmp_path_factory) -> str:
    return _fake_interpreter(tmp_path_factory.mktemp("spaced") / "uv tools" / "venv")


def _argv(shell: str, line: str) -> tuple[list[str] | str, dict[str, str] | None]:
    """What `derive_exec_args(line, false)` gives for ``shell``, quoted as Codex quotes it.

    `hooks/src/engine/command_runner.rs`, `build_command`: with `/c` among the arguments the line
    goes as a raw argument between double quotes (`raw_arg`); otherwise as one argument, quoted
    by the usual rules (what `subprocess` does with a list).
    """
    if shell in ("pwsh", "powershell"):
        exe = require_or_skip(shell)
        return [exe, "-NoProfile", "-Command", line], powershell_env(shell)
    if shell == "cmd":
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return f'"{comspec}" /c "{line}"', None
    return [require_or_skip(shell), "-c", line], None


def _starts(shell: str, line: str, tmp_path: Path) -> tuple[bool, str]:
    marker = tmp_path / f"marker-{shell}.json"
    argv, env = _argv(shell, line)
    env = {**(env if env is not None else os.environ), MARKER_VAR: str(marker)}
    result = subprocess.run(
        argv, input=b"{}", capture_output=True, env=env, timeout=TIMEOUT_S, check=False
    )
    if not marker.is_file():
        return False, result.stderr.decode("utf-8", "replace")
    assert json.loads(marker.read_text("utf-8"))[-1] == "codex-prompt"
    return True, ""


ALL_SHELLS = [
    pytest.param("pwsh", marks=pytest.mark.shell("pwsh")),
    pytest.param("powershell", marks=pytest.mark.shell("powershell")),
    pytest.param("cmd"),
    pytest.param("bash", marks=pytest.mark.shell("bash")),
]
POWERSHELL_ONLY = [
    pytest.param("pwsh", marks=pytest.mark.shell("pwsh")),
    pytest.param("powershell", marks=pytest.mark.shell("powershell")),
]


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_the_line_starts_in_every_shell(safe_python, shell, tmp_path):
    """REQ-001: a path without spaces goes bare and starts in the four shells."""
    line = codex_hooks.command(safe_python, "codex-prompt")
    assert not codex_hooks.starts_quoted(line), line
    started, stderr = _starts(shell, line, tmp_path)
    assert started, f"{shell} did not start {line!r}: {stderr}"


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_a_path_with_spaces_starts(spaced_python, shell, tmp_path):
    """REQ-002: the 8.3 name starts everywhere; without one, `& '…'` starts in PowerShell."""
    line = codex_hooks.command(spaced_python, "codex-prompt")
    if line.startswith("& ") and shell in ("cmd", "bash"):
        pytest.skip("no 8.3 name on this volume: the fallback form is PowerShell's")
    started, stderr = _starts(shell, line, tmp_path)
    assert started, f"{shell} did not start {line!r}: {stderr}"


@pytest.mark.parametrize("shell", POWERSHELL_ONLY)
def test_without_a_short_name_the_call_operator_starts_in_powershell(
    spaced_python, shell, tmp_path, monkeypatch
):
    """REQ-002, the fallback forced: a volume without 8.3 names."""
    monkeypatch.setattr(codex_hooks, "short_path", lambda path: None)
    line = codex_hooks.command(spaced_python, "codex-prompt")
    assert line.startswith("& '"), line
    started, stderr = _starts(shell, line, tmp_path)
    assert started, f"{shell} did not start {line!r}: {stderr}"


@pytest.mark.parametrize("shell", POWERSHELL_ONLY)
def test_control_the_old_quoted_line_does_not_start_in_powershell(safe_python, shell, tmp_path):
    """Control: the line of 0.54.0 fails where #718 saw it fail, so the tests above discriminate."""
    old = '"' + safe_python.replace("\\", "/") + '" -I -m local_delegate.hook codex-prompt'
    started, _stderr = _starts(shell, old, tmp_path)
    assert not started


def test_control_the_old_quoted_line_does_start_in_cmd(safe_python, tmp_path):
    """Control: the fake interpreter itself works, so a missing marker above is the shell."""
    old = '"' + safe_python.replace("\\", "/") + '" -I -m local_delegate.hook codex-prompt'
    started, stderr = _starts("cmd", old, tmp_path)
    assert started, stderr


def test_bash_is_found_where_the_guard_requires_it():
    """`find_shell("bash")` must be Git Bash's, not the WSL launcher, or `-c` runs elsewhere."""
    exe = find_shell("bash")
    if exe is None:
        pytest.skip("no bash")
    assert "system32" not in exe.lower(), exe
