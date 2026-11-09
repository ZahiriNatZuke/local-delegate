"""The files a lint/test log names are found in linear time, with the same result as `FILE`.

`lint_patterns.FILE` with `findall` tried every position of a run without spaces and scanned it to
the end each time: quadratic. The progress line of `python -m unittest` (one dot per test, no line
break) took 6 s of CPU at 8 000 dots, with the GIL held in the daemon. `file_spans` gives the spans
of `FILE.finditer` in one pass; `FILE` stays the definition, and a differential fuzz holds them
equal. The same applies to the finding counters of a JSON report (`errorCount`), once matched with
`.*(?:error|...).*count`.

Each time cap fails on the old code by its time assert, not by its result: at 20 000 chars the old
`findall` took about 40 s here.
"""

from __future__ import annotations

import json
import random
import time

import pytest

from local_delegate import config, lint_patterns, server

#: Twenty times the measured linear cost, and fifty times under the old one.
CAP_SECONDS = 1.0
N = 20_000

LONG_RUNS = {
    "dots": "." * N,
    "word_dot": "a." * (N // 2),
    "word_slash": "a/" * (N // 2),
    "tilde_word": "~a" * (N // 2),
    "word": "a" * N,
    "file_dots_file": "a.py" + "." * N + "b.py",
    "dirs_no_extension": "dir.v1/" * (N // 7) + "x.pyz",
}


def _timed(func, *args):
    start = time.perf_counter()
    result = func(*args)
    return result, time.perf_counter() - start


@pytest.mark.parametrize("name", sorted(LONG_RUNS))
def test_a_long_run_without_spaces_is_searched_in_linear_time(name):
    text = f"Ran 3 tests\n{LONG_RUNS[name]}\nFAIL: tests/test_x.py:3: E501 line\n"
    files, elapsed = _timed(lint_patterns.files_by_frequency, text)
    assert elapsed < CAP_SECONDS, f"files_by_frequency took {elapsed:.2f} s on {name}"
    assert "tests/test_x.py" in files
    codes, elapsed = _timed(lint_patterns.code_counts, text)
    assert elapsed < CAP_SECONDS, f"code_counts took {elapsed:.2f} s on {name}"
    assert ("E501", 1) in codes


# --- Same result as the regex ----------------------------------------------------------------------

#: Characters and pieces that move the regex: the separators, `~`, word characters (one not ASCII,
#: one that IGNORECASE folds to `s`), the dot, and extensions whole, cut or followed by more.
_PIECES = list("ab_9é.-~/\\: \n") + [
    ".py", ".PY", ".pyi", ".pyc", ".spec.ts", ".ts", ".tsx", ".yml", ".yaml", ".ymal",
    ".json", ".jsonl", ".lock", "ſh", ".sh", ".md", "py", "/x.", "..", "//",
]  # fmt: skip


def _random_text(rng: random.Random) -> str:
    return "".join(rng.choice(_PIECES) for _ in range(rng.randint(0, 24)))


def test_file_spans_are_the_spans_of_the_regex():
    rng = random.Random(593)
    checked = 0
    for _ in range(30_000):
        text = _random_text(rng)
        expected = [m.span() for m in lint_patterns.FILE.finditer(text)]
        assert lint_patterns.file_spans(text) == expected, text
        checked += bool(expected)
    # Guard: the fuzz reached many texts that do name a file.
    assert checked > 5_000


@pytest.mark.parametrize(
    "text",
    [
        "src/app/main.py:12:1: E501",
        r"C:\Users\dev\repo\tests\test_a.py",
        "~/proj/a.spec.ts and b.SPEC.TS",
        "a.py.bak a.py-x a.pyb.py config.yaml.lock",
        "x//y.py ~a.py a~b.py ./rel/../up.md",
        "build\\_corpus.py test_E501.py",
    ],
)
def test_known_shapes_give_what_the_regex_gives(text):
    assert lint_patterns.file_spans(text) == [m.span() for m in lint_patterns.FILE.finditer(text)]
    assert lint_patterns.files_by_frequency(text) == _old_files_by_frequency(text)


def _old_files_by_frequency(log: str) -> list[str]:
    seen: dict[str, str] = {}
    counts: dict[str, int] = {}
    for match in lint_patterns.FILE.findall(log):
        key = lint_patterns.norm_path(match)
        seen.setdefault(key, match.replace("\\", "/"))
        counts[key] = counts.get(key, 0) + 1
    order = {key: index for index, key in enumerate(seen)}
    return [seen[k] for k in sorted(counts, key=lambda k: (-counts[k], order[k]))]


# --- Finding counters of a JSON report -------------------------------------------------------------

_KEY_PIECES = ["error", "Error", "ERROR", "warning", "offense", "issue", "problem", "violation",
               "count", "Count", "COUNT", "_", "fatal", "x", "ſ", "ı", "s", "counts", "cou", "\n", "\r"]  # fmt: skip


def test_the_finding_counter_check_is_the_regex():
    rng = random.Random(210)
    hits = 0
    for _ in range(30_000):
        key = "".join(rng.choice(_KEY_PIECES) for _ in range(rng.randint(0, 6)))
        expected = lint_patterns._FINDING_COUNT.fullmatch(key) is not None
        assert lint_patterns.is_finding_counter(key) is expected, key
        hits += expected
    assert hits > 1_500


def test_a_long_json_key_is_checked_in_linear_time():
    key = "error " * 40_000 + "x"
    report = json.dumps([{"filePath": "a.js", "messages": [], key: 1}])
    verdict, elapsed = _timed(lint_patterns.clean_verdict, report)
    assert elapsed < CAP_SECONDS, f"clean_verdict took {elapsed:.2f} s"
    assert verdict == ""  # the key is no counter: the report is clean, as before


# --- The tool's own path ---------------------------------------------------------------------------


def test_a_chunked_unittest_log_returns_in_seconds(monkeypatch, tmp_path):
    users: list[str] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        users.append(user)
        result = server.ChatResult(text="- nota", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 6000)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 6000)
    log = (
        "." * N
        + "F\n"
        + "=" * 70
        + "\nFAIL: test_parse (tests.test_x.ParseTest)\nTraceback (most recent call last):\n"
        + '  File "tests/test_x.py", line 3, in test_parse\nAssertionError: 1 != 2\n'
        + "-" * 70
        + f"\nRan {N + 1} tests in 4.2s\n\nFAILED (failures=1)\n"
    )
    out, elapsed = _timed(server.local_lint_summary, None, log)
    assert elapsed < 5 * CAP_SECONDS, f"local_lint_summary took {elapsed:.2f} s"
    assert not out.startswith("[local-delegate error]")
    assert len(users) > 1  # guard: the log was chunked, so the inventory was built
    assert any("tests/test_x.py" in user.split("La lista de arriba")[0] for user in users)
    assert lint_patterns.files_by_frequency(log) == ["tests/test_x.py"]
