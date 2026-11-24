"""A PowerShell that crashes at startup is skipped with a warning, not failed (SDD ci-root-cause).

On 2026-11-03 the `pwsh` of the Ubuntu runner image aborted before running any script (`exit=-6`,
`System.IO.FileLoadException`), and the required-shell guard turned that into 28 red tests in two
runs with nothing of the repo involved. The controls: a shell that starts is not skipped, and a
required shell that is simply missing still fails.
"""

from __future__ import annotations

import subprocess

import completion_shells
import pytest

CRASH = subprocess.CompletedProcess(
    ["pwsh"],
    -6,
    stdout="",
    stderr=(
        "Unhandled exception. System.IO.FileLoadException: The given assembly name was invalid.\n"
        "File name: 'System.Collections.Specialized, Version=10.0.0.0'\n"
    ),
)


def _fake_runs(monkeypatch, *answers: subprocess.CompletedProcess) -> list[list[str]]:
    calls: list[list[str]] = []
    queue = list(answers)

    def run(cmd, env):
        calls.append(cmd)
        return queue.pop(0)

    monkeypatch.setattr(completion_shells, "_run_probe", run)
    completion_shells.startup_failure.cache_clear()
    return calls


@pytest.fixture(autouse=True)
def _fresh_cache():
    completion_shells.startup_failure.cache_clear()
    yield
    completion_shells.startup_failure.cache_clear()


def test_a_pwsh_that_aborts_at_startup_is_reported_with_its_version(monkeypatch):
    version = subprocess.CompletedProcess(["pwsh"], 0, stdout="PowerShell 7.5.4\n", stderr="")
    calls = _fake_runs(monkeypatch, CRASH, version)
    reason = completion_shells.startup_failure("pwsh", "/usr/bin/pwsh")
    assert reason is not None
    assert "PowerShell 7.5.4" in reason
    assert "exit -6" in reason
    assert "FileLoadException" in reason
    assert calls[0][-1] == "$PSVersionTable.PSVersion.ToString()"


def test_control_a_pwsh_that_starts_is_not_reported(monkeypatch):
    _fake_runs(monkeypatch, subprocess.CompletedProcess(["pwsh"], 0, stdout="7.5.4\n", stderr=""))
    assert completion_shells.startup_failure("pwsh", "/usr/bin/pwsh") is None


@pytest.mark.parametrize(
    "probe",
    [
        subprocess.CompletedProcess(["pwsh"], 1, stdout="", stderr="ParserError: bad profile\n"),
        subprocess.CompletedProcess(["pwsh"], 0, stdout="", stderr=""),
    ],
)
def test_control_a_failure_that_is_not_the_image_crash_is_not_skipped(monkeypatch, probe):
    """Only the .NET abort of the image is forgiven; any other failure must fail its tests."""
    _fake_runs(monkeypatch, probe)
    assert completion_shells.startup_failure("pwsh", "/usr/bin/pwsh") is None


def test_the_probe_does_not_go_through_the_product(monkeypatch):
    seen = []

    def run(cmd, env):
        seen.append(env)
        return subprocess.CompletedProcess(cmd, 0, stdout="7.5.4", stderr="")

    monkeypatch.setattr(completion_shells, "_run_probe", run)
    monkeypatch.setattr(completion_shells, "powershell_env", lambda name: pytest.fail("product"))
    assert completion_shells.startup_failure("pwsh", "/usr/bin/pwsh") is None
    assert seen


def test_shells_that_are_not_powershell_are_not_probed(monkeypatch):
    calls = _fake_runs(monkeypatch)
    assert completion_shells.startup_failure("bash", "/bin/bash") is None
    assert calls == []


def test_a_required_pwsh_that_crashes_is_skipped_not_failed(monkeypatch):
    monkeypatch.setattr(completion_shells, "find_shell", lambda name: "/usr/bin/pwsh")
    monkeypatch.setenv(completion_shells.REQUIRE_ENV, "bash,pwsh")
    _fake_runs(monkeypatch, CRASH, CRASH)
    with pytest.raises(pytest.skip.Exception) as caught:
        completion_shells.require_or_skip("pwsh")
    assert completion_shells.broken_shell_of(str(caught.value)) == "pwsh"


def test_control_a_required_missing_shell_still_fails(monkeypatch):
    monkeypatch.setattr(completion_shells, "find_shell", lambda name: None)
    monkeypatch.setenv(completion_shells.REQUIRE_ENV, "pwsh")
    with pytest.raises(pytest.fail.Exception):
        completion_shells.require_or_skip("pwsh")


def test_the_guard_warns_for_a_broken_shell_and_fails_for_a_missing_one():
    required = frozenset({"bash", "pwsh", "zsh"})
    fail, warn = completion_shells.required_without_pass(required, {"bash": 3}, {"pwsh"})
    assert fail == ["zsh"]
    assert warn == ["pwsh"]


def test_the_skip_reason_is_read_back_from_a_report():
    reason = "('tests/x.py', 12, \"Skipped: shell 'pwsh' crashes at startup (version 7.5.4)\")"
    assert completion_shells.broken_shell_of(reason) == "pwsh"
    assert completion_shells.broken_shell_of("Skipped: shell 'pwsh' not found") is None


def test_a_reason_with_double_quotes_is_still_read_through_the_report():
    """`str` of the tuple escapes the single quotes when the reason holds a double one."""
    reason = "Skipped: shell 'pwsh' crashes at startup (version 7.5.4, exit -6: \"x\")"
    assert completion_shells.broken_shell_of(str(("t.py", 1, reason))) is None
    assert completion_shells.broken_shell_of(("t.py", 1, reason)[2]) == "pwsh"
