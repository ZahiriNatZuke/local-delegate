"""Pure rules of `backend_params` (SDD `backend-extra-params`, T3).

Catalog, types and ranges (REQ-004), reserved and deferred keys (REQ-005), values that never reach
a warning (REQ-006/007), the grammar of `LOCAL_DELEGATE_BACKEND_PARAMS` (REQ-008), the reasoning
rule (REQ-011) and the layers of `to_body` (REQ-012, REQ-023).
"""

from __future__ import annotations

import math

import pytest

from local_delegate import backend_params as bp
from local_delegate.backend_params import Warning as W

# --- Catalog (REQ-004, REQ-005) -----------------------------------------------------------------

#: The 21 keys of the REQ-004 table of `spec.md`, written again by hand on purpose: the test must
#: not derive the expectation from the code it checks.
SPEC_KEYS = (
    "temperature",
    "top_k",
    "top_p",
    "min_p",
    "typical_p",
    "repeat_penalty",
    "repeat_last_n",
    "presence_penalty",
    "frequency_penalty",
    "dry_multiplier",
    "dry_base",
    "dry_allowed_length",
    "dry_penalty_last_n",
    "xtc_probability",
    "xtc_threshold",
    "mirostat",
    "mirostat_tau",
    "mirostat_eta",
    "enable_thinking",
    "reasoning_budget_tokens",
    "reasoning_effort",
)

#: The 27 reserved keys of REQ-005.
SPEC_RESERVED = (
    "model",
    "messages",
    "stream",
    "stream_options",
    "max_tokens",
    "max_completion_tokens",
    "n_predict",
    "response_format",
    "json_schema",
    "grammar",
    "tools",
    "tool_choice",
    "functions",
    "function_call",
    "n",
    "n_cmpl",
    "stop",
    "logprobs",
    "n_probs",
    "response_fields",
    "cache_prompt",
    "id_slot",
    "n_keep",
    "samplers",
    "seed",
    "chat_template_kwargs",
    "reasoning_format",
)

#: The deferred keys of «Fuera de alcance».
SPEC_DEFERRED = (
    "dry_sequence_breakers",
    "top_n_sigma",
    "dynatemp_range",
    "dynatemp_exponent",
    "min_keep",
    "adaptive_target",
    "adaptive_decay",
    "reasoning_budget_message",
    "reasoning_control",
)


def test_catalog_has_exactly_21_keys():
    assert len(SPEC_KEYS) == 21
    assert tuple(bp.ALLOWED_KEYS) == SPEC_KEYS
    assert len(SPEC_RESERVED) == 27
    assert bp.RESERVED_KEYS == frozenset(SPEC_RESERVED)
    assert bp.DEFERRED_KEYS == frozenset(SPEC_DEFERRED)
    assert not bp.RESERVED_KEYS & set(bp.ALLOWED_KEYS)
    assert not bp.DEFERRED_KEYS & set(bp.ALLOWED_KEYS)
    assert bp.ROLES == ("mechanical", "long", "code", "vision")
    assert (bp.BUDGET_MIN, bp.BUDGET_MAX) == (1, 8192)
    assert bp.MAX_FILE_BYTES == 64 * 1024
    assert bp.MAX_OVERRIDE_CHARS == 2048


# --- Values (REQ-004) ---------------------------------------------------------------------------

NAN, INF = math.nan, math.inf
OK, TYPE, RANGE = None, "bad_type", "out_of_range"
UNIT_KEYS = ("top_p", "min_p", "typical_p", "xtc_probability", "xtc_threshold")
FINITE_KEYS = (
    "repeat_penalty",
    "presence_penalty",
    "frequency_penalty",
    "dry_multiplier",
    "mirostat_tau",
    "mirostat_eta",
)
INT32_KEYS = ("repeat_last_n", "dry_allowed_length", "dry_penalty_last_n")


def _cases():
    cases = [
        ("temperature", 0.2, OK),
        ("temperature", 0, OK),
        ("temperature", 2, OK),
        ("temperature", "0.2", TYPE),
        ("temperature", True, TYPE),
        ("temperature", -0.1, RANGE),
        ("temperature", NAN, RANGE),
        ("temperature", INF, RANGE),
        ("top_k", 20, OK),
        ("top_k", 0, OK),
        ("top_k", 20.0, TYPE),
        ("top_k", True, TYPE),
        ("top_k", -1, RANGE),
        ("dry_base", 1, OK),
        ("dry_base", 1.75, OK),
        ("dry_base", "1.75", TYPE),
        ("dry_base", 0.99, RANGE),
        ("dry_base", INF, RANGE),
        ("mirostat", 0, OK),
        ("mirostat", 1, OK),
        ("mirostat", 2, OK),
        ("mirostat", 1.0, TYPE),
        ("mirostat", False, TYPE),
        ("mirostat", -1, RANGE),
        ("mirostat", 3, RANGE),
        ("enable_thinking", True, OK),
        ("enable_thinking", False, OK),
        ("enable_thinking", 1, TYPE),
        ("enable_thinking", "on", TYPE),
        ("reasoning_budget_tokens", 1, OK),
        ("reasoning_budget_tokens", 512, OK),
        ("reasoning_budget_tokens", 8192, OK),
        ("reasoning_budget_tokens", 512.0, TYPE),
        ("reasoning_budget_tokens", True, TYPE),
        ("reasoning_budget_tokens", 0, RANGE),
        ("reasoning_budget_tokens", 8193, RANGE),
        ("reasoning_effort", "none", TYPE),
        ("reasoning_effort", "HIGH", TYPE),
        ("reasoning_effort", 1, TYPE),
    ]
    cases += [("reasoning_effort", level, OK) for level in bp.REASONING_EFFORTS]
    for key in UNIT_KEYS:
        cases += [
            (key, 0.5, OK),
            (key, 0, OK),
            (key, 1, OK),
            (key, "0.5", TYPE),
            (key, True, TYPE),
            (key, -0.01, RANGE),
            (key, 1.01, RANGE),
            (key, NAN, RANGE),
        ]
    for key in FINITE_KEYS:
        cases += [
            (key, -2.5, OK),
            (key, 1e300, OK),
            (key, None, TYPE),
            (key, True, TYPE),
            (key, NAN, RANGE),
            (key, INF, RANGE),
            (key, -INF, RANGE),
        ]
    for key in INT32_KEYS:
        cases += [
            (key, 0, OK),
            (key, 2**31 - 1, OK),
            (key, 1.5, TYPE),
            (key, True, TYPE),
            (key, -1, RANGE),
            (key, 2**31, RANGE),
        ]
    return cases


VALUE_CASES = _cases()


@pytest.mark.parametrize(
    ("key", "value", "code"),
    VALUE_CASES,
    ids=[f"{key}-{value!r}" for key, value, _ in VALUE_CASES],
)
def test_value_validation(key, value, code):
    assert bp.validate_value(key, value) == (code is None, code)


def test_every_key_has_a_valid_and_an_invalid_case():
    """Guard: a key missing from the table above would not be checked at all."""
    valid = {key for key, _, code in VALUE_CASES if code is None}
    wrong_type = {key for key, _, code in VALUE_CASES if code == TYPE}
    assert valid == set(SPEC_KEYS)
    assert wrong_type == set(SPEC_KEYS)
    out_of_range = {key for key, _, code in VALUE_CASES if code == RANGE}
    assert out_of_range == set(SPEC_KEYS) - {"enable_thinking", "reasoning_effort"}


@pytest.mark.parametrize(
    ("key", "text", "expected"),
    [
        ("top_k", " 20 ", (20, None)),
        ("top_k", "20.5", (None, TYPE)),
        ("top_k", "1e400", (None, TYPE)),
        ("top_k", "1_000", (None, TYPE)),
        ("top_p", "0.95", (0.95, None)),
        ("top_p", "1e400", (None, RANGE)),
        ("temperature", "1e400", (None, RANGE)),
        ("temperature", "nan", (None, TYPE)),
        ("temperature", "inf", (None, TYPE)),
        ("temperature", ".5", (0.5, None)),
        ("repeat_penalty", "-1.5e2", (-150.0, None)),
        ("enable_thinking", "on", (True, None)),
        ("enable_thinking", "TRUE", (True, None)),
        ("enable_thinking", "off", (False, None)),
        ("enable_thinking", "false", (False, None)),
        ("enable_thinking", "yes", (None, TYPE)),
        ("reasoning_effort", "high", ("high", None)),
        ("reasoning_effort", "none", (None, TYPE)),
        ("reasoning_budget_tokens", "0", (None, RANGE)),
        ("reasoning_budget_tokens", "8193", (None, RANGE)),
        ("foo", "1", (None, "unknown_key")),
    ],
)
def test_parse_cli_value(key, text, expected):
    assert bp.parse_cli_value(key, text) == expected


@pytest.mark.parametrize("key", SPEC_RESERVED + SPEC_DEFERRED)
def test_reserved_and_deferred_keys_are_rejected(key):
    code = "reserved_key" if key in SPEC_RESERVED else "deferred_key"
    assert bp.validate_value(key, 1) == (False, code)
    assert bp.parse_cli_value(key, "1") == (None, code)
    entries, warnings = bp.parse_override(f"code.{key}=1;code.top_k=5")
    assert entries == {"code": {"top_k": 5}}
    assert warnings == [W("code", key, code)]
    overrides, extra = bp.to_body({key: 1, "top_k": 5}, tool_temperature=0.2, tool_max_tokens=16)
    assert overrides == {"temperature": 0.2, "max_tokens": 16}
    assert extra == {"top_k": 5}


# --- Grammar of the variable (REQ-008) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "entries", "warnings"),
    [
        ("a=b=c", {}, [W("", "a", "malformed_entry")]),
        ("code.top_k", {}, [W("code", "top_k", "malformed_entry")]),
        ("top_k=1", {}, [W("", "top_k", "malformed_entry")]),
        (";;", {}, []),
        ("", {}, []),
        ("code.top_k=1;", {"code": {"top_k": 1}}, []),
        (
            "code.top_k=1;code.top_k=2",
            {"code": {"top_k": 2}},
            [W("code", "top_k", "duplicate_key")],
        ),
        (
            "code.top_k=1;code.top_k=x",
            {},
            [W("code", "top_k", "duplicate_key"), W("code", "top_k", "bad_type")],
        ),
        ("code.top_k=1e400", {}, [W("code", "top_k", "bad_type")]),
        ("code.top_p=1e400", {}, [W("code", "top_p", "out_of_range")]),
        (
            " code . top_k = 5 ;; mechanical.min_p=0.1 ; ",
            {"code": {"top_k": 5}, "mechanical": {"min_p": 0.1}},
            [],
        ),
        ("foo.top_k=1", {}, [W("foo", "top_k", "unknown_role")]),
        ("code.foo=1;code.top_k=2", {"code": {"top_k": 2}}, [W("code", "foo", "unknown_key")]),
        (".top_k=1", {}, [W("", "top_k", "malformed_entry")]),
        ("code.=1", {}, [W("code", "", "malformed_entry")]),
        (
            "a=b=c;code.top_k=3",
            {"code": {"top_k": 3}},
            [W("", "a", "malformed_entry")],
        ),
        (
            "code.enable_thinking=on;code.reasoning_budget_tokens=512;code.reasoning_effort=low",
            {
                "code": {
                    "enable_thinking": True,
                    "reasoning_budget_tokens": 512,
                    "reasoning_effort": "low",
                }
            },
            [],
        ),
        ("code.top_k.x=1", {}, [W("code", "top_k.x", "unknown_key")]),
        ("x" * 2049, {}, [W("", "", "override_too_long")]),
    ],
    ids=lambda case: case if isinstance(case, str) and len(case) < 60 else None,
)
def test_override_grammar(text, entries, warnings):
    assert bp.parse_override(text) == (entries, warnings)


SENTINELS = ("SENTINEL-7Q", "SENTINEL-8R")


def test_override_warnings_never_carry_values():
    """REQ-006/008: a warning carries role and key, never what follows the `=`."""
    pieces = [
        # The case of REQ-006.
        "code.foo=SENTINEL-7Q",
        "code.top_k=SENTINEL-8R",
        "code.min_p=0.1",
        # Every other way a value can be dropped.
        "code.top_p=SENTINEL-7Q=SENTINEL-8R",
        "foo.top_k=SENTINEL-7Q",
        "code.model=SENTINEL-8R",
        "code.dynatemp_range=SENTINEL-7Q",
        "code.reasoning_effort=SENTINEL-8R",
        "long.temperature=SENTINEL-7Q",
        "long.temperature=SENTINEL-8R",
    ]
    entries, warnings = bp.parse_override(";".join(pieces))
    assert entries == {"code": {"min_p": 0.1}}
    assert {w.code for w in warnings} == {
        "unknown_key",
        "bad_type",
        "malformed_entry",
        "unknown_role",
        "reserved_key",
        "deferred_key",
        "duplicate_key",
    }
    for warning in warnings:
        rendered = repr(warning) + bp.warning_text(warning)
        for sentinel in SENTINELS:
            assert sentinel not in rendered, warning
    # A file value is checked by `validate_value`, whose answer has no value either.
    for sentinel in SENTINELS:
        assert sentinel not in repr(bp.validate_value("top_k", sentinel))


# --- Reasoning rule (REQ-011) -------------------------------------------------------------------


def test_thinking_without_budget_is_dropped_with_warning():
    values = {"enable_thinking": True, "top_k": 5}
    kept, warnings = bp.apply_thinking_rule("code", values)
    assert kept == {"top_k": 5}
    assert warnings == [W("code", "enable_thinking", "thinking_without_budget")]
    assert values == {"enable_thinking": True, "top_k": 5}  # the input is not mutated

    both = {"enable_thinking": True, "reasoning_budget_tokens": 512}
    assert bp.apply_thinking_rule("code", both) == (both, [])
    assert bp.apply_thinking_rule("code", {"enable_thinking": False}) == (
        {"enable_thinking": False},
        [],
    )


# --- to_body (REQ-011, REQ-012, REQ-022, REQ-023) -----------------------------------------------


def _base_body():
    return {
        "model": "m",
        "messages": [{"role": "user", "content": "x"}],
        "max_tokens": 16,
        "temperature": 0.2,
        "stream": False,
    }


def _apply(values, **kwargs):
    body = _base_body()
    overrides, extra = bp.to_body(values, tool_temperature=0.2, tool_max_tokens=16, **kwargs)
    for key, value in overrides.items():
        body[key] = value  # in place: an existing key keeps its position
    body.update(extra)
    return body


def test_to_body_without_values_is_today_body():
    assert list(_apply({}).items()) == list(_base_body().items())


def test_to_body_layers():
    values = {
        "reasoning_effort": "high",
        "min_p": 0.1,
        "enable_thinking": True,
        "temperature": 0.7,
        "reasoning_budget_tokens": 512,
        "top_k": 20,
    }
    body = _apply(values)
    # Layer 2 replaces the temperature in its place and adds the budget to the tool's cap.
    assert list(body) == [
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "stream",
        "top_k",
        "min_p",
        "reasoning_budget_tokens",
        "reasoning_effort",
        "chat_template_kwargs",
    ]
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 16 + 512
    assert body["reasoning_budget_tokens"] == 512
    assert body["reasoning_effort"] == "high"
    assert body["chat_template_kwargs"] == {"enable_thinking": True}

    # A reserved key cannot come out of the role, not even one the product sets itself.
    hostile = {
        "model": "other",
        "max_tokens": 99999,
        "stream": True,
        "seed": 1,
        "chat_template_kwargs": {"enable_thinking": True},
        "top_k": 5,
    }
    overrides, extra = bp.to_body(hostile, tool_temperature=0.2, tool_max_tokens=16)
    assert overrides == {"temperature": 0.2, "max_tokens": 16}
    assert extra == {"top_k": 5}


def test_to_body_thinking_off_and_without_budget():
    off = _apply({"enable_thinking": False, "reasoning_budget_tokens": 512})
    assert off["max_tokens"] == 16
    assert "reasoning_budget_tokens" not in off
    assert off["chat_template_kwargs"] == {"enable_thinking": False}

    no_budget = _apply({"enable_thinking": True})
    assert no_budget == _base_body()

    effort_only = _apply({"reasoning_effort": "low"})
    assert effort_only["max_tokens"] == 16
    assert "chat_template_kwargs" not in effort_only
    assert effort_only["reasoning_effort"] == "low"


def test_to_body_without_thinking_allowed():
    values = {"enable_thinking": True, "reasoning_budget_tokens": 512, "top_k": 20}
    body = _apply(values, thinking_allowed=False)
    assert body["max_tokens"] == 16
    assert "reasoning_budget_tokens" not in body
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["top_k"] == 20  # sampling still applies
