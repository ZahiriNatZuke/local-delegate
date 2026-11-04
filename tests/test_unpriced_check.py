"""#563: Claude Haiku 5.5 priced (with its prompt-length tier), and a price check that an unpriced
model no longer brings down.

The Haiku 5.5 rows marked «real» are numbers of `cost-state` lines of this PC, reduced to their six
fields and frozen here (as in `test_pricing.py`): they are not computed with the table. The rows
marked «synthetic» are built by hand to tell the two tiers apart; their expected bounds are written
out from the official prices (platform.claude.com/docs/en/about-claude/pricing, read 2026-11-04).

The logic tests judge those rows against `FROZEN`, a copy of the prices that billed them, never
against the package table: the price watcher updates `prices.json` when the official page changes,
and a legitimate price change must not turn this suite red (#567). The package table itself is only
held to invariants that a price change keeps.
"""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from local_delegate import checks, i18n, pricing, recompute, transcripts
from local_delegate.pricing import check_rows, entry, load_prices, priced_verdict, verdict

PRICE_FIELDS = ("input", "w5m", "w1h", "cache_read", "output")

# The prices in force when the real rows below were billed (official page, read 2026-11-04).
FROZEN = {
    "consulted": "2026-11-04",
    "web_search_per_1000": 10,
    "models": {
        "claude-opus-5-5": {
            "input": 4,
            "w5m": 5,
            "w1h": 8,
            "cache_read": 0.20,
            "output": 20,
            "family": "new",
            "supports_effort": True,
        },
        "claude-haiku-5-5": {
            "input": 0.10,
            "w5m": 0.125,
            "w1h": 0.20,
            "cache_read": 0.01,
            "output": 0.50,
            "family": "new",
            "supports_effort": True,
        },
        "claude-haiku-4-5": {
            "input": 1,
            "w5m": 1.25,
            "w1h": 2,
            "cache_read": 0.10,
            "output": 5,
            "family": "previous",
            "supports_effort": False,
        },
    },
    "long_prompt": {
        "claude-haiku-5-5": {
            "above_tokens": 100000,
            "input": 0.50,
            "w5m": 0.625,
            "w1h": 1,
            "cache_read": 0.05,
            "output": 2.50,
        }
    },
}


@pytest.fixture
def frozen_prices(monkeypatch):
    """The code paths that read the package table (`transcripts`, `recompute`) see `FROZEN`."""
    monkeypatch.setattr(pricing, "load_prices", lambda: copy.deepcopy(FROZEN))


# Real: Haiku 5.5 with cache writes and reads and 6 web searches.
ROW_HAIKU55_CACHE = {
    "model": "claude-haiku-5-5",
    "inputTokens": 1558576,
    "cacheCreationInputTokens": 61227,
    "cacheReadInputTokens": 258026,
    "outputTokens": 154709,
    "webSearchRequests": 6,
    "costUSD": 0.3034457349999998,
}
# Real: Haiku 5.5 with 52 web searches.
ROW_HAIKU55_WEB = {
    "model": "claude-haiku-5-5",
    "inputTokens": 1175833,
    "cacheCreationInputTokens": 0,
    "cacheReadInputTokens": 0,
    "outputTokens": 102304,
    "webSearchRequests": 52,
    "costUSD": 0.6887353000000002,
}
# Real: Opus 5.5 with many cache reads (same row as `test_pricing.ROW_OPUS_55_READ`).
ROW_OPUS_55 = {
    "model": "claude-opus-5-5[1m]",
    "inputTokens": 8,
    "cacheCreationInputTokens": 28669,
    "cacheReadInputTokens": 144347,
    "outputTokens": 199,
    "webSearchRequests": 0,
    "costUSD": 0.2622334,
}

# Synthetic Haiku 5.5 tokens. Bounds from the official prices:
#   all ≤100K, 5m writes: (100*0.10 + 4e6*0.01 + 40000*0.50 + 300000*0.125) / 1e6 = 0.09751
#   all ≤100K, 1h writes: (100*0.10 + 4e6*0.01 + 40000*0.50 + 300000*0.20)  / 1e6 = 0.12001
#   all >100K, 1h writes: (100*0.50 + 4e6*0.05 + 40000*2.50 + 300000*1)     / 1e6 = 0.60005
_TOKENS = {
    "inputTokens": 100,
    "cacheCreationInputTokens": 300000,
    "cacheReadInputTokens": 4000000,
    "outputTokens": 40000,
    "webSearchRequests": 0,
}


def _haiku(cost: float) -> dict:
    return {"model": "claude-haiku-5-5", **_TOKENS, "costUSD": cost}


def _unpriced(cost: float = 0.30) -> dict:
    return {"model": "claude-nobody-9", **_TOKENS, "costUSD": cost}


def _positive_prices(prices: dict) -> bool:
    return all(
        isinstance(prices[f], int | float) and not isinstance(prices[f], bool) and prices[f] > 0
        for f in PRICE_FIELDS
    )


def test_the_package_table_is_well_formed():
    """REQ-001 and REQ-008, as invariants a legitimate price change keeps (not the figures).

    Haiku 5.5 is priced, with its prompt-length tier; every entry has its five prices; every tier
    belongs to a priced model and has a threshold and its five prices.
    """
    table = load_prices()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", table["consulted"])
    haiku = entry("claude-haiku-5-5")
    assert haiku is not None
    assert haiku["family"] == "new"
    assert haiku["supports_effort"] is True
    for mid, e in table["models"].items():
        assert _positive_prices(e), mid
    tiers = table.get("long_prompt") or {}
    assert "claude-haiku-5-5" in tiers
    for mid, tier in tiers.items():
        assert mid in table["models"], mid
        assert isinstance(tier["above_tokens"], int) and tier["above_tokens"] > 0, mid
        assert _positive_prices(tier), mid


def test_long_prompt_lookup():
    """REQ-001: exact lookup after normalizing, like `entry`; a model without a tier has none."""
    assert (
        pricing.long_prompt("claude-haiku-5-5", FROZEN) == FROZEN["long_prompt"]["claude-haiku-5-5"]
    )
    assert pricing.long_prompt("claude-haiku-5-5-20261101", FROZEN) is not None
    assert pricing.long_prompt("claude-opus-5-5", FROZEN) is None
    assert pricing.long_prompt("claude-haiku-4-5", FROZEN) is None
    # Without `table`, the package one; the tier of Haiku 5.5 is found there as well.
    assert (
        pricing.long_prompt("claude-haiku-5-5-20261101")
        == load_prices()["long_prompt"]["claude-haiku-5-5"]
    )


def test_real_haiku_55_rows_are_inside():
    """The Mac case: real Haiku 5.5 rows, judged against a price instead of `unpriced`."""
    assert check_rows([ROW_HAIKU55_CACHE, ROW_HAIKU55_WEB], FROZEN) == ["inside", "inside"]


def test_haiku_55_row_band_spans_both_tiers():
    """REQ-002: the band goes from all ≤100K (5m) to all >100K (1h)."""
    table = FROZEN
    tolerance = 0.005
    # Mixed: above the ≤100K ceiling (0.12001), only a band with the long tier accepts it.
    assert check_rows([_haiku(0.30)], table) == ["inside"]
    assert check_rows([_haiku(0.60005 + tolerance - 1e-4)], table) == ["inside"]
    assert check_rows([_haiku(0.60005 + tolerance + 1e-3)], table) == ["outside"]
    assert check_rows([_haiku(0.09751 - tolerance - 1e-3)], table) == ["outside"]
    # Guard: without the tier the mixed row would be outside, so the tier is what decides.
    flat = copy.deepcopy(table)
    del flat["long_prompt"]
    assert check_rows([_haiku(0.30)], flat) == ["outside"]


def _message(**usage) -> dict:
    return {"model": "claude-haiku-5-5", "usage": usage}


def test_request_cost_uses_the_prompt_tier(frozen_prices):
    """REQ-003: per request, the prompt (input + writes + reads) picks the tier."""
    # 100,000 tokens exactly: still the base tier.
    at = transcripts.request_cost(
        _message(input_tokens=10000, cache_read_input_tokens=90000, output_tokens=1000)
    )
    assert abs(at - (10000 * 0.10 + 90000 * 0.01 + 1000 * 0.50) / 1e6) < 1e-12
    # One token over (in a 1h write): every token of the request at the long tier.
    over = transcripts.request_cost(
        _message(
            input_tokens=10000,
            cache_read_input_tokens=90000,
            output_tokens=1000,
            cache_creation={"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1},
        )
    )
    assert abs(over - (10000 * 0.50 + 90000 * 0.05 + 1 * 1 + 1000 * 2.50) / 1e6) < 1e-12
    # A model without a tier is not touched: Opus 5.5 with 1M of prompt keeps its price.
    opus = transcripts.request_cost(
        {"model": "claude-opus-5-5", "usage": {"cache_read_input_tokens": 1000000}}
    )
    assert abs(opus - 1000000 * 0.20 / 1e6) < 1e-12


def test_unpriced_rows_leave_the_verdict():
    """REQ-004: the unpriced rows are counted apart and do not fail the verdict."""
    results = check_rows([ROW_OPUS_55, _unpriced(), _unpriced()], FROZEN)
    assert results == ["inside", "unpriced", "unpriced"]
    assert priced_verdict(results) == "pass"
    # The old verdict still fails on them (its callers keep their behavior).
    assert verdict(results) == "fail"
    # An outside priced row still fails it.
    assert priced_verdict(["inside", "outside", "unpriced"]) == "fail"
    # Only unpriced rows: nothing vouches for the table.
    assert priced_verdict(["unpriced", None]) == "fail"
    # Nothing judged at all (every row under the minimum cost): `pass`, like the old verdict.
    assert priced_verdict([None, None]) == verdict([None, None]) == "pass"
    assert priced_verdict([]) == "pass"


def _index_with_rows(rows: list[dict]) -> transcripts.Index:
    index = transcripts.Index()
    for i, r in enumerate(rows):
        usage = {r["model"]: {k: r[k] for k in pricing.CHECK_FIELDS}}
        index.costs[(f"s{i}", "t")] = (i, usage)
    return index


def test_outside_rows_by_model(frozen_prices):
    """REQ-004 and REQ-007, through `recompute._check`: the saved check says who is outside."""
    bad_opus = dict(ROW_OPUS_55, costUSD=ROW_OPUS_55["costUSD"] * 2)
    index = _index_with_rows([ROW_OPUS_55, bad_opus, _unpriced(), ROW_HAIKU55_CACHE])
    check = recompute._check(index, now=datetime(2026, 11, 4, tzinfo=UTC))
    assert check["judged"] == 3
    assert check["outside"] == 1
    assert check["outside_by_model"] == {"claude-opus-5-5": 1}
    assert check["unpriced"] == ["claude-nobody-9"]
    assert check["unpriced_rows"] == 1
    assert check["verdict"] == "fail"

    good = recompute._check(
        _index_with_rows([ROW_OPUS_55, _unpriced(), _unpriced(0.40)]),
        now=datetime(2026, 11, 4, tzinfo=UTC),
    )
    assert good["verdict"] == "pass"
    assert (good["judged"], good["outside"], good["unpriced_rows"]) == (1, 0, 2)
    assert good["outside_by_model"] == {}


def _summary(check: dict) -> str:
    return recompute.summary_text(
        {
            "matches": {},
            "backfilled_lines": 0,
            "cleanup_days": 30,
            "transcripts": 1,
            "corrupt_lines": 0,
            "n_cases": 0,
            "check": check,
            "discards": {},
            "quota": dict.fromkeys(recompute.quota.TYPES, "uncalibrated"),
            "points": {},
        }
    )


def test_summary_names_the_unpriced_rows():
    """REQ-005 and REQ-007: separate sentences for the unpriced rows and the outside ones."""
    check = {
        "table_version": "2026-11-04",
        "verdict": "pass",
        "judged": 212,
        "outside": 0,
        "outside_by_model": {},
        "unpriced": ["claude-nobody-9"],
        "unpriced_rows": 70,
    }
    with i18n.override("es"):
        text = _summary(check)
    assert "Sin precio: claude-nobody-9, 70 fila(s) fuera del cotejo." in text
    assert "por modelo" not in text
    with i18n.override("en"):
        text = _summary(
            dict(check, verdict="fail", outside=3, outside_by_model={"claude-sonnet-5-5": 3})
        )
    assert "Unpriced: claude-nobody-9, 70 row(s) left out of the check." in text
    assert "Rows outside the band by model: claude-sonnet-5-5 (3)." in text


def _probe_with(tmp_path: Path, check: dict) -> checks.Result:
    log_dir = tmp_path / "log"
    log_dir.mkdir(parents=True)
    recompute.write_aggregates(log_dir, {"version": 1, "cleanup_days": 30, "check": check})
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    return checks._probe_cost(checks.Context(home=home, log_dir=log_dir))


def test_doctor_ok_with_unpriced_note(tmp_path):
    """REQ-006: a passing check with unpriced rows is OK and names them; outside still warns."""
    base = {
        "date": "2026-11-04T12:00:00+00:00",
        "table_version": "2026-11-04",
        "judged": 212,
        "outside": 0,
        "outside_by_model": {},
        "unpriced": ["claude-nobody-9"],
        "unpriced_rows": 70,
        "verdict": "pass",
    }
    with i18n.override("es"):
        r = _probe_with(tmp_path / "a", base)
        assert r.status == checks.OK
        assert "cuadra: 212 fila(s)" in r.detail
        assert "sin precio: claude-nobody-9, 70 fila(s) fuera del cotejo" in r.detail

        bad = dict(base, outside=4, outside_by_model={"claude-opus-5-5": 4}, verdict="fail")
        r = _probe_with(tmp_path / "b", bad)
        assert r.status == checks.WARN
        assert "4 fila(s) fuera" in r.detail
