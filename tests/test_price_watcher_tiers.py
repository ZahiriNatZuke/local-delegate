"""#564: the price watcher reads a model priced by prompt length (two rows on the page).

The page copy saved in `fixtures/vigilante/prices.html` predates Claude Haiku 5.5. These tests
insert a synthetic block with the shape the live page has (2026-11-04): the name cell spans two
rows (`rowSpan="2"`), the input cell of the first row carries «for prompts up to 100,000 tokens»
and the second row has no name cell and says «over 100,000 tokens». Only the shape is copied, not
the page.
"""

from __future__ import annotations

import copy
import datetime as dt
import json

import pytest
from test_price_watcher import EXPECTED, PACKAGE, _html_table, _prices_page, _row, _v

HAIKU55_BASE = {"input": 0.10, "output": 0.50, "w5m": 0.125, "w1h": 0.20, "cache_read": 0.01}
HAIKU55_LONG = {
    "above_tokens": 100000,
    "input": 0.50,
    "w5m": 0.625,
    "w1h": 1,
    "cache_read": 0.05,
    "output": 2.50,
}


def _cell(price: str, caption: str = "") -> str:
    extra = f"<span>{caption}</span>" if caption else ""
    return f"<td><div>${price}<!-- --> <span>/ MTok</span>{extra}</div></td>"


def _block(
    *,
    name: str = "Claude Haiku 5.5",
    label: str = "",
    first_caption: str = "for prompts up to 100,000 tokens",
    second_caption: str = "for prompts over 100,000 tokens",
    second_output: str = "2.50",
    rowspan: str = "2",
    second_row: bool = True,
) -> str:
    """Two `<tr>` with the live page's shape. Columns: Name, Input, Output, 5m, 1h, Hits."""
    button = f'<button aria-label="{label}">i</button>' if label else ""
    first = (
        f'<tr><td rowSpan="{rowspan}"><div><a href="/docs/en/models/x/overview">{name}</a>'
        f"<span>For high-volume tasks</span>{button}</div></td>"
        + _cell("0.10", first_caption)
        + _cell("0.50")
        + _cell("0.125")
        + _cell("0.20")
        + _cell("0.01")
        + "</tr>"
    )
    second = (
        "<tr>"
        + _cell("0.50", second_caption)
        + _cell(second_output)
        + _cell("0.625")
        + _cell("1")
        + _cell("0.05")
        + "</tr>"
    )
    return first + (second if second_row else "")


def _page(block: str) -> str:
    """The saved page with `block` before the Claude Haiku 4.5 row."""
    html = _prices_page()
    since, _until = _row(html, "Claude Haiku 4.5")
    return html[:since] + block + html[since:]


def test_the_two_rows_give_the_base_entry_and_the_long_tier():
    table = _v().extract_price_table(_page(_block()))
    assert table["models"]["claude-haiku-5-5"] == HAIKU55_BASE
    assert table["long_prompt"] == {"claude-haiku-5-5": HAIKU55_LONG}
    # The rest of the table is what it was: the second row did not shift or eat another one.
    rest = {k: x for k, x in table["models"].items() if k != "claude-haiku-5-5"}
    assert rest == EXPECTED["models"]
    assert table["web_search_per_1000"] == EXPECTED["web_search_per_1000"]


def test_a_page_without_tiers_has_no_long_prompt_key():
    assert "long_prompt" not in _v().extract_price_table(_prices_page())


@pytest.mark.parametrize(
    ("block", "message"),
    [
        # A caption that is not a tier: still an unreadable cell, named.
        (
            {"first_caption": "for batch requests"},
            "celda de precio ilegible en claude-haiku-5-5 / input",
        ),
        # A number that is not a price in the second row: named with its field.
        (
            {"second_output": "2,50"},
            "celda de precio ilegible en claude-haiku-5-5 / output",
        ),
        # Thresholds that do not match.
        (
            {"second_caption": "for prompts over 200,000 tokens"},
            "claude-haiku-5-5: el segundo tramo dice «over 200000»",
        ),
        # The first row says «over».
        (
            {"first_caption": "for prompts over 100,000 tokens"},
            "claude-haiku-5-5: el primer tramo dice «over 100000»",
        ),
        # A tier caption in a one-row model.
        (
            {"rowspan": "1", "second_row": False},
            "celda de precio ilegible en claude-haiku-5-5 / input",
        ),
    ],
)
def test_a_broken_tier_fails_with_a_clear_message(block, message):
    v = _v()
    with pytest.raises(v.WatcherError, match=message):
        v.extract_price_table(_page(_block(**block)))


def test_a_missing_second_row_fails():
    """rowSpan 2 followed by a full row: the second tier is missing, never skipped in silence."""
    v = _v()
    with pytest.raises(v.WatcherError, match="claude-haiku-5-5: falta la fila de su segundo tramo"):
        v.extract_price_table(_page(_block(second_row=False)))


def test_a_name_over_more_than_two_rows_fails():
    v = _v()
    with pytest.raises(v.WatcherError, match="fila con un nombre que ocupa 3 filas"):
        v.extract_price_table(_page(_block(rowspan="3")))


def test_an_ignored_tiered_model_without_its_second_row_is_named():
    v = _v()
    block = _block(
        name="Claude Mythos 9", label="Claude Mythos 9 (Verification required)", second_row=False
    )
    with pytest.raises(v.WatcherError, match="Claude Mythos 9: falta la fila de su segundo tramo"):
        v.extract_price_table(_page(block))


def test_a_table_that_ends_after_the_first_row_fails():
    v = _v()
    html = _prices_page()
    _start, end = _html_table(html)
    last = html.rindex("</tr>", 0, end) + len("</tr>")
    # The tiered first row becomes the last row of the table.
    html = html[:last] + _block(second_row=False) + html[last:]
    with pytest.raises(v.WatcherError, match="la tabla termina sin la fila de su segundo tramo"):
        v.extract_price_table(html)


def test_an_ignored_tiered_model_skips_its_second_row():
    """A tiered model marked «Verification required» is left out with both its rows."""
    table = _v().extract_price_table(
        _page(_block(name="Claude Mythos 9", label="Claude Mythos 9 (Verification required)"))
    )
    assert table["models"] == EXPECTED["models"]
    assert "long_prompt" not in table


def test_the_web_search_price_with_usd():
    """The live page writes «$10 USD per 1,000 searches» since 2026-11."""
    v = _v()
    html = _prices_page().replace("$10 per 1,000 searches", "$10 USD per 1,000 searches")
    assert "$10 USD per 1,000" in html, "guard: the saved page had the old sentence"
    assert v.extract_price_table(html)["web_search_per_1000"] == 10


def _package_with_haiku55(long_tier: dict | None) -> dict:
    package = copy.deepcopy(PACKAGE)
    package["models"]["claude-haiku-5-5"] = {
        **HAIKU55_BASE,
        "family": "new",
        "supports_effort": True,
    }
    if long_tier is not None:
        package["long_prompt"] = {"claude-haiku-5-5": dict(long_tier)}
    return package


def test_compare_and_update_the_long_tier():
    v = _v()
    new = v.extract_price_table(_page(_block()))

    # Same tier in the package: no change.
    same = v.compare(new, _package_with_haiku55(HAIKU55_LONG))
    assert not same.has_changes

    # Package without the tier: it is proposed, and the PR body shows it.
    missing = _package_with_haiku55(None)
    changes = v.compare(new, missing)
    assert changes.has_changes
    assert changes.long_prompt == {"claude-haiku-5-5": HAIKU55_LONG}
    table = v.updated_table(missing, new, changes, dt.date(2026, 11, 4))
    assert table["long_prompt"] == {"claude-haiku-5-5": HAIKU55_LONG}
    assert table["consulted"] == "2026-11-04"
    body = v.prices_pr_body(changes)
    assert "| `claude-haiku-5-5` | 100000 | 0.5 | 0.625 | 1 | 0.05 | 2.5 |" in body

    # A price of the tier changes: proposed with the new value; the base entry is untouched.
    old = dict(HAIKU55_LONG, output=3)
    changes = v.compare(new, _package_with_haiku55(old))
    assert changes.long_prompt == {"claude-haiku-5-5": HAIKU55_LONG}
    assert changes.prices == []

    # A tier the page no longer has is kept, like a vanished model.
    package = _package_with_haiku55(HAIKU55_LONG)
    gone = v.compare(v.extract_price_table(_prices_page()), package)
    assert gone.long_prompt == {}
    assert v.updated_table(package, new, gone, dt.date(2026, 11, 4))["long_prompt"] == {
        "claude-haiku-5-5": HAIKU55_LONG
    }


def test_the_serialised_table_keeps_the_tier_on_one_line():
    v = _v()
    new = v.extract_price_table(_page(_block()))
    package = _package_with_haiku55(None)
    original = json.dumps(package, indent=2)
    changes = v.compare(new, package)
    content = v.serialize_prices(v.updated_table(package, new, changes, dt.date.today()), original)
    assert json.loads(content)["long_prompt"] == {"claude-haiku-5-5": HAIKU55_LONG}
    line = next(ln for ln in content.splitlines() if ln.startswith('  "long_prompt"'))
    assert line.endswith('"output": 2.5}}')
