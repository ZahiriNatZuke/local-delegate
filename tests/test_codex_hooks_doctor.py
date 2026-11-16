"""Issue #669: the `codex.hooks` check — configured, approved and seen, told apart, and read-only."""

from __future__ import annotations

import codecs
import json
from pathlib import Path

import pytest
from conftest import snapshot
from test_checks import make_ctx, result_for

from local_delegate import checks, claude_plugin, codex_hooks, i18n

FOREIGN = {"hooks": [{"type": "command", "command": "echo mine"}]}


@pytest.fixture
def home(tmp_path) -> Path:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    return home


@pytest.fixture
def python(tmp_path) -> str:
    exe = tmp_path / "uv-tools" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    return str(exe)


def _write(home: Path, data: dict) -> Path:
    path = home / ".codex" / codex_hooks.HOOKS_FILE_NAME
    path.write_text(json.dumps(data), "utf-8")
    return path


def _installed(home: Path, python: str, *, before: list | None = None) -> Path:
    data = {"hooks": {"UserPromptSubmit": list(before or [])}}
    data, _ = codex_hooks.merge(data, python)
    return _write(home, data)


def _ctx(home: Path, python: str | None, tmp_path: Path, **kwargs):
    ld_bin = claude_plugin.LdBin(python, None if python else "editable")
    return make_ctx(home, expected_ld_bin=lambda: ld_bin, log_dir=tmp_path / "data", **kwargs)


def _result(home, python, tmp_path):
    return result_for("codex.hooks", _ctx(home, python, tmp_path))


def _ok_detail(home: Path, approved: int) -> str:
    """The exact `ok` text with two configured, ``approved`` approved and none seen."""
    return i18n.t(
        "doctor.probe.codex_hooks.ok",
        path=home / ".codex" / codex_hooks.HOOKS_FILE_NAME,
        count=2,
        total=2,
        approved=approved,
        seen=i18n.t("doctor.probe.codex_hooks.never_seen"),
    )


def test_no_codex_is_unknown(tmp_path, python):
    home = tmp_path / "home"
    home.mkdir()
    assert _result(home, python, tmp_path).status == checks.UNKNOWN


def test_none_of_ours_is_ok_and_optional(home, python, tmp_path):
    _write(home, {"hooks": {"UserPromptSubmit": [FOREIGN]}})
    result = _result(home, python, tmp_path)
    assert result.status == checks.OK and "local-delegate install --clients codex" in result.detail


def test_configured_not_approved_not_seen(home, python, tmp_path):
    _installed(home, python)
    result = _result(home, python, tmp_path)
    assert result.status == checks.OK
    assert result.detail == _ok_detail(home, 0)
    assert codex_hooks.SEEN_FILE_NAME not in result.detail


def test_approved_counts_only_our_keys_in_hooks_state(home, python, tmp_path):
    path = _installed(home, python, before=[FOREIGN])
    ours = codex_hooks.hook_key(path, "UserPromptSubmit", 1)
    theirs = codex_hooks.hook_key(path, "UserPromptSubmit", 0)
    (home / ".codex" / "config.toml").write_text(
        f'[hooks.state."{ours}"]\ntrusted_hash = "sha256:aa"\n'
        f'[hooks.state."{theirs}"]\ntrusted_hash = "sha256:bb"\n'.replace("\\", "\\\\"),
        "utf-8",
    )
    seen = codex_hooks.inspect(home / ".codex", tmp_path / "data")
    assert seen.trusted == {"codex-prompt"}
    result = _result(home, python, tmp_path)
    assert result.status == checks.OK and result.detail == _ok_detail(home, 1)


def test_the_key_names_the_index_so_a_wrong_index_is_not_approved(home, python, tmp_path):
    """Control: the same key one group off does not count."""
    path = _installed(home, python, before=[FOREIGN])
    wrong = codex_hooks.hook_key(path, "UserPromptSubmit", 0)
    (home / ".codex" / "config.toml").write_text(
        f'[hooks.state."{wrong}"]\ntrusted_hash = "sha256:aa"\n'.replace("\\", "\\\\"), "utf-8"
    )
    assert codex_hooks.inspect(home / ".codex", tmp_path / "data").trusted == set()


def test_seen_comes_from_the_dispatch_marker(home, python, tmp_path):
    _installed(home, python)
    data = tmp_path / "data"
    data.mkdir()
    (data / codex_hooks.SEEN_FILE_NAME).write_text(
        json.dumps({"codex-prompt": "2026-11-16T12:00:00+00:00", "other": "x"}), "utf-8"
    )
    result = _result(home, python, tmp_path)
    assert "codex-prompt 2026-11-16T12:00:00+00:00" in result.detail
    assert "other" not in result.detail


@pytest.mark.parametrize(
    ("toml", "noted"),
    [
        ('[hooks.state."x"]\ntrusted_hash = "sha256:aa"\n', False),
        ('[[hooks.Stop]]\n[[hooks.Stop.hooks]]\ntype = "command"\ncommand = "echo"\n', True),
    ],
    ids=["state-only", "event-groups"],
)
def test_toml_hooks_noted_only_with_event_groups(home, python, tmp_path, toml, noted):
    _installed(home, python)
    (home / ".codex" / "config.toml").write_text(toml, "utf-8")
    result = _result(home, python, tmp_path)
    assert result.status == checks.OK
    assert (checks.i18n.t("doctor.probe.codex_hooks.toml_too") in result.detail) is noted


def test_an_old_interpreter_is_a_warn_that_update_repairs(home, python, tmp_path):
    _installed(home, python.replace("uv-tools", "old"))
    result = _result(home, python, tmp_path)
    assert result.status == checks.WARN
    assert result.fix_hint == "local-delegate update"
    assert "/hooks" in result.detail


def test_one_missing_is_a_warn(home, python, tmp_path):
    data, _ = codex_hooks.merge({}, python)
    del data["hooks"]["SubagentStart"]
    _write(home, data)
    result = _result(home, python, tmp_path)
    assert result.status == checks.WARN and "codex-subagent-start" in result.detail


def test_a_different_timeout_is_a_warn(home, python, tmp_path):
    """Not only the interpreter: any difference from `entries()` changes Codex's hash."""
    data, _ = codex_hooks.merge({}, python)
    data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeout"] = 5
    _write(home, data)
    result = _result(home, python, tmp_path)
    assert result.status == checks.WARN and "codex-prompt" in result.detail


def test_without_a_uv_tool_to_compare_the_written_interpreter_is_kept(home, python, tmp_path):
    _installed(home, python)
    assert _result(home, None, tmp_path).status == checks.OK


def test_a_missing_interpreter_is_a_warn(home, tmp_path):
    gone = str(tmp_path / "gone" / "python.exe")
    _installed(home, gone)
    result = _result(home, None, tmp_path)
    assert result.status == checks.WARN and gone.replace("\\", "/") in result.detail.replace(
        "\\", "/"
    )


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        (codecs.BOM_UTF8 + b'{"hooks": {}}', checks.WARN),
        (b'{"hooks": {}, "modules": []}', checks.WARN),
        (b"{ nope", checks.UNKNOWN),
    ],
    ids=["bom", "rejected-key", "unreadable"],
)
def test_a_file_codex_would_reject(home, python, tmp_path, raw, status):
    (home / ".codex" / codex_hooks.HOOKS_FILE_NAME).write_bytes(raw)
    assert _result(home, python, tmp_path).status == status


def test_the_check_writes_nothing(home, python, tmp_path):
    _installed(home, python, before=[FOREIGN])
    (home / ".codex" / "config.toml").write_text('[hooks.state."x"]\ntrusted_hash = "a"\n', "utf-8")
    before = snapshot(tmp_path)
    _result(home, python, tmp_path)
    assert snapshot(tmp_path) == before
