"""Issue #669: `install`, `update` and `uninstall` of the Codex hooks in `~/.codex/hooks.json`.

Codex keeps the approval of each handler under its position (`"<path>:<event>:<group>:<handler>"`)
and a hash of what it runs, so these tests watch positions as much as content: a group of the
user's must never change index, and none of ours may be added where there was none.
"""

from __future__ import annotations

import codecs
import copy
import json
from pathlib import Path

import pytest

from local_delegate import checks, claude_plugin, codex_hooks, codex_plugin, install, update
from local_delegate.checks import Result
from local_delegate.i18n import t

PYTHON = "C:/tools/local-delegate-mcp/Scripts/python.exe"
OLD_PYTHON = "C:/old/local-delegate-mcp/Scripts/python.exe"

FOREIGN_PROMPT = {"hooks": [{"type": "command", "command": "echo prompt", "timeout": 5}]}
FOREIGN_BASH = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo bash"}]}


def _ours(name: str, python: str = PYTHON) -> dict:
    spec = next(spec for spec in codex_hooks.SPECS if spec.name == name)
    return codex_hooks.group(spec, python, "win32")


def _merge(data: dict, python: str = PYTHON) -> tuple[dict, list[str]]:
    return codex_hooks.merge(data, python, "win32")


# --- merge and strip, pure -----------------------------------------------------------------------
def test_merge_into_nothing_gives_both_and_a_file_codex_reads():
    data, changed = _merge({})
    assert changed == [spec.name for spec in codex_hooks.SPECS]
    assert changed[:2] == ["codex-prompt", "codex-subagent-start"]
    assert data == {"hooks": codex_hooks.entries(PYTHON, "win32")}
    assert codex_plugin.check_hooks_file(data) == []


def test_merge_goes_after_the_users_groups_and_moves_none():
    data = {
        "description": "mine",
        "hooks": {"UserPromptSubmit": [FOREIGN_PROMPT], "PreToolUse": [FOREIGN_BASH]},
    }
    before = copy.deepcopy(data)
    merged, _ = _merge(data)
    assert merged["description"] == "mine"
    # The user's group stays first; ours (`codex-tool-guard` #670, `codex-mcp-call` #669) go
    # behind it, in the order of `SPECS`.
    assert merged["hooks"]["PreToolUse"][0] == before["hooks"]["PreToolUse"][0]
    assert [codex_hooks.our_name(g) for g in merged["hooks"]["PreToolUse"][1:]] == [
        spec.name for spec in codex_hooks.SPECS if spec.event == "PreToolUse"
    ]
    assert merged["hooks"]["UserPromptSubmit"][0] == FOREIGN_PROMPT
    assert codex_hooks.our_name(merged["hooks"]["UserPromptSubmit"][1]) == "codex-prompt"


def test_second_merge_changes_nothing():
    data, _ = _merge({"hooks": {"UserPromptSubmit": [FOREIGN_PROMPT]}})
    again = copy.deepcopy(data)
    assert _merge(again) == (data, [])


def test_an_old_group_of_ours_is_rewritten_in_its_index():
    data = {
        "hooks": {
            "UserPromptSubmit": [_ours("codex-prompt", OLD_PYTHON), FOREIGN_PROMPT],
            "SubagentStart": [_ours("codex-subagent-start")],
            "PreToolUse": [_ours("codex-mcp-call")],
        }
    }
    merged, changed = _merge(data)
    # Of the two hooks of #669 in `data`, only the old one is rewritten (the rest are added).
    assert [n for n in changed if n in {"codex-prompt", "codex-subagent-start"}] == ["codex-prompt"]
    assert merged["hooks"]["UserPromptSubmit"] == [_ours("codex-prompt"), FOREIGN_PROMPT]


def test_a_duplicate_with_groups_behind_becomes_a_hole_and_at_the_end_is_dropped():
    data = {
        "hooks": {
            "UserPromptSubmit": [_ours("codex-prompt"), _ours("codex-prompt"), FOREIGN_PROMPT],
            "SubagentStart": [_ours("codex-subagent-start"), _ours("codex-subagent-start")],
        }
    }
    merged, _ = _merge(data)
    assert merged["hooks"]["UserPromptSubmit"] == [
        _ours("codex-prompt"),
        codex_hooks.EMPTY_GROUP,
        FOREIGN_PROMPT,
    ]
    assert merged["hooks"]["SubagentStart"] == [_ours("codex-subagent-start")]


def test_a_group_of_ours_under_another_event_is_vacated():
    data = {"hooks": {"Stop": [_ours("codex-prompt"), FOREIGN_PROMPT]}}
    merged, _ = _merge(data)
    assert merged["hooks"]["Stop"] == [codex_hooks.EMPTY_GROUP, FOREIGN_PROMPT]
    assert merged["hooks"]["UserPromptSubmit"] == [_ours("codex-prompt")]


def test_a_group_with_command_windows_is_the_users():
    mine = {
        "hooks": [
            {
                "type": "command",
                "command": f'"{PYTHON}" -I -m local_delegate.hook codex-prompt',
                "commandWindows": "echo mine",
            }
        ]
    }
    merged, _ = _merge({"hooks": {"UserPromptSubmit": [mine]}})
    assert merged["hooks"]["UserPromptSubmit"] == [mine, _ours("codex-prompt")]


def test_a_file_codex_rejects_is_not_merged():
    with pytest.raises(codex_hooks.RejectedFile):
        _merge({"hooks": {}, "modules": []})


def test_strip_keeps_every_index_of_the_user():
    data = {
        "hooks": {
            "UserPromptSubmit": [_ours("codex-prompt"), FOREIGN_PROMPT],
            "SubagentStart": [_ours("codex-subagent-start")],
            "PreToolUse": [FOREIGN_BASH],
        }
    }
    stripped, removed = codex_hooks.strip(data)
    assert removed == 2
    assert stripped["hooks"] == {
        "UserPromptSubmit": [codex_hooks.EMPTY_GROUP, FOREIGN_PROMPT],
        "PreToolUse": [FOREIGN_BASH],
    }
    assert codex_plugin.check_hooks_file(stripped) == []


def test_strip_then_merge_gives_the_same_indices_and_no_holes():
    original = {"hooks": {"UserPromptSubmit": [_ours("codex-prompt"), FOREIGN_PROMPT]}}
    original, _ = _merge(original)
    stripped, _ = codex_hooks.strip(copy.deepcopy(original))
    again, _ = _merge(stripped)
    assert again == original
    assert codex_hooks.EMPTY_GROUP not in again["hooks"]["UserPromptSubmit"]


def test_strip_of_a_hole_of_the_user_leaves_it():
    """Control: `strip` vacates groups by our command, not any empty group it finds."""
    data = {"hooks": {"UserPromptSubmit": [{"hooks": []}, FOREIGN_PROMPT]}}
    assert codex_hooks.strip(copy.deepcopy(data)) == (data, 0)


# --- install, on a simulated HOME ----------------------------------------------------------------
@pytest.fixture
def home(tmp_path) -> Path:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    return home


@pytest.fixture
def ld_bin(tmp_path) -> claude_plugin.LdBin:
    python = tmp_path / "uv-tools" / "local-delegate-mcp" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    return claude_plugin.LdBin(str(python), None)


def _options(home: Path, ld_bin, **kwargs) -> install.Options:
    values = {
        "components": {"hooks"},
        "targets": {"codex"},
        "python_exe": "python",
        "use_cli": False,
        "write_language": False,
        "claude_ld_bin": ld_bin,
        # The tests compare with `_ours`, which spells the Windows command.
        "platform": "win32",
    }
    values.update(kwargs)
    return install.Options(home=home, **values)


def _apply(actions, *, dry_run=False) -> tuple[int, str]:
    lines: list[str] = []
    code = install.apply(
        actions, dry_run=dry_run, out=lambda *a: lines.append(" ".join(map(str, a)))
    )
    return code, "\n".join(lines)


def _hooks_file(home: Path) -> Path:
    return home / ".codex" / "hooks.json"


def _read(home: Path) -> dict:
    return json.loads(_hooks_file(home).read_text("utf-8"))


def test_install_writes_both_hooks_and_a_second_run_writes_nothing(home, ld_bin):
    code, _ = _apply(install.plan_install(_options(home, ld_bin)))
    assert code == 0
    assert _read(home) == {"hooks": codex_hooks.entries(ld_bin.path, "win32")}
    first = _hooks_file(home).read_bytes()
    code, out = _apply(install.plan_install(_options(home, ld_bin)))
    assert code == 0 and _hooks_file(home).read_bytes() == first
    assert not _hooks_file(home).with_suffix(".json.bak").exists()
    assert t("install.codex_hooks.up_to_date") in out


def test_install_keeps_the_users_file_its_line_ending_and_one_backup(home, ld_bin):
    users = {"hooks": {"UserPromptSubmit": [FOREIGN_PROMPT]}}
    raw = json.dumps(users, indent=2).replace("\n", "\r\n").encode()
    _hooks_file(home).write_bytes(raw)
    assert _apply(install.plan_install(_options(home, ld_bin)))[0] == 0
    written = _hooks_file(home).read_bytes()
    assert b"\r\n" in written and b"\n" not in written.replace(b"\r\n", b"")
    data = json.loads(written)
    assert data["hooks"]["UserPromptSubmit"][0] == FOREIGN_PROMPT
    backup = _hooks_file(home).with_suffix(".json.bak")
    assert backup.read_bytes() == raw
    _apply(
        install.plan_install(
            _options(home, ld_bin, claude_ld_bin=claude_plugin.LdBin(OLD_PYTHON, None))
        )
    )
    assert backup.read_bytes() == raw


@pytest.mark.parametrize(
    ("raw", "failed"),
    [
        # Codex rejects these whole: `install` says so and goes on (not a failure of its own, so
        # `update` does not fail on every run over a file of the user's like that).
        (codecs.BOM_UTF8 + b'{"hooks": {}}', False),
        (b'{"hooks": {}, "modules": []}', False),
        # Not a JSON object at all: like every other config `install` cannot read.
        (b"{ not json", True),
        (b"[]", True),
    ],
    ids=["bom", "rejected-key", "not-json", "not-object"],
)
def test_install_refuses_a_file_codex_would_reject_and_leaves_it(home, ld_bin, raw, failed):
    _hooks_file(home).write_bytes(raw)
    code, out = _apply(install.plan_install(_options(home, ld_bin)))
    assert (code != 0) is failed
    assert str(_hooks_file(home)) in out
    assert _hooks_file(home).read_bytes() == raw
    assert not _hooks_file(home).with_suffix(".json.bak").exists()


def test_update_over_a_file_codex_rejects_exits_zero_and_leaves_it(home, ld_bin):
    """The repair runs on any `warn`, a rejected file included: it must not make `update` fail."""
    raw = codecs.BOM_UTF8 + json.dumps({"hooks": {"UserPromptSubmit": [FOREIGN_PROMPT]}}).encode()
    _hooks_file(home).write_bytes(raw)
    results = [(_check("codex.hooks"), Result(checks.WARN, "x"))]
    actions, _ = update.plan_repairs(results, _update_opts(home, ld_bin))
    assert any(action.kind == "codex-hooks" for action in actions), "nothing planned: no proof"
    code, _ = _apply(actions)
    assert code == 0 and _hooks_file(home).read_bytes() == raw


def test_uninstall_takes_ours_out_of_a_file_with_a_bom_and_keeps_it(home, ld_bin):
    data, _ = _merge({"hooks": {"UserPromptSubmit": [FOREIGN_PROMPT]}}, ld_bin.path)
    _hooks_file(home).write_bytes(codecs.BOM_UTF8 + json.dumps(data).encode())
    code, _ = _apply(install.plan_uninstall(_options(home, ld_bin)))
    raw = _hooks_file(home).read_bytes()
    assert code == 0 and raw.startswith(codecs.BOM_UTF8)
    assert json.loads(raw.decode("utf-8-sig"))["hooks"] == {"UserPromptSubmit": [FOREIGN_PROMPT]}


def test_install_without_a_uv_tool_interpreter_writes_nothing(home):
    code, out = _apply(install.plan_install(_options(home, claude_plugin.LdBin(None, "editable"))))
    assert code == 0 and "editable" in out
    assert not _hooks_file(home).exists()


def test_an_interpreter_path_we_could_not_read_back_writes_nothing(home):
    """A quote in the path: the next run would not see its groups and would add them again."""
    odd = claude_plugin.LdBin("/opt/it's/python", None)
    code, out = _apply(install.plan_install(_options(home, odd, platform="linux")))
    assert code == 0 and "unreadable_path" in out
    assert not _hooks_file(home).exists()


def test_dry_run_prints_our_groups_and_writes_nothing(home, ld_bin):
    code, out = _apply(install.plan_install(_options(home, ld_bin)), dry_run=True)
    assert code == 0
    assert "local_delegate.hook codex-prompt" in out
    assert not _hooks_file(home).exists()


def test_install_for_claude_only_leaves_codex_alone(home, ld_bin):
    actions = install.plan_install(_options(home, ld_bin, targets={"claude"}))
    assert all(action.kind != "codex-hooks" for action in actions)


# --- uninstall -----------------------------------------------------------------------------------
def test_uninstall_of_a_file_install_created_deletes_it(home, ld_bin):
    _apply(install.plan_install(_options(home, ld_bin)))
    code, _ = _apply(install.plan_uninstall(_options(home, ld_bin)))
    assert code == 0
    assert not _hooks_file(home).exists()
    assert not _hooks_file(home).with_suffix(".json.bak").exists()


def test_uninstall_keeps_the_users_groups_and_their_indices(home, ld_bin):
    config = home / ".codex" / "config.toml"
    config.write_text('[hooks.state."x"]\ntrusted_hash = "sha256:00"\n', "utf-8")
    toml_before = config.read_bytes()
    data, _ = _merge({"hooks": {"PreToolUse": [FOREIGN_BASH]}}, ld_bin.path)
    data["hooks"]["UserPromptSubmit"].append(FOREIGN_PROMPT)  # the user's, behind ours
    _hooks_file(home).write_text(json.dumps(data), "utf-8")
    code, _ = _apply(install.plan_uninstall(_options(home, ld_bin)))
    assert code == 0
    assert _read(home)["hooks"] == {
        "PreToolUse": [FOREIGN_BASH],
        "UserPromptSubmit": [codex_hooks.EMPTY_GROUP, FOREIGN_PROMPT],
    }
    assert config.read_bytes() == toml_before
    # And installing again puts ours back where it was.
    _apply(install.plan_install(_options(home, ld_bin)))
    assert _read(home)["hooks"]["UserPromptSubmit"][0] == _ours("codex-prompt", ld_bin.path)
    assert codex_hooks.EMPTY_GROUP not in _read(home)["hooks"]["UserPromptSubmit"]


def test_uninstall_without_a_file_does_nothing(home, ld_bin):
    code, out = _apply(install.plan_uninstall(_options(home, ld_bin)))
    assert code == 0 and not _hooks_file(home).exists()
    assert t("install.codex_hooks.none") in out


# --- update --------------------------------------------------------------------------------------
def _update_opts(home: Path, ld_bin) -> update.Options:
    return update.Options(home=home, claude_ld_bin=ld_bin, claude_which=lambda name: None)


def _check(check_id: str):
    return next(check for check in checks.CHECKS if check.id == check_id)


@pytest.mark.parametrize(
    ("status", "planned"), [(checks.WARN, True), (checks.OK, False), (checks.UNKNOWN, False)]
)
def test_update_repairs_only_a_warn(home, ld_bin, status, planned):
    results = [(_check("codex.hooks"), Result(status, "x"))]
    actions, _ = update.plan_repairs(results, _update_opts(home, ld_bin))
    assert any(action.kind == "codex-hooks" for action in actions) is planned


def test_update_never_creates_a_codex_folder(tmp_path, ld_bin):
    home = tmp_path / "bare"
    home.mkdir()
    results = [(_check("codex.hooks"), Result(checks.WARN, "x"))]
    actions, _ = update.plan_repairs(results, _update_opts(home, ld_bin))
    assert not any(action.kind == "codex-hooks" for action in actions)
