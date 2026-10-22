"""La entrada `local-delegate` de `claude_desktop_config.json` (SDD claude-plugin-and-mods, REQ-012).

Todo sobre ficheros temporales: la suite nunca toca el `claude_desktop_config.json` real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import desktop_config

EXE = Path(r"C:\Users\someone\.local\bin\local-delegate.exe")
SECRET = "s3cr3t-port-token-value"


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def cfg(tmp_path) -> Path:
    folder = tmp_path / "Claude"
    folder.mkdir()
    return folder / "claude_desktop_config.json"


def test_config_path_lives_under_the_base_dir(tmp_path):
    assert desktop_config.config_path(tmp_path) == tmp_path / "Claude" / desktop_config.FILE_NAME


def test_bridge_entry_is_the_absolute_exe_and_the_subcommand():
    assert desktop_config.bridge_entry(EXE) == {"command": str(EXE), "args": ["desktop-bridge"]}


def test_writes_only_our_key(cfg):
    original = {
        "globalShortcut": "Ctrl+Space",
        "mcpServers": {
            "other": {"command": "npx", "args": ["-y", "other-mcp"], "env": {"A": "1"}},
        },
        "preferences": {"x": [1, 2, 3]},
    }
    _write(cfg, original)

    result = desktop_config.write_entry(cfg, EXE)

    data = _read(cfg)
    assert result.changed is True
    assert data["mcpServers"]["local-delegate"] == desktop_config.bridge_entry(EXE)
    expected = json.loads(json.dumps(original))
    expected["mcpServers"]["local-delegate"] = desktop_config.bridge_entry(EXE)
    assert data == expected
    assert list(data) == list(original)  # el orden de las claves de fuera no cambia


def test_creates_the_file_when_missing_without_backup(tmp_path):
    path = tmp_path / "Claude" / desktop_config.FILE_NAME

    result = desktop_config.write_entry(path, EXE)

    assert _read(path) == {"mcpServers": {"local-delegate": desktop_config.bridge_entry(EXE)}}
    assert result.backup is None
    assert desktop_config.backups(path) == []


def test_same_entry_is_a_no_op(cfg):
    _write(cfg, {"mcpServers": {"local-delegate": desktop_config.bridge_entry(EXE)}})
    before = cfg.read_bytes()

    result = desktop_config.write_entry(cfg, EXE)

    assert result.changed is False
    assert result.backup is None
    assert cfg.read_bytes() == before
    assert desktop_config.backups(cfg) == []


def test_backup_once_rotated_in_config_folder(cfg):
    _write(cfg, {"mcpServers": {}})
    states = []
    for n in range(desktop_config.MAX_BACKUPS + 2):
        states.append(cfg.read_bytes())
        result = desktop_config.write_entry(cfg, Path(rf"C:\v{n}\local-delegate.exe"))
        # Una sola copia nueva por escritura, en la misma carpeta, con lo que había antes.
        assert result.backup is not None
        assert result.backup.parent == cfg.parent
        assert result.backup.read_bytes() == states[-1]

    copies = desktop_config.backups(cfg)
    assert len(copies) == desktop_config.MAX_BACKUPS
    assert all(copy.parent == cfg.parent for copy in copies)
    # Más reciente primero: las copias guardan los últimos estados, en orden.
    assert [copy.read_bytes() for copy in copies] == states[::-1][: desktop_config.MAX_BACKUPS]


def test_foreign_existing_key_needs_explicit_replace(cfg):
    foreign = {
        "command": "npx",
        "args": [
            "-y",
            "mcp-remote",
            "http://127.0.0.1:9393/mcp",
            "--header",
            f"Authorization: Bearer {SECRET}",
        ],
    }
    _write(cfg, {"mcpServers": {"local-delegate": foreign}})
    before = cfg.read_bytes()

    with pytest.raises(desktop_config.ForeignEntryError) as raised:
        desktop_config.write_entry(cfg, EXE)
    assert SECRET not in str(raised.value)
    assert cfg.read_bytes() == before
    assert desktop_config.backups(cfg) == []

    result = desktop_config.write_entry(cfg, EXE, replace_foreign=True)

    assert result.replaced_foreign is True
    assert _read(cfg)["mcpServers"]["local-delegate"] == desktop_config.bridge_entry(EXE)
    # La copia conserva la entrada anterior para poder recuperarla a mano.
    assert result.backup is not None and result.backup.read_bytes() == before


def test_an_older_bridge_entry_is_ours_and_is_rewritten_without_flag(cfg):
    old = desktop_config.bridge_entry(Path(r"D:\old\local-delegate.exe"))
    _write(cfg, {"mcpServers": {"local-delegate": old}})

    result = desktop_config.write_entry(cfg, EXE)

    assert result.replaced_foreign is False
    assert _read(cfg)["mcpServers"]["local-delegate"] == desktop_config.bridge_entry(EXE)


def test_owned_flag_lets_install_rewrite_its_own_entry(cfg):
    _write(cfg, {"mcpServers": {"local-delegate": {"command": "something", "args": []}}})

    result = desktop_config.write_entry(cfg, EXE, owned=True)

    assert result.replaced_foreign is False
    assert _read(cfg)["mcpServers"]["local-delegate"] == desktop_config.bridge_entry(EXE)


def test_invalid_json_is_never_overwritten(cfg):
    cfg.write_text("{ not json", encoding="utf-8")

    with pytest.raises(desktop_config.DesktopConfigError):
        desktop_config.write_entry(cfg, EXE)
    assert cfg.read_text(encoding="utf-8") == "{ not json"


def test_reads_a_file_with_bom(cfg):
    cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps({"mcpServers": {}}).encode("utf-8"))

    desktop_config.write_entry(cfg, EXE)

    assert _read(cfg)["mcpServers"]["local-delegate"] == desktop_config.bridge_entry(EXE)


def test_remove_entry_keeps_the_rest(cfg):
    _write(
        cfg,
        {"mcpServers": {"local-delegate": desktop_config.bridge_entry(EXE), "other": {"a": 1}}},
    )

    result = desktop_config.remove_entry(cfg)

    assert result.changed is True
    assert _read(cfg) == {"mcpServers": {"other": {"a": 1}}}
    assert result.backup is not None
    assert desktop_config.remove_entry(cfg).changed is False


def test_detects_literal_token_without_printing(cfg, capsys):
    entry = {
        "command": "npx",
        "args": [
            "mcp-remote",
            "http://127.0.0.1:9393/mcp",
            "--header",
            f"Authorization: Bearer {SECRET}",
        ],
    }
    _write(cfg, {"mcpServers": {"local-delegate": entry}})

    report = desktop_config.check_entry(cfg, token=SECRET)

    assert report.present is True
    assert report.is_bridge is False
    assert report.literal_token is True
    assert report.unexpanded_variable is False
    assert SECRET not in repr(report)
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err


def test_detects_literal_bearer_even_without_knowing_the_token(cfg):
    entry = {"command": "npx", "args": ["mcp-remote", "--header", "Authorization: Bearer abcdef"]}
    _write(cfg, {"mcpServers": {"local-delegate": entry}})

    assert desktop_config.check_entry(cfg, token="").literal_token is True


def test_detects_token_in_env_block(cfg):
    entry = {"command": "x", "args": [], "env": {"LOCAL_DELEGATE_WEB_TOKEN": SECRET}}
    _write(cfg, {"mcpServers": {"local-delegate": entry}})

    assert desktop_config.check_entry(cfg, token=None).literal_token is True


def test_detects_unexpanded_var(cfg):
    entry = {
        "command": "npx",
        "args": ["mcp-remote", "--header", "Authorization: Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"],
    }
    _write(cfg, {"mcpServers": {"local-delegate": entry}})

    report = desktop_config.check_entry(cfg, token=SECRET)

    assert report.unexpanded_variable is True
    assert report.literal_token is False


def test_the_bridge_entry_is_clean(cfg):
    desktop_config.write_entry(cfg, EXE)

    report = desktop_config.check_entry(cfg, token=SECRET)

    assert report == desktop_config.EntryReport(
        present=True, is_bridge=True, unexpanded_variable=False, literal_token=False
    )


def test_check_without_file_or_entry(cfg):
    assert desktop_config.check_entry(cfg, token=SECRET).present is False
    _write(cfg, {"mcpServers": {"other": {}}})
    assert desktop_config.check_entry(cfg, token=SECRET).present is False
