"""The Claude Code plugin that ships inside the package (SDD claude-plugin-and-mods, F1-package).

REQ-001: the package carries the plugin folder and a marketplace that publishes it, with the
package version. REQ-002: `hooks.json` declares the same events and filters that 0.39 writes into
`settings.json`. REQ-003 (declarative half): every entry runs the uv tool interpreter with
`-I -m local_delegate.hook <name>`, the path T0 measured as the only one that never blocks
(`.sdd/changes/claude-plugin-and-mods/evidence/T0.md`, route B).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from local_delegate import install

ROOT = Path(__file__).parents[1]
MARKETPLACE_DIR = install.resources_dir() / "claude-plugin"
PLUGIN_DIR = MARKETPLACE_DIR / "local-delegate"
REPO_MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"

#: Script of the settings delivery → subcommand of `local-delegate hook`, per (event, matcher).
#: The read script serves two matchers in settings (Read and other MCP's read tools); the plugin
#: names them apart so the hook knows which surface it is looking at.
HOOK_NAMES = {
    ("UserPromptSubmit", None): "prompt",
    ("PreToolUse", "mcp__local-delegate__.*"): "record-call",
    ("PreToolUse", "Read"): "read",
    ("PreToolUse", "mcp__.+__(read_[a-z_]*|get_file_contents)"): "mcp-read",
    ("PreToolUse", "Bash|PowerShell"): "shell",
    ("SubagentStart", None): "subagent-start",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pyproject_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def _hook_entries() -> list[tuple[str, str | None, dict]]:
    """(event, matcher, hook) for every hook in `hooks.json`."""
    data = _json(PLUGIN_DIR / "hooks" / "hooks.json")
    out = []
    for event, groups in data["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                out.append((event, group.get("matcher"), hook))
    return out


def test_plugin_version_matches_package():
    version = _pyproject_version()
    assert _json(PLUGIN_DIR / ".claude-plugin" / "plugin.json")["version"] == version
    for marketplace in (MARKETPLACE_DIR / ".claude-plugin" / "marketplace.json", REPO_MARKETPLACE):
        entries = _json(marketplace)["plugins"]
        assert [e["version"] for e in entries] == [version], marketplace


def test_marketplace_points_at_plugin_folder():
    """Both marketplaces publish the same folder: the one inside the package."""
    plugin = _json(PLUGIN_DIR / ".claude-plugin" / "plugin.json")
    assert plugin["name"] == "local-delegate"
    # `validate --strict` fails on warnings; these two are the ones T0 saw.
    assert plugin["author"]["name"]
    for marketplace in (MARKETPLACE_DIR / ".claude-plugin" / "marketplace.json", REPO_MARKETPLACE):
        data = _json(marketplace)
        assert data["name"] == "local-delegate"
        assert data["owner"]["name"]
        (entry,) = data["plugins"]
        assert entry["name"] == plugin["name"]
        assert entry["description"]
        source = entry["source"]
        assert source.startswith("./"), source
        base = marketplace.parent.parent
        assert (base / source).resolve() == PLUGIN_DIR.resolve(), marketplace


def test_no_bin_at_plugin_root():
    """A `bin/` at the root would go to the PATH of the Bash tool (decision 1)."""
    assert PLUGIN_DIR.is_dir()
    assert not (PLUGIN_DIR / "bin").exists()


def test_hooks_json_matches_settings_delivery_0_39():
    expected = {
        (event, matcher)
        for _script, event, matcher in (
            *install._HOOK_EVENTS,
            install._READ_HOOK,
            install._MCP_READ_HOOK,
            install._SHELL_HOOK,
        )
    }
    declared = [(event, matcher) for event, matcher, _hook in _hook_entries()]
    assert len(declared) == len(set(declared)), "an event/matcher pair is declared twice"
    assert set(declared) == expected
    assert set(HOOK_NAMES) == expected
    for event, matcher, hook in _hook_entries():
        assert hook["args"][-1] == HOOK_NAMES[(event, matcher)], (event, matcher)


def test_every_hook_entry_is_fail_open():
    """Route B of T0: the interpreter of the uv tool env runs an always-exit-0 module.

    `local-delegate hook …` on 0.39 exits with 2 (argparse) and 2 blocks the prompt; with
    `-I -m local_delegate.hook` an old env exits 1 (`No module named`), a missing interpreter fails
    to start, and both let the call through. A shell form or the console script would lose that.
    """
    manifest = _json(PLUGIN_DIR / ".claude-plugin" / "plugin.json")
    ld_bin = manifest["userConfig"]["ld_bin"]
    assert ld_bin["type"] == "string"
    # A `default` does not fill `${user_config.*}` (T0): `install` always passes `--config`.
    assert ld_bin["required"] is True
    assert "default" not in ld_bin

    entries = _hook_entries()
    assert len(entries) == len(HOOK_NAMES)
    for event, matcher, hook in entries:
        where = (event, matcher)
        assert hook["type"] == "command", where
        assert hook["command"] == "${user_config.ld_bin}", where
        assert hook["args"][:3] == ["-I", "-m", "local_delegate.hook"], where
        assert len(hook["args"]) == 4, where
        assert "shell" not in hook, where
        assert "onFailure" not in hook, where  # T0: it does not turn exit 2 into a pass
        assert isinstance(hook.get("timeout"), int) and 0 < hook["timeout"] <= 60, where


@pytest.mark.parametrize(
    "path",
    [
        PLUGIN_DIR / ".claude-plugin" / "plugin.json",
        PLUGIN_DIR / "hooks" / "hooks.json",
        MARKETPLACE_DIR / ".claude-plugin" / "marketplace.json",
        REPO_MARKETPLACE,
    ],
    ids=lambda p: p.relative_to(ROOT).as_posix(),
)
def test_plugin_files_are_utf8_json_without_bom(path: Path):
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    json.loads(raw.decode("utf-8"))
