"""Config JSON read before a rewrite: a BOM is read and kept; an unreadable file is never
overwritten (SDD retire-legacy-aliases, L10, REQ-026 and REQ-027).

Before L10, `install._read_json` read with strict `utf-8` and returned `{}` on ANY error, so the
steps that write afterwards rebuilt `settings.json` (or `~/.claude.json`) from scratch: with a BOM
or invalid JSON, `env` and foreign keys were lost and the read hook was switched off.
"""

from __future__ import annotations

import codecs
import hashlib
import json

import pytest
from conftest import make_home
from test_update import _GONE_ENV, _retired_registry, _run

from local_delegate import checks, install

BOM = codecs.BOM_UTF8
INVALID = b'{"env": {"FOREIGN_FLAG": "1"}, "hooks": '  # truncated: not valid JSON
NOT_OBJECT = b'["a list", "not an object"]'


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _quiet(*_a) -> None:
    return None


def _hook_opts(home, **kwargs) -> install.Options:
    return install.Options(
        home=home, components={"hooks"}, targets={"claude"}, python_exe="python", **kwargs
    )


def _install_hooks(home) -> tuple[int, str]:
    lines: list[str] = []
    failures = install.apply(
        install.plan_install(_hook_opts(home)),
        dry_run=False,
        out=lambda *a: lines.append(" ".join(str(x) for x in a)),
    )
    return failures, "\n".join(lines)


def _settings(home):
    return home / ".claude" / "settings.json"


def _load(path) -> dict:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig"))


def _registered(data: dict) -> int:
    hooks = data.get("hooks") or {}
    return sum(
        1
        for groups in hooks.values()
        for group in groups
        for hook in group.get("hooks", [])
        if install.HOOKS_SUBDIR in hook.get("command", "")
    )


# --- The reader -------------------------------------------------------------------------------


def test_read_json_accepts_a_bom(tmp_path):
    path = tmp_path / "x.json"
    path.write_bytes(BOM + b'{"a": 1}')
    assert install._read_json(path) == {"a": 1}


def test_read_config_json_tells_missing_from_unreadable(tmp_path):
    assert install._read_config_json(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_bytes(INVALID)
    with pytest.raises(install.UnreadableConfigError) as exc:
        install._read_config_json(bad)
    assert str(bad) in str(exc.value)
    other = tmp_path / "list.json"
    other.write_bytes(NOT_OBJECT)
    with pytest.raises(install.UnreadableConfigError):
        install._read_config_json(other)
    latin = tmp_path / "latin.json"
    latin.write_bytes(b'{"a": "\xe9"}')
    with pytest.raises(install.UnreadableConfigError):
        install._read_config_json(latin)


def test_write_json_keeps_the_bom_and_the_line_ending(tmp_path):
    path = tmp_path / "x.json"
    path.write_bytes(BOM + b'{\r\n  "a": 1\r\n}\r\n')
    install._write_json(path, {"a": 2})
    raw = path.read_bytes()
    assert raw.startswith(BOM)
    assert b"\r\n" in raw
    assert _load(path) == {"a": 2}


def test_write_json_adds_no_bom_to_a_file_without_one(tmp_path):
    path = tmp_path / "x.json"
    path.write_bytes(b'{"a": 1}\n')
    install._write_json(path, {"a": 2})
    assert not path.read_bytes().startswith(BOM)


# --- install / uninstall over settings.json ---------------------------------------------------


def test_install_keeps_a_bom_settings_with_env_and_foreign_keys(tmp_path):
    home = make_home(tmp_path, complete=False)
    path = _settings(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = {"env": {"FOREIGN_FLAG": "1"}, "theme": "dark", "hooks": {}}
    path.write_bytes(BOM + json.dumps(original, indent=2).encode("utf-8"))

    failures, text = _install_hooks(home)

    assert failures == 0, text
    raw = path.read_bytes()
    assert raw.startswith(BOM)
    data = _load(path)
    assert data["env"] == {"FOREIGN_FLAG": "1"}
    assert data["theme"] == "dark"
    assert _registered(data) == len(install._HOOK_EVENTS)


@pytest.mark.parametrize(
    "content", [INVALID, NOT_OBJECT, BOM + INVALID], ids=["bad", "list", "bom"]
)
def test_install_never_overwrites_an_unreadable_settings(tmp_path, content):
    home = make_home(tmp_path, complete=False)
    path = _settings(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    before = _sha(path)

    failures, text = _install_hooks(home)

    assert failures >= 1, text
    assert _sha(path) == before
    assert str(path) in text
    assert install.t("install.config_unreadable.fix") in text


def test_uninstall_never_overwrites_an_unreadable_settings(tmp_path):
    home = make_home(tmp_path, complete=False)
    path = _settings(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(INVALID)
    before = _sha(path)
    lines: list[str] = []

    failures = install.apply(
        [a for a in install.plan_uninstall(_hook_opts(home)) if a.kind == "settings"],
        dry_run=False,
        out=lambda *a: lines.append(" ".join(str(x) for x in a)),
    )

    assert failures == 1, lines
    assert _sha(path) == before


# --- update -----------------------------------------------------------------------------------


def _home_with_stale_hooks(tmp_path):
    home = make_home(tmp_path, complete=False)
    failures, text = _install_hooks(home)
    assert failures == 0, text
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    (hooks_dir / install._HOOK_EVENTS[0][0]).write_text("# versión anterior\n", encoding="utf-8")
    return home


def test_update_keeps_bom_env_foreign_keys_and_migrates(monkeypatch, tmp_path):
    """The live-verification defect: BOM + old `env` + foreign key + stale hooks."""
    _retired_registry(monkeypatch)
    home = _home_with_stale_hooks(tmp_path)
    path = _settings(home)
    data = _load(path)
    data["env"] = {_GONE_ENV[0]: "1", "OTHER_TOOL_FLAG": "x"}
    data["theme"] = "dark"
    data["hooks"] = {}
    path.write_bytes(BOM + json.dumps(data, indent=2).encode("utf-8"))

    code, text = _run(home)

    assert code == 0, text
    raw = path.read_bytes()
    assert raw.startswith(BOM)
    final = _load(path)
    assert final["env"] == {_GONE_ENV[1]: "1", "OTHER_TOOL_FLAG": "x"}
    assert final["theme"] == "dark"
    assert _registered(final) == len(install._HOOK_EVENTS)


def test_update_never_overwrites_an_invalid_settings(monkeypatch, tmp_path):
    _retired_registry(monkeypatch)
    home = _home_with_stale_hooks(tmp_path)
    path = _settings(home)
    path.write_bytes(INVALID)
    before = _sha(path)

    code, text = _run(home)

    assert code != 0, text
    assert _sha(path) == before
    assert str(path) in text
    assert install.t("install.config_unreadable.fix") in text


# --- ~/.claude.json ---------------------------------------------------------------------------


def _mcp_opts(home) -> install.Options:
    return install.Options(
        home=home, components={"mcp"}, targets={"claude"}, python_exe="python", use_cli=False
    )


def test_register_mcp_keeps_a_bom_claude_json(tmp_path):
    home = make_home(tmp_path, complete=False)
    path = home / ".claude.json"
    path.write_bytes(BOM + b'{"projects": {"x": 1}, "mcpServers": {"other": {}}}')

    install._register_claude_mcp(_mcp_opts(home), {"command": "x"})

    assert path.read_bytes().startswith(BOM)
    data = _load(path)
    assert data["projects"] == {"x": 1}
    assert set(data["mcpServers"]) == {"other", install.SERVER_NAME}


@pytest.mark.parametrize("step", ["register", "unregister"])
def test_mcp_steps_never_overwrite_an_unreadable_claude_json(tmp_path, step):
    home = make_home(tmp_path, complete=False)
    path = home / ".claude.json"
    path.write_bytes(INVALID)
    before = _sha(path)

    with pytest.raises(install.UnreadableConfigError):
        if step == "register":
            install._register_claude_mcp(_mcp_opts(home), {"command": "x"})
        else:
            install._unregister_claude_mcp(_mcp_opts(home))

    assert _sha(path) == before


# --- doctor -----------------------------------------------------------------------------------


def _ctx(home) -> checks.Context:
    return checks.Context(home=home)


def test_doctor_reads_a_bom_settings(tmp_path):
    home = make_home(tmp_path, complete=False)
    failures, text = _install_hooks(home)
    assert failures == 0, text
    path = _settings(home)
    path.write_bytes(BOM + path.read_bytes())

    result = checks._probe_hook_settings(_ctx(home))

    assert result.status != checks.UNKNOWN, result


def test_doctor_reports_an_invalid_settings_as_unknown(tmp_path):
    home = make_home(tmp_path, complete=False)
    path = _settings(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(INVALID)

    result = checks._probe_hook_settings(_ctx(home))
    assert result.status == checks.UNKNOWN
    assert str(path) in result.detail
    # The whole run does not blow up either.
    checks.run_all(_ctx(home))
