"""Warning texts of `backend_params` in the i18n catalog (SDD `backend-extra-params`, T5).

REQ-017: one text per warning code in `es` and `en`, with no placeholder that could carry a value,
and rendered warnings never show the sentinels of REQ-006.
"""

from __future__ import annotations

import string

import pytest

from local_delegate import backend_params as bp
from local_delegate import i18n

PREFIX = "common.backend_params.warning."
SENTINELS = ("SENTINEL-7Q", "SENTINEL-8R")


@pytest.mark.parametrize("lang", ["es", "en"])
def test_every_warning_code_has_text_in_both_languages(lang):
    catalog = i18n.catalog(lang)
    for code in bp.WARNING_CODES:
        assert catalog.get(PREFIX + code, "").strip(), code
    # And no orphan text for a code the module does not define.
    defined = {key.removeprefix(PREFIX) for key in catalog if key.startswith(PREFIX)}
    assert defined == set(bp.WARNING_CODES)


@pytest.mark.parametrize("lang", ["es", "en"])
def test_warning_texts_have_no_value_placeholder(lang):
    catalog = i18n.catalog(lang)
    for code in bp.WARNING_CODES:
        fields = {
            name for _, name, _, _ in string.Formatter().parse(catalog[PREFIX + code]) if name
        }
        assert fields <= {"role", "key"}, (code, fields)


def _sentinel_warnings() -> list[bp.Warning]:
    """Every warning code, produced from inputs that carry the sentinels where a value goes."""
    pieces = [
        "code.foo=SENTINEL-7Q",
        "code.top_k=SENTINEL-8R",
        "code.top_p=1e400",
        "code.min_p=SENTINEL-7Q=SENTINEL-8R",
        "foo.top_k=SENTINEL-7Q",
        "code.model=SENTINEL-8R",
        "code.dynatemp_range=SENTINEL-7Q",
        "long.temperature=SENTINEL-7Q",
        "long.temperature=SENTINEL-8R",
    ]
    _, warnings = bp.parse_override(";".join(pieces))
    _, too_long = bp.parse_override("code.top_k=SENTINEL-7Q;" * 200)
    _, thinking = bp.apply_thinking_rule("code", {"enable_thinking": True})
    warnings += too_long + thinking
    # The file and context warnings are produced by the loader and the context check (later
    # tasks of the plan); their shape is the same: a role and, at most, a key.
    warnings += [
        bp.Warning("", "", "file_unreadable"),
        bp.Warning("", "", "file_bad_version"),
        bp.Warning("", "", "file_too_large"),
        bp.Warning("code", "", "context_estimated"),
        bp.Warning("code", "", "context_overflow"),
        bp.Warning("", "", "file_busy"),
        bp.Warning("", "", "file_write_failed"),
    ]
    return warnings


@pytest.mark.parametrize("lang", ["es", "en"])
def test_rendered_warnings_hide_sentinels(lang, reload_config):
    reload_config(LOCAL_DELEGATE_LANG=lang)
    i18n.reset()
    assert i18n.lang() == lang
    warnings = _sentinel_warnings()
    assert {w.code for w in warnings} == set(bp.WARNING_CODES)
    for warning in warnings:
        text = bp.warning_text(warning)
        assert text == i18n.t_lang(lang, PREFIX + warning.code, role=warning.role, key=warning.key)
        assert not text.startswith(PREFIX), text  # the key exists: this is a real text
        for sentinel in SENTINELS:
            assert sentinel not in text, (warning.code, text)
