"""#461: `local_commit_msg` on a big diff must stay within what the diff says.

The reduce of the map-reduce only saw per-chunk notes plus a path/line inventory; a vague note
(«date utilities») let it add «time zones», absent from the diff. Now the inventory carries each
file's A/M/D/R status and its top-level definitions, computed without a model, and the reduce is
told to mention nothing outside them and the notes. The commit language also follows the recent
commits of the repo that holds the diff file, when the reflog says it clearly.

Each test says which mutant makes it fail and with which assert.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import config, i18n, server

VARIABLE = "LOCAL_DELEGATE_COMMIT_LANGUAGE"

DIFF = (
    "diff --git a/src/dates.ts b/src/dates.ts\n"
    "new file mode 100644\n"
    "--- /dev/null\n+++ b/src/dates.ts\n@@ -0,0 +1,6 @@\n"
    "+export function addDays(d: Date, n: number) {\n"
    "+  const inner = 1\n"
    "+}\n"
    "+export const HOUR_FORMAT = 'HH:mm'\n"
    "+  function nestedHelper() {}\n"
    "+class Calendar {}\n"
    "diff --git a/old.py b/old.py\n"
    "deleted file mode 100644\n"
    "--- a/old.py\n+++ /dev/null\n@@ -1,3 +0,0 @@\n"
    "-def legacy():\n-    pass\n-class Gone:\n"
    "diff --git a/mod.py b/mod.py\n"
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,2 +1,2 @@\n"
    "-def run(a):\n+def run(a, b):\n+async def fresh():\n"
    "diff --git a/before.md b/after.md\nsimilarity index 90%\n"
    "rename from before.md\nrename to after.md\n"
)


def test_facts_record_status_and_top_level_definitions():
    """Mutant «always status M» fails the status list; mutant «also indented defs» fails the
    `nestedHelper`/`inner` assert; mutant «no symbols» fails the `addDays` one."""
    facts = {f.path: f for f in server._diff_facts(DIFF)}

    assert [(f.path, f.status) for f in server._diff_facts(DIFF)] == [
        ("src/dates.ts", "A"),
        ("old.py", "D"),
        ("mod.py", "M"),
        ("after.md", "R"),
    ]
    added = facts["src/dates.ts"].symbols()[0]
    assert added == ["addDays", "HOUR_FORMAT", "Calendar"]
    assert "nestedHelper" not in added and "inner" not in added
    assert facts["old.py"].symbols() == ([], ["legacy", "Gone"], [])
    assert facts["mod.py"].symbols() == (["fresh"], [], ["run"])
    # The tuple inventory keeps its contract.
    assert server._diff_inventory(DIFF)[0] == ("src/dates.ts", 6, 0)


def test_formatted_facts_carry_status_and_names_within_budget():
    """Mutant «drop the symbols block»: the `+ addDays` assert fails. Mutant «no cap on the
    names»: the length assert fails on the tight budget."""
    text = server._format_diff_facts(server._diff_facts(DIFF), 4_000)
    assert "  A src/dates.ts | +6 -0" in text
    assert "  D old.py | +0 -3" in text
    assert "src/dates.ts: + addDays, HOUR_FORMAT, Calendar" in text
    assert "old.py: - legacy, Gone" in text
    assert "mod.py: + fresh; ~ run" in text

    many = "".join(
        f"diff --git a/m{i}.py b/m{i}.py\n--- a/m{i}.py\n+++ b/m{i}.py\n@@ -0,0 +1 @@\n"
        f"+def function_number_{i}_with_a_long_name(): pass\n"
        for i in range(200)
    )
    tight = server._format_diff_facts(server._diff_facts(many), 3_000)
    assert len(tight) <= 3_000
    assert "archivos más con definiciones, omitidos por espacio" in tight


def _big_diff(files: int = 30, lines: int = 60) -> str:
    return "".join(
        f"diff --git a/paquete/mod{i}.py b/paquete/mod{i}.py\n"
        f"--- a/paquete/mod{i}.py\n+++ b/paquete/mod{i}.py\n"
        f"@@ -1,{lines} +1,{lines} @@\n"
        f"+def parse_day_{i}(value):\n"
        + "".join(f"+    linea {j} del modulo {i} con relleno de sobra\n" for j in range(lines))
        for i in range(files)
    )


@backend_mock.mock
def _request(monkeypatch, tmp_path, **kwargs) -> list[dict]:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    views: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        views.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "feat: algo"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    server.local_commit_msg(**kwargs)
    return views


def _user(request: dict) -> str:
    return request["messages"][-1]["content"]


def _system(request: dict) -> str:
    return request["messages"][0]["content"]


def test_the_reduce_prompt_carries_the_facts_and_the_grounding_rule(monkeypatch, tmp_path):
    """Mutant «reduce gets the old inventory» (`_format_inventory`): the `parse_day_29` and
    status asserts fail. Mutant «drop the rule»: the `Menciona SOLO` assert fails."""
    diff = _big_diff()
    assert len(diff) > config.max_chars_for_role("code"), "the diff must exceed the ceiling"
    views = _request(monkeypatch, tmp_path, diff=diff)

    assert len(views) > 2
    reduce_prompt = _user(views[-1])
    assert "M paquete/mod29.py | +61 -0" in reduce_prompt
    assert "paquete/mod29.py: + parse_day_29" in reduce_prompt
    assert "Menciona SOLO lo que respalden esa lista" in reduce_prompt
    # The map is told to be concrete and gets the names of its own piece.
    assert all("Sé concreto" in _system(v) for v in views[:-1])
    assert "paquete/mod0.py: + parse_day_0" in _user(views[0])


# --- Commit language from the repo history ---------------------------------------------------
def _repo_with_reflog(root: Path, subjects: list[str]) -> Path:
    logs = root / ".git" / "logs"
    logs.mkdir(parents=True)
    lines = [
        f"{'0' * 40} {'1' * 40} Someone <s@example.invalid> 1700000000 +0000\tcommit: {s}"
        for s in subjects
    ]
    lines.insert(1, f"{'1' * 40} {'2' * 40} X <x@example.invalid> 1700000001 +0000\tcheckout: a")
    (logs / "HEAD").write_text("\n".join(lines) + "\n", encoding="utf-8")
    nested = root / "sub" / "dir"
    nested.mkdir(parents=True)
    return nested


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
    "chore: sube la versión",
    "fix(panel): separa trozos y llamadas al backend",
    "docs: explica el uso del token",
]


@pytest.mark.parametrize(("subjects", "expected"), [(ENGLISH, "en"), (SPANISH, "es")])
def test_guess_language_reads_clear_histories(subjects, expected):
    """Mutant «always None»: fails here."""
    assert server._guess_language(subjects) == expected


def test_guess_language_abstains_when_mixed_or_short():
    """Mutant «majority wins without a threshold»: the mixed assert fails."""
    assert server._guess_language(ENGLISH[:3] + SPANISH[:3]) is None
    assert server._guess_language(ENGLISH[:2]) is None
    assert server._guess_language([]) is None


def test_a_diff_inside_an_english_repo_gets_an_english_message(monkeypatch, tmp_path):
    """Mutant «ignore the repo» (`_commit_language_instruction()` without `path`): the system says
    «en español» and the first assert fails."""
    assert VARIABLE not in os.environ
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    folder = _repo_with_reflog(tmp_path / "repo", ENGLISH)
    diff_file = folder / "change.diff"
    diff_file.write_text(
        "diff --git a/uno.py b/uno.py\n--- a/uno.py\n+++ b/uno.py\n@@ -1 +1 @@\n-a\n+b\n",
        encoding="utf-8",
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    system = _system(_request(monkeypatch, logs, path=str(diff_file))[0])
    assert system.endswith("(primera línea y cuerpo) en inglés.")


def test_the_repo_rule_falls_back_and_yields_to_the_variable(monkeypatch, tmp_path):
    """Outside a repo, or with a mixed history, the product language stays; the variable wins.

    Mutant «default to English»: the first assert fails.
    """
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    loose = tmp_path / "loose"
    loose.mkdir()
    assert server._repo_commit_language(str(loose / "x.diff")) is None
    assert server._commit_language_instruction(str(loose / "x.diff")).endswith(" en español.")

    mixed = _repo_with_reflog(tmp_path / "mixed", ENGLISH[:3] + SPANISH[:3])
    assert server._commit_language_instruction(str(mixed / "x.diff")).endswith(" en español.")

    english = _repo_with_reflog(tmp_path / "english", ENGLISH)
    monkeypatch.setenv(VARIABLE, "fr")
    assert server._commit_language_instruction(str(english / "x.diff")).endswith(" en francés.")


def test_a_worktree_git_file_is_followed(tmp_path):
    """A linked worktree has a `.git` FILE pointing at its git dir. Mutant «only `.git` dirs»:
    the assert gets None."""
    real = tmp_path / "gitdirs" / "wt"
    (real / "logs").mkdir(parents=True)
    (real / "logs" / "HEAD").write_text(
        "".join(f"a b c 1 +0000\tcommit (amend): {s}\n" for s in ENGLISH), encoding="utf-8"
    )
    work = tmp_path / "work"
    work.mkdir()
    (work / ".git").write_text(f"gitdir: {real}\n", encoding="utf-8")
    assert server._repo_commit_language(str(work / "change.diff")) == "en"
