"""#650: `local_extract` warns about a value that sits only in the row of another requested key.

The model hands the rows of a table out to the keys almost by position (`licensed_user_limits` got
the row «Custom domains»). `cross_fill.cross_filled` finds that case from the source and the answer
and `local_extract` reports it in `_local_delegate.cross_filled_keys`, with a warning, without
touching the value.

The measuring gate of the SDD `extract-cross-filled-warning` is this file: the detector runs over
answers, not over a model. Three sets, all in `tests/data/cross_fill/`:

- `new_cases.json`: 32 invented tables (HTML, Markdown, CSV, TSV, JSON, text lines; synonyms,
  another language, repeated numbers, labels with the words of two keys, derived and free-text
  keys such as `currency`, `first_name` or `product_summary`), each with a correct and most with a
  crossed answer written by hand;
- `holdout/`: the blind set of 2026-11-10 (24 cases, `expected` and `crossed` answers by hand),
  where yesterday's strict detector flagged `c01/price` (`39`, own row «Retail cost (USD)»);
- `recorded/`: real answers of the local models recorded on 2026-11-10, with the hand verdicts,
  among them the two crosses of #586.

The target is 0 false positives over all of them and the #586 crosses flagged. Backend faked in the
`local_extract` tests (`_run_chat` doubled), no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import config, cross_fill, i18n, server

DATA = Path(__file__).parent / "data" / "cross_fill"


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


NEW = _load("new_cases.json")["cases"]
HOLDOUT = _load("holdout/cases.json")["cases"]
RECORDED = _load("recorded/recorded_runs.json")["runs"]


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _new_params():
    for case in NEW:
        for index, answer in enumerate(case["answers"]):
            yield pytest.param(case, answer, id=f"{case['id']}-{index}")


def _recorded_params():
    for row in RECORDED:
        yield pytest.param(row, id=f"{row['run']}-{row['case']}")


# --- The gate: 0 false positives, the designed crosses caught -----------------------------------


@pytest.mark.parametrize(("case", "answer"), list(_new_params()))
def test_new_set_flags_only_crossed_keys(case, answer):
    flagged = cross_fill.cross_filled(case["source"], case["fields"], answer["answer"])
    assert set(flagged) <= set(answer["crossed"]), f"false positive: {flagged}"
    assert set(answer["must_flag"]) <= set(flagged), f"missed: {flagged}"


@pytest.mark.parametrize("case", HOLDOUT, ids=[case["id"] for case in HOLDOUT])
def test_holdout_hand_answers_are_never_flagged(case):
    source = _read(DATA / "holdout" / case["input"])
    assert cross_fill.cross_filled(source, case["fields"], case["expected"]) == {}


@pytest.mark.parametrize(
    "case", [c for c in HOLDOUT if c.get("crossed")], ids=lambda case: case["id"]
)
def test_holdout_crossed_answers_flag_only_crossed_keys(case):
    source = _read(DATA / "holdout" / case["input"])
    crossed = case["crossed"]
    flagged = cross_fill.cross_filled(source, case["fields"], crossed["answer"])
    assert set(flagged) <= set(crossed["crossed_keys"]), f"false positive: {flagged}"


@pytest.mark.parametrize("row", list(_recorded_params()))
def test_recorded_model_answers_flag_only_crossed_keys(row):
    source = _read(DATA / "recorded" / "inputs" / row["file"])
    flagged = cross_fill.cross_filled(source, row["fields"], row["answer"])
    assert set(flagged) <= set(row["crossed"]), f"false positive: {flagged}"


#: The two crosses of #586, with the row and the key the warning must name; kept in the data file
#: (the Spanish key names are data, not code).
CROSSES_586 = _load("recorded/recorded_runs.json")["crosses_586"]


@pytest.mark.parametrize(
    ("case", "key", "row", "other"),
    [(c["case"], c["key"], c["row"], c["other_key"]) for c in CROSSES_586],
    ids=[c["case"] for c in CROSSES_586],
)
def test_the_crosses_of_586_are_flagged(case, key, row, other):
    runs = [r for r in RECORDED if r["case"] == case and key in r["crossed"]]
    assert runs, "the recorded set lost the #586 cross"
    for run in runs:
        source = _read(DATA / "recorded" / "inputs" / run["file"])
        flagged = cross_fill.cross_filled(source, run["fields"], run["answer"])
        assert flagged.get(key) == {"row": row, "other_key": other}, run["run"]


def test_yesterdays_false_positive_stays_quiet():
    """`price` = 39, own row «Retail cost (USD)»; 39 is also the row of `noise_level`."""
    case = next(c for c in HOLDOUT if c["id"] == "c01")
    source = _read(DATA / "holdout" / case["input"])
    assert "Retail cost (USD)" in source
    flagged = cross_fill.cross_filled(source, case["fields"], case["expected"])
    assert "price" not in flagged


def test_gate_totals():
    """The whole measurement in one number each: no false positive, and the catches it had."""
    false_positives, caught = [], 0
    for case in NEW:
        for answer in case["answers"]:
            flagged = cross_fill.cross_filled(case["source"], case["fields"], answer["answer"])
            false_positives += [(case["id"], k) for k in flagged if k not in answer["crossed"]]
            caught += sum(1 for k in flagged if k in answer["crossed"])
    for case in HOLDOUT:
        source = _read(DATA / "holdout" / case["input"])
        flagged = cross_fill.cross_filled(source, case["fields"], case["expected"])
        false_positives += [(case["id"], k) for k in flagged]
        if case.get("crossed"):
            crossed = case["crossed"]
            flagged = cross_fill.cross_filled(source, case["fields"], crossed["answer"])
            false_positives += [
                (case["id"], k) for k in flagged if k not in crossed["crossed_keys"]
            ]
            caught += sum(1 for k in flagged if k in crossed["crossed_keys"])
    for row in RECORDED:
        source = _read(DATA / "recorded" / "inputs" / row["file"])
        flagged = cross_fill.cross_filled(source, row["fields"], row["answer"])
        false_positives += [(row["case"], k) for k in flagged if k not in row["crossed"]]
        caught += sum(1 for k in flagged if k in row["crossed"])
    assert false_positives == []
    # Measured when the gate passed (2026-11-11): 37 new + 30 holdout + 5 recorded.
    assert caught >= 72


# --- The rules, one by one ----------------------------------------------------------------------

TABLE = (
    "| Item | Value |\n| --- | --- |\n| Custom domains | 25 |\n| Licensed users | 40 |\n"
    "| Storage per workspace | 50 GB |\n"
)
FIELDS = ["custom_domain_limits", "licensed_user_limits", "storage_per_workspace"]


def test_a_value_from_the_row_of_another_key_is_flagged():
    flagged = cross_fill.cross_filled(TABLE, FIELDS, {"licensed_user_limits": 25})
    assert flagged == {
        "licensed_user_limits": {"row": "Custom domains", "other_key": "custom_domain_limits"}
    }


def test_the_right_value_is_not_flagged():
    answer = {
        "custom_domain_limits": 25,
        "licensed_user_limits": 40,
        "storage_per_workspace": "50 GB",
    }
    assert cross_fill.cross_filled(TABLE, FIELDS, answer) == {}


def test_a_value_repeated_elsewhere_is_not_flagged():
    source = TABLE + "\nEvery plan includes 25 domains.\n"
    assert cross_fill.cross_filled(source, FIELDS, {"licensed_user_limits": 25}) == {}


def test_a_value_made_of_cells_of_two_rows_is_not_flagged():
    value = ["25", "50 GB"]
    assert cross_fill.cross_filled(TABLE, FIELDS, {"licensed_user_limits": value}) == {}


def test_a_row_no_other_key_fits_is_not_flagged():
    fields = ["licensed_user_limits", "storage_per_workspace"]
    assert cross_fill.cross_filled(TABLE, fields, {"licensed_user_limits": 25}) == {}


@pytest.mark.parametrize("value", [True, False, None, "", "N/A", "yes", "No", 7, "-"])
def test_trivial_values_are_not_flagged(value):
    source = "| Item | Value |\n| --- | --- |\n| Custom domains | 7 |\n| Licensed users | yes |\n"
    assert cross_fill.cross_filled(source, FIELDS, {"storage_per_workspace": value}) == {}


def test_strings_inside_a_list_or_an_object_are_checked():
    assert "licensed_user_limits" in cross_fill.cross_filled(
        TABLE, FIELDS, {"licensed_user_limits": ["25"]}
    )
    assert "licensed_user_limits" in cross_fill.cross_filled(
        TABLE, FIELDS, {"licensed_user_limits": {"standard": 25}}
    )


def test_one_field_or_a_huge_source_is_not_scanned():
    assert (
        cross_fill.cross_filled(TABLE, ["licensed_user_limits"], {"licensed_user_limits": 25}) == {}
    )
    huge = TABLE + "x" * cross_fill.MAX_SOURCE_CHARS
    assert cross_fill.cross_filled(huge, FIELDS, {"licensed_user_limits": 25}) == {}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("licensedUserLimits", {"licensed", "user", "limit"}),
        ("custom_domain-limits", {"custom", "domain", "limit"}),
        ("Cities covered", {"city", "covered"}),
        ("Boxes per pallet", {"box", "pallet"}),
        ("Licenses and classes", {"license", "class"}),
        ("Compañías aliadas", {"compania", "aliada"}),
    ],
)
def test_label_words_are_normalized(name, expected):
    assert cross_fill.words(name) == expected


def test_a_comma_between_csv_cells_is_not_a_decimal_comma():
    source = "item,price,stock\nShirt,15,7\nTrousers,30,8\n"
    flagged = cross_fill.cross_filled(
        source, ["shirt_price", "trousers_price"], {"shirt_price": 30}
    )
    assert flagged == {"shirt_price": {"row": "Trousers", "other_key": "trousers_price"}}


# --- `local_extract` reports it -----------------------------------------------------------------


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    state = {"answer": "{}"}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        return _ok(state["answer"]), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    return state


def test_local_extract_reports_a_cross_and_keeps_the_value(backend):
    backend["answer"] = json.dumps(
        {"custom_domain_limits": 25, "licensed_user_limits": 25, "storage_per_workspace": "50 GB"}
    )
    data = server.local_extract(fields=FIELDS, text=TABLE)
    assert data["licensed_user_limits"] == 25
    meta = data["_local_delegate"]
    assert meta["cross_filled_keys"] == {
        "licensed_user_limits": {"row": "Custom domains", "other_key": "custom_domain_limits"}
    }
    assert "cross_filled_keys" in meta["warning"]
    assert "licensed_user_limits <- Custom domains (custom_domain_limits)" in meta["warning"]


def test_local_extract_says_nothing_when_the_answer_is_right(backend):
    backend["answer"] = json.dumps(
        {"custom_domain_limits": 25, "licensed_user_limits": 40, "storage_per_workspace": "50 GB"}
    )
    data = server.local_extract(fields=FIELDS, text=TABLE)
    assert "cross_filled_keys" not in data.get("_local_delegate", {})


def test_the_warning_is_appended_after_an_earlier_one(backend):
    backend["answer"] = json.dumps({"licensed_user_limits": 40, "extra": 1})
    earlier = server.local_extract(fields=FIELDS, text=TABLE)["_local_delegate"]["warning"]
    assert "cross_filled_keys" not in earlier
    backend["answer"] = json.dumps({"licensed_user_limits": 25, "extra": 1})
    warning = server.local_extract(fields=FIELDS, text=TABLE)["_local_delegate"]["warning"]
    notice = i18n.t(
        "mcp.warning.extract_cross_filled_keys",
        pairs="licensed_user_limits <- Custom domains (custom_domain_limits)",
    )
    assert warning == f"{earlier}; {notice}"


def test_location_fields_are_not_checked(backend, tmp_path):
    """`10-14` in a field asking for lines would hit a cell `14` of another key's row."""
    source = "| Item | Value |\n| --- | --- |\n| Custom domains | 14 |\n| Licensed users | 40 |\n"
    path = tmp_path / "plans.md"
    path.write_bytes(source.encode("utf-8"))
    fields = ["custom_domain_limits", "licensed_user_limits", "table_lines"]
    assert "table_lines" in cross_fill.cross_filled(source, fields, {"table_lines": 14})
    assert cross_fill.cross_filled(source, fields, {"table_lines": 14}, skip=["table_lines"]) == {}
    backend["answer"] = json.dumps(
        {"custom_domain_limits": 14, "licensed_user_limits": 40, "table_lines": "3-4"}
    )
    data = server.local_extract(fields=fields, path=str(path))
    assert "cross_filled_keys" not in data.get("_local_delegate", {})


@pytest.mark.parametrize(
    ("source", "answer"),
    [
        ("a\tb\n" + "x" * 140_000 + "\nc\td\n", {"k": "x"}),
        ('a,b\n"' + "y" * 140_000 + "\nc,d\n", {"k": "yy"}),
        ("a\rb\nc,d\ne,f\n", {"k": "dd"}),
        ("item,value\nfoo,12\n", {"k": 10**400}),
        ('{"a":' + "[" * 5000 + "]" * 5000 + "}", {"k": "aa"}),
        ("<table><tr><td>a</td><td>bb</td></tr></table><![x]>", {"k": "bb"}),
    ],
    ids=["huge-tsv-field", "open-quote", "stray-cr", "huge-int", "deep-json", "odd-html"],
)
def test_an_odd_source_never_breaks_the_answer(source, answer):
    assert isinstance(cross_fill.cross_filled(source, ["k", "a_key"], answer), dict)


def test_a_long_row_label_is_cut_in_the_warning():
    label = "Custom domains " + "x" * 200
    source = f"| Item | Value |\n| --- | --- |\n| {label} | 25 |\n| Licensed users | 40 |\n"
    flagged = cross_fill.cross_filled(source, FIELDS, {"licensed_user_limits": 25})
    assert len(flagged["licensed_user_limits"]["row"]) <= 80


def test_both_catalogs_carry_the_warning():
    for lang in ("en", "es"):
        catalog = json.loads(
            (Path(server.__file__).parent / "resources" / "i18n" / lang / "mcp.json").read_text(
                encoding="utf-8"
            )
        )
        assert "{pairs}" in catalog["mcp.warning.extract_cross_filled_keys"]


def test_the_docstring_names_cross_filled_keys():
    assert "cross_filled_keys" in (server.local_extract.__doc__ or "")
