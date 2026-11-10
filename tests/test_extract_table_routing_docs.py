"""#586: every surface that describes the routing, `_local_delegate` or the log names the new rule.

REQ-032 of the SDD change `extract-cross-fill-and-routing`: a release touches three places
(CHANGELOG, README and `docs/wiki/`), and the surfaces are counted by the program, not by eye.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VARIABLE = "LOCAL_DELEGATE_EXTRACT_TABLE_LONG"
FIELD = "role_reason"
TEXT_KEY = "mcp.warning.extract_role_reason_table"

#: (file, names it must carry).
SURFACES = {
    "README.md": (VARIABLE, FIELD),
    "docs/wiki/Tools.md": (VARIABLE, FIELD),
    "docs/wiki/Configuration.md": (VARIABLE, FIELD),
    "CHANGELOG.md": (VARIABLE, FIELD),
    "docs/wiki/Architecture.md": (VARIABLE, FIELD, "tabla"),
    "docs/recipes/claude-code-integration.md": ("tabla",),
    "docs/wiki/Savings-and-metrics.md": (FIELD, VARIABLE),
}


def _read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        pytest.skip(f"{relative} is not in the tree")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", sorted(SURFACES))
def test_each_surface_names_the_rule(relative):
    text = _read(relative)
    missing = [name for name in SURFACES[relative] if name not in text]
    assert not missing, f"{relative} does not name {missing}"


def test_the_changelog_entry_is_newer_than_0_50_0():
    """The rule shipped after 0.50.0: in [Unreleased] before the release, in 0.51.0 or later after."""
    text = _read("CHANGELOG.md")
    newer = text.split("## [Unreleased]", 1)[1].split("\n## [0.50.0]", 1)[0]
    assert VARIABLE in newer and FIELD in newer
    assert "#586" in newer


def test_the_role_field_sits_next_to_routing_in_the_log_fields():
    text = _read("docs/wiki/Savings-and-metrics.md")
    assert text.index('routing: "affinity"') < text.index('role_reason: "table"')


@pytest.mark.parametrize("language", ["es", "en"])
def test_the_text_key_exists_in_both_languages(language):
    catalog = ROOT / "src" / "local_delegate" / "resources" / "i18n" / language / "mcp.json"
    texts = json.loads(catalog.read_text(encoding="utf-8"))
    assert TEXT_KEY in texts
    assert VARIABLE + "=0" in texts[TEXT_KEY]
