"""The project rule, the salt and the list of own projects (usage-log-project-and-own-repo-exclusion,
REQ-001, REQ-002 and REQ-003).

`hook_common` is loaded as a LOOSE module, from its file and without the package, as the hooks
load it: every test gets a fresh copy, so the per-process caches start empty. All names, roots and
`LOG_DIR` are synthetic and live in `tmp_path`.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

import local_delegate

HOOK_COMMON = Path(local_delegate.__file__).parent / "resources" / "hooks" / "hook_common.py"
REPO_DIR = "D--Projects-local-delegate"
SESSION = "0b9c3f9e-1d2a-4c5b-8e7f-123456789abc"


@pytest.fixture
def hc(monkeypatch, tmp_path):
    """A fresh loose copy of `hook_common`, with `LOG_DIR` in `tmp_path / "logs"`."""
    name = f"loose_hook_common_{id(tmp_path)}"
    spec = importlib.util.spec_from_file_location(name, HOOK_COMMON)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "logs"))
    yield module
    sys.modules.pop(name, None)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "home" / ".claude" / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _transcript(root: Path, project: str, session: str = SESSION) -> Path:
    return root / project / f"{session}.jsonl"


def _identity(hc, root: Path, project: str, **kwargs) -> dict:
    return hc.project_identity(_transcript(root, project), root=root, **kwargs)


def _write_list(tmp_path: Path, names: object) -> None:
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "self-projects.json").write_text(json.dumps({"names": names}), encoding="utf-8")


def _kind(hc, root: Path, project: str) -> str | None:
    return _identity(hc, root, project).get("caller_project_kind")


# --- The loose module -------------------------------------------------------------------------


def test_the_rule_runs_from_the_loose_module_without_the_package(hc, tmp_path):
    root = _root(tmp_path)
    fields = _identity(hc, root, REPO_DIR)
    assert hc.__name__.startswith("loose_hook_common_")
    assert fields["caller_project_kind"] == "self"
    imports = [
        line.strip()
        for line in HOOK_COMMON.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not [line for line in imports if "local_delegate" in line or line.startswith("from .")]


# --- REQ-001: the hash ------------------------------------------------------------------------


def test_the_hash_is_the_salted_sha256_of_the_lower_case_name(hc, tmp_path):
    root = _root(tmp_path)
    fields = _identity(hc, root, "D--Work-Shop")
    salt = (tmp_path / "logs" / "project-salt").read_text(encoding="ascii")
    expected = hashlib.sha256(f"local-delegate-project:{salt}:d--work-shop".encode()).hexdigest()
    assert fields["caller_project"] == expected[:16]
    assert len(fields["caller_project"]) == 16
    assert set(fields) == {"caller_project", "caller_project_kind"}


def test_the_same_name_gives_the_same_hash_and_two_names_two_hashes(hc, tmp_path):
    """Mutant 2 (the hash ignores the name): the two names give the same hash."""
    root = _root(tmp_path)
    first = _identity(hc, root, "D--work-shop")["caller_project"]
    again = hc.project_identity(
        root / "D--work-shop" / "10000000-1d2a-4c5b-8e7f-123456789abc.jsonl", root=root
    )["caller_project"]
    other = _identity(hc, root, "D--work-other")["caller_project"]
    assert first == again
    assert first != other


def test_two_salts_give_two_hashes(hc, tmp_path):
    """Mutant 1 (the hash ignores the salt): both `LOG_DIR` give the same hash."""
    root = _root(tmp_path)
    one, two = tmp_path / "one", tmp_path / "two"
    for directory, salt in ((one, "a" * 64), (two, "b" * 64)):
        directory.mkdir()
        (directory / "project-salt").write_text(salt, encoding="ascii")
    h1 = _identity(hc, root, "D--work-shop", directory=one)["caller_project"]
    h2 = _identity(hc, root, "D--work-shop", directory=two)["caller_project"]
    assert h1 != h2


@pytest.mark.parametrize(
    "where",
    ["outside", "not_jsonl", "at_the_root", "dot_dot", "empty", "not_text"],
)
def test_an_invalid_path_gives_no_field(hc, tmp_path, where):
    """Mutant 3 (a path outside the root is accepted): the `outside` and `dot_dot` cases give
    fields."""
    root = _root(tmp_path)
    path = {
        # As deep as a real transcript, so only the prefix check can reject it.
        "outside": tmp_path / "elsewhere" / ".claude" / "projects" / REPO_DIR / f"{SESSION}.jsonl",
        "not_jsonl": root / REPO_DIR / f"{SESSION}.json",
        "at_the_root": root / f"{SESSION}.jsonl",
        "dot_dot": root / REPO_DIR / ".." / ".." / REPO_DIR / f"{SESSION}.jsonl",
        "empty": "",
        "not_text": 42,
    }[where]
    assert hc.project_identity(path, root=root) == {}


def test_a_valid_path_needs_nothing_on_disk(hc, tmp_path):
    """The rule is lexical: the project directory does not exist and the fields still come."""
    root = _root(tmp_path)
    assert not (root / "D--gone").exists()
    assert _identity(hc, root, "D--gone")["caller_project_kind"] == "other"


def test_the_subagent_path_gives_the_main_sessions_project(hc, tmp_path):
    root = _root(tmp_path)
    main = _identity(hc, root, "D--work-shop")
    sub = hc.project_identity(
        root / "D--work-shop" / SESSION / "subagents" / "agent-a1.jsonl", root=root
    )
    assert sub == main


# --- REQ-002: the kind ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "project",
    [REPO_DIR, f"{REPO_DIR}--claude-worktrees-agent-a1b2", f"{REPO_DIR}-src", "local-delegate"],
)
def test_the_repo_its_worktree_and_a_subdirectory_are_self(hc, tmp_path, project):
    """Mutant 4 (the kind is always `other`)."""
    assert _kind(hc, _root(tmp_path), project) == "self"


@pytest.mark.parametrize(
    "project", ["D--work-shop", "D--work-local-delegates", "D--mylocal-delegate"]
)
def test_other_projects_are_other(hc, tmp_path, project):
    assert _kind(hc, _root(tmp_path), project) == "other"


def test_a_clone_with_another_name_is_self_only_with_the_list(hc, tmp_path):
    """Mutant 5 (the list is not read): the clone stays `other`."""
    root = _root(tmp_path)
    assert _kind(hc, root, "D--work-ld-fork") == "other"
    fresh = tmp_path / "with-list"
    fresh.mkdir()
    (fresh / "self-projects.json").write_text(json.dumps({"names": ["ld-fork"]}), encoding="utf-8")
    fields = _identity(hc, root, "D--work-ld-fork", directory=fresh)
    assert fields["caller_project_kind"] == "self"


def test_short_and_non_text_entries_are_ignored(hc, tmp_path):
    """Mutant 6 (short entries are not ignored): `ap` marks `D--work-ap` as `self`."""
    _write_list(tmp_path, ["ap", "a-b", "", 7, None, ["ld-fork"], "  "])
    root = _root(tmp_path)
    assert _kind(hc, root, "D--work-ap") == "other"
    assert _kind(hc, root, "D--work-a-b") == "other"
    assert hc.self_project_entries() == ()


@pytest.mark.parametrize(
    "content",
    ["{not json", json.dumps(["ld-fork"]), json.dumps({"names": "ld-fork"}), "", "\x00\xff"],
)
def test_a_broken_list_is_an_empty_list_without_error(hc, tmp_path, content):
    """Mutant 7 (a broken list raises): the call raises instead of giving `self`."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "self-projects.json").write_text(content, encoding="utf-8", errors="replace")
    root = _root(tmp_path)
    assert _kind(hc, root, REPO_DIR) == "self"
    assert _kind(hc, root, "D--work-ld-fork") == "other"


def test_the_match_is_by_whole_segment_not_by_substring(hc, tmp_path):
    """Mutant 7a (substring again): `app` marks `webapp` and `happy`."""
    _write_list(tmp_path, ["app"])
    root = _root(tmp_path)
    assert _kind(hc, root, "D--work-webapp") == "other"
    assert _kind(hc, root, "D--work-happy") == "other"
    assert _kind(hc, root, "D--work-app") == "self"
    assert _kind(hc, root, "D--work-app-web") == "self"


def test_an_entry_with_a_path_matches_its_directory_subdirectories_and_worktrees(hc, tmp_path):
    """Mutant 7b (an entry with a path does not match what hangs from it)."""
    _write_list(tmp_path, ["D:\\work\\app\\"])
    root = _root(tmp_path)
    assert _kind(hc, root, "D--work-app") == "self"
    assert _kind(hc, root, "D--work-app-sub") == "self"
    assert _kind(hc, root, "D--work-app--claude-worktrees-agent-1") == "self"
    assert _kind(hc, root, "D--work-apple") == "other"
    assert _kind(hc, root, "E--work-app") == "other"


def test_letters_outside_ascii_are_normalized_on_both_sides(hc, tmp_path):
    """Mutant 7c (the normalization keeps `ñ` and accents): `Diseño` does not match `D--dise-o`."""
    _write_list(tmp_path, ["Diseño"])
    root = _root(tmp_path)
    assert _kind(hc, root, "D--dise-o") == "self"
    assert _kind(hc, root, "D--Diseño") == "self"
    assert _kind(hc, root, "D--diseno") == "other"
    assert hc.normalize_project_name("Diseño") == "dise-o"


def test_a_list_above_64_kib_marks_nothing(hc, tmp_path):
    """Mutant 7d (no size cap)."""
    logs = tmp_path / "logs"
    logs.mkdir()
    payload = {"names": ["ld-fork"], "padding": "x" * (64 * 1024)}
    (logs / "self-projects.json").write_text(json.dumps(payload), encoding="utf-8")
    root = _root(tmp_path)
    assert _kind(hc, root, "D--work-ld-fork") == "other"
    assert _kind(hc, root, REPO_DIR) == "self"


def test_a_list_just_below_the_cap_is_read(hc, tmp_path):
    """Guard of the previous one: the cap is the size, not the presence of padding."""
    logs = tmp_path / "logs"
    logs.mkdir()
    base = json.dumps({"names": ["ld-fork"], "padding": ""})
    padding = 64 * 1024 - len(base)
    text = json.dumps({"names": ["ld-fork"], "padding": "x" * padding})
    assert len(text.encode()) == 64 * 1024
    (logs / "self-projects.json").write_text(text, encoding="utf-8")
    assert _kind(hc, _root(tmp_path), "D--work-ld-fork") == "self"


def test_the_list_is_read_once_per_process_and_path(hc, tmp_path):
    _write_list(tmp_path, ["ld-fork"])
    root = _root(tmp_path)
    assert _kind(hc, root, "D--work-ld-fork") == "self"
    _write_list(tmp_path, [])
    assert _kind(hc, root, "D--work-ld-fork") == "self"


# --- REQ-003: the salt ------------------------------------------------------------------------


def test_the_salt_is_created_with_64_hex_and_no_temporary_left(hc, tmp_path):
    salt = hc.project_salt()
    logs = tmp_path / "logs"
    assert salt is not None and len(salt) == 64 and int(salt, 16) >= 0
    assert (logs / "project-salt").read_text(encoding="ascii") == salt
    assert sorted(p.name for p in logs.iterdir() if p.name.endswith(".tmp")) == []
    if os.name != "nt":
        assert (logs / "project-salt").stat().st_mode & 0o777 == 0o600


def test_a_valid_salt_is_never_overwritten(hc, tmp_path):
    """Mutant 8 (creation overwrites a valid salt)."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "project-salt").write_text("c" * 64, encoding="ascii")
    assert hc.project_salt() == "c" * 64
    assert (logs / "project-salt").read_text(encoding="ascii") == "c" * 64


def test_when_another_process_wins_the_race_its_salt_is_the_one(hc, tmp_path, monkeypatch):
    """Deterministic race: the other process links its salt just before this one."""
    logs = tmp_path / "logs"
    real_link = os.link

    def the_other_won(source, target):
        Path(target).write_text("d" * 64, encoding="ascii")
        return real_link(source, target)  # raises FileExistsError, as the real race would

    monkeypatch.setattr(hc.os, "link", the_other_won)
    assert hc.project_salt() == "d" * 64
    assert (logs / "project-salt").read_text(encoding="ascii") == "d" * 64


@pytest.mark.parametrize("content", ["", "not-a-salt", "e" * 63])
def test_an_empty_or_invalid_salt_file_is_repaired(hc, tmp_path, content):
    """Mutant 10 (an empty salt file is not repaired): no salt and no hash, forever."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "project-salt").write_text(content, encoding="ascii")
    fields = _identity(hc, _root(tmp_path), "D--work-shop")
    repaired = (logs / "project-salt").read_text(encoding="ascii")
    assert len(repaired) == 64 and int(repaired, 16) >= 0
    assert fields.get("caller_project") == hc.project_hash("D--work-shop", repaired)


def test_without_a_salt_there_is_the_kind_and_never_an_unsalted_hash(hc, tmp_path, monkeypatch):
    """Mutant 9 (without salt an unsalted hash is written)."""
    blocked = tmp_path / "logs"
    blocked.write_text("a file where LOG_DIR should be", encoding="utf-8")
    fields = _identity(hc, _root(tmp_path), REPO_DIR)
    assert "caller_project" not in fields
    assert fields["caller_project_kind"] == "self"


def test_a_salt_failure_is_not_cached(hc, tmp_path):
    blocked = tmp_path / "logs"
    blocked.write_text("a file where LOG_DIR should be", encoding="utf-8")
    assert hc.project_salt() is None
    blocked.unlink()
    assert hc.project_salt() is not None


def test_the_salt_is_read_once_per_process(hc, tmp_path, monkeypatch):
    """Mutant 11 (the salt is read in every call): the second call opens the file again."""
    first = hc.project_salt()
    opened: list[str] = []
    real_open = builtins.open

    def spy(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    second = hc.project_salt()
    assert first == second
    assert not [p for p in opened if p.endswith("project-salt")]


def test_the_cache_goes_by_path(hc, tmp_path, monkeypatch):
    """Mutant 12 (the cache is not per path): the second `LOG_DIR` gets the first salt."""
    one = hc.project_salt()
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "other-logs"))
    two = hc.project_salt()
    assert one and two and one != two
    assert (tmp_path / "other-logs" / "project-salt").read_text(encoding="ascii") == two


def test_the_salt_comes_from_the_process_environment(hc, tmp_path):
    """Inside `run_with_environ` with another `LOCAL_DELEGATE_LOG_DIR`, nothing is created there."""
    elsewhere = tmp_path / "request-logs"
    salt = hc.run_with_environ({"LOCAL_DELEGATE_LOG_DIR": str(elsewhere)}, hc.project_salt)
    assert salt == (tmp_path / "logs" / "project-salt").read_text(encoding="ascii")
    assert not elsewhere.exists()


# --- project_of_session ------------------------------------------------------------------------


def _session_world(tmp_path: Path, *projects: str, session: str = SESSION) -> Path:
    root = _root(tmp_path)
    for project in projects:
        _transcript(root, project, session).parent.mkdir(parents=True, exist_ok=True)
        _transcript(root, project, session).write_text("{}\n", encoding="utf-8")
    return root


def test_a_uuid_session_in_one_directory_is_found(hc, tmp_path):
    root = _session_world(tmp_path, "D--work-shop")
    (root / "D--work-other").mkdir()
    assert hc.project_of_session(SESSION, root=root) == _transcript(root, "D--work-shop")


@pytest.mark.parametrize(
    "session_id",
    [
        "..",
        f"../{SESSION}",
        f"x/{SESSION}",
        f"x\\{SESSION}",
        # `$` of a regex also matches before a final line break: the shape is checked whole.
        f"{SESSION}\n",
        f"{SESSION}x",
        "not-a-uuid",
        "",
        None,
        7,
    ],
)
def test_an_id_without_uuid_shape_forms_no_path(hc, tmp_path, monkeypatch, session_id):
    root = _session_world(tmp_path, "D--work-shop")
    walked: list = []
    real_scandir = os.scandir
    monkeypatch.setattr(hc.os, "scandir", lambda p: walked.append(p) or real_scandir(p))
    assert hc.project_of_session(session_id, root=root) is None
    assert walked == []


def test_a_session_in_two_directories_has_no_project(hc, tmp_path):
    root = _session_world(tmp_path, "D--work-shop", "D--work-other")
    assert hc.project_of_session(SESSION, root=root) is None


def test_a_missing_session_has_no_project(hc, tmp_path):
    root = _session_world(tmp_path, "D--work-shop")
    assert hc.project_of_session("10000000-1d2a-4c5b-8e7f-123456789abc", root=root) is None


def test_the_root_comes_from_the_process_home(hc, tmp_path, monkeypatch):
    root = _session_world(tmp_path, "D--work-shop")
    monkeypatch.setenv("USERPROFILE" if os.name == "nt" else "HOME", str(tmp_path / "home"))
    other = tmp_path / "request-home"
    foreign = other / ".claude" / "projects" / "D--elsewhere" / f"{SESSION}.jsonl"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("{}\n", encoding="utf-8")
    request = {"HOME": str(other), "USERPROFILE": str(other)}
    found = hc.run_with_environ(request, hc.project_of_session, SESSION)
    assert found == _transcript(root, "D--work-shop")


def test_the_search_stops_at_its_budget_and_is_not_cached(hc, tmp_path):
    root = _session_world(tmp_path, "D--work-zz")
    for name in ("D--work-a", "D--work-b", "D--work-c"):
        (root / name).mkdir()
    ticks = iter(i * 0.030 for i in range(100))
    assert hc.project_of_session(SESSION, root=root, clock=lambda: next(ticks)) is None
    assert hc.project_of_session(SESSION, root=root) == _transcript(root, "D--work-zz")


def test_a_found_or_ambiguous_result_is_cached_and_not_found_is_not(hc, tmp_path, monkeypatch):
    root = _session_world(tmp_path, "D--work-shop")
    assert hc.project_of_session(SESSION, root=root) is not None
    walked: list = []
    real_scandir = os.scandir
    monkeypatch.setattr(hc.os, "scandir", lambda p: walked.append(p) or real_scandir(p))
    assert hc.project_of_session(SESSION, root=root) == _transcript(root, "D--work-shop")
    assert walked == []

    twice = "20000000-1d2a-4c5b-8e7f-123456789abc"
    _session_world(tmp_path, "D--work-shop", "D--work-other", session=twice)
    assert hc.project_of_session(twice, root=root) is None
    walked.clear()
    assert hc.project_of_session(twice, root=root) is None
    assert walked == []

    later = "30000000-1d2a-4c5b-8e7f-123456789abc"
    assert hc.project_of_session(later, root=root) is None
    _session_world(tmp_path, "D--work-shop", session=later)
    assert hc.project_of_session(later, root=root) == _transcript(root, "D--work-shop", later)
