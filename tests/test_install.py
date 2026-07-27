"""Tests del instalador de la integración (hooks, skill, memoria, entrada MCP).

Todo corre contra un HOME de prueba (`tmp_path`); ninguna prueba toca el HOME real.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from local_delegate import install as inst


def _opts(home: Path, **kw) -> inst.Options:
    base = dict(
        home=home,
        components={"hooks", "skill", "memory", "mcp"},
        targets={"claude", "codex"},
        python_exe="python3",
        use_cli=False,  # jamás invocar el binario `claude` real desde la suite
    )
    base.update(kw)
    return inst.Options(**base)


def _install(home: Path, **kw) -> int:
    return inst.apply(inst.plan_install(_opts(home, **kw)), dry_run=False, out=lambda *_a: None)


def _uninstall(home: Path, **kw) -> int:
    return inst.apply(inst.plan_uninstall(_opts(home, **kw)), dry_run=False, out=lambda *_a: None)


# --- Recursos empaquetados ----------------------------------------------------
def test_packaged_resources_exist():
    res = inst.resources_dir()
    assert (res / "hooks" / "hook_common.py").is_file()
    assert (res / "hooks" / "suggest_delegate_prompt.py").is_file()
    assert (res / "skills" / "delegacion-local" / "SKILL.md").is_file()
    assert (res / "memory" / "local-delegate.md").is_file()


# --- Instalación completa -----------------------------------------------------
def test_install_writes_hooks_skill_memory_and_mcp(tmp_path):
    assert _install(tmp_path) == 0
    hooks_dir = tmp_path / ".claude" / "hooks" / "local-delegate"
    assert (hooks_dir / "suggest_delegate_prompt.py").is_file()
    assert (hooks_dir / "hook_common.py").is_file()  # los hooks lo importan por sys.path[0]
    assert (tmp_path / ".claude" / "skills" / "delegacion-local" / "SKILL.md").is_file()
    assert inst.MD_BEGIN in (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert inst.MD_BEGIN in (tmp_path / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    servers = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers["local-delegate"]["command"] == "uvx"


def test_hook_command_is_a_single_shell_string(tmp_path):
    """Claude Code ejecuta `command` como UN string; el formato con `args` nunca corría."""
    _install(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = [h for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]
    assert entries, "no se registró ningún hook"
    for entry in entries:
        assert set(entry) == {"type", "command"}
        assert entry["type"] == "command"
        assert entry["command"].startswith("python3 ")


def test_read_hook_is_opt_in(tmp_path):
    _install(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = {g.get("matcher") for g in settings["hooks"].get("PreToolUse", [])}
    assert matchers == {"Bash"}

    _install(tmp_path, enable_read_hook=True)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = {g.get("matcher") for g in settings["hooks"]["PreToolUse"]}
    assert matchers == {"Bash", "Read"}


def test_install_is_idempotent_and_keeps_foreign_config(tmp_path):
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Skill"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "~/mio.sh"}]}]},
            }
        ),
        encoding="utf-8",
    )
    memory = tmp_path / ".claude" / "CLAUDE.md"
    memory.write_text("# Mis reglas\n\nNo borrar.\n", encoding="utf-8")

    for _ in range(3):
        assert _install(tmp_path) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["permissions"] == {"allow": ["Skill"]}
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "~/mio.sh"
    assert len(settings["hooks"]["UserPromptSubmit"]) == 1  # no se duplica al reinstalar
    assert len(settings["hooks"]["PreToolUse"]) == 1
    text = memory.read_text(encoding="utf-8")
    assert text.count(inst.MD_BEGIN) == 1
    assert "No borrar." in text


def test_uninstall_reverts_only_our_changes(tmp_path):
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "~/mio.sh"}]}]}}),
        encoding="utf-8",
    )
    memory = tmp_path / ".claude" / "CLAUDE.md"
    memory.write_text("# Mis reglas\n", encoding="utf-8")
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_config.parent.mkdir(parents=True)
    codex_config.write_text('[mcp_servers.otro]\ncommand = "foo"\n', encoding="utf-8")

    _install(tmp_path)
    assert _uninstall(tmp_path) == 0

    assert not (tmp_path / ".claude" / "hooks" / "local-delegate").exists()
    assert not (tmp_path / ".claude" / "skills" / "delegacion-local").exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "~/mio.sh"}]}]}
    assert memory.read_text(encoding="utf-8") == "# Mis reglas\n"
    remaining = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    assert list(remaining["mcp_servers"]) == ["otro"]
    assert json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))["mcpServers"] == {}


def test_dry_run_writes_nothing(tmp_path):
    lines: list[str] = []
    actions = inst.plan_install(_opts(tmp_path))
    assert inst.apply(actions, dry_run=True, out=lines.append) == 0
    assert lines and all(line.startswith("[dry-run]") for line in lines)
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".codex").exists()


# --- Entrada MCP --------------------------------------------------------------
def test_mcp_entry_never_writes_the_api_key(tmp_path):
    entry = inst.mcp_entry("stdio", "https://pc:9292/v1", api_key_env=True, version="0.11.0")
    assert entry["args"] == ["--from", "local-delegate-mcp==0.11.0", "local-delegate-mcp"]
    assert entry["env"]["LOCAL_DELEGATE_API_KEY"] == "${LOCAL_DELEGATE_API_KEY}"
    block = inst.codex_mcp_block(entry)
    assert 'env_vars = ["LOCAL_DELEGATE_API_KEY"]' in block
    assert "${LOCAL_DELEGATE_API_KEY}" not in block  # TOML no expande variables


def test_codex_block_is_valid_toml_and_replaces_manual_entries(tmp_path):
    existing = (
        "[mcp_servers.otro]\ncommand = 'foo'\n\n"
        "[mcp_servers.local-delegate]\ncommand = 'viejo'\n\n"
        "[mcp_servers.local-delegate.env]\nX = '1'\n"
    )
    entry = inst.mcp_entry("stdio", "http://127.0.0.1:9292/v1", api_key_env=False, version=None)
    result = inst.upsert_codex_mcp(existing, inst.codex_mcp_block(entry))
    data = tomllib.loads(result)
    assert data["mcp_servers"]["local-delegate"]["command"] == "uvx"
    assert data["mcp_servers"]["otro"]["command"] == "foo"
    assert result.count("[mcp_servers.local-delegate]") == 1
    # el bloque gestionado es una sola tabla: lo que se escriba después no cae dentro de env
    appended = tomllib.loads(result + '\n[otra.cosa]\nz = "1"\n')
    assert appended["otra"]["cosa"]["z"] == "1"
    assert "env" not in appended["mcp_servers"]["local-delegate"] or set(
        appended["mcp_servers"]["local-delegate"]["env"]
    ) == {"LOCAL_DELEGATE_BASE_URL", "LOCAL_DELEGATE_AUTOSTART"}


def test_http_mode_points_to_the_shared_daemon(tmp_path):
    entry = inst.mcp_entry("http", None, api_key_env=False, version=None)
    assert entry["type"] == "http"
    assert entry["url"].endswith("/mcp")


# --- Bloques gestionados ------------------------------------------------------
def test_upsert_block_replaces_without_duplicating():
    text = "antes\n"
    once = inst.upsert_block(text, "A", inst.MD_BEGIN, inst.MD_END)
    twice = inst.upsert_block(once, "B", inst.MD_BEGIN, inst.MD_END)
    assert twice.count(inst.MD_BEGIN) == 1
    assert "B" in twice and "antes" in twice


def test_remove_block_on_text_without_block_is_noop():
    assert inst.remove_block("solo mío\n", inst.MD_BEGIN, inst.MD_END) == "solo mío\n"


def test_foreign_hook_mentioning_local_delegate_is_not_removed(tmp_path):
    hooks_dir = tmp_path / ".claude" / "hooks" / "local-delegate"
    settings = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "python3 ~/mios/local-delegate.py"}]}
            ]
        }
    }
    cleaned, removed = inst.strip_hook_settings(settings, hooks_dir)
    assert cleaned["hooks"]["Stop"] and removed == 0


def test_install_migrates_the_broken_legacy_hook_entries(tmp_path):
    """La recipe vieja documentaba `{"command":"python","args":[…]}`, formato que Claude Code
    no ejecuta: esas entradas quedaban muertas en `~/.claude/hooks/` (sin subdirectorio).
    Instalar debe retirarlas en vez de dejar un duplicado inerte al lado del bueno."""
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python",
                                    "args": [
                                        str(tmp_path / ".claude/hooks/suggest_delegate_prompt.py")
                                    ],
                                }
                            ]
                        }
                    ],
                    "Stop": [{"hooks": [{"type": "command", "command": "~/mio.sh"}]}],
                }
            }
        ),
        encoding="utf-8",
    )
    _install(tmp_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    prompt_hooks = [h for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert len(prompt_hooks) == 1, "la entrada heredada debería haberse retirado"
    assert "args" not in prompt_hooks[0]
    assert prompt_hooks[0]["command"].startswith("python3 ")
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "~/mio.sh"
