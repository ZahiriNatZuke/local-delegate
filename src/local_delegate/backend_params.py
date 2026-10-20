"""Per-role parameters sent to the backend (SDD `backend-extra-params`).

Single copy of the rule (REQ-001): the closed catalog of keys with their type and range
(REQ-004), the reserved and deferred keys (REQ-005), the grammar of
`LOCAL_DELEGATE_BACKEND_PARAMS` (REQ-008), the reasoning rule (REQ-011) and how the values go into
the request body (REQ-012, `to_body`).

The first half is pure: no I/O. The second half (REQ-001/002/009, T6) reads and writes
`LOG_DIR/backend-params.json`, resolves the effective values of each role (`effective`) and builds
the report that `show`, `doctor` and `local_status` paint (`report`).

Warnings are codes (`role`, `key`, `code`), never values: a rejected value may be a secret pasted by
mistake (REQ-006/007), so it never reaches a warning, a log or a screen. The texts come from the
i18n catalog (`common.backend_params.warning.<code>`).
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from filelock import FileLock, Timeout

from . import config, i18n, llamaswap_config

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
    "file_busy",
    "file_write_failed",
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


# --- File, writing, cache and resolution (T6, REQ-001/002/008/009/011/023) -----------------------

FILE_NAME = "backend-params.json"
LOCK_NAME = "backend-params.json.lock"
FILE_VERSION = 1
#: Seconds `write` waits for the lock before giving up with `file_busy`.
LOCK_TIMEOUT = 10.0

#: Where an effective value comes from (`Effective.source`, `show --json`).
SOURCE_FILE = "file"
SOURCE_ENV = "env"


def path(log_dir: Path | None = None) -> Path:
    """`LOG_DIR/backend-params.json` (REQ-001); `LOG_DIR` is read when called, not at import."""
    return Path(log_dir if log_dir is not None else config.LOG_DIR) / FILE_NAME


class LoadResult(NamedTuple):
    roles: dict[str, dict[str, object]]  # only known roles and valid keys
    warnings: list[Warning]


class Effective(NamedTuple):
    values: dict[str, object]  # in catalog order
    source: dict[str, str]  # key -> SOURCE_FILE | SOURCE_ENV
    warnings: list[Warning]


class RoleReport(NamedTuple):
    """One group of rows of `show`, `doctor` and `local_status`: data only, each surface writes text.

    `role == ""` holds the warnings that belong to no role (a broken file, a variable that is too
    long, a malformed entry without a role, an unknown role).
    """

    role: str
    values: dict[str, object]
    source: dict[str, str]
    warnings: list[Warning]


class WriteRefused(Exception):
    """A `write` that did not touch the file, with the code of the reason (never a value)."""

    def __init__(self, code: str, warning: Warning | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.warning = warning or Warning("", "", code)


def _empty_document() -> dict:
    return {"version": FILE_VERSION, "roles": {}}


def _read_document(file: Path) -> tuple[dict | None, str | None]:
    """The raw document, `(doc, None)`, or `(None, code)` if it must be ignored whole (REQ-001).

    An absent or empty file is the empty document. Too large, unreadable, not JSON, not an object,
    a `version` other than the integer 1 or `roles` that is not an object: ignored whole.
    """
    try:
        if file.stat().st_size > MAX_FILE_BYTES:
            return None, "file_too_large"
        data = file.read_bytes()
    except FileNotFoundError:
        return _empty_document(), None
    except OSError:
        return None, "file_unreadable"
    if len(data) > MAX_FILE_BYTES:  # it grew between `stat` and the read
        return None, "file_too_large"
    try:
        text = data.decode("utf-8-sig")  # a BOM from a hand edit on Windows is not an error
        if not text.strip():
            return _empty_document(), None
        doc = json.loads(text)
    except (ValueError, RecursionError):  # UnicodeDecodeError and JSONDecodeError are ValueError
        return None, "file_unreadable"
    if not isinstance(doc, dict):
        return None, "file_unreadable"
    version = doc.get("version")
    if type(version) is not int or version != FILE_VERSION:  # `true` is not 1
        return None, "file_bad_version"
    roles = doc.setdefault("roles", {})
    if not isinstance(roles, dict):
        return None, "file_unreadable"
    return doc, None


def _catalog_order(values: dict[str, object]) -> dict[str, object]:
    return {key: values[key] for key in ALLOWED_KEYS if key in values}


def _validate_roles(raw_roles: dict) -> LoadResult:
    """Keep the known roles and their valid keys; each dropped entry leaves a warning."""
    roles: dict[str, dict[str, object]] = {}
    warnings: list[Warning] = []
    for role, entries in raw_roles.items():
        if role not in ROLES:
            keys = list(entries) if isinstance(entries, dict) and entries else [""]
            warnings.extend(Warning(role, key, "unknown_role") for key in keys)
            continue
        if not isinstance(entries, dict):
            warnings.append(Warning(role, "", "bad_type"))
            continue
        valid: dict[str, object] = {}
        for key, value in entries.items():
            ok, code = validate_value(key, value)
            if ok:
                valid[key] = value
            else:
                warnings.append(Warning(role, key, code or "bad_type"))
        if valid:
            roles[role] = _catalog_order(valid)
    return LoadResult(roles, warnings)


def load(log_dir: Path | None = None) -> LoadResult:
    """The valid entries of the file and the warnings of what was dropped. It never raises."""
    try:
        doc, problem = _read_document(path(log_dir))
        if doc is None:
            return LoadResult({}, [Warning("", "", problem or "file_unreadable")])
        return _validate_roles(doc["roles"])
    except Exception:  # reading the parameters never breaks a tool, `show` or `doctor`
        return LoadResult({}, [Warning("", "", "file_unreadable")])


def write(mutator: Callable[[dict], None], log_dir: Path | None = None) -> None:
    """Change the file atomically under the lock (REQ-002).

    `mutator` gets the current document (`{"version": 1, "roles": {...}}`) and changes `roles` in
    place, or raises `WriteRefused` to leave the file untouched. A file that `load` would ignore
    whole is never overwritten (`WriteRefused` with its code). The new content goes to a temporary
    file in the same directory and replaces the old one with `os.replace`; if anything fails, the
    old file stays and the temporary file is removed. Raises `filelock.Timeout` if the lock is
    busy and `OSError` if the disk fails.
    """
    file = path(log_dir)
    file.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(file.parent / LOCK_NAME), timeout=LOCK_TIMEOUT):
        doc, problem = _read_document(file)
        if doc is None:
            raise WriteRefused(problem or "file_unreadable")
        mutator(doc)
        document = {"version": FILE_VERSION, "roles": doc["roles"]}
        fd, tmp = tempfile.mkstemp(dir=file.parent, prefix=".backend-params.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(document, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, file)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass  # best-effort cleanup: the original error is the one that propagates
            raise


def _env_entries() -> tuple[dict[str, dict[str, object]], list[Warning]]:
    """The valid entries of `LOCAL_DELEGATE_BACKEND_PARAMS` and its warnings (REQ-008)."""
    override = config.backend_params_override()
    if override.problem is not None:
        return {}, [Warning("", "", override.problem)]
    return parse_override(override.value or "")


def _file_has_budget(entries: dict) -> bool:
    if "reasoning_budget_tokens" not in entries:
        return False
    return validate_value("reasoning_budget_tokens", entries["reasoning_budget_tokens"])[0]


def _commit(
    mutator: Callable[[dict], None], log_dir: Path | None
) -> tuple[bool, str | None, list[Warning]]:
    try:
        write(mutator, log_dir)
    except WriteRefused as refused:
        return False, refused.code, [refused.warning]
    except Timeout:
        return False, "file_busy", [Warning("", "", "file_busy")]
    except OSError:
        return False, "file_write_failed", [Warning("", "", "file_write_failed")]
    return True, None, []


def _role_entries(doc: dict, role: str) -> dict:
    """The role's object in the document, replacing a hand-edited value that is not an object."""
    entries = doc["roles"].get(role)
    if not isinstance(entries, dict):
        entries = doc["roles"][role] = {}
    return entries


def set_value(
    role: str, key: str, text: str, log_dir: Path | None = None
) -> tuple[bool, str | None, list[Warning]]:
    """`backend-params set <role> <key> <value>` (REQ-003/011/023): `(ok, code, warnings)`.

    Validates the role, the key, the type and the range **before** writing; a rejection leaves the
    file untouched and its code and warning never carry the value. `enable_thinking on` needs an
    effective budget in the same role (in the file or in the variable). A written value may come
    back with the context warnings of REQ-023 (`set` warns, it does not refuse).
    """
    if role not in ROLES:
        return False, "unknown_role", [Warning(role, key, "unknown_role")]
    value, code = parse_cli_value(key, text)
    if code is not None:
        return False, code, [Warning(role, key, code)]

    def mutate(doc: dict) -> None:
        entries = _role_entries(doc, role)
        if key == "enable_thinking" and value is True:
            env_budget = "reasoning_budget_tokens" in _env_entries()[0].get(role, {})
            if not (_file_has_budget(entries) or env_budget):
                raise WriteRefused(
                    "thinking_without_budget", Warning(role, key, "thinking_without_budget")
                )
        entries[key] = value

    ok, code, warnings = _commit(mutate, log_dir)
    if ok:
        warnings = context_warnings(role, log_dir)
    return ok, code, warnings


def _refuse_budget_loss(role: str, entries: object) -> None:
    """REQ-011: the budget cannot go while `enable_thinking` stays on in the file."""
    if (
        isinstance(entries, dict)
        and entries.get("enable_thinking") is True
        and "reasoning_budget_tokens" in entries
    ):
        raise WriteRefused(
            "thinking_without_budget",
            Warning(role, "reasoning_budget_tokens", "thinking_without_budget"),
        )


def unset(
    role: str, key: str, log_dir: Path | None = None
) -> tuple[bool, str | None, list[Warning]]:
    """`backend-params unset <role> <key>`: `(ok, code, warnings)`. A missing key is not an error.

    Any key can be removed, also one the catalog rejects (cleaning a hand edit). The budget cannot
    be removed while `enable_thinking` is on in the file (REQ-011).
    """
    if role not in ROLES:
        return False, "unknown_role", [Warning(role, key, "unknown_role")]

    def mutate(doc: dict) -> None:
        entries = doc["roles"].get(role)
        if key == "reasoning_budget_tokens":
            _refuse_budget_loss(role, entries)
        if isinstance(entries, dict):
            entries.pop(key, None)
            if not entries:
                del doc["roles"][role]

    return _commit(mutate, log_dir)


def reset(
    role: str | None = None, log_dir: Path | None = None
) -> tuple[bool, str | None, list[Warning]]:
    """`backend-params reset [<role>]`: empty one role, or every role. `(ok, code, warnings)`.

    The role goes whole, `enable_thinking` included, so it never leaves reasoning without its
    budget: no `unset <role> enable_thinking` is needed first (user decision 12).
    """
    if role is not None and role not in ROLES:
        return False, "unknown_role", [Warning(role, "", "unknown_role")]

    def mutate(doc: dict) -> None:
        targets = [role] if role is not None else list(doc["roles"])
        for target in targets:
            doc["roles"].pop(target, None)

    return _commit(mutate, log_dir)


class _Resolved(NamedTuple):
    roles: dict[str, Effective]  # every role of ROLES; warnings: only the role's own
    general: list[Warning]  # warnings that belong to no role of ROLES


_cache_lock = threading.Lock()
# {file path: (key, _Resolved)}; key = (path, (st_mtime_ns, st_size, st_ino) | None, raw variable).
_cache: dict[str, tuple[tuple, _Resolved]] = {}


def _file_key(file: Path) -> tuple[int, int, int] | None:
    """The cache key of the file: `None` if it does not exist. Raises `OSError` otherwise."""
    try:
        st = os.stat(file)
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _compute(log_dir: Path | None) -> _Resolved:
    loaded = load(log_dir)
    env_entries, env_warnings = _env_entries()
    every = loaded.warnings + env_warnings
    roles: dict[str, Effective] = {}
    for role in ROLES:
        values = dict(loaded.roles.get(role, {}))
        source = dict.fromkeys(values, SOURCE_FILE)
        for key, value in env_entries.get(role, {}).items():  # the variable wins key by key
            values[key] = value
            source[key] = SOURCE_ENV
        values, thinking = apply_thinking_rule(role, values)
        values = _catalog_order(values)
        roles[role] = Effective(
            values,
            {key: source[key] for key in values},
            [w for w in every if w.role == role] + thinking,
        )
    return _Resolved(roles, [w for w in every if w.role not in ROLES])


def _resolved(log_dir: Path | None = None) -> _Resolved:
    """Everything resolved, cached by the file's `(st_mtime_ns, st_size, st_ino)` and the variable.

    Read on every operation (REQ-009): a change of the file or of the variable is seen by the next
    call without a restart. If the file changes while it is being read, the result is not cached.
    """
    file = path(log_dir)
    raw = config.backend_params_override().raw
    try:
        key = (str(file), _file_key(file), raw)
    except OSError:
        return _compute(log_dir)  # cannot stat it: no cache, `load` reports the problem
    with _cache_lock:
        cached = _cache.get(str(file))
        if cached is not None and cached[0] == key:
            return cached[1]
    result = _compute(log_dir)
    try:
        still = (str(file), _file_key(file), raw) == key
    except OSError:
        still = False
    if still:
        with _cache_lock:
            _cache[str(file)] = (key, result)
    return result


def _forget() -> None:
    """Empty the cache of `effective` (for the tests)."""
    with _cache_lock:
        _cache.clear()


def effective(role: str, log_dir: Path | None = None) -> Effective:
    """The values a role sends (REQ-008): variable > file, key by key, after REQ-011.

    `source[key]` is `"env"` only for the keys that come from the variable. `enable_thinking=true`
    without an effective budget is dropped with `thinking_without_budget`. The warnings are the
    role's own plus those that belong to no role (a broken file, a variable that is too long...).
    An unknown role has no values.
    """
    resolved = _resolved(log_dir)
    own = resolved.roles.get(role)
    if own is None:
        return Effective({}, {}, list(resolved.general))
    return Effective(dict(own.values), dict(own.source), own.warnings + resolved.general)


def context_warnings(role: str, log_dir: Path | None = None) -> list[Warning]:
    """REQ-023, the warning of `set`, `show`, `doctor` and `local_status`.

    With reasoning on, `ceil(MAX_CHARS of the role / CHARS_PER_TOKEN) + CHUNK_MAX_TOKENS + budget`
    is compared with the context of the role's model: `context_overflow` if it does not fit, and
    `context_estimated` if that context is the estimate. `vision` is left out (its input is an
    image). This is the static check of `set`, not the per-call one.
    """
    if role == "vision" or role not in ROLES:
        return []
    values = _resolved(log_dir).roles[role].values
    budget = values.get("reasoning_budget_tokens")
    if values.get("enable_thinking") is not True or not isinstance(budget, int):
        return []
    model = config.models_by_role().get(role, "")
    n_ctx, estimated = llamaswap_config.model_context_size(model)
    needed = (
        math.ceil(config.max_chars_for_role(role) / config.CHARS_PER_TOKEN)
        + config.CHUNK_MAX_TOKENS
        + budget
    )
    warnings: list[Warning] = []
    if estimated:
        warnings.append(Warning(role, "", "context_estimated"))
    if needed > n_ctx:
        warnings.append(Warning(role, "", "context_overflow"))
    return warnings


def report(log_dir: Path | None = None) -> list[RoleReport]:
    """What `show`, `doctor` and `local_status` paint: one entry per role, in `ROLES` order.

    Each entry has the effective values, their source and the role's warnings, the context ones
    included. A last entry with `role == ""` holds the warnings that belong to no role, only when
    there are any. Data only, never a value of a dropped entry.
    """
    resolved = _resolved(log_dir)
    rows = [
        RoleReport(
            role,
            dict(own.values),
            dict(own.source),
            own.warnings + context_warnings(role, log_dir),
        )
        for role, own in resolved.roles.items()
    ]
    if resolved.general:
        rows.append(RoleReport("", {}, {}, list(resolved.general)))
    return rows
