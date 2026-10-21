"""The CI declares the shells that the completion tests must run (SDD cli-completion, REQ-037).

The value goes in the `env` of the `Tests (pytest)` step as an expression on `matrix.os`, not
with `matrix.include` (which `tests/test_ci_gate.py` refuses), with the final values: Windows
`pwsh,powershell,bash`, ubuntu `bash,pwsh` and macOS `zsh,bash,bash3,pwsh`.
"""

from __future__ import annotations

from pathlib import Path

import completion_shells
import pytest
import yaml

CI_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
EXPECTED = (
    "${{ matrix.os == 'windows-latest' && 'pwsh,powershell,bash'"
    " || matrix.os == 'macos-latest' && 'zsh,bash,bash3,pwsh'"
    " || 'bash,pwsh' }}"
)
#: What the expression gives on each runner of the matrix (REQ-037).
PER_SYSTEM = {
    "windows-latest": {"pwsh", "powershell", "bash"},
    "ubuntu-latest": {"bash", "pwsh"},
    "macos-latest": {"zsh", "bash", "bash3", "pwsh"},
}


def _jobs() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]


def _step(job: dict, name: str) -> dict:
    [step] = [step for step in job["steps"] if step.get("name") == name]
    return step


def test_tests_step_requires_the_shells_per_system():
    step = _step(_jobs()["test"], "Tests (pytest)")
    assert step["env"][completion_shells.REQUIRE_ENV] == EXPECTED


def _evaluate(expression: str, os_name: str) -> str:
    """The `a && 'x' || b && 'y' || 'z'` form of GitHub expressions, for one value of matrix.os."""
    body = expression.removeprefix("${{").removesuffix("}}").strip()
    *branches, fallback = (part.strip() for part in body.split("||"))
    for branch in branches:
        condition, _, value = (part.strip() for part in branch.partition("&&"))
        if condition == f"matrix.os == '{os_name}'":
            return value.strip("'")
    return fallback.strip("'")


def test_every_system_requires_its_final_shells():
    """REQ-037: every runner of the matrix has at least one required shell, with the final set."""
    job = _jobs()["test"]
    systems = job["strategy"]["matrix"]["os"]
    assert set(systems) == set(PER_SYSTEM)
    for os_name in systems:
        value = _evaluate(EXPECTED, os_name)
        names = set(value.split(","))
        assert names == PER_SYSTEM[os_name], os_name
        assert names <= set(completion_shells.SHELL_NAMES)


def test_render_tests_run_in_the_python_matrix():
    step = _step(_jobs()["cli-python-matrix"], "CLI tests (pytest)")
    assert "tests/test_completion_render.py" in step["run"].split()


def _outcome(name: str) -> tuple[type, str]:
    """How `require_or_skip(name)` ends; caught here so a skip cannot skip the test itself."""
    try:
        completion_shells.require_or_skip(name)
    except (pytest.fail.Exception, pytest.skip.Exception) as exc:
        return type(exc), str(exc)
    raise AssertionError("require_or_skip returned with no shell")


def test_helper_fails_a_required_missing_shell_and_skips_the_rest(monkeypatch):
    """REQ-037: the helper fails when the missing shell is required, and skips it otherwise."""
    monkeypatch.setattr(completion_shells, "find_shell", lambda name: None)
    monkeypatch.setenv(completion_shells.REQUIRE_ENV, "zsh, pwsh")
    kind, message = _outcome("zsh")
    assert kind is pytest.fail.Exception
    assert "'zsh' is required" in message
    assert _outcome("bash") == (pytest.skip.Exception, "shell 'bash' not found")
    monkeypatch.setenv(completion_shells.REQUIRE_ENV, "")
    assert _outcome("zsh")[0] is pytest.skip.Exception


def test_windows_bash_is_never_the_one_of_system32(monkeypatch, tmp_path):
    """REQ-037: on Windows, `bash` is derived from Git, never `System32\bash.exe` (WSL)."""
    git = tmp_path / "Git" / "cmd" / "git.exe"
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    for path in (git, bash):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"")
    monkeypatch.setattr(completion_shells.shutil, "which", lambda name: str(git))
    assert completion_shells._git_bash() == str(bash.resolve())
    wsl = tmp_path / "System32" / "cmd" / "git.exe"
    (tmp_path / "System32" / "bin").mkdir(parents=True)
    (tmp_path / "System32" / "bin" / "bash.exe").write_bytes(b"")
    wsl.parent.mkdir(parents=True)
    wsl.write_bytes(b"")
    monkeypatch.setattr(completion_shells.shutil, "which", lambda name: str(wsl))
    assert completion_shells._git_bash() is None


def test_windows_bash_from_a_git_two_levels_below_the_root(monkeypatch, tmp_path):
    """From a Git Bash session `git` is `<root>/ucrt64/bin/git.exe`: the root is two levels up."""
    git = tmp_path / "Git" / "ucrt64" / "bin" / "git.exe"
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    for path in (git, bash):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    monkeypatch.setattr(completion_shells.shutil, "which", lambda name: str(git))
    assert completion_shells._git_bash() == str(bash.resolve())
    bash.unlink()  # control: without `<root>\bin\bash.exe` there is no bash
    assert completion_shells._git_bash() is None
