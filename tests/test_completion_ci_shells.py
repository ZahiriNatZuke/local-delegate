"""The CI declares the shells that the completion tests must run (SDD cli-completion, REQ-037).

The value goes in the `env` of the `Tests (pytest)` step as an expression on `matrix.os`, not
with `matrix.include` (which `tests/test_ci_gate.py` refuses), with the final values: Windows
`pwsh,powershell,bash`, ubuntu `bash,pwsh` and macOS `zsh,bash,bash3,pwsh`.
"""

from __future__ import annotations

import importlib.util
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


# --- `PSModulePath` and the execution policy of the real-shell launches -------------------------
#: What `os.environ` looks like on Windows: the keys come upper case, whatever the system spells.
MODULE_PATH_KEY = "PSModulePath".upper()
WINDOWS_ENVIRON = {MODULE_PATH_KEY: r"C:\pwsh7\Modules", "PATH": r"C:\bin", "HOME": r"C:\h"}


def _e2e_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_install_e2e.py"
    spec = importlib.util.spec_from_file_location("check_install_e2e", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("environ", [WINDOWS_ENVIRON, {**WINDOWS_ENVIRON, "PSModulePath": "x"}])
def test_helper_drops_the_module_path_for_51_in_any_case(environ):
    """5.1 never inherits the module path of pwsh 7, spelled upper case (Windows) or not; pwsh
    keeps it. Positive control (checked): with the old `env.pop("PSModulePath", None)`, the
    upper-case `PSMODULEPATH` survives and the first assert fails."""
    env = completion_shells.powershell_env("powershell", environ)
    assert not {key for key in env if key.upper() == MODULE_PATH_KEY}
    assert env["PATH"] == r"C:\bin"
    assert completion_shells.powershell_env("pwsh", environ)[MODULE_PATH_KEY] == r"C:\pwsh7\Modules"


def test_e2e_drops_the_module_path_for_51_in_any_case(monkeypatch, tmp_path):
    """The same rule in `scripts/check_install_e2e.py`. Positive control (checked): with the old
    `env.pop("PSModulePath", None)`, `PSMODULEPATH` survives in the 5.1 environment."""
    e2e = _e2e_module()
    monkeypatch.setattr(e2e.os, "environ", dict(WINDOWS_ENVIRON))
    env = e2e._shell_env(tmp_path, windows_powershell=True)
    assert not {key for key in env if key.upper() == MODULE_PATH_KEY}
    assert env["HOME"] == str(tmp_path)
    assert MODULE_PATH_KEY in e2e._shell_env(tmp_path)


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("RemoteSigned", ()),
        ("Unrestricted", ()),
        ("Restricted", ("-ExecutionPolicy", "Bypass")),
        ("AllSigned", ("-ExecutionPolicy", "Bypass")),
        (None, ("-ExecutionPolicy", "Bypass")),
    ],
)
def test_policy_override_only_when_the_real_policy_blocks(monkeypatch, policy, expected):
    """`Bypass` is added only when the effective policy would not run the script (or is unknown),
    in the helper and in the E2E. Positive control: always returning `Bypass` (the old fixed
    argument) fails the `RemoteSigned` and `Unrestricted` cases."""
    answer = lambda executable, **_: (None, policy)
    monkeypatch.setattr(completion_shells.shell_profiles, "query_powershell", answer)
    completion_shells.execution_policy_args.cache_clear()
    try:
        assert completion_shells.execution_policy_args("powershell.exe") == expected
        command = completion_shells.powershell_command("powershell.exe", Path("s.ps1"))
        assert ("Bypass" in command) == bool(expected)
    finally:
        completion_shells.execution_policy_args.cache_clear()
    assert tuple(_e2e_module()._execution_policy_args("powershell.exe")) == expected
