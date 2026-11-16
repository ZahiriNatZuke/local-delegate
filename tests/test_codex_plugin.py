"""Issue #668: the Claude Code plugin imported into Codex, and what Codex reads of a ``hooks.json``.

The fixtures of ``tests/fixtures/codex_plugin`` were loaded as plugins in a real Codex CLI 0.169.0
(app-server ``hooks/list``, temporary ``CODEX_HOME``): ``hooks_codex_native`` listed its two hooks
with no warning; ``hooks_modules`` and the packaged Claude ``hooks.json`` gave ``unknown field
`modules``` and zero hooks; ``hooks_unknown_type`` gave ``unknown variant `http``` and zero hooks;
``hooks_args_user_config`` loaded one hook whose command is ``${user_config.ld_bin}``, without its
arguments. These tests pin the validator to those observations.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from conftest import make_home, snapshot
from test_checks import make_ctx, result_for

from local_delegate import checks, codex_plugin, install

FIXTURES = Path(__file__).parent / "fixtures" / "codex_plugin"
PACKAGED_PLUGIN = install.resources_dir() / "claude-plugin" / "local-delegate"


def _load(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _reasons(findings) -> set[tuple[str, str, str]]:
    return {(f.effect, f.where, f.reason) for f in findings}


# --- The validator against the fixtures --------------------------------------------------------
def test_the_codex_native_fixture_is_read_whole():
    assert codex_plugin.check_hooks_file(_load("hooks_codex_native")) == []


def test_modules_rejects_the_whole_file():
    findings = codex_plugin.check_hooks_file(_load("hooks_modules"))
    assert _reasons(findings) == {(codex_plugin.REJECTED, "modules", "unknown_top_key")}
    assert codex_plugin.rejected(findings)


def test_the_packaged_claude_hooks_file_is_rejected_by_codex_because_of_modules():
    """The repro of #668: the file Claude Code reads is not one Codex reads."""
    data = json.loads((PACKAGED_PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    findings = codex_plugin.check_hooks_file(data)
    rejected = [f for f in findings if f.effect == codex_plugin.REJECTED]
    assert [(f.where, f.reason) for f in rejected] == [("modules", "unknown_top_key")]
    # Without `modules` it would still not work: every handler loses `args` and keeps
    # `${user_config.ld_bin}` unexpanded.
    dropped = {f.reason for f in findings if f.effect == codex_plugin.DROPPED}
    assert dropped == {"unknown_field", "claude_user_config"}


def test_args_and_user_config_are_dropped_not_rejected():
    findings = codex_plugin.check_hooks_file(_load("hooks_args_user_config"))
    where = "hooks.UserPromptSubmit[0].hooks[0]"
    assert _reasons(findings) == {
        (codex_plugin.DROPPED, f"{where}.args", "unknown_field"),
        (codex_plugin.DROPPED, f"{where}.command", "claude_user_config"),
    }
    assert not codex_plugin.rejected(findings)


def test_an_unknown_handler_type_rejects_the_file():
    findings = codex_plugin.check_hooks_file(_load("hooks_unknown_type"))
    assert _reasons(findings) == {
        (codex_plugin.REJECTED, "hooks.UserPromptSubmit[0].hooks[0].type", "unknown_type")
    }


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ([], {(codex_plugin.REJECTED, "$", "not_an_object")}),
        ({"hooks": []}, {(codex_plugin.REJECTED, "hooks", "not_an_object")}),
        ({"hooks": {"Stop": {}}}, {(codex_plugin.REJECTED, "hooks.Stop", "not_a_list")}),
        # Claude Code's `Notification` is not a Codex event: ignored, without a warning.
        (
            {"hooks": {"Notification": []}},
            {(codex_plugin.DROPPED, "hooks.Notification", "unknown_event")},
        ),
        (
            {"hooks": {"Stop": [{"hooks": [], "x": 1}]}},
            {(codex_plugin.DROPPED, "hooks.Stop[0].x", "unknown_field")},
        ),
        ({"description": "d", "hooks": {}}, set()),
        ({}, set()),
    ],
)
def test_shapes(data, expected):
    assert _reasons(codex_plugin.check_hooks_file(data)) == expected


def test_every_codex_event_and_handler_type_is_accepted():
    """Control: the lists accept what Codex 0.169.0 declares, so a finding means something."""
    handlers = [
        {
            "type": "command",
            "command": "x",
            "commandWindows": "y",
            "timeout": 1,
            "async": False,
            "statusMessage": "s",
            "additionalContextLimit": 0,
        },
        {"type": "mcp_tool", "server": "s", "tool": "t", "input": {}, "timeout": 1},
        {"type": "prompt"},
        {"type": "agent"},
    ]
    data = {
        "hooks": {
            event: [{"matcher": ".*", "hooks": handlers}] for event in codex_plugin.HOOK_EVENTS
        }
    }
    assert codex_plugin.check_hooks_file(data) == []


# --- The doctor check ---------------------------------------------------------------------------
def _cache_plugin(
    home: Path, hooks: Path | None, *, enabled: bool | str | None, market="local-delegate"
):
    """What `codex plugin add` leaves: the copy in the cache and the entry in `config.toml`.

    ``enabled``: ``True``/``False`` write ``enabled = …``; ``"no-key"`` writes the table without
    the key (Codex takes it as enabled); ``None`` writes no entry at all (only in the cache).
    """
    root = home / ".codex" / "plugins" / "cache" / market / "local-delegate" / "0.52.0"
    shutil.copytree(PACKAGED_PLUGIN, root)
    target = root / "hooks" / "hooks.json"
    if hooks is None:
        target.unlink()
    else:
        shutil.copyfile(hooks, target)
    if enabled is not None:
        config = home / ".codex" / "config.toml"
        text = config.read_text(encoding="utf-8") if config.exists() else ""
        text += f'\n[plugins."local-delegate@{market}"]\n'
        if enabled != "no-key":
            text += f"enabled = {'true' if enabled else 'false'}\n"
        config.write_text(text, encoding="utf-8")
    return root


def test_the_check_is_registered_in_scaffold():
    check = next(c for c in checks.CHECKS if c.id == "codex.plugin")
    assert check.group == "scaffold"


def test_no_plugin_in_codex_is_ok(tmp_path):
    home = make_home(tmp_path)
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.OK
    assert result.fix_hint == ""


def test_no_codex_is_unknown_like_every_absent_client(tmp_path):
    home = make_home(tmp_path, codex=False)
    assert result_for("codex.plugin", make_ctx(home)).status == checks.UNKNOWN


def test_the_imported_claude_plugin_enabled_is_a_warning_that_names_modules(tmp_path):
    """#668: enabled + cached + exit 0 is not loaded; doctor says why and how to undo it."""
    home = make_home(tmp_path)
    _cache_plugin(home, PACKAGED_PLUGIN / "hooks" / "hooks.json", enabled=True)
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.WARN
    assert "modules" in result.detail
    assert "local-delegate@local-delegate" in result.detail
    assert "Claude Code" in result.detail  # `modules` is named as the Claude mod
    assert result.fix_hint == "codex plugin remove local-delegate@local-delegate"


def test_a_rejection_without_modules_does_not_blame_the_claude_plugin(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_unknown_type.json", enabled=True)
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.WARN
    assert ".type" in result.detail
    assert "Claude Code" not in result.detail


def test_the_same_plugin_disabled_is_ok_but_still_said(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_modules.json", enabled=False)
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.OK
    assert "modules" in result.detail


def test_a_cache_without_config_entry_counts_as_not_enabled(tmp_path):
    """Codex loads only the plugins of `config.toml` (`configured_plugins` in `loader.rs`)."""
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_modules.json", enabled=None)
    assert result_for("codex.plugin", make_ctx(home)).status == checks.OK


def test_an_entry_without_enabled_counts_as_enabled(tmp_path):
    """`plugin.enabled.unwrap_or(true)` in `loader.rs`: the table alone enables it."""
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_modules.json", enabled="no-key")
    assert result_for("codex.plugin", make_ctx(home)).status == checks.WARN


def test_a_non_text_type_is_a_rejection_not_a_crash(tmp_path):
    data = {"hooks": {"Stop": [{"hooks": [{"type": ["command"]}, {"type": {"a": 1}}]}]}}
    reasons = {f.reason for f in codex_plugin.check_hooks_file(data)}
    assert reasons == {"unknown_type"}
    home = make_home(tmp_path)
    root = _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=True)
    (root / "hooks" / "hooks.json").write_text(json.dumps(data), encoding="utf-8")
    assert result_for("codex.plugin", make_ctx(home)).status == checks.WARN


def test_a_deeply_nested_hooks_file_is_a_rejection_not_a_crash(tmp_path):
    home = make_home(tmp_path)
    root = _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=True)
    (root / "hooks" / "hooks.json").write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    assert result_for("codex.plugin", make_ctx(home)).status == checks.WARN


def test_a_hooks_file_that_is_not_utf8_is_a_rejection(tmp_path):
    home = make_home(tmp_path)
    root = _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=True)
    (root / "hooks" / "hooks.json").write_bytes(b'{"hooks": {"\xff": []}}')
    assert result_for("codex.plugin", make_ctx(home)).status == checks.WARN


def test_an_unreadable_hooks_file_is_unknown_only_when_enabled(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=True, market="on")
    _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=False, market="off")
    real = Path.read_text

    def denied(self, *args, **kwargs):
        if self.name == "hooks.json":
            raise PermissionError(13, "Permission denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    plugins = {p.marketplace: p for p in codex_plugin.cached_plugins(home / ".codex")}
    assert checks._codex_plugin_result(plugins["on"]).status == checks.UNKNOWN
    assert checks._codex_plugin_result(plugins["off"]).status == checks.OK


def test_a_file_where_a_folder_is_expected_is_skipped(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_modules.json", enabled=True, market="b")
    cache = home / ".codex" / "plugins" / "cache"
    (cache / "a-file").write_text("x", encoding="utf-8")
    (cache / "c").mkdir()
    (cache / "c" / "local-delegate").write_text("x", encoding="utf-8")
    assert [p.marketplace for p in codex_plugin.cached_plugins(home / ".codex")] == ["b"]
    assert result_for("codex.plugin", make_ctx(home)).status == checks.WARN


def test_more_than_three_places_are_cut(tmp_path):
    handler = {"type": "command", "command": "x", "a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    data = {"hooks": {"Stop": [{"hooks": [handler]}]}}
    home = make_home(tmp_path)
    root = _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=True)
    (root / "hooks" / "hooks.json").write_text(json.dumps(data), encoding="utf-8")
    detail = result_for("codex.plugin", make_ctx(home)).detail
    assert "hooks[0].c" in detail and "hooks[0].d" not in detail
    assert "y 2 más" in detail


def test_an_odd_marketplace_name_gets_no_command_to_paste(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_modules.json", enabled=True, market="x & y")
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.WARN
    assert result.fix_hint == ""


def test_dropped_arguments_are_a_warning(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_args_user_config.json", enabled=True)
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.WARN
    assert ".args" in result.detail
    assert result.fix_hint.startswith("codex plugin remove ")


def test_the_codex_native_format_is_ok_and_does_not_claim_it_loaded(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=True)
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.OK
    assert "/hooks" in result.detail  # the real load is confirmed in Codex, not here


def test_an_invalid_json_hooks_file_is_a_warning(tmp_path):
    home = make_home(tmp_path)
    root = _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=True)
    (root / "hooks" / "hooks.json").write_text("{nope", encoding="utf-8")
    assert result_for("codex.plugin", make_ctx(home)).status == checks.WARN


def test_no_hooks_file_is_ok(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, None, enabled=True)
    assert result_for("codex.plugin", make_ctx(home)).status == checks.OK


def test_the_worst_of_two_marketplaces_wins(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_codex_native.json", enabled=True, market="a")
    _cache_plugin(home, FIXTURES / "hooks_modules.json", enabled=True, market="b")
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.WARN
    assert "local-delegate@b" in result.detail
    assert "local-delegate@a" not in result.detail


def test_a_broken_config_toml_does_not_break_the_check(tmp_path):
    """Enabled first, then broken: the `ok` comes from not reading it, not from the entry."""
    home = make_home(tmp_path)
    _cache_plugin(home, FIXTURES / "hooks_modules.json", enabled=True)
    assert result_for("codex.plugin", make_ctx(home)).status == checks.WARN
    config = home / ".codex" / "config.toml"
    config.write_text(config.read_text(encoding="utf-8") + "\n[[[", encoding="utf-8")
    assert result_for("codex.plugin", make_ctx(home)).status == checks.OK


def test_the_check_only_reads(tmp_path):
    home = make_home(tmp_path)
    _cache_plugin(home, PACKAGED_PLUGIN / "hooks" / "hooks.json", enabled=True)
    before = snapshot(home)
    result_for("codex.plugin", make_ctx(home))
    assert snapshot(home) == before


def test_the_english_text_names_the_same_things(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    home = make_home(tmp_path)
    _cache_plugin(home, PACKAGED_PLUGIN / "hooks" / "hooks.json", enabled=True)
    result = result_for("codex.plugin", make_ctx(home))
    assert result.status == checks.WARN
    assert "rejects" in result.detail and "modules" in result.detail


# --- What `install` gives Codex -----------------------------------------------------------------
def test_install_for_codex_writes_no_plugin(tmp_path):
    """`install` gives Codex the MCP entry and `AGENTS.md`, never the Claude plugin (#668)."""
    opts = install.Options(
        home=tmp_path,
        components={"hooks", "skill", "memory", "mcp"},
        targets={"codex"},
        python_exe="python3",
        use_cli=False,
    )
    assert install.apply(install.plan_install(opts), dry_run=False, out=lambda *_a: None) == 0
    codex_dir = tmp_path / ".codex"
    assert not (codex_dir / "plugins").exists()
    assert codex_plugin.cached_plugins(codex_dir) == []
    config = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert "[plugins." not in config and "[marketplaces." not in config
