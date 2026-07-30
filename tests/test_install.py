"""Tests del instalador de la integración (hooks, skill, memoria, entrada MCP).

Todo corre contra un HOME de prueba (`tmp_path`); ninguna prueba toca el HOME real.
"""

from __future__ import annotations

import json
import shlex
import tomllib
from pathlib import Path, PureWindowsPath

from local_delegate import install as inst


def _opts(home: Path, **kw) -> inst.Options:
    base = dict(  # noqa: C408 — kwargs legibles, no un literal
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
    """Claude Code entrega `command` a un shell como UN string."""
    _install(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = [h for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]
    assert entries, "no se registró ningún hook"
    for entry in entries:
        assert set(entry) == {"type", "command"}
        assert entry["type"] == "command"
        assert entry["command"].startswith("python3 ")


def test_hook_command_survives_a_windows_path(tmp_path):
    """La ruta va citada y con `/`, o el shell se come los `\\` y el hook no abre el archivo.

    Con `UserPromptSubmit` eso no degrada nada: **bloquea cada prompt** del usuario. Pasó de
    verdad en Windows, así que la propiedad se prueba con la forma exacta del bug.
    """
    # PureWindowsPath y no Path: en Linux, `Path(r"C:\\Users\\…")` es un nombre de archivo con
    # barras invertidas dentro, no una ruta con separadores, y el test no probaría nada.
    command = inst.hook_command(
        PureWindowsPath(r"C:\Users\Yohan\.claude\hooks\local-delegate"),
        "suggest_delegate_prompt.py",
        "python",
    )
    assert command == (
        'python "C:/Users/Yohan/.claude/hooks/local-delegate/suggest_delegate_prompt.py"'
    )
    assert "\\" not in command  # ni un solo escape que el shell pueda comerse
    # Lo que de verdad importa: el argumento que recibiría el intérprete sigue siendo la ruta.
    assert shlex.split(command)[1].endswith("local-delegate/suggest_delegate_prompt.py")


def test_hook_command_quotes_paths_with_spaces(tmp_path):
    command = inst.hook_command(tmp_path / "con espacio", "x.py", "python3")
    assert shlex.split(command)[1].endswith("con espacio/x.py")


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


def test_install_preserva_el_terminador_de_linea_del_usuario(tmp_path):
    """Añadir un bloque no debe reescribir el archivo entero.

    `write_text` usa el terminador de la plataforma: en Windows convertía a CRLF un
    `CLAUDE.md` guardado en LF. El usuario veía su archivo completo como modificado —diff
    ilegible, y conflictos si lo comparte entre una Mac y un Windows.
    """
    original = b"# Mis reglas\n\nNo borrar.\n"
    memory = tmp_path / ".claude" / "CLAUDE.md"
    memory.parent.mkdir(parents=True)
    memory.write_bytes(original)

    _install(tmp_path)
    tocado = memory.read_bytes()
    assert b"\r\n" not in tocado, "se convirtió a CRLF un archivo que estaba en LF"
    assert tocado.startswith(original.rstrip(b"\n"))

    _uninstall(tmp_path)
    assert memory.read_bytes() == original


def test_install_respeta_crlf_si_el_archivo_ya_lo_usaba(tmp_path):
    """Y al revés: a quien lo tenga en CRLF no se le convierte a LF."""
    original = b"# Mis reglas\r\n\r\nNo borrar.\r\n"
    memory = tmp_path / ".claude" / "CLAUDE.md"
    memory.parent.mkdir(parents=True)
    memory.write_bytes(original)

    _install(tmp_path)
    tocado = memory.read_bytes()
    assert b"\r\n" in tocado
    assert b"\n" not in tocado.replace(b"\r\n", b""), "quedaron saltos sueltos en LF"

    _uninstall(tmp_path)
    assert memory.read_bytes() == original


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


def test_install_migrates_the_legacy_hook_entries(tmp_path):
    """La recipe vieja documentaba `{"command":"python","args":[…]}` y dejaba los scripts en
    `~/.claude/hooks/` (sin subdirectorio).

    Ese formato **sí se ejecuta**: es el *exec form* del schema de Claude Code, verificado en
    vivo dos veces viendo disparar `suggest_lint_summary.py`. Aquí se decía lo contrario —«un
    formato que Claude Code no ejecuta, entradas muertas»— y era falso; el mismo comentario ya
    provocó un falso positivo en un check (PR #55), así que conviene no volver a escribirlo.

    Se retiran porque cambió la ruta y el formato que ponemos, no porque estuvieran rotas:
    dejarlas produciría dos hooks vivos sugiriendo lo mismo."""
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
