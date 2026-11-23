"""The JSON schema of `local_extract`, typed field by field, and the check of what came back.

#692: every field had the same primitive schema (`string|number|boolean|null`), so a field that
asks for a list could come back as `true`. Here each field gets a kind from its name
(`field_kind`), the schema follows the kind (`payload`), the parsed answer is checked against it
(`validate`, also in free mode) and the output cap is sized to what was asked (`output_budget`,
#698: a fixed 512 tokens cut the JSON of a long list).

Pure program: no network, no model. Words are split as `line_check.is_location_field` splits them
(camelCase, `_`, `-`, spaces; lower case, no accents).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from local_delegate import line_check

Kind = Literal["location", "boolean", "count", "list", "scalar"]

#: REQ-015: a first word that makes the field a yes/no question. It only promotes: a question the
#: list does not know (`soporta_windows`) stays `scalar`, which still admits a boolean.
_QUESTION_WORDS = frozenset(
    {
        "es",
        "esta",
        "son",
        "tiene",
        "tienen",
        "hay",
        "existe",
        "puede",
        "debe",
        "usa",
        "contiene",
        "is",
        "are",
        "has",
        "have",
        "can",
        "should",
        "does",
        "do",
        "uses",
        "contains",
    }
)
#: REQ-015: numerals and quantifiers that ask for several values.
_NUMERALS = frozenset(
    {
        "dos",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
    }
)
_QUANTIFIERS = frozenset({"lista", "list", "todos", "todas", "all", "cada", "each"})
#: Endings of a word of 4 letters or more ending in `s` that are not a plural (`status`, `class`).
_NOT_PLURAL_ENDINGS = ("ss", "us", "is")
#: Words of that shape that are not plurals, so a yes/no field named with them (`soporta_windows`)
#: is not taken for a list (REQ-015 wants it `scalar`, where a boolean holds). Short on purpose:
#: a plural it misses only costs the boolean guard of #692, never a value.
_NOT_PLURALS = frozenset(
    {"windows", "macos", "news", "series", "species", "canvas", "alias", "atlas", "chaos", "lens"}
)

#: REQ-017: output tokens per field kind, the base, and per expected item of a location field.
_BASE_TOKENS = 64
_KIND_TOKENS: dict[str, int] = {"boolean": 16, "count": 32, "scalar": 192, "list": 384}
_TOKENS_PER_ITEM = 40
#: Items expected from a location field answered with anchors (no catalogue to count).
ANCHOR_ITEMS = 40
#: REQ-017: floor (what one call asked before) and ceiling of the output cap.
MIN_OUTPUT_TOKENS = 512
MAX_OUTPUT_TOKENS = 4096
#: REQ-010: above this many names the `enum` is left out (the name goes as a free string).
MAX_ENUM_NAMES = 300


def _words(name: str) -> list[str]:
    return line_check._FIELD_WORD.findall(
        line_check._fold(line_check._CAMEL_BOUNDARY.sub(" ", name))
    )


def _is_count(words: list[str]) -> bool:
    if not words:
        return False
    first, second = words[0], words[1] if len(words) > 1 else ""
    if (first == "number" and second == "of") or (
        first in {"numero", "cantidad"} and second == "de"
    ):
        return True
    if first in {"num", "total", "count"} and len(words) > 1:
        return True
    return len(words) > 1 and words[-1] in {"count", "total"}


def _is_list(words: list[str]) -> bool:
    for word in words:
        if word in _NUMERALS or word in _QUANTIFIERS or word.isdigit():
            return True
        if (
            len(word) >= 4
            and word.endswith("s")
            and not word.endswith(_NOT_PLURAL_ENDINGS)
            and word not in _NOT_PLURALS
        ):
            return True
    return False


def field_kind(name: str, by_path: bool) -> Kind:
    """The kind of the field `name` (REQ-015): the first of location > boolean > count > list.

    `location` only with the input read by `path`: with `text=` a location field follows the
    other rules, as before this change (REQ-019).
    """
    if by_path and line_check.is_location_field(name):
        return "location"
    words = _words(name)
    if name.rstrip().endswith("?") or (words and words[0] in _QUESTION_WORDS):
        return "boolean"
    if _is_count(words):
        return "count"
    if _is_list(words):
        return "list"
    return "scalar"


def property_schema(kind: Kind, *, singular: bool = False, names: list[str] | None = None) -> dict:
    """The schema of one property. No kind admits a free nested object (gemma3-4b nested the
    value, `{"campo": {"valor": "x"}}`); `list` and `location` never admit a boolean (#692).

    `location`: a list of `{name, anchor, anchor_end}`; `names` (REQ-010) becomes the `enum` of
    `name` when there are 300 or fewer, and `singular` caps the list at one item.
    """
    if kind == "boolean":
        return {"type": ["boolean", "null"]}
    if kind == "count":
        return {"type": ["number", "string", "null"]}
    if kind == "list":
        return {
            "type": ["array", "string", "number", "null"],
            "items": {"type": ["string", "number"]},
        }
    if kind == "location":
        name_schema: dict[str, Any] = {"type": "string"}
        if names and len(names) <= MAX_ENUM_NAMES:
            name_schema["enum"] = list(dict.fromkeys(names))
        out: dict[str, Any] = {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "name": name_schema,
                    "anchor": {"type": ["string", "null"]},
                    "anchor_end": {"type": ["string", "null"]},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        }
        if singular:
            out["maxItems"] = 1
        return out
    return {"type": ["string", "number", "boolean", "null"]}


def payload(
    kinds: Mapping[str, Kind],
    *,
    singular: Iterable[str] = (),
    names: Mapping[str, list[str]] | None = None,
) -> dict:
    """The `response_format` (json_object + schema of llama-server) for the fields of `kinds`."""
    singular = set(singular)
    names = names or {}
    return {
        "type": "json_object",
        "schema": {
            "type": "object",
            "properties": {
                name: property_schema(kind, singular=name in singular, names=names.get(name))
                for name, kind in kinds.items()
            },
            "required": list(kinds),
        },
    }


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _location_ok(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict) and isinstance(item.get("name"), str) for item in value
    )


def mismatch(kind: Kind, value: Any) -> bool:
    """Whether `value` breaks `kind` (REQ-016). A null never does; a number in `list` does not
    (a count with a plural name still holds); a boolean in `scalar` does not."""
    if value is None:
        return False
    if kind in ("list", "count"):
        return isinstance(value, (bool, dict))
    if kind == "scalar":
        return isinstance(value, dict)
    if kind == "location":
        return not _location_ok(value)
    return False


def expected_label(kind: Kind) -> str:
    """The machine name of what `kind` expects, for `type_mismatch_keys.expected`."""
    return {
        "location": "array",
        "boolean": "boolean",
        "count": "number",
        "list": "array",
        "scalar": "string|number|boolean",
    }[kind]


def validate(data: Mapping[str, Any], kinds: Mapping[str, Kind]) -> dict[str, dict[str, str]]:
    """`{field: {"expected", "got"}}` for each value of `data` that breaks its kind."""
    out: dict[str, dict[str, str]] = {}
    for name, kind in kinds.items():
        if name in data and mismatch(kind, data[name]):
            out[name] = {"expected": expected_label(kind), "got": _type_name(data[name])}
    return out


def retry_message(mismatches: Mapping[str, Mapping[str, str]]) -> str:
    """The instruction appended to the user message of the one retry (REQ-016), for the model."""
    detail = "; ".join(
        f'"{name}": se esperaba {info["expected"]} y llegó {info["got"]}'
        for name, info in mismatches.items()
    )
    return (
        "\n\nTu respuesta anterior no cumplía el tipo de estas claves: "
        f"{detail}. Devuelve otra vez el objeto JSON completo con esos tipos."
    )


def output_budget(kinds: Mapping[str, Kind], index_sizes: Mapping[str, int] | None = None) -> int:
    """Output tokens for the fields of `kinds` (REQ-017), between 512 and 4096.

    `index_sizes`: the items expected from each location field (the catalogue when the model
    chooses names, `ANCHOR_ITEMS` with anchors; absent means `ANCHOR_ITEMS`).
    """
    index_sizes = index_sizes or {}
    total = _BASE_TOKENS
    for name, kind in kinds.items():
        if kind == "location":
            total += _TOKENS_PER_ITEM * index_sizes.get(name, ANCHOR_ITEMS)
        else:
            total += _KIND_TOKENS[kind]
    return max(MIN_OUTPUT_TOKENS, min(MAX_OUTPUT_TOKENS, total))
