"""El conjunto «después» de huellas de hooks y quien lo lee (REQ-041, plan D9; ola B3).

Cada evento de telemetría lleva la huella del script que corrió (`hook_common.version_de`). La
frontera entre tramos es el conjunto `scripts/data/hook_hashes_after.json`: un evento cuya huella
está dentro es del tramo «después», sea cual sea su fecha. El conjunto solo crece: lo regenera
`scripts/bump_version.py --boundaries` en cada PR de release, por unión.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "src" / "local_delegate" / "resources" / "hooks"

if not (SCRIPTS / "bump_version.py").is_file():
    pytest.skip("scripts/ no está en el árbol (sdist)", allow_module_level=True)


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bump_version = _load("bump_version")
measurement_boundaries = _load("measurement_boundaries")
measure_adoption = _load("measure_adoption")


def _fake_repo(tmp_path: Path) -> Path:
    """Una copia de los hooks y del conjunto actual, para regenerar sin tocar el repo."""
    hooks = tmp_path / bump_version.HOOKS_DIR
    shutil.copytree(HOOKS, hooks, ignore=shutil.ignore_patterns("__pycache__"))
    target = tmp_path / bump_version.HOOK_HASHES_FILE
    target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / bump_version.HOOK_HASHES_FILE, target)
    return tmp_path


# --- El conjunto del repo está al día -------------------------------------------------------------


def test_the_hashed_hooks_are_the_ones_that_stamp_their_footprint():
    """Un hook nuevo que estampe `context_of` sin entrar en `HASHED_HOOKS` se mediría siempre «antes»."""
    stamping = sorted(
        path.name
        for path in HOOKS.glob("*.py")
        if path.name != "hook_common.py"
        and "context_of(payload, __file__)" in path.read_text("utf-8")
    )
    assert stamping == sorted(bump_version.HASHED_HOOKS)


def test_the_current_hash_of_each_hook_is_in_the_set():
    """Tocar un hook sin `bump_version.py --boundaries` deja sus eventos nuevos en «antes»."""
    after = measurement_boundaries.hook_hashes_after()
    current = bump_version.current_hook_hashes()
    assert set(current) == set(bump_version.HASHED_HOOKS)
    missing = {name: h for name, h in current.items() if h not in after.get(name, set())}
    assert missing == {}, "corre `uv run python scripts/bump_version.py --boundaries`"


def test_a_touched_hook_is_caught(tmp_path):
    """Control positivo del test de arriba: el mutante «tocar un hook sin regenerar»."""
    repo = _fake_repo(tmp_path)
    hook = repo / bump_version.HOOKS_DIR / "suggest_delegate_read.py"
    hook.write_bytes(hook.read_bytes() + b"# cambio\n")
    after = measurement_boundaries.hook_hashes_after(root=repo)
    assert (
        bump_version.current_hook_hashes(repo)["suggest_delegate_read.py"]
        not in after["suggest_delegate_read.py"]
    )


def test_the_footprint_is_the_one_the_hook_writes(tmp_path):
    """La huella del conjunto es la de `version_de` sobre el script, la que lleva cada evento."""
    from local_delegate.resources.hooks import hook_common

    name = "suggest_delegate_shell.py"
    assert bump_version.current_hook_hashes()[name] == hook_common.version_de(str(HOOKS / name))


def test_the_hooks_are_checked_out_byte_for_byte():
    """Sin `-text`, un checkout de Windows con autocrlf daría otra huella al mismo hook."""
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "src/local_delegate/resources/hooks/*.py -text" in attributes
    for path in HOOKS.glob("*.py"):
        assert b"\r\n" not in path.read_bytes(), path.name


# --- El conjunto solo crece -----------------------------------------------------------------------


def test_regenerating_after_a_change_keeps_the_old_hash(tmp_path):
    repo = _fake_repo(tmp_path)
    old = bump_version.current_hook_hashes(repo)["suggest_delegate_read.py"]
    hook = repo / bump_version.HOOKS_DIR / "suggest_delegate_read.py"
    hook.write_bytes(hook.read_bytes() + b"# 0.37.0\n")
    new = bump_version.current_hook_hashes(repo)["suggest_delegate_read.py"]
    assert new != old

    data = bump_version.update_boundaries(repo)

    assert old in data["suggest_delegate_read.py"], "la regeneración sustituyó en vez de unir"
    assert new in data["suggest_delegate_read.py"]
    on_disk = json.loads((repo / bump_version.HOOK_HASHES_FILE).read_text(encoding="utf-8"))
    assert on_disk == data


def test_a_replacing_regeneration_would_be_caught(tmp_path):
    """Control positivo: una regeneración que SUSTITUYE pierde el hash viejo, y el assert lo ve."""
    repo = _fake_repo(tmp_path)
    old = bump_version.current_hook_hashes(repo)["suggest_delegate_read.py"]
    hook = repo / bump_version.HOOKS_DIR / "suggest_delegate_read.py"
    hook.write_bytes(hook.read_bytes() + b"# 0.37.0\n")
    replaced = {name: [h] for name, h in bump_version.current_hook_hashes(repo).items()}
    assert old not in replaced["suggest_delegate_read.py"]


def test_regenerating_twice_changes_nothing(tmp_path):
    repo = _fake_repo(tmp_path)
    first = bump_version.update_boundaries(repo)
    assert bump_version.update_boundaries(repo) == first


def test_the_cli_option_updates_the_file(tmp_path, monkeypatch, capsys):
    repo = _fake_repo(tmp_path)
    (repo / bump_version.HOOK_HASHES_FILE).unlink()
    monkeypatch.setattr(bump_version, "ROOT", repo)
    assert bump_version.main(["--boundaries"]) == 0
    data = json.loads((repo / bump_version.HOOK_HASHES_FILE).read_text(encoding="utf-8"))
    assert set(data) == set(bump_version.HASHED_HOOKS)
    assert "3 huellas" in capsys.readouterr().out


# --- Quien lo lee: `measure_adoption.py` ----------------------------------------------------------


HASHES = {
    "suggest_delegate_read.py": {"newread1"},
    "suggest_delegate_shell.py": {"newshel1"},
    "suggest_delegate_prompt.py": {"newprom1"},
}


@pytest.mark.parametrize(
    ("event", "side"),
    [
        ({"category": "read", "version": "newread1", "ts": "2026-09-01T00:00:00Z"}, "after"),
        ({"category": "read", "version": "oldread1", "ts": "2026-12-01T00:00:00Z"}, "before"),
        ({"category": "shell", "version": "newshel1"}, "after"),
        # La huella de OTRO hook no vale: cada script tiene su conjunto.
        ({"category": "shell", "version": "newread1"}, "before"),
        ({"event": "UserPromptSubmit", "version": "newprom1"}, "after"),
        ({"category": "read"}, "before"),
    ],
)
def test_the_side_of_a_hook_event_is_decided_by_its_footprint(event, side):
    assert measure_adoption.hook_side(event, HASHES) == side


def test_two_machines_an_old_hash_with_a_later_date_stays_before():
    """La Mac en la versión vieja escribe con fecha nueva: su evento sigue en «antes»."""
    mac = {"category": "read", "version": "oldread1", "ts": "2030-01-01T00:00:00Z"}
    pc = {"category": "read", "version": "newread1", "ts": "2026-01-01T00:00:00Z"}
    assert measure_adoption.hook_side(mac, HASHES) == "before"
    assert measure_adoption.hook_side(pc, HASHES) == "after"


def test_by_side_counts_reads_blocks_and_delegations(tmp_path):
    hashes_file = tmp_path / "hashes.json"
    hashes_file.write_text(json.dumps({"suggest_delegate_read.py": ["newread1"]}), "utf-8")
    boundaries = {"package_version_after": "0.36.0", "hook_hashes_after": "hashes.json"}
    reads = [
        {"category": "read", "version": "newread1", "suggested": True, "blocked": True, "id": "b1"},
        {"category": "read", "version": "oldread1", "suggested": True, "blocked": True, "id": "b2"},
        {"category": "read", "version": "oldread1"},
    ]
    usages = [
        {"tool": "local_summarize", "v": "0.36.0", "block_id": "b1"},
        {"tool": "local_summarize", "v": "0.35.0"},
        {"tool": "local_summarize"},  # sin versión: siempre «antes»
        {"tool": "other"},
    ]
    result = measure_adoption.by_side(reads, usages, {"b1"}, boundaries, root=tmp_path)
    assert result["after"] == {
        "reads": 1,
        "offered": 1,
        "blocks": 1,
        "accepted": 1,
        "delegations": 1,
    }
    assert result["before"] == {
        "reads": 2,
        "offered": 1,
        "blocks": 1,
        "accepted": 0,
        "delegations": 2,
    }
