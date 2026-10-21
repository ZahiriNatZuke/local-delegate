"""Real shells for the completion tests (SDD cli-completion, REQ-037).

`find_shell(name)` resolves the executable of a shell, or `None`. `require_or_skip(name)` returns
it, skips the test with a reason when it is missing, or FAILS the test when the shell is listed
in `COMPLETION_TEST_REQUIRE_SHELLS` (comma separated): in CI a missing shell must not turn into a
green run. The guard in `tests/conftest.py` covers the other half: a required shell whose tests
were all deselected or skipped.

Shell names: `pwsh`, `powershell` (Windows PowerShell 5.1, Windows only), `bash` (on Windows,
the one of Git, never `System32\\bash.exe`, which is WSL), `bash3` (`/bin/bash` 3.x, macOS) and
`zsh`.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REQUIRE_ENV = "COMPLETION_TEST_REQUIRE_SHELLS"
SHELL_NAMES = ("pwsh", "powershell", "bash", "bash3", "zsh")
#: Seconds for any shell process launched by the tests.
SHELL_TIMEOUT = 120


def required_shells() -> frozenset[str]:
    raw = os.environ.get(REQUIRE_ENV, "")
    return frozenset(name.strip() for name in raw.split(",") if name.strip())


@functools.cache
def find_shell(name: str) -> str | None:
    if name not in SHELL_NAMES:
        raise ValueError(f"shell={name!r}")
    if name == "pwsh":
        return shutil.which("pwsh")
    if name == "powershell":
        return shutil.which("powershell") if sys.platform == "win32" else None
    if name == "bash":
        return _git_bash() if sys.platform == "win32" else shutil.which("bash")
    if name == "bash3":
        return _bash3()
    return shutil.which("zsh")


def _git_bash() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    candidate = Path(git).resolve().parents[1] / "bin" / "bash.exe"
    if not candidate.is_file() or "system32" in str(candidate).lower():
        return None
    return str(candidate)


def _bash3() -> str | None:
    if sys.platform == "win32" or not Path("/bin/bash").is_file():
        return None
    try:
        major = subprocess.run(
            ["/bin/bash", "-c", "echo ${BASH_VERSINFO[0]}"],
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return "/bin/bash" if major == "3" else None


def require_or_skip(name: str) -> str:
    """The executable of `name`; skip if missing, or fail if the shell is required."""
    executable = find_shell(name)
    if executable is not None:
        return executable
    if name in required_shells():
        pytest.fail(f"shell {name!r} is required by {REQUIRE_ENV} and was not found")
    pytest.skip(f"shell {name!r} not found")


def powershell_env(name: str) -> dict[str, str]:
    """Environment for a PowerShell process; 5.1 without the `PSModulePath` of pwsh 7.

    Launched from pwsh or Git Bash, `powershell.exe` inherits the module path of pwsh 7 and fails
    to load its own `Microsoft.PowerShell.Security` (research-shells §1).
    """
    env = dict(os.environ)
    if name == "powershell":
        env.pop("PSModulePath", None)
    return env


def powershell_command(executable: str, script: Path, *args: str) -> list[str]:
    return [
        executable,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *args,
    ]
