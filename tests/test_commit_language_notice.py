"""#546: `local_commit_msg` says when the language fell back because the diff's repo gave none.

The diff is usually dumped to a temp folder outside the repo; the language then came from the
product language with no sign of why, and an English repo got Spanish messages. Now a
`[local-delegate warning: …]` block after the message says which language was used and how to
change it. The system prompt stays byte for byte the same (it is the footprint of the affinity
measurements).

Each test says which mutant makes it fail and with which assert.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import config, i18n, server

VARIABLE = "LOCAL_DELEGATE_COMMIT_LANGUAGE"
ANSWER = "feat: algo\n\n- cambia algo"
DIFF = "diff --git a/uno.py b/uno.py\n--- a/uno.py\n+++ b/uno.py\n@@ -1 +1 @@\n-a\n+b\n"
ENGLISH = [
    "fix(ci): give the lint job room for the browser steps",
    "feat: add the panel to the status line",
    "chore: bump the version",
    "fix(server): retry when the backend is down",
    "docs: explain the use of the token",
    "refactor: move the helpers to a module",
]
SPANISH = [
    "fix(ci): da margen al job lint para los pasos del navegador",
    "feat: añade la tarjeta de la cuota",
    "fix(server): el map/reduce reintenta partiendo los parciales",
]
NO_REPO_ES = "el fichero del diff no está dentro de un repo git"
MIXED_ES = "los commits recientes del repo no dejan claro su idioma"


@pytest.fixture(autouse=True)
def _spanish_product(monkeypatch):
    assert VARIABLE not in os.environ
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    yield
    i18n.reset()


def _repo_with_reflog(root: Path, subjects: list[str]) -> Path:
    logs = root / ".git" / "logs"
    logs.mkdir(parents=True)
    lines = [
        f"{'0' * 40} {'1' * 40} Someone <s@example.invalid> 1700000000 +0000\tcommit: {s}"
        for s in subjects
    ]
    (logs / "HEAD").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _diff_file(folder: Path, text: str = DIFF) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "change.diff"
    target.write_text(text, encoding="utf-8")
    return str(target)


@backend_mock.mock
def _call(monkeypatch, logs: Path, **kwargs) -> tuple[str, list[dict]]:
    """`local_commit_msg` against a fake backend: its output and the requests it sent."""
    logs.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "LOG_DIR", logs)
    monkeypatch.setattr(config, "USAGE_LOG", logs / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    views: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        views.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": ANSWER}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return server.local_commit_msg(**kwargs), views


def _system(request: dict) -> str:
    return request["messages"][0]["content"]


def test_a_diff_outside_any_repo_gets_the_warning_after_the_message(monkeypatch, tmp_path):
    """Mutant «no warning» (`_commit_language_notice` returns ""): the `NO_REPO_ES` assert fails.
    The message itself stays first and untouched, and the prompt keeps its old text."""
    path = _diff_file(tmp_path / "loose")
    out, views = _call(monkeypatch, tmp_path / "logs", path=path)

    assert NO_REPO_ES in out
    message, _, warning = out.partition("\n\n" + server.WARNING_MARKER)
    assert message == ANSWER
    assert warning.endswith("]")
    assert "(es)" in warning
    assert VARIABLE in warning
    assert _system(views[0]).endswith("(primera línea y cuerpo) en español.")


def test_a_diff_inside_an_english_repo_gets_no_warning(monkeypatch, tmp_path):
    """Mutant «always warn when a path is given»: the `WARNING_MARKER not in` assert fails."""
    repo = _repo_with_reflog(tmp_path / "repo", ENGLISH)
    path = _diff_file(repo / "sub")
    out, views = _call(monkeypatch, tmp_path / "logs", path=path)

    assert _system(views[0]).endswith("(primera línea y cuerpo) en inglés.")
    assert server.WARNING_MARKER not in out
    assert out == ANSWER


def test_a_repo_with_a_mixed_history_gets_its_own_warning(monkeypatch, tmp_path):
    """Mutant «treat a mixed repo as a clear one» (no warning when the repo was found): the
    `MIXED_ES` assert fails; mutant «one text for both cases»: the `NO_REPO_ES` one fails."""
    repo = _repo_with_reflog(tmp_path / "mixed", ENGLISH[:3] + SPANISH)
    path = _diff_file(repo)
    out, views = _call(monkeypatch, tmp_path / "logs", path=path)

    assert MIXED_ES in out
    assert NO_REPO_ES not in out
    assert _system(views[0]).endswith("(primera línea y cuerpo) en español.")


@pytest.mark.parametrize("value", ["en", "diff"])
def test_the_variable_turns_off_the_warning(monkeypatch, tmp_path, value):
    """Whoever set the variable chose the language. Mutant «check the repo before the
    variable»: the `WARNING_MARKER not in` assert fails."""
    monkeypatch.setenv(VARIABLE, value)
    path = _diff_file(tmp_path / "loose")
    out, views = _call(monkeypatch, tmp_path / "logs", path=path)

    assert server.WARNING_MARKER not in out
    expected = "en inglés." if value == "en" else "mensajes)."
    assert _system(views[0]).endswith(expected)


def test_an_inline_diff_gets_no_warning(monkeypatch, tmp_path):
    """Without `path` there is never a repo to look at (the docstring says so): a warning on every
    inline call would be noise. Mutant «warn whenever the product language is the default»: the
    assert fails."""
    out, _ = _call(monkeypatch, tmp_path / "logs", diff=DIFF)
    assert out == ANSWER


def test_the_warning_also_follows_the_map_reduce_receipt(monkeypatch, tmp_path):
    """A diff above the ceiling goes through the map-reduce. Mutant «warn only on the single
    call»: the `NO_REPO_ES` assert fails."""
    big = "".join(
        f"diff --git a/m{i}.py b/m{i}.py\n--- a/m{i}.py\n+++ b/m{i}.py\n@@ -0,0 +1,60 @@\n"
        + "".join(f"+linea {j} del modulo {i} con relleno de sobra\n" for j in range(60))
        for i in range(30)
    )
    assert len(big) > config.max_chars_for_role("code"), "the diff must exceed the ceiling"
    path = _diff_file(tmp_path / "loose", big)
    out, views = _call(monkeypatch, tmp_path / "logs", path=path)

    assert len(views) > 2
    assert NO_REPO_ES in out
    receipt = out.index("(alcance:")
    assert receipt < out.index(server.WARNING_MARKER)


def test_the_choice_names_its_source(tmp_path, monkeypatch):
    """`_commit_language_choice` says where the language came from. Mutant «no_repo and
    mixed_repo swapped»: the second and third asserts fail."""
    english = _repo_with_reflog(tmp_path / "en", ENGLISH)
    mixed = _repo_with_reflog(tmp_path / "mixed", ENGLISH[:3] + SPANISH)
    (tmp_path / "loose").mkdir()
    assert server._commit_language_choice(str(english / "x.diff")) == ("en", "repo")
    assert server._commit_language_choice(str(mixed / "x.diff")) == ("es", "mixed_repo")
    assert server._commit_language_choice(str(tmp_path / "loose" / "x.diff")) == ("es", "no_repo")
    assert server._commit_language_choice(None) == ("es", "inline")
    monkeypatch.setenv(VARIABLE, "fr")
    assert server._commit_language_choice(None) == ("fr", "variable")


# --- #548: a freshly made linked worktree ------------------------------------------------------
def _git(cwd: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ana",
        "GIT_AUTHOR_EMAIL": "ana@example.org",
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@example.org",
    }
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_diff_inside_a_fresh_worktree_follows_the_shared_history(monkeypatch, tmp_path):
    """A real `git worktree add`: its own reflog has no `commit:` line, the shared one has six in
    English. Mutant «do not read the shared git dir» (`_common_git_dir` returns None): the
    `("en", "repo")` assert gets `("es", "mixed_repo")`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for i, subject in enumerate(ENGLISH):
        (repo / "file.txt").write_text(f"{i}\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", subject)
    tree = tmp_path / "tree"
    _git(repo, "worktree", "add", "-q", "-b", "work", str(tree))
    assert (tree / ".git").is_file(), "the worktree must have a `.git` file"
    path = _diff_file(tree / "sub")

    assert server._commit_language_choice(path) == ("en", "repo")
    out, views = _call(monkeypatch, tmp_path / "logs", path=path)
    assert _system(views[0]).endswith("(primera línea y cuerpo) en inglés.")
    assert out == ANSWER


def test_a_common_dir_in_an_odd_place_is_not_followed(tmp_path):
    """`commondir` is disk input. One that points at a folder other than the one two levels
    above the worktree's git dir is ignored, even if that folder has an English history.
    Mutant «follow any commondir»: the second assert gets `"en"`."""
    elsewhere = _repo_with_reflog(tmp_path / "elsewhere", ENGLISH) / ".git"
    (elsewhere / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    common = tmp_path / "main" / ".git"
    wt_git = common / "worktrees" / "wt"
    (wt_git / "logs").mkdir(parents=True)
    (common / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (wt_git / "logs" / "HEAD").write_text("a b c 1 +0000\tcheckout: x\n", encoding="utf-8")
    (wt_git / "commondir").write_text(f"{elsewhere}\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")

    assert server._common_git_dir(wt_git) is None
    assert server._repo_commit_language(str(work / "x.diff")) is None
    (wt_git / "commondir").write_text("../..\n", encoding="utf-8")
    assert server._common_git_dir(wt_git) == common.resolve()
