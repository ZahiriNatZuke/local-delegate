"""#582: `local_explain_code` over a large unified diff gave 5 of 32 files and shifted ranges.

The `N| ` numbering of every chunk was right; the model took the `+c,d` of a hunk header for lines
of the patch (242–257 is `+242,16`), the map asked for one bullet per function (a diff has none at
column 0), the reduce was told not to enumerate, and nothing said the answer came from chunks
unless the feedback receipt was on. Now, with `path` and a diff: the system says which numbers are
lines of the patch, each chunk is told its files and lines by program, the reduce gets the whole
index, and the answer ends with that index. Every chunked answer says it was chunked. The backend
is faked (`_run_chat`): no network, log in tmp.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from local_delegate import config, i18n, line_check, server

QUESTION = "Lista los ficheros del diff con el rango de líneas de cada uno dentro del patch"
FILES = 32
# The answer of the issue: five files, one of them with the hunk header's numbers.
REDUCE = "El diff toca 5 ficheros:\n- src/mod_0.py (líneas 242-257)\n- src/mod_1.py (líneas 30-50)"
MAP = "- src/mod_0.py (líneas 1-20): cambia valores."
HINT = "Ficheros del diff que hay en este fragmento"
INDEX_HEAD = "Índice COMPLETO de los ficheros del diff"


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """Every call recorded; the map answers `MAP`, the reduce `REDUCE`."""
    calls: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user})
        text = MAP if user.startswith("Toma notas") else REDUCE
        return _ok(text), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.delenv("LOCAL_DELEGATE_DUMP_CHUNK_NOTES", raising=False)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return calls


def _diff(files: int = FILES, git: bool = True) -> str:
    """A unified diff of `files` files, two hunks each, headers with numbers far from the patch's."""
    out: list[str] = []
    for i in range(files):
        if git:
            out.append(f"diff --git a/src/mod_{i}.py b/src/mod_{i}.py\nindex 111..222 100644\n")
        out.append(f"--- a/src/mod_{i}.py\n+++ b/src/mod_{i}.py\n")
        for h in range(2):
            out.append(f"@@ -{240 + h * 40},15 +{242 + h * 40},16 @@ def f_{i}_{h}():\n")
            out += [f"     ctx_{i}_{h}_{k} = compute({k})  # context line\n" for k in range(12)]
            out.append(f"-    old_{i}_{h} = 1\n+    new_{i}_{h} = 2\n+    extra_{i}_{h} = 3\n")
    return "".join(out)


def _real_ranges(text: str) -> dict[str, tuple[int, int]]:
    """Each file's first and last line in the patch, by hand (header to line before the next)."""
    lines = text.split("\n")
    starts = [n for n, line in enumerate(lines, 1) if line.startswith("diff --git ")]
    last = len(text.rstrip("\n").split("\n"))
    ends = [s - 1 for s in starts[1:]] + [last]
    return {
        re.search(r"b/(\S+)$", lines[s - 1]).group(1): (s, e)
        for s, e in zip(starts, ends, strict=True)
    }


@pytest.fixture
def patch(tmp_path: Path) -> Path:
    file = tmp_path / "big.patch"
    file.write_bytes(_diff().encode("utf-8"))
    return file


# --- the pure index -------------------------------------------------------------------------


def test_the_ranges_of_a_git_diff_are_its_header_lines_in_the_patch():
    text = _diff()
    ranges = line_check.diff_file_ranges(text)
    expected = _real_ranges(text)
    assert len(ranges) == FILES
    assert {path: (a, b) for a, b, path in ranges} == expected
    lines = text.split("\n")
    assert all(lines[a - 1].startswith("diff --git ") for a, _b, _p in ranges)


def test_a_diff_without_git_headers_starts_each_file_at_its_minus_header():
    text = _diff(files=3, git=False)
    ranges = line_check.diff_file_ranges(text)
    lines = text.split("\n")
    assert [p for _a, _b, p in ranges] == ["src/mod_0.py", "src/mod_1.py", "src/mod_2.py"]
    assert all(lines[a - 1].startswith("--- a/") for a, _b, _p in ranges)
    assert ranges[0][1] == ranges[1][0] - 1


def test_deleted_renamed_and_added_files_get_their_real_path():
    text = (
        "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n--- a/gone.py\n+++ /dev/null\n"
        "@@ -1 +0,0 @@\n-x = 1\n"
        "diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n"
        "diff --git a/born.py b/born.py\nnew file mode 100644\n--- /dev/null\n+++ b/born.py\n"
        "@@ -0,0 +1 @@\n+y = 2\n"
    )
    assert line_check.diff_file_ranges(text) == [
        (1, 6, "gone.py"),
        (7, 10, "new.py"),
        (11, 16, "born.py"),
    ]


def test_what_is_not_a_diff_has_no_ranges():
    assert line_check.diff_file_ranges("def f():\n    return 1\n") == []
    assert line_check.diff_file_ranges("") == []


# --- the chunked path -----------------------------------------------------------------------


def test_the_issue_case_ends_with_every_file_and_its_real_lines(backend, patch):
    """Mutant «no index at the end»: the 32 `- path: a–b` asserts fall."""
    result = server.local_explain_code(path=str(patch), question=QUESTION)
    assert len(backend) > 2  # guard: it chunked, as in the issue
    assert result.startswith(REDUCE)  # the prose is not rewritten
    assert i18n.t("mcp.explain.diff_index", count=FILES) in result
    for path, (first, last) in _real_ranges(patch.read_text(encoding="utf-8")).items():
        assert f"- {path}: {first}–{last}" in result


def test_a_chunked_answer_says_it_was_chunked_with_feedback_off(backend, patch):
    """Mutant «no chunk notice»: the notice assert falls (`FEEDBACK_ENABLED` is off here)."""
    result = server.local_explain_code(path=str(patch), question=QUESTION)
    maps = [c for c in backend if c["user"].startswith("Toma notas")]
    assert len(maps) > 1
    assert i18n.t("mcp.explain.chunked", pieces=len(maps)) in result
    # The notice goes after the prose and before what the program adds.
    assert result.index("(local-delegate:") < result.index(
        i18n.t("mcp.explain.diff_index", count=FILES)
    )


def test_each_chunk_is_told_its_files_and_lines_by_program(backend, patch):
    """Mutant «no diff hint»: the hint asserts fall. Every file is named in some chunk."""
    server.local_explain_code(path=str(patch), question=QUESTION)
    maps = [c for c in backend if c["user"].startswith("Toma notas")]
    real = _real_ranges(patch.read_text(encoding="utf-8"))
    named: set[str] = set()
    for call in maps:
        assert HINT in call["user"]
        hint = call["user"].split("\n\n", 1)[0]
        for path, (first, last) in real.items():
            if f"{path} (líneas {first}–{last})" in hint:
                named.add(path)
        # A file named in a chunk's hint does start or end inside it.
        body = call["user"].split("\n\n", 1)[1]
        held = {int(n) for n in re.findall(r"(?m)^(\d+)\| ", body)}
        for path in re.findall(r"(src/mod_\d+\.py) \(líneas", hint):
            first, last = real[path]
            assert held & set(range(first, last + 1))
    assert named == set(real)


def test_the_map_asks_one_bullet_per_file_and_the_reduce_gets_the_whole_index(backend, patch):
    """Mutant «map per function» or «reduce forbids enumerating»: these asserts fall."""
    server.local_explain_code(path=str(patch), question=QUESTION)
    maps = [c for c in backend if c["user"].startswith("Toma notas")]
    reduce = backend[-1]
    assert "CADA fichero del diff" in maps[0]["system"]
    assert "función, clase o método" not in maps[0]["system"]
    assert INDEX_HEAD in reduce["user"]
    assert "ni enumeres sus partes" not in reduce["user"]
    for path, (first, last) in _real_ranges(patch.read_text(encoding="utf-8")).items():
        assert f"- {path}: {first}–{last}" in reduce["user"]


def test_the_system_says_hunk_header_numbers_are_not_lines_of_the_patch(backend, patch):
    """Mutant «no diff clause»: the clause asserts fall, in the map and the reduce."""
    server.local_explain_code(path=str(patch), question=QUESTION)
    assert all(server._DIFF_LINES_CLAUSE in c["system"] for c in backend)
    assert all(server._DIFF_NOTE in c["system"] for c in backend)


# --- what does not change -------------------------------------------------------------------


def test_a_small_diff_is_one_call_with_the_clause_and_no_index(backend, tmp_path):
    file = tmp_path / "small.patch"
    file.write_bytes(_diff(files=2).encode("utf-8"))
    result = server.local_explain_code(path=str(file), question=QUESTION)
    assert len(backend) == 1
    assert server._DIFF_LINES_CLAUSE in backend[0]["system"]
    assert "(local-delegate:" not in result
    assert i18n.t("mcp.explain.diff_index", count=2) not in result


def _big_python(tmp_path: Path) -> Path:
    body = "".join(
        f"def func_{i}(args):\n"
        + "".join(f"    v{j} = h_{i}_{j}(args)\n" for j in range(12))
        + "\n\n"
        for i in range(120)
    )
    assert len(body) > config.max_chars_for_role("code")
    file = tmp_path / "big.py"
    file.write_text(body, encoding="utf-8")
    return file


def test_chunked_code_with_a_question_gets_the_notice_but_no_diff_prompts(backend, tmp_path):
    """A chunked Python file asked a question: the notice, nothing of the diff path."""
    result = server.local_explain_code(path=str(_big_python(tmp_path)), question="¿Qué hace?")
    maps = [c for c in backend if c["user"].startswith("Toma notas")]
    assert len(maps) > 1
    assert i18n.t("mcp.explain.chunked", pieces=len(maps)) in result
    assert all(HINT not in c["user"] for c in backend)
    assert all(server._DIFF_LINES_CLAUSE not in c["system"] for c in backend)
    assert "función, clase o método" in maps[0]["system"]


def test_a_plain_chunked_explanation_keeps_its_output(backend, tmp_path):
    """Without a question or a diff the output stays as before #582 (its hash is frozen)."""
    result = server.local_explain_code(path=str(_big_python(tmp_path)))
    assert len(backend) > 2
    assert "(local-delegate:" not in result


def test_inline_diff_has_no_numbered_prompts(backend):
    """With `code=` there are no line numbers, so no diff clause or index; still the notice."""
    result = server.local_explain_code(code=_diff(), question=QUESTION)
    assert len(backend) > 2
    assert all(server._DIFF_LINES_CLAUSE not in c["system"] for c in backend)
    assert i18n.t("mcp.explain.diff_index", count=FILES) not in result
    assert "(local-delegate:" in result
