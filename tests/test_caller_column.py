"""Who asked, in one rule, and the project kind of a row (usage-log-project-and-own-repo-exclusion,
REQ-008 and REQ-022). Rows are synthetic."""

from __future__ import annotations

import pytest

from local_delegate import attribution, cost

MOD_ID = "toolu_plugin_abc123"


def test_a_mod_row_is_mod_even_with_caller_kind_main():
    """Mutant 28 (`caller_column` looks at `caller_kind` before the mod)."""
    row = {"tool_use_id": MOD_ID, "caller_kind": "main", "caller_src": "hook"}
    assert attribution.caller_column(row) == "mod"


@pytest.mark.parametrize("kind", ["main", "subagent"])
def test_the_hook_note_makes_the_thread_real_data(kind):
    row = {"tool_use_id": "toolu_x1", "caller_kind": kind, "caller_src": "hook+transcript"}
    assert attribution.caller_column(row) == kind


@pytest.mark.parametrize(
    ("match", "kind", "expected"),
    [
        ("exact", "subagent", "subagent"),
        ("window", "main", "main"),
        ("window+path", "subagent", "subagent"),
        ("ambiguous", "main", "unknown"),
        ("no_match", "main", "unknown"),
    ],
)
def test_a_backfilled_thread_counts_only_with_a_real_cross(match, kind, expected):
    row = {"tool": "local_summarize", "client": "claude-code"}
    merged = cost.merge_row(row, {"match": match, "caller_kind": kind})
    assert attribution.caller_column(merged) == expected


def test_the_fallback_thread_is_not_data():
    """Mutant 29 (`caller_column` takes the fallback as good): the merged row says `subagent`."""
    merged = cost.merge_row({"tool": "local_summarize", "client": "claude-code"})
    assert merged["caller_kind"] == "subagent", "guard: the fallback filled the thread in"
    assert merged["caller_origin"] == "fallback"
    assert attribution.caller_column(merged) == "unknown"


@pytest.mark.parametrize(
    "row",
    [
        {},
        {"caller_kind": "main"},
        {"caller_kind": "weird", "caller_src": "hook"},
        {"caller_kind": None, "match": "exact"},
        {"tool_use_id": "toolu_x2", "caller_kind": "subagent"},
    ],
)
def test_everything_else_is_unknown(row):
    assert attribution.caller_column(row) == "unknown"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("self", "self"), ("other", "other"), (None, "unknown"), ("", "unknown"), ("SELF", "unknown")],
)
def test_the_project_kind_of_a_row(value, expected):
    row = {} if value is None else {"caller_project_kind": value}
    assert attribution.project_kind(row) == expected
    assert attribution.project_kind({"caller_project": "0123456789abcdef"}) == "unknown"
