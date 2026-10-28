"""Config files that are not UTF-8 (or cannot be read) are left untouched and count as a failure.

Before, `install._read_text` gave ``""`` for a `CLAUDE.md`/`AGENTS.md`/`config.toml` in cp1252 or
UTF-16, and the step rebuilt the file from that ``""``: the user's rules and every other
`[mcp_servers.*]` were lost, `apply` said 0 failures and `uninstall` left `CLAUDE.md` at 0 bytes.
`update` changed the pin by rewriting `~/.claude.json` and `config.toml` whole, as text read with
``errors="replace"``, and wrote ``""`` if the read failed.

Everything runs against a fake HOME (`tmp_path`).
"""

from __future__ import annotations

import codecs
import json
from pathlib import Path

import pytest

from local_delegate import install as inst
from local_delegate import update

USER_RULES = "# Reglas de Yohan\n\nNunca borres esto: configuración y acentuación.\n"
CODEX_FOREIGN = (
    '# configuración de Yohan\nmodel = "gpt-5"\n\n[mcp_servers.otro]\ncommand = "otro"\n'
)


def _opts(home: Path, **kw) -> inst.Options:
    base = dict(  # noqa: C408 — readable kwargs
        home=home,
        components={"memory", "mcp"},
        targets={"claude", "codex"},
        python_exe="python3",
        use_cli=False,  # never call the real `claude` binary from the suite
    )
    base.update(kw)
    return inst.Options(**base)


def _run(actions: list[inst.Action]) -> tuple[int, str]:
    lines: list[str] = []
    failures = inst.apply(
        actions, dry_run=False, out=lambda *a: lines.append(" ".join(map(str, a)))
    )
    return failures, "\n".join(lines)


def _install(home: Path, **kw) -> tuple[int, str]:
    return _run(inst.plan_install(_opts(home, **kw)))


def _uninstall(home: Path, **kw) -> tuple[int, str]:
    return _run(inst.plan_uninstall(_opts(home, **kw)))


NON_UTF8 = {
    "cp1252": lambda text: text.encode("cp1252"),
    "utf-16": lambda text: text.encode("utf-16"),  # with BOM: what `>` leaves in PowerShell 5.1
    "utf-16-le-no-bom": lambda text: text.encode("utf-16-le"),
}


def _fail_reading(monkeypatch, target: Path) -> None:
    """Simulates a file that exists but cannot be opened (locked, no permission)."""
    saved = {name: getattr(Path, name) for name in ("read_bytes", "read_text")}

    def failing(name):
        def read(self: Path, *args, **kwargs):
            if self == target:
                raise PermissionError(13, "simulated: locked", str(self))
            return saved[name](self, *args, **kwargs)

        return read

    for name in saved:
        monkeypatch.setattr(Path, name, failing(name))


# --- install -----------------------------------------------------------------
@pytest.mark.parametrize("encoding", sorted(NON_UTF8))
def test_install_leaves_a_non_utf8_claude_md_untouched_and_fails(tmp_path, encoding):
    claude_md = tmp_path / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True)
    original = NON_UTF8[encoding](USER_RULES)
    claude_md.write_bytes(original)

    failures, out = _install(tmp_path)

    assert claude_md.read_bytes() == original, "the user's CLAUDE.md was rewritten"
    assert failures == 1, out
    assert "CLAUDE.md" in out and "UTF-8" in out
    assert not claude_md.with_name("CLAUDE.md.bak").exists(), "not even opened for writing"
    # The rest of the install goes on.
    assert inst.MD_BEGIN in (tmp_path / ".codex" / "AGENTS.md").read_text(encoding="utf-8")


def test_install_leaves_a_codex_config_with_a_cp1252_comment_untouched(tmp_path):
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    original = CODEX_FOREIGN.encode("cp1252")
    config.write_bytes(original)

    failures, out = _install(tmp_path)

    assert config.read_bytes() == original, "[mcp_servers.otro] and the comment were lost"
    assert failures == 1, out
    assert "config.toml" in out


def test_install_leaves_an_unreadable_claude_md_untouched(tmp_path, monkeypatch):
    claude_md = tmp_path / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True)
    claude_md.write_bytes(USER_RULES.encode("utf-8"))
    _fail_reading(monkeypatch, claude_md)

    failures, out = _install(tmp_path)

    monkeypatch.undo()
    assert claude_md.read_bytes() == USER_RULES.encode("utf-8")
    assert failures == 1, out
    assert "simulated: locked" in out


def test_install_keeps_a_utf8_bom_once_and_the_user_text(tmp_path):
    claude_md = tmp_path / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True)
    claude_md.write_bytes(codecs.BOM_UTF8 + USER_RULES.encode("utf-8"))

    for _ in range(2):  # the second run must not add a second BOM nor duplicate the block
        failures, out = _install(tmp_path)
        assert failures == 0, out

    raw = claude_md.read_bytes()
    assert raw.startswith(codecs.BOM_UTF8) and not raw[3:].startswith(codecs.BOM_UTF8)
    text = raw[3:].decode("utf-8")
    assert text.startswith(USER_RULES.rstrip())
    assert text.count(inst.MD_BEGIN) == 1


def test_a_codex_section_right_after_a_bom_is_replaced_not_duplicated(tmp_path):
    """With the BOM kept in the text, `^[mcp_servers.local-delegate]` on the first line was not
    seen and install appended a second table: invalid TOML, Codex without any MCP."""
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_bytes(
        codecs.BOM_UTF8 + b'[mcp_servers.local-delegate]\ncommand = "viejo"\n\n[mcp_servers.otro]\n'
        b'command = "otro"\n'
    )

    failures, out = _install(tmp_path)

    assert failures == 0, out
    text = config.read_bytes()
    assert text.startswith(codecs.BOM_UTF8)
    assert text.count(b"[mcp_servers.local-delegate]") == 1
    assert b"[mcp_servers.otro]" in text and b'"viejo"' not in text


# --- uninstall ---------------------------------------------------------------
@pytest.mark.parametrize("encoding", sorted(NON_UTF8))
def test_uninstall_does_not_empty_a_non_utf8_claude_md(tmp_path, encoding):
    assert _install(tmp_path)[0] == 0
    claude_md = tmp_path / ".claude" / "CLAUDE.md"
    # The user rewrote it in another encoding after installing, block included.
    original = NON_UTF8[encoding](USER_RULES + "\n" + claude_md.read_text(encoding="utf-8"))
    claude_md.write_bytes(original)

    failures, out = _uninstall(tmp_path)

    assert claude_md.read_bytes() == original, "uninstall left CLAUDE.md rewritten (or empty)"
    assert failures == 1, out


def test_uninstall_leaves_a_cp1252_codex_config_untouched(tmp_path):
    assert _install(tmp_path)[0] == 0
    config = tmp_path / ".codex" / "config.toml"
    original = (CODEX_FOREIGN + "\n" + config.read_text(encoding="utf-8")).encode("cp1252")
    config.write_bytes(original)

    failures, out = _uninstall(tmp_path)

    assert config.read_bytes() == original
    assert failures == 1, out


def test_uninstall_with_a_utf8_bom_removes_only_the_block(tmp_path):
    claude_md = tmp_path / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True)
    claude_md.write_bytes(codecs.BOM_UTF8 + USER_RULES.encode("utf-8"))
    assert _install(tmp_path)[0] == 0

    failures, out = _uninstall(tmp_path)

    assert failures == 0, out
    raw = claude_md.read_bytes()
    assert raw == codecs.BOM_UTF8 + USER_RULES.encode("utf-8")


# --- .bak --------------------------------------------------------------------
def test_the_bak_keeps_the_first_version_and_is_not_overwritten(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("v1\n", encoding="utf-8")
    inst._write_text(path, "v2\n")
    inst._write_text(path, "v3\n")
    assert path.read_text(encoding="utf-8") == "v3\n"
    assert (tmp_path / "CLAUDE.md.bak").read_text(encoding="utf-8") == "v1\n"


def test_a_bak_the_user_already_had_is_not_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}\n", encoding="utf-8")
    (tmp_path / "settings.json.bak").write_text("mío\n", encoding="utf-8")
    inst._write_json(path, {"a": 1})
    assert (tmp_path / "settings.json.bak").read_text(encoding="utf-8") == "mío\n"


# --- update: the pin -----------------------------------------------------------
def _pin_actions(home: Path, target: Path, version: str = "0.43.0") -> list[inst.Action]:
    actions = [a for a in update.plan_pin(update.Options(home=home), version) if a.target == target]
    assert len(actions) == 1, "the pin should have been planned"
    return actions


def _codex_pinned(home: Path, prefix: str = "") -> Path:
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        prefix + "[mcp_servers.local-delegate]\n"
        'command = "uvx"\n'
        'args = ["--from", "local-delegate-mcp==0.40.0", "local-delegate-mcp"]\n',
        encoding="utf-8",
    )
    return config


@pytest.mark.parametrize("encoding", ["cp1252", "utf-16"])
def test_the_pin_leaves_a_non_utf8_codex_config_untouched(tmp_path, encoding):
    config = _codex_pinned(tmp_path)
    original = (CODEX_FOREIGN + "\n" + config.read_text(encoding="utf-8")).encode(encoding)
    config.write_bytes(original)
    # Planning reads leniently (it must find the pin); the write step must refuse.
    actions = update.plan_pin(update.Options(home=tmp_path), "0.43.0")
    if encoding == "cp1252":
        assert actions, "the pin is ASCII: it is found and planned, so the write must refuse"
    failures, out = _run(actions)

    assert config.read_bytes() == original, "the comment was saved back as U+FFFD"
    assert failures == (1 if actions else 0), out


def test_the_pin_does_not_empty_claude_json_when_the_read_fails(tmp_path, monkeypatch):
    claude_json = tmp_path / ".claude.json"
    original = json.dumps(
        {
            "mcpServers": {"local-delegate": {"args": ["--from", "local-delegate-mcp==0.40.0"]}},
            "projects": {"x": {}},
        }
    ).encode("utf-8")
    claude_json.write_bytes(original)
    actions = _pin_actions(tmp_path, claude_json)
    _fail_reading(monkeypatch, claude_json)

    failures, out = _run(actions)

    monkeypatch.undo()
    assert claude_json.read_bytes() == original, "~/.claude.json ended up rewritten (or empty)"
    assert failures == 1, out


def test_the_pin_only_changes_our_entry_in_claude_json(tmp_path):
    claude_json = tmp_path / ".claude.json"
    other = {"command": "uvx", "args": ["--from", "local-delegate-mcp==0.40.0", "x"]}
    history = "pegué: uvx --from local-delegate-mcp==0.40.0"
    claude_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local-delegate": {"args": ["--from", "local-delegate-mcp==0.40.0", "y"]}
                },
                "projects": {"p": {"mcpServers": {"copy": other}, "history": [history]}},
            }
        ),
        encoding="utf-8",
    )

    failures, out = _run(_pin_actions(tmp_path, claude_json))

    assert failures == 0, out
    data = json.loads(claude_json.read_text(encoding="utf-8"))
    assert data["mcpServers"]["local-delegate"]["args"][1] == "local-delegate-mcp==0.43.0"
    assert data["projects"]["p"]["mcpServers"]["copy"] == other
    assert data["projects"]["p"]["history"] == [history]


def test_the_pin_keeps_the_utf8_bom_of_claude_json(tmp_path):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_bytes(
        codecs.BOM_UTF8
        + json.dumps(
            {"mcpServers": {"local-delegate": {"args": ["local-delegate-mcp==0.40.0"]}}, "n": "ñ"},
            ensure_ascii=False,
        ).encode("utf-8")
    )

    failures, out = _run(_pin_actions(tmp_path, claude_json))

    assert failures == 0, out
    raw = claude_json.read_bytes()
    assert raw.startswith(codecs.BOM_UTF8) and not raw[3:].startswith(codecs.BOM_UTF8)
    data = json.loads(raw[3:].decode("utf-8"))
    assert data["n"] == "ñ"
    assert data["mcpServers"]["local-delegate"]["args"] == ["local-delegate-mcp==0.43.0"]


def test_the_pin_only_changes_our_codex_table(tmp_path):
    foreign = (
        '# configuración\n[mcp_servers.copy]\nargs = ["--from", "local-delegate-mcp==0.40.0"]\n\n'
    )
    config = _codex_pinned(tmp_path, prefix=foreign)

    failures, out = _run(_pin_actions(tmp_path, config))

    assert failures == 0, out
    text = config.read_text(encoding="utf-8")
    assert text.startswith(foreign), "the other table was rewritten too"
    assert '"local-delegate-mcp==0.43.0"' in text.split("[mcp_servers.local-delegate]")[1]


def test_a_pin_outside_our_entry_is_not_a_pin(tmp_path):
    """Only a `local-delegate-mcp==` in some project's history: nothing to change."""
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {"mcpServers": {}, "projects": {"p": {"history": ["local-delegate-mcp==0.1.0"]}}}
        ),
        encoding="utf-8",
    )
    assert update.plan_pin(update.Options(home=tmp_path), "0.43.0") == []


def test_the_pin_finds_our_codex_table_in_a_crlf_file(tmp_path):
    """Bytes are decoded strictly, but with universal newlines: the table regex expects `\n`."""
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_bytes(
        b'model = "x"\r\n\r\n[mcp_servers.local-delegate]\r\ncommand = "uvx"\r\n'
        b'args = ["--from", "local-delegate-mcp==0.40.0", "local-delegate-mcp"]\r\n'
    )

    failures, out = _run(_pin_actions(tmp_path, config))

    assert failures == 0, out
    raw = config.read_bytes()
    assert b"local-delegate-mcp==0.43.0" in raw
    assert b"\n" not in raw.replace(b"\r\n", b""), "the CRLF line ending was not kept"
