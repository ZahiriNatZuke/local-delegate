"""`i18n.override(lang)` (SDD cli-completion, REQ-042)."""

from __future__ import annotations

import argparse

import pytest

from local_delegate import cli, i18n


def test_override_switches_lang_t_and_argparse():
    assert i18n.lang() == "es"
    with i18n.override("en"):
        assert i18n.lang() == "en"
        assert i18n.t("cli.help.backend_params") == i18n.t_lang("en", "cli.help.backend_params")
        assert i18n.argparse_gettext("show this help message and exit") == (
            "show this help message and exit"
        )
    assert i18n.lang() == "es"
    assert i18n.argparse_gettext("show this help message and exit") == i18n.t_lang(
        "es", "argparse.help_help"
    )


def test_override_restores_after_an_exception():
    def fail_inside() -> None:
        with i18n.override("en"):
            assert i18n.lang() == "en"
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        fail_inside()
    assert i18n.lang() == "es"


def test_overrides_nest():
    with i18n.override("en"):
        with i18n.override("es"):
            assert i18n.lang() == "es"
        assert i18n.lang() == "en"
    assert i18n.lang() == "es"


def test_override_does_not_touch_the_cache_of_current():
    resolution = i18n.current()
    with i18n.override("en"):
        assert i18n.current() is resolution
        assert i18n.current().lang == "es"
    assert i18n.current() is resolution


def test_override_rejects_an_unknown_language():
    with pytest.raises(ValueError, match="fr"):
        i18n.override("fr").__enter__()
    assert i18n.lang() == "es"


def test_override_nests_with_the_argparse_scaffold_of_the_cli():
    """The parser built inside both blocks has its `-h` help in the overridden language."""
    saved = (argparse._, argparse.ngettext)
    with i18n.override("en"), cli._argparse_in_language():
        parser = cli.build_parser()
    help_action = next(a for a in parser._actions if "-h" in a.option_strings)
    assert help_action.help == "show this help message and exit"
    assert (argparse._, argparse.ngettext) == saved
    assert i18n.lang() == "es"
