"""vision-default-qwen36: the vision role defaults to `qwen36-35b-a3b-vision` (REQ-001, REQ-005).

The measurement of #699 (2026-11-23): `qwen36-35b-a3b` with `--mmproj` made up 0 of 9 layout
defects, `gemma4-12b` 5 of 9. `gemma4-12b` stays as the documented light alternative.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from local_delegate import config

ROOT = Path(__file__).resolve().parents[1]
NEW = "qwen36-35b-a3b-vision"
LIGHT = "gemma4-12b"
SKILLS = ROOT / "src" / "local_delegate" / "resources" / "skills" / "local-delegation"


def test_the_vision_default_is_qwen36_with_mmproj():
    # The suite runs without any package variable (conftest), so this is the default.
    assert config.MODEL_VISION == NEW


def test_the_light_alternative_is_one_constant():
    assert config.MODEL_VISION_LIGHT == LIGHT
    assert config.MODEL_VISION_LIGHT != config.MODEL_VISION


def test_the_variable_still_chooses_the_light_one(reload_config):
    reload_config(LOCAL_DELEGATE_MODEL_VISION=LIGHT)
    assert config.MODEL_VISION == LIGHT


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "docs/wiki/Configuration.md",
        "docs/wiki/Tools.md",
        "docs/wiki/Troubleshooting.md",
        "docs/recipes/llama-swap-blackwell.md",
        "docs/recipes/llama-swap-vision.md",
    ],
)
def test_the_docs_name_the_new_default_and_the_light_one(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert NEW in text, relative
    assert "LOCAL_DELEGATE_MODEL_VISION" in text, relative
    assert LIGHT in text, relative


@pytest.mark.parametrize("relative", ["README.md", "docs/wiki/Configuration.md"])
def test_the_variable_table_shows_the_new_default(relative):
    rows = [
        line
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if line.startswith("| `LOCAL_DELEGATE_MODEL_VISION`")
    ]
    assert rows and all(f"`{NEW}`" in row for row in rows), rows


@pytest.mark.parametrize("name", ["SKILL.md", "SKILL.en.md"])
def test_the_skill_names_the_default_and_how_to_choose_the_light_one(name):
    text = (SKILLS / name).read_text(encoding="utf-8")
    assert NEW in text
    assert f"LOCAL_DELEGATE_MODEL_VISION={LIGHT}" in text


def test_the_changelog_has_the_migration_note():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert NEW in text
    assert f"LOCAL_DELEGATE_MODEL_VISION={LIGHT}" in text
