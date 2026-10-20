"""Per-role parameters sent to the backend (SDD `backend-extra-params`).

Single copy of the rule (REQ-001): the closed catalog of keys with their type and range
(REQ-004), the reserved and deferred keys (REQ-005), the grammar of
`LOCAL_DELEGATE_BACKEND_PARAMS` (REQ-008), the reasoning rule (REQ-011) and how the values go into
the request body (REQ-012, `to_body`).

This first half is pure: no I/O. Warnings are codes (`role`, `key`, `code`), never values: a
rejected value may be a secret pasted by mistake (REQ-006/007), so it never reaches a warning, a
log or a screen. The texts come from the i18n catalog (`common.backend_params.warning.<code>`).
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

from . import config, i18n

#: Roles that accept parameters, the same as the routing roles.
ROLES = ("mechanical", "long", "code", "vision")

#: Group names of the catalog (REQ-004).
GROUP_SAMPLING = "sampling"
GROUP_REASONING = "reasoning"

#: Where a key goes in the body.
TARGET_ROOT = "root"
TARGET_TEMPLATE = "chat_template_kwargs"

#: Upper bound of the 32-bit counters of the backend (`0–2³¹−1`).
INT32_MAX = 2**31 - 1

#: Reasoning budget range (REQ-004, decision 9): 0 closes reasoning at once, so the minimum is 1.
BUDGET_MIN = 1
BUDGET_MAX = 8192

#: Size limits of the two sources (REQ-001, REQ-008).
MAX_FILE_BYTES = 64 * 1024
MAX_OVERRIDE_CHARS = config.BACKEND_PARAMS_OVERRIDE_MAX_CHARS  # one copy, read by `config`

#: Values of `reasoning_effort` (REQ-004): without `none`, which would read as "turn it off".
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")


class KeySpec(NamedTuple):
    group: str
    kind: str  # "float" | "int" | "bool" | "enum"
    minimum: float | None  # inclusive; None = no lower bound (only "finite")
    maximum: float | None  # inclusive; None = no upper bound
    target: str
    choices: tuple[str, ...] = ()


def _float(minimum: float | None = None, maximum: float | None = None) -> KeySpec:
    return KeySpec(GROUP_SAMPLING, "float", minimum, maximum, TARGET_ROOT)


def _int(minimum: int | None = None, maximum: int | None = None) -> KeySpec:
    return KeySpec(GROUP_SAMPLING, "int", minimum, maximum, TARGET_ROOT)


#: The 21 keys of REQ-004, copied from the table of `spec.md`, in its order.
ALLOWED_KEYS: dict[str, KeySpec] = {
    "temperature": _float(0),
    "top_k": _int(0),
    "top_p": _float(0, 1),
    "min_p": _float(0, 1),
    "typical_p": _float(0, 1),
    "repeat_penalty": _float(),
    "repeat_last_n": _int(0, INT32_MAX),
    "presence_penalty": _float(),
    "frequency_penalty": _float(),
    "dry_multiplier": _float(),
    "dry_base": _float(1),
    "dry_allowed_length": _int(0, INT32_MAX),
    "dry_penalty_last_n": _int(0, INT32_MAX),
    "xtc_probability": _float(0, 1),
    "xtc_threshold": _float(0, 1),
    "mirostat": _int(0, 2),
    "mirostat_tau": _float(),
    "mirostat_eta": _float(),
    "enable_thinking": KeySpec(GROUP_REASONING, "bool", None, None, TARGET_TEMPLATE),
    "reasoning_budget_tokens": KeySpec(GROUP_REASONING, "int", BUDGET_MIN, BUDGET_MAX, TARGET_ROOT),
    "reasoning_effort": KeySpec(
        GROUP_REASONING, "enum", None, None, TARGET_ROOT, REASONING_EFFORTS
    ),
}

#: The 27 reserved keys of REQ-005, copied from `spec.md`: never configurable.
RESERVED_KEYS: frozenset[str] = frozenset(
    {
        # tool contract
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
        # server
        "cache_prompt",
        "id_slot",
        "n_keep",
        "samplers",
        "seed",
        # raw reasoning
        "chat_template_kwargs",
        "reasoning_format",
    }
)

#: Deferred keys ("Fuera de alcance" of `spec.md`): rejected like the reserved ones.
DEFERRED_KEYS: frozenset[str] = frozenset(
    {
        "dry_sequence_breakers",
        "top_n_sigma",
        "dynatemp_range",
        "dynatemp_exponent",
        "min_keep",
        "adaptive_target",
        "adaptive_decay",
        "reasoning_budget_message",
        "reasoning_control",
    }
)

#: Stable warning codes (English, machine values). Each one has a text in
#: `resources/i18n/{es,en}/common.json` under `common.backend_params.warning.<code>`.
WARNING_CODES = (
    "unknown_role",
    "unknown_key",
    "reserved_key",
    "deferred_key",
    "bad_type",
    "out_of_range",
    "malformed_entry",
    "duplicate_key",
    "override_too_long",
    "thinking_without_budget",
    "file_unreadable",
    "file_bad_version",
    "file_too_large",
    "context_estimated",
    "context_overflow",
)

_TEXT_PREFIX = "common.backend_params.warning."


class Warning(NamedTuple):  # the name of the plan; it shadows the builtin, it never raises
    """A problem with one entry: who and why, never the value."""

    role: str
    key: str
    code: str


def warning_text(warning: Warning) -> str:
    """The text of a warning in the current language. It only carries the role and the key."""
    return i18n.t(_TEXT_PREFIX + warning.code, role=warning.role, key=warning.key)


def key_problem(key: str) -> str | None:
    """Why a key cannot be configured, or None if it is in the catalog."""
    if key in ALLOWED_KEYS:
        return None
    if key in RESERVED_KEYS:
        return "reserved_key"
    if key in DEFERRED_KEYS:
        return "deferred_key"
    return "unknown_key"


def validate_value(key: str, value: object) -> tuple[bool, str | None]:
    """Whether `value` is valid for `key` (REQ-004/005): `(True, None)` or `(False, code)`.

    A JSON boolean is not a number, `NaN` and `±inf` are never valid, and a float key accepts an
    int (`top_p: 1`), but an int key does not accept a float (`top_k: 20.0`).
    """
    problem = key_problem(key)
    if problem is not None:
        return False, problem
    spec = ALLOWED_KEYS[key]
    if spec.kind == "bool":
        return (True, None) if isinstance(value, bool) else (False, "bad_type")
    if spec.kind == "enum":
        return (True, None) if value in spec.choices else (False, "bad_type")
    if isinstance(value, bool):
        return False, "bad_type"
    if spec.kind == "int":
        if not isinstance(value, int):
            return False, "bad_type"
    elif not isinstance(value, (int, float)):
        return False, "bad_type"
    elif not math.isfinite(value):
        return False, "out_of_range"
    if spec.minimum is not None and value < spec.minimum:
        return False, "out_of_range"
    if spec.maximum is not None and value > spec.maximum:
        return False, "out_of_range"
    return True, None


_INT_TEXT = re.compile(r"[+-]?\d+")
_FLOAT_TEXT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_BOOL_TEXT = {"on": True, "true": True, "off": False, "false": False}


def parse_cli_value(key: str, text: str) -> tuple[object | None, str | None]:
    """Parse a value written by a person (`set` and the variable): `(value, None)` or `(None, code)`.

    Numbers in plain decimal notation (`nan`, `inf`, `1_000` and hexadecimal are not numbers
    here); a number that overflows to `inf`, such as `1e400`, is out of range. `on`/`off`/`true`/
    `false` for `enable_thinking`. The result goes through `validate_value`.
    """
    problem = key_problem(key)
    if problem is not None:
        return None, problem
    spec = ALLOWED_KEYS[key]
    word = text.strip()
    value: object
    if spec.kind == "bool":
        if word.lower() not in _BOOL_TEXT:
            return None, "bad_type"
        value = _BOOL_TEXT[word.lower()]
    elif spec.kind == "enum":
        value = word
    elif spec.kind == "int":
        if not _INT_TEXT.fullmatch(word):
            return None, "bad_type"
        value = int(word)
    else:
        if not _FLOAT_TEXT.fullmatch(word):
            return None, "bad_type"
        value = float(word)
    ok, code = validate_value(key, value)
    return (value, None) if ok else (None, code)


def parse_override(text: str) -> tuple[dict[str, dict[str, object]], list[Warning]]:
    """Parse `LOCAL_DELEGATE_BACKEND_PARAMS` (`role.key=value;…`) with the grammar of REQ-008.

    Returns the valid entries per role and the warnings. A bad piece is dropped without dragging
    the others. The warnings only carry the role and the key of each piece, never what follows
    the `=`.
    """
    if len(text) > MAX_OVERRIDE_CHARS:
        return {}, [Warning("", "", "override_too_long")]
    warnings: list[Warning] = []
    # Last one wins per (role, key): collect first, validate after, so a repeated key is decided
    # by its last occurrence even when that one is the invalid one.
    pieces: dict[tuple[str, str], str] = {}
    for raw_piece in text.split(";"):
        piece = raw_piece.strip()
        if not piece:
            continue
        left, sep, value = piece.partition("=")
        role, dot, key = left.partition(".")
        role, key = role.strip(), key.strip()
        if not sep or "=" in value or not dot or not role or not key:
            if not dot:
                role, key = "", left.strip()
            warnings.append(Warning(role, key, "malformed_entry"))
            continue
        if (role, key) in pieces:
            warnings.append(Warning(role, key, "duplicate_key"))
            del pieces[(role, key)]
        pieces[(role, key)] = value.strip()
    entries: dict[str, dict[str, object]] = {}
    for (role, key), value_text in pieces.items():
        if role not in ROLES:
            warnings.append(Warning(role, key, "unknown_role"))
            continue
        parsed, code = parse_cli_value(key, value_text)
        if code is not None:
            warnings.append(Warning(role, key, code))
            continue
        entries.setdefault(role, {})[key] = parsed
    return entries, warnings


def apply_thinking_rule(
    role: str, values: dict[str, object]
) -> tuple[dict[str, object], list[Warning]]:
    """REQ-011: `enable_thinking=true` without a budget in the same role is ignored, with warning.

    `values` are the effective values of one role (after the precedence of REQ-008). Returns a
    new dict; `enable_thinking=false` needs no budget.
    """
    if values.get("enable_thinking") is True and "reasoning_budget_tokens" not in values:
        kept = {key: value for key, value in values.items() if key != "enable_thinking"}
        return kept, [Warning(role, "enable_thinking", "thinking_without_budget")]
    return dict(values), []


def to_body(
    values: dict[str, object],
    *,
    tool_temperature: float,
    tool_max_tokens: int,
    thinking_allowed: bool = True,
) -> tuple[dict[str, object], dict[str, object]]:
    """Layer 2 of REQ-012: what the role puts into one real call.

    Returns `(overrides, extra)`:

    - `overrides` replaces in place, keeping the key order of the body (REQ-022): `temperature`
      (the role's, or the tool's) and `max_tokens` (the tool's cap plus the budget when reasoning
      is on, REQ-011; it is added, never substituted).
    - `extra` goes at the end, in catalog order: the sampling keys, `reasoning_budget_tokens` and
      `reasoning_effort` at the root, and `chat_template_kwargs: {"enable_thinking": bool}`.

    With `thinking_allowed=False` (REQ-023, the call does not fit in the context) a role with
    reasoning on sends `enable_thinking: false`, no budget and the tool's cap. Only catalog keys
    are taken from `values`; a reserved key can never come out of here.
    """
    role_values = {key: value for key, value in values.items() if key in ALLOWED_KEYS}
    budget = role_values.get("reasoning_budget_tokens")
    wants_thinking = role_values.get("enable_thinking") is True and budget is not None
    thinking_on = wants_thinking and thinking_allowed

    temperature = role_values.get("temperature", tool_temperature)
    max_tokens = tool_max_tokens + budget if thinking_on else tool_max_tokens
    overrides: dict[str, object] = {"temperature": temperature, "max_tokens": max_tokens}

    extra: dict[str, object] = {}
    for key, spec in ALLOWED_KEYS.items():
        if key != "temperature" and spec.group == GROUP_SAMPLING and key in role_values:
            extra[key] = role_values[key]
    if thinking_on:
        extra["reasoning_budget_tokens"] = budget
    if "reasoning_effort" in role_values:
        extra["reasoning_effort"] = role_values["reasoning_effort"]
    if "enable_thinking" in role_values and (
        wants_thinking or role_values["enable_thinking"] is False
    ):
        extra[TARGET_TEMPLATE] = {"enable_thinking": thinking_on}

    # Defence in depth: only catalog keys and the product-built template kwargs leave here.
    assert all(key not in RESERVED_KEYS or key == TARGET_TEMPLATE for key in extra), extra.keys()
    return overrides, extra
