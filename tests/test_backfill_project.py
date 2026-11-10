"""The project in the backfill, by cross and by session key (usage-log-project-and-own-repo-exclusion,
REQ-007 and REQ-031).

A synthetic world in `tmp_path`: two project directories (this repo and another one), their
sessions and subagents, a session repeated in both directories, and a usage log with exact,
window and window+path crosses and rows of the mod. Nothing real.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest
from test_transcripts import (
    BASE,
    log_line,
    main_transcript,
    request_entry,
    result_entry,
    subagent,
    write_jsonl,
    write_log,
)

from local_delegate import attribution, cost, recompute
from local_delegate.resources.hooks import hook_common

NOW = BASE + timedelta(days=1)
MONTH = "202610"
REPO_DIR = "D--Projects-local-delegate"
OTHER_DIR = "D--work-shop"
S_REPO = "11111111-1111-4111-8111-111111111111"
S_OTHER = "22222222-2222-4222-8222-222222222222"
S_TWICE = "33333333-3333-4333-8333-333333333333"
S_GONE = "44444444-4444-4444-8444-444444444444"


def _key(session: str) -> str:
    key = hook_common.session_key(session)
    assert key is not None
    return key


def _build(claude: Path) -> None:
    write_jsonl(
        main_transcript(claude, session=S_REPO, project=REPO_DIR),
        [
            request_entry(0, "r0", session=S_REPO, tool_use=("toolu_e1", "local_summarize", None)),
            result_entry(1, "toolu_e1", session=S_REPO),
            request_entry(2, "r1", session=S_REPO),
            request_entry(3, "r2", session=S_REPO),
        ],
    )
    # A subagent of the repo's session: the window crosses.
    write_jsonl(
        subagent(claude, "a1", session=S_REPO, project=REPO_DIR),
        [
            request_entry(100, "w0", session=S_REPO, tool_use=("toolu_w1", "local_extract", None)),
            result_entry(103, "toolu_w1", session=S_REPO),
            request_entry(
                400, "p0", session=S_REPO, tool_use=("toolu_p1", "local_lint_summary", "a.md")
            ),
            request_entry(
                400, "p1", session=S_REPO, tool_use=("toolu_p2", "local_lint_summary", "b.md")
            ),
            result_entry(402, "toolu_p1", session=S_REPO),
            result_entry(402, "toolu_p2", session=S_REPO),
        ],
    )
    write_jsonl(
        main_transcript(claude, session=S_OTHER, project=OTHER_DIR),
        [
            request_entry(
                10, "o0", session=S_OTHER, tool_use=("toolu_e2", "local_summarize", None)
            ),
            result_entry(11, "toolu_e2", session=S_OTHER),
            request_entry(
                12, "o1", session=S_OTHER, tool_use=("toolu_e3", "local_summarize", None)
            ),
            result_entry(13, "toolu_e3", session=S_OTHER),
            request_entry(
                200, "o2", session=S_OTHER, tool_use=("toolu_c1", "local_classify", None)
            ),
            result_entry(201, "toolu_c1", session=S_OTHER),
            request_entry(
                300, "o3", session=S_OTHER, tool_use=("toolu_t1", "local_translate", None)
            ),
            result_entry(301, "toolu_t1", session=S_OTHER),
        ],
    )
    for project in (REPO_DIR, OTHER_DIR):
        write_jsonl(main_transcript(claude, session=S_TWICE, project=project), [{"type": "user"}])


ROWS = {
    "exact_self": log_line(1, tool_use_id="toolu_e1", caller_session_key=_key(S_REPO)),
    "exact_other": log_line(13, tool_use_id="toolu_e3", caller_session_key=_key(S_OTHER)),
    "exact_mismatch": log_line(11, tool_use_id="toolu_e2", caller_session_key=_key(S_REPO)),
    "window_old": log_line(101, tool="local_extract"),
    "window_new": log_line(200, tool="local_classify"),
    "window_under_exact": log_line(300, tool="local_translate"),
    "window_path": log_line(401, tool="local_lint_summary", path="a.md"),
    "mod_self": log_line(
        500, tool_use_id="toolu_plugin_m1", caller_kind="main", caller_session_key=_key(S_REPO)
    ),
    "mod_twice": log_line(
        501, tool_use_id="toolu_plugin_m2", caller_kind="main", caller_session_key=_key(S_TWICE)
    ),
    "mod_gone": log_line(
        502, tool_use_id="toolu_plugin_m3", caller_kind="main", caller_session_key=_key(S_GONE)
    ),
    "mod_no_key": log_line(503, tool_use_id="toolu_plugin_m4", caller_kind="main"),
}
NAMES = list(ROWS)


def _keys() -> dict[str, str]:
    return dict(zip(NAMES, attribution.file_keys(list(ROWS.values())), strict=True))


def _seed(log: Path) -> dict[str, dict]:
    """What an older version left: entries of the same rank without project, and an `exact`
    under a key whose cross is now only a `window`. `n` differs from what the new pass computes."""
    keys = _keys()
    old = {
        keys["exact_self"]: {
            "match": "exact",
            "bench": False,
            "n": 99,
            "expiries": 0,
            "caller_model": "claude-opus-5-5",
            "caller_kind": "main",
        },
        keys["window_old"]: {
            "match": "window",
            "bench": False,
            "n": 98,
            "expiries": 0,
            "caller_kind": "subagent",
        },
        keys["window_under_exact"]: {
            "match": "exact",
            "bench": False,
            "n": 97,
            "expiries": 0,
            "caller_kind": "main",
        },
        keys["mod_self"]: {"match": "no_match", "bench": False},
    }
    log.mkdir(parents=True, exist_ok=True)
    path = attribution.backfill_path(log, MONTH)
    path.write_text(json.dumps({"version": 1, "entries": old}), encoding="utf-8")
    return old


@pytest.fixture
def ran(tmp_path):
    claude, log = tmp_path / "claude", tmp_path / "log"
    _build(claude)
    write_log(log, list(ROWS.values()), month=MONTH)
    old = _seed(log)
    recompute.run(claude, log, now=NOW)
    keys = _keys()
    entries = attribution.read_backfill(log, MONTH)
    by_name = {name: entries.get(keys[name]) for name in NAMES}
    salt = (log / "project-salt").read_text(encoding="ascii")
    return claude, log, by_name, old, salt


def _hash(salt: str, project: str) -> str:
    digest = hashlib.sha256(f"local-delegate-project:{salt}:{project.lower()}".encode())
    return digest.hexdigest()[:16]


def _project(entry: dict | None) -> tuple:
    entry = entry or {}
    return entry.get("caller_project"), entry.get("caller_project_kind")


# --- REQ-007: crosses ---------------------------------------------------------------------------


def test_exact_window_and_window_path_entries_carry_the_project(ran):
    """Mutant 22 (`entry_for` only gives the project to `exact`): the new `window` has none."""
    _claude, _log, e, _old, salt = ran
    assert e["exact_other"]["match"] == "exact"
    assert _project(e["exact_other"]) == (_hash(salt, OTHER_DIR), "other")
    assert e["window_new"]["match"] == "window"
    assert _project(e["window_new"]) == (_hash(salt, OTHER_DIR), "other")
    assert e["window_path"]["match"] == "window+path"
    assert _project(e["window_path"]) == (_hash(salt, REPO_DIR), "self")


def test_older_entries_of_the_same_rank_are_enriched(ran):
    """Mutant 19 (`write_backfill` does not enrich the same rank)."""
    _claude, _log, e, _old, salt = ran
    assert e["exact_self"]["match"] == "exact"
    assert _project(e["exact_self"]) == (_hash(salt, REPO_DIR), "self")
    assert e["window_old"]["match"] == "window"
    assert _project(e["window_old"]) == (_hash(salt, REPO_DIR), "self")


def test_enriching_adds_the_fields_and_changes_no_other(ran):
    """Mutant 20 (`write_backfill` replaces instead of adding): the old `n` is lost."""
    _claude, _log, e, old, _salt = ran
    keys = _keys()
    for name in ("exact_self", "window_old"):
        before = old[keys[name]]
        after = e[name]
        assert {k: v for k, v in after.items() if k not in attribution.PROJECT_FIELDS} == before
    assert e["exact_self"]["n"] == 99


def test_a_lower_rank_never_touches_a_higher_one(ran):
    """Mutant 23 (a lower rank enriches a higher one): the `exact` gains the `window`'s project."""
    _claude, _log, e, old, _salt = ran
    assert e["window_under_exact"] == old[_keys()["window_under_exact"]]


def test_the_merged_row_takes_the_project_from_the_backfill(ran):
    """Mutant 21 (`BACKFILL_FIELDS` without the new fields): the merged row has no kind."""
    _claude, log, _e, _old, salt = ran
    rows = [json.loads(x) for x in (log / f"usage-{MONTH}.jsonl").read_text().splitlines()]
    merged = dict(zip(NAMES, cost.merge(rows, log_dir=log), strict=True))
    assert merged["exact_self"]["caller_project_kind"] == "self"
    assert merged["exact_self"]["caller_project"] == _hash(salt, REPO_DIR)
    assert merged["window_new"]["caller_project_kind"] == "other"
    assert "caller_project_kind" not in rows[NAMES.index("exact_self")], "guard: not in the line"


def test_a_row_already_sealed_keeps_its_own_project():
    sealed = {"caller_project": "aaaaaaaaaaaaaaaa", "caller_project_kind": "other"}
    entry = {"match": "exact", "caller_project": "bbbbbbbbbbbbbbbb", "caller_project_kind": "self"}
    out = cost.merge_row({"tool": "local_summarize", **sealed}, entry)
    assert (out["caller_project"], out["caller_project_kind"]) == ("aaaaaaaaaaaaaaaa", "other")


def test_a_second_pass_enriches_nothing_else_and_loses_nothing(ran):
    claude, log, e, _old, _salt = ran
    first = attribution.backfill_path(log, MONTH).read_text(encoding="utf-8")
    recompute.run(claude, log, now=NOW + timedelta(minutes=1))
    second = attribution.backfill_path(log, MONTH).read_text(encoding="utf-8")
    assert json.loads(second) == json.loads(first)
    assert e["exact_self"].get("caller_project_kind") == "self"


# --- REQ-031: the session key -------------------------------------------------------------------


def test_a_mod_row_gets_the_project_of_its_session_key(ran):
    """Mutant 24 (the session key is not used): the mod's `no_match` has no project."""
    _claude, _log, e, _old, salt = ran
    assert _project(e["mod_self"]) == (_hash(salt, REPO_DIR), "self")


def test_the_session_key_does_not_rewrite_the_match(ran):
    """Mutant 25 (the session key rewrites the `match`)."""
    _claude, _log, e, _old, _salt = ran
    assert e["mod_self"]["match"] == "no_match"
    assert e["mod_self"]["bench"] is False


def test_a_cross_and_a_key_in_different_projects_give_none(ran):
    """Mutant 26 (with cross and key in different projects one wins)."""
    _claude, _log, e, _old, _salt = ran
    assert e["exact_mismatch"]["match"] == "exact", "guard: there was a cross"
    assert _project(e["exact_mismatch"]) == (None, None)


def test_a_session_in_two_directories_gives_none(ran):
    """Mutant 27 (the index keeps the first directory of a repeated session)."""
    _claude, _log, e, _old, _salt = ran
    assert e["mod_twice"]["match"] == "no_match"
    assert _project(e["mod_twice"]) == (None, None)


@pytest.mark.parametrize("name", ["mod_gone", "mod_no_key"])
def test_without_a_live_session_or_a_key_there_is_none(ran, name):
    _claude, _log, e, _old, _salt = ran
    assert e[name]["match"] == "no_match"
    assert _project(e[name]) == (None, None)


def test_no_name_or_session_id_reaches_the_backfill(ran):
    _claude, log, _e, _old, _salt = ran
    text = attribution.backfill_path(log, MONTH).read_text(encoding="utf-8")
    for secret in (REPO_DIR, OTHER_DIR, S_REPO, S_OTHER, S_TWICE, "shop"):
        assert secret not in text
