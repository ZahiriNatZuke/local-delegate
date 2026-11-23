"""`scripts/check_local.py`, el bump que regenera y el release que se niega (SDD ci-root-cause).

REQ-008: lo generado que el CI comprueba (huellas de los hooks, versión de la captura del README,
nombres y catálogo) falla en local, al hacer el commit; `bump_version.py <versión>` lo regenera
siempre; `release.py` no publica con ello viejo. Cada caso que da OK tiene su control que falla.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"

if not (SCRIPTS / "check_local.py").is_file():
    pytest.skip("scripts/ no está en el árbol (sdist)", allow_module_level=True)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_test_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_local = _load("check_local")
bump_version = _load("bump_version")
release = _load("release")


def _repo(tmp_path: Path, *, version: str = "1.2.3", captured: str = "1.2.3") -> Path:
    """Un árbol mínimo: hooks, el conjunto de huellas al día, `pyproject.toml` y dos manifiestos."""
    hooks = tmp_path / bump_version.HOOKS_DIR
    shutil.copytree(
        ROOT / bump_version.HOOKS_DIR, hooks, ignore=shutil.ignore_patterns("__pycache__")
    )
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(SCRIPTS / "bump_version.py", tmp_path / "scripts" / "bump_version.py")
    shutil.copyfile(SCRIPTS / "check_local.py", tmp_path / "scripts" / "check_local.py")
    target = tmp_path / bump_version.HOOK_HASHES_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / bump_version.HOOK_HASHES_FILE, target)
    bump_version.update_boundaries(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8"
    )
    for rel in check_local.CAPTURE_MANIFESTS:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": captured}), encoding="utf-8")
    return tmp_path


def _names_ok(_root):
    return subprocess.CompletedProcess([], 0, stdout="2 passed", stderr="")


def _names_red(_root):
    return subprocess.CompletedProcess(
        [],
        1,
        stdout="E   palabras sin clasificar:\nE     tainted (tests/x.py:3)\n1 failed",
        stderr="",
    )


def _touch_hook(root: Path) -> str:
    name = bump_version.HASHED_HOOKS[0]
    hook = root / bump_version.HOOKS_DIR / name
    hook.write_text(hook.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8")
    return name


# --- check_local -------------------------------------------------------------------------------


def test_an_up_to_date_tree_passes(tmp_path):
    assert check_local.run_checks(_repo(tmp_path), names=_names_ok) == []


def test_control_a_touched_hook_is_caught_with_its_remedy(tmp_path):
    root = _repo(tmp_path)
    name = _touch_hook(root)
    problems = check_local.run_checks(root, names=_names_ok)
    assert len(problems) == 1
    assert name in problems[0] and "--boundaries" in problems[0]


def test_fix_joins_the_footprint_and_still_asks_to_stage_it(tmp_path):
    root = _repo(tmp_path)
    _touch_hook(root)
    problems = check_local.run_checks(root, fix=True, names=_names_ok)
    assert "regeneradas" in problems[0] and "hook_hashes_after.json" in problems[0]
    assert check_local.stale_boundaries(root) == {}
    assert check_local.run_checks(root, names=_names_ok) == []


def test_control_a_capture_of_the_previous_version_is_caught(tmp_path):
    root = _repo(tmp_path, version="1.3.0", captured="1.2.3")
    problems = check_local.run_checks(root, names=_names_ok)
    assert len(problems) == 1
    assert "1.3.0" in problems[0] and "dice 1.2.3" in problems[0]
    assert "bump_version.py" in problems[0]


def test_control_a_red_name_or_catalog_test_is_reported_with_its_output(tmp_path):
    problems = check_local.run_checks(_repo(tmp_path), names=_names_red)
    assert len(problems) == 1
    assert "tainted (tests/x.py:3)" in problems[0]


def test_the_name_and_catalog_checks_are_the_ci_tests():
    for node in check_local.NAME_AND_CATALOG_TESTS:
        path, _, name = node.partition("::")
        assert f"def {name}(" in (ROOT / path).read_text(encoding="utf-8"), node


def test_the_real_tree_has_its_footprints_and_captures_up_to_date():
    assert check_local.stale_boundaries(ROOT) == {}
    assert check_local.stale_captures(ROOT) == {}


def test_pre_commit_runs_the_script_with_fix():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}
    hook = hooks["check-local"]
    assert hook["entry"] == "uv run python scripts/check_local.py --fix"
    assert hook["pass_filenames"] is False


# --- bump_version regenerates; release refuses -----------------------------------------------


def test_a_bump_regenerates_footprints_and_captures(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bump_version, "plan", lambda version: {})
    monkeypatch.setattr(bump_version, "read_versions", dict)
    monkeypatch.setattr(bump_version, "relock", lambda: calls.append("lock"))
    monkeypatch.setattr(bump_version, "update_boundaries", lambda root: calls.append("hooks"))
    monkeypatch.setattr(bump_version, "regenerate_captures", lambda root: calls.append("capture"))
    monkeypatch.setattr(bump_version, "warn_if_changelog_missing", lambda version: None)
    monkeypatch.setattr(bump_version, "check", lambda: "9.9.9")
    assert bump_version.main(["9.9.9"]) == 0
    assert calls == ["lock", "hooks", "capture"]

    calls.clear()
    assert bump_version.main(["9.9.9", "--no-capture"]) == 0
    assert calls == ["lock", "hooks"]


def test_the_capture_runs_both_themes_against_a_free_port_and_stops_the_app(monkeypatch):
    runs, events = [], []

    class Server:
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append("wait")
            return 0

    def popen(cmd, cwd):
        events.append("start")
        assert "metrics.app" in cmd[-1]
        return Server()

    def run(cmd, cwd, timeout, check):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bump_version, "_wait_listening", lambda port, server, timeout: None)
    bump_version.regenerate_captures(ROOT, run=run, popen=popen)
    assert [cmd[cmd.index("--theme") + 1] for cmd in runs] == ["dark", "light"]
    assert all(str(bump_version.CAPTURE_SCRIPT.as_posix()) in Path(c[1]).as_posix() for c in runs)
    assert events == ["start", "terminate", "wait"]


def test_control_a_failed_capture_stops_the_bump_and_the_app(monkeypatch):
    events = []

    class Server:
        def poll(self):
            return None

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(bump_version, "_wait_listening", lambda port, server, timeout: None)
    with pytest.raises(bump_version.BumpError, match="dark"):
        bump_version.regenerate_captures(
            ROOT,
            run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1),
            popen=lambda cmd, cwd: Server(),
        )
    assert events == ["terminate"]


def test_release_refuses_stale_generated_files(tmp_path):
    root = _repo(tmp_path, version="1.3.0", captured="1.2.3")
    _touch_hook(root)
    stale = release._stale_generated("1.3.0", root)
    assert any("huella vieja" in s for s in stale)
    assert any("dashboard.json es de la 1.2.3" in s for s in stale)


def test_control_release_accepts_an_up_to_date_tree(tmp_path):
    assert release._stale_generated("1.2.3", _repo(tmp_path)) == []
