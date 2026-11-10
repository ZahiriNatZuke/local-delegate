"""#636: a chunked `local_commit_msg` inverted the sense of a changed condition, typed a fix as
`feat` and said nothing.

The diff of the issue (~27 KB, 3 parts) changed `_running() if probe.available` into «also when the
probe failed with the backend taking the connection, never when the backend is not there». The
reduce saw only the per-part notes plus the file inventory: not one literal line of the condition,
and no hint of the type. Now the reduce gets the changed condition lines copied from the diff and
the type the diff itself points to (a `fix/` branch, the CHANGELOG section, only tests or only
docs), the first line's type is set to that one when it differs, and a chunked message always ends
with a warning that names it as chunked and lists the changed conditions to review it against.

Each test says which mutant makes it fail and with which assert.
"""

from __future__ import annotations

import json
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import config, server

CODE = "src/app/web/probe_view.py"
TESTS = "tests/test_probe_view.py"


def _code_file() -> str:
    filler = "".join(
        f" def helper_{i}(value):\n"
        f"     return value + {i}  # untouched helper number {i} of the probe view\n"
        " \n"
        for i in range(60)
    )
    return (
        f"diff --git a/{CODE} b/{CODE}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{CODE}\n+++ b/{CODE}\n"
        "@@ -40,11 +40,13 @@ def backend(lang=None):\n"
        "     probe = server.probe_backend()\n"
        "-    running, running_ok = _running() if probe.available else ([], False)\n"
        "+    ask_running = probe.available or probe.cause in CAUSES_WORTH_RUNNING\n"
        "+    running, running_ok = _running() if ask_running else ([], False)\n"
        "     return JSONResponse({'available': probe.available, 'running': running})\n"
        "@@ -60,6 +62,15 @@ def backend(lang=None):\n"
        "+# The backend took the connection: /running is still worth asking. A refused or\n"
        "+# unreachable backend is left out on purpose, so «down» keeps costing one deadline.\n"
        "+CAUSES_WORTH_RUNNING = frozenset(\n"
        "+    {\n"
        "+        'no_response',\n"
        "+        'http_error',\n"
        "+        'invalid_response',\n"
        "+    }\n"
        "+)\n"
        "@@ -90,6 +101,6 @@ def _running():\n" + filler
    )


def _tests_file() -> str:
    cases = "".join(
        f"+def test_cause_{i}_decides_whether_running_is_asked(monkeypatch):\n"
        f"+    calls = _probe_with(monkeypatch, cause=CAUSES[{i} % len(CAUSES)])\n"
        f"+    if CAUSES[{i} % len(CAUSES)] in ('refused', 'dns', 'no_route'):\n"
        "+        assert calls == []\n"
        "+    else:\n"
        "+        assert calls == ['/running']\n"
        "+\n"
        for i in range(70)
    )
    return (
        f"diff --git a/{TESTS} b/{TESTS}\n"
        "new file mode 100644\n"
        "index 0000000..3333333\n"
        f"--- /dev/null\n+++ b/{TESTS}\n"
        "@@ -0,0 +1,500 @@\n"
        "+CAUSES = ['refused', 'dns', 'no_route', 'no_response', 'http_error']\n"
        "+\n" + cases
    )


def _changelog(section: str = "### Corregido") -> str:
    return (
        "diff --git a/CHANGELOG.md b/CHANGELOG.md\n"
        "index 4444444..5555555 100644\n"
        "--- a/CHANGELOG.md\n+++ b/CHANGELOG.md\n"
        "@@ -7,6 +7,10 @@\n"
        " ## [Unreleased]\n"
        " \n"
        f" {section}\n"
        " \n"
        "+- La banda ya no dice «caído» con el backend vivo: el daemon pide `/running` también\n"
        "+  cuando `/v1/models` falla con el backend atendiendo la conexión, y no lo pide cuando\n"
        "+  el backend no está (#628).\n"
        "+\n"
    )


def _issue_diff(section: str = "### Corregido") -> str:
    return _changelog(section) + _code_file() + _tests_file()


INVERTED = (
    "feat(backend): consulta /running en errores de red\n\n"
    "- Pide /running cuando hay errores de red\n"
    "- Añade tests de las causas"
)


@backend_mock.mock
def _run(monkeypatch, tmp_path, answer: str = INVERTED, **kwargs) -> tuple[str, list[dict]]:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setenv("LOCAL_DELEGATE_COMMIT_LANGUAGE", "es")
    views: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        views.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return server.local_commit_msg(**kwargs), views


def _user(request: dict) -> str:
    return request["messages"][-1]["content"]


def test_the_issue_diff_is_chunked_with_the_condition_apart_from_its_tests():
    """Guard: the shape of the issue holds, or the tests below check nothing."""
    diff = _issue_diff()
    assert len(diff) > config.max_chars_for_role("code")
    pieces = server._chunk_text(diff, server._map_budget(config.max_chars_for_role("code")))
    assert len(pieces) >= 2
    with_condition = [p for p in pieces if "ask_running = probe.available" in p]
    with_tests = [p for p in pieces if "assert calls == ['/running']" in p]
    assert with_condition and with_tests and with_condition[0] is not with_tests[-1]


def test_the_reduce_gets_the_changed_condition_lines_literally(monkeypatch, tmp_path):
    """Mutant «no conditions block in the reduce»: the `- running, running_ok` assert fails."""
    _, views = _run(monkeypatch, tmp_path, diff=_issue_diff())
    reduce_prompt = _user(views[-1])

    assert "- running, running_ok = _running() if probe.available else ([], False)" in (
        reduce_prompt
    )
    assert "+ ask_running = probe.available or probe.cause in CAUSES_WORTH_RUNNING" in (
        reduce_prompt
    )
    # The code file goes before its tests, and a comment line is not a condition.
    block = reduce_prompt[reduce_prompt.index("Condiciones cambiadas") :]
    assert block.index(f"{CODE}:") < block.index(f"{TESTS}:")
    assert "+ # The backend took the connection" not in reduce_prompt


def test_the_reduce_is_told_the_type_the_changelog_points_to(monkeypatch, tmp_path):
    """Mutant «no type hint in the reduce»: the `tipo: fix` assert fails."""
    _, views = _run(monkeypatch, tmp_path, diff=_issue_diff())
    assert "tipo: fix" in _user(views[-1])


def test_a_feat_on_a_fix_changelog_becomes_fix_and_says_so(monkeypatch, tmp_path):
    """Mutant «no type correction»: the `startswith('fix(backend):')` assert fails."""
    answer, _ = _run(monkeypatch, tmp_path, diff=_issue_diff())

    assert answer.startswith("fix(backend): consulta /running en errores de red\n")
    assert "`feat` → `fix`" in answer


def test_a_chunked_message_always_ends_with_the_review_warning(monkeypatch, tmp_path):
    """Mutant «no chunked warning»: the `partes` assert fails. The changed condition goes in it,
    so whoever reads the message can check its sense without the diff."""
    answer, _ = _run(monkeypatch, tmp_path, diff=_issue_diff())
    warnings = [p for p in answer.split("\n\n") if p.startswith(server.WARNING_MARKER)]

    chunked = [w for w in warnings if "se redactó por partes" in w]
    assert chunked, answer
    assert "+ ask_running = probe.available or probe.cause in CAUSES_WORTH_RUNNING" in chunked[0]
    # It goes before the receipts, which stay last.
    assert answer.rstrip().endswith(")")
    assert answer.index("se redactó por partes") < answer.index("(alcance:")


def test_a_single_call_message_gets_neither_warning_nor_correction(monkeypatch, tmp_path):
    """The one-call path is unchanged: a small diff keeps the model's type and has no warning."""
    small = _changelog() + (
        f"diff --git a/{CODE} b/{CODE}\n--- a/{CODE}\n+++ b/{CODE}\n@@ -1,1 +1,1 @@\n"
        "-    x = a if b else c\n+    x = a if d else c\n"
    )
    answer, views = _run(monkeypatch, tmp_path, diff=small)

    assert len(views) == 1
    assert answer.startswith("feat(backend):")
    assert "se redactó por partes" not in answer


def test_the_plain_style_keeps_its_first_line(monkeypatch, tmp_path):
    """No conventional type to correct in the plain style; the warning still goes."""
    plain = "Consulta /running en errores de red\n\n- Pide /running\n- Añade tests"
    answer, _ = _run(monkeypatch, tmp_path, answer=plain, diff=_issue_diff(), style="plain")
    assert answer.startswith("Consulta /running en errores de red\n")
    assert "se redactó por partes" in answer


# --- The facts, without the tool -----------------------------------------------------------------
def test_condition_changes_rank_code_first_skip_comments_and_fit_the_budget():
    """Mutant «tests first»: the order assert fails; mutant «comments count»: the comment one."""
    text = server._format_condition_changes(_issue_diff(), 2_000)
    assert text.index(f"{CODE}:") < text.index(f"{TESTS}:")
    assert "The backend took the connection" not in text
    assert len(text) <= 2_000
    tight = server._format_condition_changes(_issue_diff(), 400)
    assert len(tight) <= 400
    assert "ask_running = probe.available" in tight
    assert server._format_condition_changes(_changelog(), 2_000) == ""


@pytest.mark.parametrize(
    ("diff", "expected"),
    [
        (_issue_diff(), "fix"),
        (_issue_diff("### Fixed"), "fix"),
        (_issue_diff("### Añadido"), "feat"),
        (_issue_diff("### Added"), "feat"),
        (_tests_file(), "test"),
        (
            (
                "diff --git a/docs/a.md b/docs/a.md\n--- a/docs/a.md\n+++ b/docs/a.md\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            ),
            "docs",
        ),
        (_code_file(), None),
        (_issue_diff("### Cambiado"), None),
        (
            "diff --git a/CHANGELOG.md b/CHANGELOG.md\n--- a/CHANGELOG.md\n+++ b/CHANGELOG.md\n"
            "@@ -7,4 +7,8 @@\n ### Añadido\n+- algo nuevo\n ### Corregido\n+- algo roto\n"
            + _code_file(),
            None,
        ),
    ],
)
def test_the_type_signal_of_the_diff(diff, expected):
    """Mutant «changelog section ignored»: the `fix`/`feat` rows fail; mutant «no tests-only
    rule»: the `test` row fails."""
    signal = server._commit_type_signal(diff, None)
    assert (signal[0] if signal else None) == expected


def test_a_fix_branch_names_the_type(tmp_path: Path):
    """Mutant «branch ignored»: the `fix` assert fails."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/fix/running-on-failed-probe\n", encoding="utf-8")
    diff_path = tmp_path / "change.diff"
    diff_path.write_text(_code_file(), encoding="utf-8")

    assert server._commit_type_signal(_code_file(), str(diff_path)) == (
        "fix",
        "branch",
        "fix/running-on-failed-probe",
    )
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert server._commit_type_signal(_code_file(), str(diff_path)) is None
