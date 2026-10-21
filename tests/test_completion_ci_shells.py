"""The CI declares the shells that the completion tests must run (SDD cli-completion, REQ-037).

The value goes in the `env` of the `Tests (pytest)` step as an expression on `matrix.os`, not
with `matrix.include` (which `tests/test_ci_gate.py` refuses). L2a: provisional values; L2b sets
the final ones (`pwsh,powershell,bash` / `bash,pwsh` / `zsh,bash,bash3,pwsh`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from completion_shells import REQUIRE_ENV

CI_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
EXPECTED = "${{ matrix.os == 'windows-latest' && 'pwsh,powershell' || 'pwsh' }}"


def _jobs() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]


def _step(job: dict, name: str) -> dict:
    [step] = [step for step in job["steps"] if step.get("name") == name]
    return step


def test_tests_step_requires_the_shells_per_system():
    step = _step(_jobs()["test"], "Tests (pytest)")
    assert step["env"][REQUIRE_ENV] == EXPECTED


def test_render_tests_run_in_the_python_matrix():
    step = _step(_jobs()["cli-python-matrix"], "CLI tests (pytest)")
    assert "tests/test_completion_render.py" in step["run"].split()


def _outcome(name: str) -> tuple[type, str]:
    """How `require_or_skip(name)` ends; caught here so a skip cannot skip the test itself."""
    import completion_shells

    try:
        completion_shells.require_or_skip(name)
    except (pytest.fail.Exception, pytest.skip.Exception) as exc:
        return type(exc), str(exc)
    raise AssertionError("require_or_skip returned with no shell")


def test_helper_fails_a_required_missing_shell_and_skips_the_rest(monkeypatch):
    """REQ-037: the helper fails when the missing shell is required, and skips it otherwise."""
    import completion_shells

    monkeypatch.setattr(completion_shells, "find_shell", lambda name: None)
    monkeypatch.setenv(REQUIRE_ENV, "zsh, pwsh")
    kind, message = _outcome("zsh")
    assert kind is pytest.fail.Exception
    assert "'zsh' is required" in message
    assert _outcome("bash") == (pytest.skip.Exception, "shell 'bash' not found")
    monkeypatch.setenv(REQUIRE_ENV, "")
    assert _outcome("zsh")[0] is pytest.skip.Exception


def test_windows_bash_is_never_the_one_of_system32(monkeypatch, tmp_path):
    """REQ-037: on Windows, `bash` is derived from Git, never `System32\bash.exe` (WSL)."""
    import completion_shells

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
