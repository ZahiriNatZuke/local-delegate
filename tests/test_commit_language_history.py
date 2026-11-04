"""#548 reopened: the commit language comes from the commits on HEAD, not from the reflog.

The main checkout of this very repo gets `main` through `git pull`: its `logs/HEAD` holds
`pull: Fast-forward` lines (no subject), `checkout:` lines and a few old `commit:` lines from the
time the repo wrote Spanish subjects. From an agent worktree nested in that checkout
(`<repo>/.claude/worktrees/<name>/`) the reflog voted «mixed» on an English history. These tests
build that shape with a real `git` and check the language follows the history.

Each test says which mutant makes it fail and with which assert.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import zlib
from pathlib import Path

import pytest

from local_delegate import git_history, i18n, server

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

VARIABLE = "LOCAL_DELEGATE_COMMIT_LANGUAGE"
ENGLISH = [
    "fix(ci): give the lint job room for the browser steps",
    "feat: add the panel to the status line",
    "chore: bump the version",
    "fix(server): retry when the backend is down",
    "docs: explain the use of the token",
    "refactor: move the helpers to a module",
]
OLD_SPANISH = [
    "fix(i18n): la llamada única del rol largo dobla su tope de salida",
    "docs(sdd): medición en vivo y cierre de la ola",
    "fix(ci): da margen al job lint para los pasos del navegador",
    "docs(sdd): evidencia de las mediciones de sobrecarga",
    "chore: judge.sh de la pasada en vivo, ejecutable",
]
OLD_ENGLISH = [
    "docs: drop retired records from the config",
    "test: wait for the panel row without eval",
    "chore(sdd): close the changes of the day",
]


@pytest.fixture(autouse=True)
def _spanish_product(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    yield
    i18n.reset()


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@example.org",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@example.org",
    }
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


def _repo(root: Path, subjects: list[str], body: str = "") -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    for i, subject in enumerate(subjects):
        (root / "file.txt").write_text(f"{i}\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", subject, *(["-m", body] if body else []))
    return root


def _pulled_reflog(repo: Path) -> None:
    """The main checkout's reflog as it really looks: `main` arrives by `git pull`, and the only
    `commit:` lines are old ones, more Spanish than English (they vote «mixed» on their own)."""
    head = _git(repo, "rev-parse", "HEAD").strip()
    who = "Ana <ana@example.org> 1760000000 +0000"
    lines = []
    for i, subject in enumerate(OLD_SPANISH + OLD_ENGLISH):
        lines.append(f"{'1' * 40} {'2' * 40} {who}\tcommit: {subject}")
        lines.append(f"{'2' * 40} {'3' * 40} {who}\tcheckout: moving from fix/x{i} to main")
    for _ in range(30):
        lines.append(f"{'3' * 40} {head} {who}\tpull -q --ff-only: Fast-forward")
        lines.append(f"{head} {head} {who}\tcheckout: moving from main to main")
    (repo / ".git" / "logs" / "HEAD").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _diff(folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "change.diff"
    target.write_text("diff --git a/x b/x\n", encoding="utf-8")
    return str(target)


@pytest.mark.parametrize("packed", [False, True], ids=["loose", "packed"])
def test_a_worktree_nested_in_the_main_checkout_follows_the_history(tmp_path, packed):
    """The real shape of the report: an agent worktree under `<repo>/.claude/worktrees/`, the diff
    in its root and in `.sdd/changes/<slug>/`, and a pulled reflog that alone says «mixed».
    Mutant «no history, reflog only» (`head_commit_subjects` returns []): both `("en", "repo")`
    asserts get `("es", "mixed_repo")`; the guard below shows the reflog really says that."""
    repo = _repo(tmp_path / "repo", ENGLISH)
    if packed:
        _git(repo, "gc", "-q", "--prune=now")
        assert not any((repo / ".git" / "objects").glob("[0-9a-f][0-9a-f]")), "all packed"
    _pulled_reflog(repo)
    tree = repo / ".claude" / "worktrees" / "agent-x"
    _git(repo, "worktree", "add", "-q", "-b", "worktree-agent-x", str(tree))
    root_diff = _diff(tree)
    sub_diff = _diff(tree / ".sdd" / "changes" / "some-slug")

    reflog_only = server._recent_commit_subjects(repo / ".git")
    assert server._guess_language(reflog_only) is None, "the reflog alone must say «mixed»"
    assert server._commit_language_choice(root_diff) == ("en", "repo")
    assert server._commit_language_choice(sub_diff) == ("en", "repo")
    assert server._commit_language_choice(_diff(repo / "src")) == ("en", "repo")


def test_the_walk_follows_first_parents_newest_last(tmp_path):
    """The subjects are the commits on HEAD, in order, capped. Mutant «no parent followed»: one
    subject instead of six."""
    repo = _repo(tmp_path / "repo", ENGLISH)
    assert git_history.head_commit_subjects(repo / ".git") == ENGLISH
    assert git_history.head_commit_subjects(repo / ".git", limit=2) == ENGLISH[-2:]


@pytest.mark.parametrize("offset_deltas", ["true", "false"], ids=["ofs-delta", "ref-delta"])
def test_commits_stored_as_deltas_are_rebuilt(tmp_path, offset_deltas):
    """Long shared commit bodies make `git repack` store commits as deltas of each other, by
    offset or by name. Mutant «delta copies from the start of the base» breaks the subjects. The
    guard checks the pack really has delta commits."""
    body = "\n".join(f"line {i} of a long shared commit body" for i in range(80))
    repo = _repo(tmp_path / "repo", ENGLISH, body=body)
    _git(repo, "-c", f"repack.useDeltaBaseOffset={offset_deltas}", "repack", "-adfq", "--window=50")
    _git(repo, "prune-packed")
    idx = [str(p) for p in (repo / ".git" / "objects" / "pack").glob("*.idx")]
    verify = _git(repo, "verify-pack", "-v", *idx)
    deltas = [ln for ln in verify.splitlines() if " commit " in ln and len(ln.split()) > 5]
    assert deltas, "the pack must hold commits stored as deltas"
    assert git_history.head_commit_subjects(repo / ".git") == ENGLISH


def _loose_path(repo: Path) -> Path:
    head = _git(repo, "rev-parse", "HEAD").strip()
    return repo / ".git" / "objects" / head[:2] / head[2:]


def test_a_corrupt_store_falls_back_to_the_reflog(tmp_path):
    """A truncated HEAD object stops the walk with nothing read; the reflog decides, as before.
    Mutant «errors escape»: the call raises instead of returning []."""
    repo = _repo(tmp_path / "repo", ENGLISH)
    obj = _loose_path(repo)
    obj.chmod(0o644)
    obj.write_bytes(obj.read_bytes()[:10])
    assert git_history.head_commit_subjects(repo / ".git") == []
    _pulled_reflog(repo)
    assert server._commit_language_choice(_diff(repo / "src")) == ("es", "mixed_repo")


def test_an_object_over_the_cap_is_not_inflated(tmp_path, monkeypatch):
    """Disk input is bounded: an object over `MAX_OBJECT_BYTES` inflated is refused. Mutant «no
    size cap»: the subjects come back."""
    repo = _repo(tmp_path / "repo", ENGLISH)
    monkeypatch.setattr(git_history, "MAX_OBJECT_BYTES", 64)
    assert git_history.head_commit_subjects(repo / ".git") == []


def test_a_zip_bomb_loose_object_stops_at_the_cap(tmp_path):
    """A 64 MiB run of zeros compresses to a few KB; it is refused once past the cap. Mutant
    «no size check»: `_inflate` does not raise `_Unreadable` (it ends in another error) and
    `pytest.raises` fails."""
    bomb = zlib.compress(b"commit 67108864\0" + b"\0" * (64 << 20))
    chunks = iter([bomb[i : i + 4096] for i in range(0, len(bomb), 4096)])
    with pytest.raises(git_history._Unreadable):
        git_history._inflate(lambda: next(chunks, b""), 1 << 20)


@pytest.mark.parametrize(
    ("ref", "target"),
    [("refs/../../outside", "outside"), ("ORIG_HEAD", ".git/ORIG_HEAD")],
    ids=["dot-dot", "outside-refs"],
)
def test_an_odd_head_is_not_followed(tmp_path, ref, target):
    """`HEAD` is disk input: a ref outside `refs/` or with `..` is refused, even when the file it
    names holds a valid commit. Mutant «any ref»: the file is followed and the subjects come back."""
    repo = _repo(tmp_path / "repo", ENGLISH)
    head = _git(repo, "rev-parse", "HEAD").strip()
    (repo / target).write_text(head + "\n", encoding="utf-8")
    (repo / ".git" / "HEAD").write_text(f"ref: {ref}\n", encoding="utf-8")
    assert git_history.head_commit_subjects(repo / ".git") == []
    (repo / ".git" / "HEAD").write_text("garbage\n", encoding="utf-8")
    assert git_history.head_commit_subjects(repo / ".git") == []


def test_a_full_fresh_clone_reads_its_history(tmp_path):
    """A full `git clone` has one `clone:` reflog line and its commits in a pack: it now answers
    from the history instead of «short history». Mutant «reflog only»: `("es", "short_history")`."""
    origin = _repo(tmp_path / "origin", ENGLISH)
    copy = tmp_path / "copy"
    _git(tmp_path, "clone", "-q", str(origin), str(copy))
    assert server._recent_commit_subjects(copy / ".git") == [], "a clone's reflog has no commit"
    assert server._commit_language_choice(_diff(copy / "sub")) == ("en", "repo")


SPANISH = [
    "fix(ci): da margen al job lint para los pasos del navegador",
    "feat: añade la tarjeta de la cuota",
    "fix(server): el map/reduce reintenta partiendo los parciales",
    "docs: explica el uso del token",
    "refactor: mueve las funciones a un módulo",
    "chore: sube la versión del paquete",
]


def test_merge_subjects_written_by_the_tool_do_not_vote(tmp_path):
    """A Spanish repo merged with GitHub's button: the first-parent chain is «Merge pull request
    #N from owner/branch» (English `from`). The merge's body (the PR title, in Spanish) is what
    counts; a merge without a body counts nothing. Mutant «use the merge subject»: the subjects
    are the «Merge pull request» lines and the language is `en`."""
    repo = _repo(tmp_path / "repo", ["chore: arranque del repo"])
    for i, title in enumerate(SPANISH):
        _git(repo, "switch", "-q", "-c", f"b{i}")
        (repo / f"f{i}.txt").write_text(f"{i}\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", title)
        _git(repo, "switch", "-q", "main")
        message = f"Merge pull request #{i} from owner/b{i}"
        body = ["-m", title] if i else []  # the first merge has no body
        _git(repo, "merge", "-q", "--no-ff", "-m", message, *body, f"b{i}")
    subjects = git_history.head_commit_subjects(repo / ".git")
    assert not any(s.startswith("Merge pull request") for s in subjects)
    assert subjects == ["chore: arranque del repo", *SPANISH[1:]]
    assert server._commit_language_choice(_diff(repo / "src")) == ("es", "repo")


def test_a_short_history_is_filled_from_the_reflog(tmp_path):
    """A walk cut early (here by a damaged older commit; also a shallow clone or alternates) gives
    too few votes; the reflog fills the rest instead of being dropped. Mutant «history replaces
    the reflog whenever it is not empty»: `("es", "short_history")`. The guard checks the walk
    really was cut after two commits. (Loose objects on purpose: which commit `git repack` keeps
    whole and which as a delta changes between git versions.)"""
    repo = _repo(tmp_path / "repo", ENGLISH)
    third = _git(repo, "rev-parse", "HEAD~2").strip()
    obj = repo / ".git" / "objects" / third[:2] / third[2:]
    obj.chmod(0o644)
    obj.write_bytes(obj.read_bytes()[:10])
    cut = git_history.head_commit_subjects(repo / ".git")
    assert cut == ENGLISH[-2:], f"the walk must stop after two commits: {cut}"
    assert server._commit_language_choice(_diff(repo / "src")) == ("en", "repo")


def test_the_delta_depth_cap_stops_the_walk(tmp_path, monkeypatch):
    """`MAX_DELTA_DEPTH` bounds the work of a delta chain. Mutant «no depth check» (both checks,
    in `read` and in `_from_pack`): all six subjects come back."""
    body = "\n".join(f"line {i} of a long shared commit body" for i in range(80))
    repo = _repo(tmp_path / "repo", ENGLISH, body=body)
    _git(repo, "repack", "-adfq", "--window=50")
    _git(repo, "prune-packed")
    monkeypatch.setattr(git_history, "MAX_DELTA_DEPTH", 0)
    assert git_history.head_commit_subjects(repo / ".git") != ENGLISH


def test_a_huge_packed_refs_is_not_read(tmp_path, monkeypatch):
    """`packed-refs` is disk input: over the cap it is not read, and a line is read in bounded
    pieces. Mutant «no size check» (both, the file size and the bytes read): the branch is found
    and the subjects come back."""
    repo = _repo(tmp_path / "repo", ENGLISH)
    _git(repo, "pack-refs", "--all", "--prune")
    monkeypatch.setattr(git_history, "_PACKED_REFS_MAX_BYTES", 10)
    assert git_history.head_commit_subjects(repo / ".git") == []


def test_a_packed_ref_is_resolved(tmp_path):
    """`git pack-refs` moves the branch to `packed-refs`. Mutant «loose refs only»: []."""
    repo = _repo(tmp_path / "repo", ENGLISH)
    _git(repo, "pack-refs", "--all", "--prune")
    assert not (repo / ".git" / "refs" / "heads" / "main").exists()
    assert git_history.head_commit_subjects(repo / ".git") == ENGLISH


def test_no_git_process_is_started(tmp_path, monkeypatch):
    """#461's rule: nothing in the repo may run. Mutant «ask `git log`»: the spy fires."""
    repo = _repo(tmp_path / "repo", ENGLISH)

    def _no(*args, **kwargs):
        raise AssertionError("no subprocess allowed")

    monkeypatch.setattr(subprocess, "run", _no)
    monkeypatch.setattr(subprocess, "Popen", _no)
    assert server._commit_language_choice(_diff(repo / "src")) == ("en", "repo")
