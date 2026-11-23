"""REQ-020: every surface that documents `local_extract` describes the new location value.

The lines of a location field are the program's, as a list of `{name, start, end}`, with
`located`, `unlocated` and `type_mismatch_keys`; `lines_unverified`, `outline_copies` and
`diff_files` are no longer keys of extract (decision D6).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from local_delegate import server

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "src" / "local_delegate" / "resources"


def _unreleased() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    start = text.index("## [Unreleased]")
    return text[start : text.index("\n## [", start + 1)]


def _readme_extract_row() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    return next(line for line in text.splitlines() if line.startswith("| `local_extract` |"))


def _wiki_extract() -> str:
    text = (ROOT / "docs" / "wiki" / "Tools.md").read_text(encoding="utf-8")
    start = text.index("- **Tipo por campo**")
    return text[start : text.index("- **Valor de otra fila**", start)]


SURFACES = {
    "docstring": lambda: inspect.getdoc(server.local_extract),
    "changelog": _unreleased,
    "readme": _readme_extract_row,
    "wiki": _wiki_extract,
}


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_each_surface_names_the_new_keys(surface):
    text = SURFACES[surface]()
    for key in ("located", "unlocated", "type_mismatch_keys"):
        assert re.search(rf"`[^`]*\b{key}\b", text), f"{surface} does not name `{key}`"
    assert "start" in text and "end" in text, f"{surface} does not show the new shape"


@pytest.mark.parametrize("surface", ["docstring", "readme"])
def test_no_surface_offers_the_retired_keys(surface):
    text = SURFACES[surface]()
    for key in ("outline_copies", "lines_unverified", "diff_files"):
        assert key not in text, f"{surface} still offers `{key}`"


def test_the_changelog_marks_the_change_as_breaking():
    text = _unreleased()
    section = text[text.index("### Cambiado (incompatible)") :]
    assert "0.54.0" in section
    assert '"funciones_con_lineas": [{"name"' in section, "the example after the change"


@pytest.mark.parametrize(
    "path",
    [
        RESOURCES / "skills" / "local-delegation" / "SKILL.md",
        RESOURCES / "skills" / "local-delegation" / "SKILL.en.md",
        RESOURCES / "memory" / "local-delegate.md",
        RESOURCES / "memory" / "local-delegate.en.md",
    ],
    ids=lambda p: p.name,
)
def test_the_skill_and_the_memory_say_the_lines_are_the_programs(path):
    text = path.read_text(encoding="utf-8")
    assert "unlocated" in text and "grep -n" in text
    assert "lines_unverified" not in text
    assert "{name, start, end}" in text or '{"name", "start", "end"}' in text
