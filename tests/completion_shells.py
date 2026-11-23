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
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from local_delegate import shell_profiles

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
    """`<Git root>\\bin\\bash.exe`, with `git` in `cmd\\`, `bin\\` or `<mingw64|ucrt64>\\bin\\`.

    The same two roots as `shell_profiles.git_bash`. From a Git Bash session `git` resolves to
    `ucrt64\\bin\\git.exe`, two levels below the root.
    """
    git = shutil.which("git")
    if git is None:
        return None
    resolved = Path(git).resolve()
    for root in (resolved.parents[1], resolved.parents[2]):
        candidate = root / "bin" / "bash.exe"
        if candidate.is_file() and "system32" not in str(candidate).lower():
            return str(candidate)
    return None


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


#: The prefix of the skip of a shell that crashes at startup; `tests/conftest.py` reads it back from
#: the report to turn its guard into a warning (SDD ci-root-cause, REQ-007).
STARTUP_CRASH = "crashes at startup"
_STARTUP_CRASH_RE = re.compile(rf"shell '(\w+)' {STARTUP_CRASH}")
_PROBE = "$PSVersionTable.PSVersion.ToString()"
#: The signature of the image's crash: the .NET runtime aborting (SIGABRT, `exit=-6` or 134) or
#: failing to load its own assemblies. Any other failure to start is a real failure, not a skip.
_IMAGE_CRASH_CODES = frozenset({-6, 134})
_IMAGE_CRASH_TEXT = ("FileLoadException", "Unhandled exception")


def _run_probe(cmd: list[str], env: Mapping[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        env=dict(env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SHELL_TIMEOUT,
        stdin=subprocess.DEVNULL,
        check=False,
    )


@functools.cache
def startup_failure(name: str, executable: str) -> str | None:
    """`None` when a PowerShell starts; otherwise why not, with the version it claims.

    On 2026-11-03 the `pwsh` of the Ubuntu image aborted before running any script (`exit=-6`,
    `System.IO.FileLoadException` loading `System.Collections.Specialized`): 28 red tests in two
    runs with nothing of the repo involved. A shell that starts and then fails is NOT this: the
    probe only asks for its version.
    """
    if name not in ("pwsh", "powershell"):
        return None
    # The runner's own environment, not `powershell_env`: that goes through the product
    # (`shell_profiles`), and a regression there must fail the tests, not skip them.
    env = os.environ
    try:
        probe = _run_probe([executable, "-NoProfile", "-NonInteractive", "-Command", _PROBE], env)
    except (OSError, subprocess.TimeoutExpired):
        return None  # not the image's signature: let the tests run and fail for real
    if probe.returncode == 0 and probe.stdout.strip():
        return None
    if probe.returncode not in _IMAGE_CRASH_CODES and not any(
        text in probe.stderr for text in _IMAGE_CRASH_TEXT
    ):
        return None
    version = "5.1" if name == "powershell" else "unknown"
    if name == "pwsh":  # `pwsh -Version` prints it from the native host; 5.1 reads it as an option
        try:
            version = _run_probe([executable, "-Version"], env).stdout.strip() or version
        except (OSError, subprocess.TimeoutExpired) as exc:
            version = f"unknown ({type(exc).__name__})"
    first = next((line for line in probe.stderr.splitlines() if line.strip()), "")
    return f"version {version}, exit {probe.returncode}: {first[:200]}"


def broken_shell_of(skip_reason: str) -> str | None:
    """The shell whose skip says it crashed at startup, or `None`."""
    match = _STARTUP_CRASH_RE.search(skip_reason)
    return match.group(1) if match else None


def required_without_pass(
    required: frozenset[str], passes: Mapping[str, int], broken: set[str]
) -> tuple[list[str], list[str]]:
    """(shells that fail the guard, shells that only warn because they crash at startup)."""
    missing = sorted(name for name in required if not passes.get(name))
    return [n for n in missing if n not in broken], [n for n in missing if n in broken]


def require_or_skip(name: str) -> str:
    """The executable of `name`; skip if missing, or fail if the shell is required.

    A PowerShell that crashes at startup is skipped even when required, with a reason that names its
    version: that is the runner image, not the repo. The guard of `tests/conftest.py` reports it as
    a warning.
    """
    executable = find_shell(name)
    if executable is not None:
        reason = startup_failure(name, executable)
        if reason is not None:
            raise pytest.skip.Exception(f"shell {name!r} {STARTUP_CRASH} ({reason})")
        return executable
    if name in required_shells():
        raise pytest.fail.Exception(
            f"shell {name!r} is required by {REQUIRE_ENV} and was not found"
        )
    raise pytest.skip.Exception(f"shell {name!r} not found")


def powershell_env(name: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for a PowerShell process; 5.1 without the `PSModulePath` of pwsh 7.

    Launched from pwsh or Git Bash, `powershell.exe` inherits the module path of pwsh 7 and fails
    to load its own `Microsoft.PowerShell.Security` (research-shells §1). On Windows the keys of
    `os.environ` are upper case, so the variable is dropped with the product's case-insensitive
    rule (`shell_profiles.query_environment`), not with `dict.pop("PSModulePath")`.
    """
    return shell_profiles.query_environment(name, os.environ if environ is None else environ)


def _run_policy_query(cmd: list[str], *, env: Mapping[str, str], timeout: float):
    """Real runner for the policy query. Passed explicitly because `tests/conftest.py` replaces
    the product's default runner with one that fails (no unit test may ask the real shell)."""
    return subprocess.run(
        cmd,
        env=dict(env),
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )


@functools.cache
def execution_policy_args(executable: str) -> tuple[str, ...]:
    """`-ExecutionPolicy Bypass` only when the real effective policy would not run the script.

    The policy is asked with the product's query (REQ-025); an unknown answer also gets `Bypass`,
    so a broken query never turns into a red test for the wrong reason.
    """
    _, policy = shell_profiles.query_powershell(executable, run=_run_policy_query)
    if policy is None or shell_profiles.policy_blocks(policy):
        return ("-ExecutionPolicy", "Bypass")
    return ()


def powershell_command(executable: str, script: Path, *args: str) -> list[str]:
    return [
        executable,
        "-NoProfile",
        "-NonInteractive",
        *execution_policy_args(executable),
        "-File",
        str(script),
        *args,
    ]
