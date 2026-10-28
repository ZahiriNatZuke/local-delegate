"""Tests del instalador de la integración (hooks, skill, memoria, entrada MCP).

Todo corre contra un HOME de prueba (`tmp_path`); ninguna prueba toca el HOME real.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path, PureWindowsPath

import pytest
from conftest import downgrade_to_0_34, live_memory_files, make_home, snapshot

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
    assert (res / "skills" / "local-delegation" / "SKILL.md").is_file()
    assert (res / "memory" / "local-delegate.md").is_file()


# --- Instalación completa -----------------------------------------------------
def test_install_writes_hooks_skill_memory_and_mcp(tmp_path):
    assert _install(tmp_path) == 0
    hooks_dir = tmp_path / ".claude" / "hooks" / "local-delegate"
    assert (hooks_dir / "suggest_delegate_prompt.py").is_file()
    assert (hooks_dir / "hook_common.py").is_file()  # los hooks lo importan por sys.path[0]
    assert (tmp_path / ".claude" / "skills" / "local-delegation" / "SKILL.md").is_file()
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


def test_hook_command_quotes_an_exe_with_spaces_and_backslash():
    """`--python "C:\\Program Files\\..."` iba desnudo: el shell lo cortaba en el espacio.

    Y Git Bash se comía además cada `\\`. En `UserPromptSubmit` eso bloquea cada prompt.
    """
    command = inst.hook_command(
        PureWindowsPath(r"C:\Users\Yohan\.claude\hooks\local-delegate"),
        "record_call.py",
        r"C:\Program Files\Python312\python.exe",
    )
    assert "\\" not in command
    words = shlex.split(command)
    assert words[0] == "C:/Program Files/Python312/python.exe"
    assert words[1] == "C:/Users/Yohan/.claude/hooks/local-delegate/record_call.py"


def test_hook_command_keeps_a_bare_exe_untouched(tmp_path):
    """La instalación por defecto no cambia ni un byte: `python` sigue desnudo."""
    assert inst.hook_command(tmp_path, "x.py", "python").startswith("python ")
    assert inst.hook_command(tmp_path, "x.py", "/usr/bin/python3").startswith("/usr/bin/python3 ")


def test_hook_command_does_not_double_the_quotes_of_the_user(tmp_path):
    command = inst.hook_command(tmp_path, "x.py", '"C:\\Program Files\\Python312\\python.exe"')
    assert command.startswith('"C:/Program Files/Python312/python.exe" ')
    assert shlex.split(command)[0] == "C:/Program Files/Python312/python.exe"


def _exe_in_a_dir_with_spaces(base: Path) -> Path:
    """A working Python inside a folder whose name has a space, or skip if none can be made.

    On Windows the venv launcher is copied with its ``pyvenv.cfg`` (a ``.bat`` would not do:
    Git Bash cannot hand a quoted ``.bat`` path with spaces to cmd). Elsewhere, a symlink.
    """
    folder = base / "Program Files" / "Py thon"
    folder.mkdir(parents=True)
    if sys.platform == "win32":
        cfg = Path(sys.prefix) / "pyvenv.cfg"
        if sys.prefix == sys.base_prefix or not cfg.is_file():
            pytest.skip("needs a venv to copy a runnable python.exe")
        exe = folder / "python.exe"
        exe.write_bytes(Path(sys.executable).read_bytes())
        (folder / "pyvenv.cfg").write_bytes(cfg.read_bytes())
        return exe
    exe = folder / "python3"
    exe.symlink_to(os.path.realpath(sys.executable))
    return exe


def _shells_to_try() -> list[tuple[str, list[str] | None]]:
    """(name, argv prefix) of each shell available here; ``None`` means cmd via ``shell=True``."""
    shells: list[tuple[str, list[str] | None]] = []
    sh = shutil.which("sh")
    if sh and "system32" not in sh.lower():  # never WSL's launcher
        shells.append(("sh", [sh, "-c"]))
    if sys.platform == "win32":
        shells.append(("cmd", None))
    if not shells:
        pytest.skip("no shell to run the hook command with")
    return shells


def test_hook_command_with_an_exe_with_spaces_really_runs(tmp_path):
    """El comando, ejecutado de verdad por el shell, llega al script con sus argumentos."""
    exe = _exe_in_a_dir_with_spaces(tmp_path)
    hooks_dir = tmp_path / "hooks dir" / "local-delegate"
    hooks_dir.mkdir(parents=True)
    out = tmp_path / "reached.txt"
    (hooks_dir / "probe.py").write_text(
        "import sys, pathlib\n"
        f"pathlib.Path({str(out)!r}).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    # The form the user types: native separators, so `\` on Windows.
    command = inst.hook_command(hooks_dir, "probe.py", str(exe), ("--flag",))
    ran = 0
    for name, prefix in _shells_to_try():
        out.unlink(missing_ok=True)
        argv: str | list[str] = command if prefix is None else [*prefix, command]
        result = subprocess.run(
            argv, shell=prefix is None, capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"
        assert out.read_text(encoding="utf-8") == "--flag", name
        ran += 1
    assert ran  # guard: at least one shell really ran the command


def test_hooks_with_a_quoted_exe_are_still_ours(tmp_path):
    """Detección, reparación y desinstalación reconocen el comando nuevo como nuestro."""
    hooks_dir = tmp_path / ".claude" / "hooks" / inst.HOOKS_SUBDIR
    command = inst.hook_command(
        hooks_dir, "record_call.py", r"C:\Program Files\Python312\python.exe"
    )
    assert inst._is_ours({"type": "command", "command": command}, hooks_dir)
    # Re-registering replaces it instead of piling up a duplicate, and stripping removes it.
    entries = [("PostToolUse", "mcp__local-delegate__.*", command)]
    data, _ = inst.merge_hook_settings({}, entries, hooks_dir)
    data, removed = inst.merge_hook_settings(data, entries, hooks_dir)
    assert removed == 1
    assert len(data["hooks"]["PostToolUse"]) == 1
    _, removed = inst.strip_hook_settings(data, hooks_dir)
    assert removed == 1


def test_read_hook_is_opt_in(tmp_path):
    _install(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = {g.get("matcher") for g in settings["hooks"].get("PreToolUse", [])}
    # Sin opt-in solo queda el de atribución (coste-api-y-cuota, REQ-002), que no avisa ni
    # bloquea: ninguno de los de lectura.
    assert matchers == {"mcp__local-delegate__.*"}

    _install(tmp_path, enable_read_hook=True)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = {g.get("matcher") for g in settings["hooks"]["PreToolUse"]}
    # Los TRES caminos de lectura, con una sola bandera: cerrar la tool `Read` y dejar abierto
    # `cat informe.md` no cambia la conducta, la muda de sitio; y las lecturas por otros MCP se
    # cuentan aunque no se cierren (REQ-F1-9).
    assert matchers == {
        "Read",
        "Bash|PowerShell",
        inst._MCP_READ_HOOK[2],
        "mcp__local-delegate__.*",
    }


def test_the_attribution_hook_is_registered(tmp_path):
    """coste-api-y-cuota, REQ-002: el hook que anota quién pide cada delegación va siempre.

    Control (a): contra el código de antes no hay ningún `PreToolUse` registrado por defecto.
    """
    _install(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    registered = {
        (event, group.get("matcher"))
        for event, groups in settings["hooks"].items()
        for group in groups
    }
    assert ("PreToolUse", "mcp__local-delegate__.*") in registered
    commands = [
        h["command"]
        for g in settings["hooks"]["PreToolUse"]
        if g.get("matcher") == "mcp__local-delegate__.*"
        for h in g["hooks"]
    ]
    assert len(commands) == 1 and "record_call.py" in commands[0]
    hooks_dir = tmp_path / ".claude" / "hooks" / inst.HOOKS_SUBDIR
    assert (hooks_dir / "record_call.py").is_file(), "el script registrado tiene que estar copiado"


def _simulate_install_034(home: Path) -> Path:
    """Lo que dejaba `install` en la 0.34.0: el hook de atribución con su nombre viejo, copiado y
    registrado. Se parte de una instalación de hoy y se le devuelve el nombre de entonces."""
    assert _install(home) == 0
    hooks_dir = home / ".claude" / "hooks" / inst.HOOKS_SUBDIR
    (hooks_dir / "record_call.py").rename(hooks_dir / "anotar_llamada.py")
    settings_path = home / ".claude" / "settings.json"
    text = settings_path.read_text(encoding="utf-8")
    assert "record_call.py" in text
    settings_path.write_text(text.replace("record_call.py", "anotar_llamada.py"), encoding="utf-8")
    return hooks_dir


def test_install_over_a_034_retires_anotar_llamada_and_registers_record_call(tmp_path):
    """REQ-012: tras `install` sobre una 0.34.0, el hook viejo no queda ni en el disco ni en
    `settings.json`, y el nuevo está una sola vez. Sin esto la copia vieja seguiría anotando cada
    llamada por su cuenta."""
    hooks_dir = _simulate_install_034(tmp_path)
    assert (hooks_dir / "anotar_llamada.py").is_file(), "guarda: la 0.34.0 simulada lo tiene"

    assert _install(tmp_path) == 0

    assert not (hooks_dir / "anotar_llamada.py").exists(), "la copia vieja sigue en el disco"
    assert (hooks_dir / "record_call.py").is_file()
    text = (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "anotar_llamada.py" not in text, "el registro viejo sigue en settings.json"
    assert text.count("record_call.py") == 1


def test_a_hand_made_copy_of_anotar_llamada_is_also_retired(tmp_path):
    """La otra mitad de REQ-012, y la que depende de `_RETIRED_SCRIPTS`: la copia de
    `hooks/local-delegate/` la repone `install` entera, pero una puesta a mano siguiendo la recipe
    (en la raíz de `~/.claude/hooks/`, registrada con su ruta) solo se reconoce como nuestra por el
    nombre. Sin la entrada, se quedaría anotando cada llamada para siempre."""
    claude = tmp_path / ".claude"
    (claude / "hooks").mkdir(parents=True)
    by_hand = claude / "hooks" / "anotar_llamada.py"
    by_hand.write_text("# copiado a mano desde la recipe de la 0.34.0\n", encoding="utf-8")
    (claude / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "mcp__local-delegate__.*",
                            "hooks": [
                                {"type": "command", "command": f"python {by_hand.as_posix()}"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert _install(tmp_path) == 0

    assert not by_hand.exists(), "la copia a mano del hook viejo sigue en el disco"
    text = (claude / "settings.json").read_text(encoding="utf-8")
    assert "anotar_llamada.py" not in text, "su registro sigue en settings.json"
    assert text.count("record_call.py") == 1


def _read_hook_command(home: Path) -> str | None:
    """El comando de Read tal y como quedó escrito en settings.json, o None si no hay."""
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for group in settings.get("hooks", {}).get("PreToolUse", []):
        if group.get("matcher") == "Read":
            return group["hooks"][0]["command"]
    return None


def test_enable_read_hook_leaves_the_hook_REALLY_on(tmp_path, monkeypatch):
    """El test que faltaba: el que **cruza el instalador con el script**.

    Había uno que probaba que el instalador registra (`test_read_hook_is_opt_in`) y otro que
    probaba que el script obedece la variable de entorno (`test_read_hook_is_disabled_by_default`).
    Los dos en verde, y entre ellos un agujero: el instalador registraba el hook **sin** poner la
    variable, así que la opción no encendía nada y no lo decía. Probar la pieza no es probar el
    uso.

    Aquí se coge el comando **tal cual quedó en `settings.json`**, se ejecuta con el entorno
    limpio de `LD_HOOK_READ_ENABLED` y se mira si sugiere.
    """
    monkeypatch.delenv("LD_HOOK_READ_ENABLED", raising=False)
    _install(tmp_path, enable_read_hook=True)

    command = _read_hook_command(tmp_path)
    assert command is not None, "el hook de Read no quedó registrado"

    large = tmp_path / "large.txt"
    large.write_text("x" * 40_000, encoding="utf-8")  # 39 KB: por encima del umbral de aviso
    hook_input = json.dumps({"tool_input": {"file_path": str(large)}})

    # Se respeta el comando escrito, cambiando SOLO el intérprete: el registrado es un nombre
    # resuelto por PATH ("python"/"python3") que en el runner puede no ser el de la suite.
    argv = shlex.split(command)
    argv[0] = sys.executable
    env = {**os.environ, "PYTHONPATH": str(tmp_path / ".claude" / "hooks" / "local-delegate")}
    env.pop("LD_HOOK_READ_ENABLED", None)

    output = subprocess.run(argv, input=hook_input, capture_output=True, text=True, env=env).stdout

    assert "additionalContext" in output, (
        f"instalado con --enable-read-hook y sin la variable, el hook no sugirió nada.\n"
        f"comando registrado: {command!r}\nsalida: {output!r}"
    )


def test_without_the_flag_the_read_hook_is_neither_registered_nor_suggested(tmp_path, monkeypatch):
    """Control negativo del test de arriba.

    Sin él, el anterior pasaría igual con un hook que sugiriera **siempre**, que es el fallo
    opuesto y peor: ruido en cada lectura de quien nunca pidió el experimento.
    """
    monkeypatch.delenv("LD_HOOK_READ_ENABLED", raising=False)
    _install(tmp_path)
    assert _read_hook_command(tmp_path) is None


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
    # Por defecto el único `PreToolUse` es el de atribución, y una sola vez aunque se reinstale:
    # el de Read es opt-in y el de lint se retiró.
    assert [g.get("matcher") for g in settings["hooks"]["PreToolUse"]] == [
        "mcp__local-delegate__.*"
    ]
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
    codex_config.write_text('[mcp_servers.other]\ncommand = "foo"\n', encoding="utf-8")

    _install(tmp_path)
    assert _uninstall(tmp_path) == 0

    assert not (tmp_path / ".claude" / "hooks" / "local-delegate").exists()
    assert not (tmp_path / ".claude" / "skills" / "local-delegation").exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "~/mio.sh"}]}]}
    assert memory.read_text(encoding="utf-8") == "# Mis reglas\n"
    remaining = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    assert list(remaining["mcp_servers"]) == ["other"]
    assert json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))["mcpServers"] == {}


def test_install_preserves_the_user_line_terminator(tmp_path):
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
    touched = memory.read_bytes()
    assert b"\r\n" not in touched, "se convirtió a CRLF un archivo que estaba en LF"
    assert touched.startswith(original.rstrip(b"\n"))

    _uninstall(tmp_path)
    assert memory.read_bytes() == original


def test_install_respects_crlf_if_the_file_already_used_it(tmp_path):
    """Y al revés: a quien lo tenga en CRLF no se le convierte a LF."""
    original = b"# Mis reglas\r\n\r\nNo borrar.\r\n"
    memory = tmp_path / ".claude" / "CLAUDE.md"
    memory.parent.mkdir(parents=True)
    memory.write_bytes(original)

    _install(tmp_path)
    touched = memory.read_bytes()
    assert b"\r\n" in touched
    assert b"\n" not in touched.replace(b"\r\n", b""), "quedaron saltos sueltos en LF"

    _uninstall(tmp_path)
    assert memory.read_bytes() == original


def test_dry_run_writes_nothing(tmp_path):
    lines: list[str] = []
    actions = inst.plan_install(_opts(tmp_path))
    assert inst.apply(actions, dry_run=True, out=lines.append) == 0
    # Una acción puede ocupar varias líneas: la suya, y debajo indentado el literal que va a
    # escribir. Lo que este test defiende es que NINGUNA línea anuncia una escritura de verdad.
    assert lines and all(line.startswith(("[dry-run]", "          ")) for line in lines)
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".codex").exists()


def test_dry_run_shows_the_literal_command_of_each_hook(tmp_path):
    """No basta con «registra 2 hook(s)»: el defecto puede vivir en el string generado.

    Es exactamente lo que pasó el 2026-07-30 en Windows — un comando de shell sin comillas dejó
    los hooks registrados y muertos, y el plan del `--dry-run` decía que todo iba bien porque solo
    contaba cuántos eran. Un resumen no es revisable; el comando sí.
    """
    lines: list[str] = []
    inst.apply(inst.plan_install(_opts(tmp_path)), dry_run=True, out=lines.append)
    output = "\n".join(lines)
    for script, _event, _matcher in inst._HOOK_EVENTS:
        assert script in output, f"el plan no enseña el comando de {script}"
    # Y la entrada MCP, por el mismo motivo: es lo otro que se escribe generado y no copiado.
    assert '"command": "uvx"' in output or 'command = "uvx"' in output


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
        "[mcp_servers.other]\ncommand = 'foo'\n\n"
        "[mcp_servers.local-delegate]\ncommand = 'viejo'\n\n"
        "[mcp_servers.local-delegate.env]\nX = '1'\n"
    )
    entry = inst.mcp_entry("stdio", "http://127.0.0.1:9292/v1", api_key_env=False, version=None)
    result = inst.upsert_codex_mcp(existing, inst.codex_mcp_block(entry))
    data = tomllib.loads(result)
    assert data["mcp_servers"]["local-delegate"]["command"] == "uvx"
    assert data["mcp_servers"]["other"]["command"] == "foo"
    assert result.count("[mcp_servers.local-delegate]") == 1
    # el bloque gestionado es una sola tabla: lo que se escriba después no cae dentro de env
    appended = tomllib.loads(result + '\n[another.thing]\nz = "1"\n')
    assert appended["another"]["thing"]["z"] == "1"
    assert "env" not in appended["mcp_servers"]["local-delegate"] or set(
        appended["mcp_servers"]["local-delegate"]["env"]
    ) == {"LOCAL_DELEGATE_BASE_URL", "LOCAL_DELEGATE_AUTOSTART"}


def test_http_mode_points_to_the_shared_daemon(tmp_path):
    entry = inst.mcp_entry("http", None, api_key_env=False, version=None)
    assert entry["type"] == "http"
    assert entry["url"].endswith("/mcp")


def test_unless_asked_the_http_entry_carries_no_header():
    """El default no cambia: quien no usa token sigue con la entrada de siempre."""
    entry = inst.mcp_entry("http", None, api_key_env=False, version=None)
    assert "headers" not in entry
    assert "bearer_token_env_var" not in inst.codex_mcp_block(entry)


def test_the_port_token_is_referenced_and_never_written():
    """Ni el JSON de Claude Code ni el TOML de Codex ven el secreto, solo el nombre de la variable.

    Los dos clientes resuelven lo mismo por caminos distintos y ninguno vale para el otro:
    Claude Code expande `${VAR}` dentro de `headers` —medido contra la 2.1.220—, y Codex **no
    expande nada** en TOML, pero tiene `bearer_token_env_var`, que además es obligatorio ahí:
    su validador rechaza un `bearer_token` literal en `streamable_http`.
    """
    entry = inst.mcp_entry("http", None, api_key_env=False, version=None, web_token_env=True)
    assert entry["headers"] == {"Authorization": "Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"}

    block = inst.codex_mcp_block(entry)
    data = tomllib.loads(block)
    server = data["mcp_servers"]["local-delegate"]
    assert server["bearer_token_env_var"] == "LOCAL_DELEGATE_WEB_TOKEN"
    assert server["url"].endswith("/mcp")
    # Lo que NO puede aparecer: la sintaxis que TOML no expande, y cualquier clave de secreto.
    assert "${" not in block
    assert "bearer_token =" not in block


def test_the_port_token_does_not_slip_into_a_stdio_entry():
    """El token protege el puerto del daemon; una entrada `stdio` no habla con ese puerto.

    Escribirlo ahí sería una cabecera muerta que invita a pensar que la entrada está autenticada.
    """
    entry = inst.mcp_entry("stdio", None, api_key_env=False, version=None, web_token_env=True)
    assert "headers" not in entry
    assert "LOCAL_DELEGATE_WEB_TOKEN" not in json.dumps(entry)


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


# --- Retirar los hooks huérfanos de instalaciones anteriores -------------------
# Es la primera operación del repo que **borra** ficheros del HOME del usuario, así que lo que
# se comprueba no es tanto qué se borró como **qué sobrevivió**.


def _with_orphans(home: Path) -> Path:
    """Reproduce el caso real: los huérfanos conviviendo con cosas que NO son nuestras."""
    root = home / ".claude" / "hooks"
    root.mkdir(parents=True, exist_ok=True)
    for name in inst.packaged_hook_names():
        (root / name).write_text("# instalacion anterior\n", encoding="utf-8")
    (root / "telemetry.jsonl").write_text('{"ok": true}\n', encoding="utf-8")
    (root / "third_party_hook.py").write_text("# ajeno\n", encoding="utf-8")
    (root / "__pycache__").mkdir(exist_ok=True)
    (root / "__pycache__" / "something.pyc").write_bytes(b"\x00")
    return root


def test_hook_names_come_from_the_package_not_from_a_constant(tmp_path):
    """`_SCRIPT_NAMES` no sirve: tiene tres y no incluye `hook_common.py`, que es huérfano real."""
    names = inst.packaged_hook_names()
    assert "hook_common.py" in names
    assert set(inst._SCRIPT_NAMES) <= names
    assert all(n.endswith(".py") for n in names), "__pycache__ no debe colarse"


def test_install_retires_the_orphans_and_touches_nothing_else(tmp_path):
    root = _with_orphans(tmp_path)
    foreign_before = {
        p.name: snapshot(p) if p.is_dir() else p.read_bytes()
        for p in root.iterdir()
        if p.name not in inst.packaged_hook_names()
    }

    assert _install(tmp_path) == 0

    for name in inst.packaged_hook_names():
        assert not (root / name).exists(), f"{name} debía retirarse de la raíz"
    for name, content in foreign_before.items():
        dest = root / name
        assert dest.exists(), f"{name} NO era nuestro y se borró"
        current = snapshot(dest) if dest.is_dir() else dest.read_bytes()
        assert current == content, f"{name} se modificó"


def test_the_good_install_survives_the_retirement(tmp_path):
    """El fallo peor posible: borrar `hooks/local-delegate/`, que es lo recién instalado."""
    _with_orphans(tmp_path)
    assert _install(tmp_path) == 0
    good_ones = tmp_path / ".claude" / "hooks" / inst.HOOKS_SUBDIR
    packaged = inst.packaged_hook_names() - set(inst._RETIRED_SCRIPTS)
    assert packaged, "sin scripts empaquetados este test no comprobaría nada"
    for name in packaged:
        assert (good_ones / name).is_file(), f"{name} debía seguir en {good_ones}"
    # Y la otra mitad: un retirado se reconoce como nuestro para poder limpiarlo, pero NO se
    # instala. Sin esto, meterlo en `packaged_hook_names()` podría hacer que volviera a copiarse.
    for name in inst._RETIRED_SCRIPTS:
        assert not (good_ones / name).exists(), f"{name} está retirado y no debe instalarse"


def test_a_retired_script_is_unregistered_and_cleaned(tmp_path):
    """Un script que deja de empaquetarse **no puede volverse inmortal**.

    Es el defecto que la revisión adversarial del plan encontró: la limpieza de huérfanos sale de
    `packaged_hook_names()`, que lista el directorio empaquetado, así que en cuanto el fichero
    desaparece de ahí su copia vieja deja de ser reconocible y nadie la borra jamás. Igual con
    `_is_ours`, que es quien quita la entrada de `settings.json`.

    Se simula una instalación anterior: el script en la raíz de `hooks/` (como lo dejaba la
    recipe vieja) y su entrada registrada en `settings.json`.
    """
    retired = inst._RETIRED_SCRIPTS[0]
    claude = tmp_path / ".claude"
    (claude / "hooks").mkdir(parents=True)
    old = claude / "hooks" / retired
    old.write_text("# instalado por una version anterior\n", encoding="utf-8")
    settings_path = claude / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": f"python ~/{retired}"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert _install(tmp_path) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    registered = json.dumps(settings.get("hooks", {}))
    assert retired not in registered, "la entrada del script retirado sigue en settings.json"
    assert not old.exists(), "la copia vieja del script retirado sigue en el disco"


def test_dry_run_retires_no_orphan(tmp_path):
    _with_orphans(tmp_path)
    before = snapshot(tmp_path)
    inst.apply(inst.plan_install(_opts(tmp_path)), dry_run=True, out=lambda *_a: None)
    assert snapshot(tmp_path) == before


def test_without_orphans_no_retirement_is_planned(tmp_path):
    """Idempotencia: la segunda pasada no tiene nada que hacer."""
    _with_orphans(tmp_path)
    _install(tmp_path)
    assert [a for a in inst.plan_install(_opts(tmp_path)) if a.kind == "prune"] == []


def test_a_directory_named_like_a_script_is_neither_counted_nor_touched(tmp_path):
    """Se borran ficheros, no lo que casualmente se llame igual.

    La primera versión de este test solo comprobaba que el directorio sobreviviera, y **pasaba
    igual con el `is_file()` quitado**: `unlink` sobre un directorio lanza `OSError` y el
    `except` del retirado se lo traga. O sea que no probaba nada. Lo caza la aserción de
    abajo — sin `is_file()`, el directorio entra en la lista y el `doctor` avisaría de un
    huérfano que no existe.
    """
    root = tmp_path / ".claude" / "hooks"
    root.mkdir(parents=True)
    (root / "hook_common.py").mkdir()

    assert inst.orphan_hook_scripts(tmp_path / ".claude") == [], "un directorio no es un script"

    _install(tmp_path)
    assert (root / "hook_common.py").is_dir(), "un directorio homónimo no es nuestro script"


def _shell_hook_command(home: Path) -> str | None:
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for group in settings.get("hooks", {}).get("PreToolUse", []):
        if group.get("matcher") == "Bash|PowerShell":
            return group["hooks"][0]["command"]
    return None


def test_enable_read_hook_ALSO_leaves_the_shell_hook_on(tmp_path, monkeypatch):
    """El mismo cruce instalador-script, para la otra mitad de la superficie de lectura.

    El hook de shell importa de `suggest_delegate_read`, así que aquí se comprueba de paso algo
    que ningún test de módulo puede ver: que la copia instalada tiene los dos ficheros y que el
    import entre ellos funciona con el `sys.path` que tiene un hook de verdad.
    """
    monkeypatch.delenv("LD_HOOK_READ_ENABLED", raising=False)
    _install(tmp_path, enable_read_hook=True)

    command = _shell_hook_command(tmp_path)
    assert command is not None, "el hook de shell no quedó registrado"

    large = tmp_path / "report.md"
    large.write_text("x" * 40_000, encoding="utf-8")
    hook_input = json.dumps({"tool_input": {"command": f"cat {large}"}})

    argv = shlex.split(command)
    argv[0] = sys.executable
    hooks_dir = tmp_path / ".claude" / "hooks" / "local-delegate"
    env = {**os.environ, "PYTHONPATH": str(hooks_dir)}
    env.pop("LD_HOOK_READ_ENABLED", None)
    # El bloqueo nace apagado; aquí se enciende a mano para ver que el camino entero funciona.
    env["LD_HOOK_READ_BLOCK"] = "1"
    # Sin backend no se bloquea, que es lo correcto, así que se apunta a uno que sí responde...
    # salvo que no hay ninguno en CI. Se comprueba entonces el caso que no depende de él.
    env["LOCAL_DELEGATE_BASE_URL"] = "http://127.0.0.1:9/v1"

    process = subprocess.run(argv, input=hook_input, capture_output=True, text=True, env=env)

    assert process.returncode == 0, f"el hook de shell falló: {process.stderr!r}"
    # Sin backend vivo no bloquea (REQ-F1-10). Lo que este test demuestra es que el script
    # instalado ARRANCA, importa a su vecino y decide, que es donde estaba el agujero.
    assert process.stdout.strip() == "", process.stdout
    assert "Traceback" not in process.stderr


# Tal como dejó `~/.codex/config.toml` el plugin de JetBrains el 2026-09-22: todo indentado dos
# espacios, sin comentarios salvo nuestro marcador de apertura, y SIN el de cierre. Con una
# entrada ajena justo después y más tablas detrás, que es lo que un emparejamiento de marcadores
# mal hecho se llevaría por delante.
_CODEX_REWRITTEN_BY_OTHER = """model = "x"

  [mcp_servers.git]
    command = "uvx"
    args = ["mcp-server-git"]

  # local-delegate:begin
  [mcp_servers.local-delegate]
    url = "http://127.0.0.1:9393/mcp"
    bearer_token_env_var = "LOCAL_DELEGATE_WEB_TOKEN"

  [mcp_servers.pycharm]
    url = "http://127.0.0.1:64342/sse"

  [projects.project]
    trust_level = "trusted"
"""


def test_codex_rewritten_by_another_program_is_replaced_without_duplicating(tmp_path):
    """La entrada indentada se reconoce, se reemplaza y no se duplica.

    Antes, la búsqueda exigía la cabecera al principio de la línea y no la veía: `install` añadía una segunda `[mcp_servers.local-delegate]`, el TOML
    quedaba inválido y Codex se quedaba sin ningún MCP.
    """
    assert tomllib.loads(_CODEX_REWRITTEN_BY_OTHER)  # el de partida es TOML válido
    entry = inst.mcp_entry("http", None, api_key_env=False, version=None)
    result = inst.upsert_codex_mcp(_CODEX_REWRITTEN_BY_OTHER, inst.codex_mcp_block(entry))

    data = tomllib.loads(result)
    assert result.count("mcp_servers.local-delegate]") == 1
    assert data["mcp_servers"]["pycharm"]["url"].endswith("/sse")
    assert data["mcp_servers"]["git"]["command"] == "uvx"
    assert data["projects"]["project"]["trust_level"] == "trusted"
    assert result.count(inst.TOML_BEGIN) == 1
    assert result.count(inst.TOML_END) == 1


def test_an_orphan_marker_does_not_take_what_follows(tmp_path):
    """Dos reinstalaciones seguidas sobre el fichero sin marcador de cierre.

    Emparejando marcadores, la segunda casaría el `begin` huérfano con el `end` escrito por la
    primera y borraría lo de en medio: `pycharm` y los proyectos. El huérfano tiene que desaparecer
    en la primera pasada, y la segunda tiene que dejar el fichero igual.
    """
    entry = inst.mcp_entry("http", None, api_key_env=False, version=None)
    block = inst.codex_mcp_block(entry)
    first = inst.upsert_codex_mcp(_CODEX_REWRITTEN_BY_OTHER, block)
    second = inst.upsert_codex_mcp(first, block)

    assert second == first
    data = tomllib.loads(second)
    assert "pycharm" in data["mcp_servers"]
    assert "project" in data["projects"]


def test_removing_the_entry_of_a_rewritten_codex_leaves_the_rest(tmp_path):
    result = inst.remove_codex_mcp(_CODEX_REWRITTEN_BY_OTHER)
    data = tomllib.loads(result)
    assert "local-delegate" not in data["mcp_servers"]
    assert set(data["mcp_servers"]) == {"git", "pycharm"}
    assert inst.TOML_BEGIN not in result


# --- Skills retiradas (REQ-013) -----------------------------------------------
def test_retired_skill_is_removed_from_every_target_and_foreign_one_stays(tmp_path, monkeypatch):
    """Renombrar la skill no puede dejar la copia vieja viva, ni llevarse una del usuario."""
    monkeypatch.setattr(inst, "_RETIRED_SKILLS", ("retired-test-skill",))
    targets = [
        tmp_path / ".claude" / "skills",
        inst.opencode_dir(tmp_path) / inst.OPENCODE_SKILL_SUBDIR,
    ]
    for target_dir in targets:
        (target_dir / "retired-test-skill").mkdir(parents=True)
        (target_dir / "retired-test-skill" / "SKILL.md").write_text("vieja\n", encoding="utf-8")
        (target_dir / "ajena").mkdir()
        (target_dir / "ajena" / "SKILL.md").write_text("del usuario\n", encoding="utf-8")

    assert _install(tmp_path, targets={"claude", "opencode"}) == 0

    for target_dir in targets:
        assert not (target_dir / "retired-test-skill").exists(), (
            f"sigue la retirada en {target_dir}"
        )
        assert (target_dir / "ajena").exists(), f"se borró la skill ajena en {target_dir}"
        assert (target_dir / inst.SKILL_NAME / "SKILL.md").is_file()


def test_no_retired_skills_means_no_skill_removal_planned(tmp_path, monkeypatch):
    monkeypatch.setattr(inst, "_RETIRED_SKILLS", ("retired-test-skill",))
    (tmp_path / ".claude" / "skills" / "ajena").mkdir(parents=True)
    actions = inst.plan_install(_opts(tmp_path))
    assert [a for a in actions if a.kind == "prune" and "skills" in str(a.target)] == []


def test_install_over_0_34_replaces_the_skill_and_the_blocks_name_the_new_one(tmp_path):
    """A6 (REQ-012/013): sobre una 0.34.0, la skill nueva queda y la vieja se va de cada destino."""
    home = make_home(tmp_path, complete=True)
    downgrade_to_0_34(home)
    skills = home / ".claude" / "skills"
    assert (skills / "delegacion-local").is_dir()

    assert _install(home, targets={"claude", "codex", "opencode"}) == 0

    for target_dir in (skills, inst.opencode_dir(home) / inst.OPENCODE_SKILL_SUBDIR):
        assert not (target_dir / "delegacion-local").exists(), target_dir
        assert (target_dir / "local-delegation" / "SKILL.md").is_file(), target_dir
    for md in live_memory_files(home):
        text = md.read_text(encoding="utf-8")
        assert "`local-delegation`" in text and "delegacion-local" not in text, md


def test_uninstall_also_removes_the_retired_skill(tmp_path):
    """Una máquina que pasó de la 0.34 sin `install` conserva la skill vieja: también es nuestra."""
    targets = [
        tmp_path / ".claude" / "skills",
        inst.opencode_dir(tmp_path) / inst.OPENCODE_SKILL_SUBDIR,
    ]
    for target_dir in targets:
        (target_dir / "delegacion-local").mkdir(parents=True)
        (target_dir / "delegacion-local" / "SKILL.md").write_text("vieja\n", encoding="utf-8")
        (target_dir / "ajena").mkdir()
        (target_dir / "ajena" / "SKILL.md").write_text("del usuario\n", encoding="utf-8")

    assert _uninstall(tmp_path, targets={"claude", "opencode"}) == 0

    for target_dir in targets:
        assert not (target_dir / "delegacion-local").exists(), target_dir
        assert (target_dir / "ajena" / "SKILL.md").is_file(), target_dir


# --- Migración de nombres retirados con sucesor (REQ-015, REQ-016, REQ-017) -----------------
# Registro sintético (con un alias vivo, que el real ya no tiene); el caso real va aparte.
_GONE_ENV = ("LD_OLD_GONE_VAR", "LD_GONE_VAR_NEW")
_GONE_ENV_2 = ("LD_OLD_SECOND_VAR", "LD_SECOND_VAR_NEW")
_GONE_SWITCH = ("old-gone-switch", "gone-switch-new")
_LIVE_ALIAS = ("LD_OLD_LIVE_VAR", "LD_LIVE_VAR_NEW")


def _retired_registry(monkeypatch):
    from local_delegate import deprecations

    def retired(names, surface):
        return deprecations.DeprecatedName(
            "retired", *names, "0.38.0", "0.40.0", retired_from=surface
        )

    entries = (
        retired(_GONE_ENV, "env_var"),
        retired(_GONE_ENV_2, "env_var"),
        retired(_GONE_SWITCH, "switch_file"),
        deprecations.DeprecatedName("env_var", *_LIVE_ALIAS, "0.37.0"),
    )
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", entries)


def _settings_home(tmp_path, settings: dict | None = None, raw: bytes | None = None) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    path = home / ".claude" / "settings.json"
    if raw is not None:
        path.write_bytes(raw)
    elif settings is not None:
        path.write_bytes(json.dumps(settings, indent=2).encode("utf-8"))
    return home


def _migrate(home, data_dir=None) -> int:
    return inst.apply(
        inst.plan_retired_name_migration(home, data_dir), dry_run=False, out=lambda *a: None
    )


def _settings(home) -> dict:
    return json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8-sig"))


def _backups(home) -> list[Path]:
    return sorted((home / ".claude").glob("settings.json.retired-names*.bak"))


def test_retired_name_migration_renames_the_key_in_place(monkeypatch, tmp_path):
    """(a) Solo el viejo: pasa a llamarse como el nuevo, mismo valor y misma posición."""
    _retired_registry(monkeypatch)
    original = {
        "hooks": {"PreToolUse": []},
        "env": {"FIRST": "1", _GONE_ENV[0]: "", "LAST": "z"},
    }
    home = _settings_home(tmp_path, original)
    assert _migrate(home) == 0
    data = _settings(home)
    assert list(data["env"]) == ["FIRST", _GONE_ENV[1], "LAST"]
    assert data["env"][_GONE_ENV[1]] == ""
    expected = dict(original, env={"FIRST": "1", _GONE_ENV[1]: "", "LAST": "z"})
    assert data == expected


def test_retired_name_migration_drops_the_old_key_when_both_exist(monkeypatch, tmp_path):
    """(b) Los dos: queda el nuevo con su valor (ya ganaba)."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": {_GONE_ENV[0]: "a", _GONE_ENV[1]: "b"}})
    assert _migrate(home) == 0
    assert _settings(home)["env"] == {_GONE_ENV[1]: "b"}


def test_retired_name_migration_renames_the_switch_file(monkeypatch, tmp_path):
    """(c) Interruptor solo viejo → existe el nuevo y no el viejo; (k) sin `.bak`."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": {"OTHER": "x"}})
    before = (home / ".claude" / "settings.json").read_bytes()
    (home / ".claude" / _GONE_SWITCH[0]).write_text("", encoding="utf-8")
    assert _migrate(home) == 0
    assert (home / ".claude" / _GONE_SWITCH[1]).is_file()
    assert not (home / ".claude" / _GONE_SWITCH[0]).exists()
    assert (home / ".claude" / "settings.json").read_bytes() == before
    assert _backups(home) == []


def test_retired_name_migration_removes_the_old_switch_when_both_exist(monkeypatch, tmp_path):
    """(d) Los dos interruptores → queda solo el nuevo, con su contenido."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path)
    (home / ".claude" / _GONE_SWITCH[0]).write_text("old", encoding="utf-8")
    (home / ".claude" / _GONE_SWITCH[1]).write_text("new", encoding="utf-8")
    assert _migrate(home) == 0
    assert not (home / ".claude" / _GONE_SWITCH[0]).exists()
    assert (home / ".claude" / _GONE_SWITCH[1]).read_text(encoding="utf-8") == "new"


def test_retired_name_migration_leaves_a_directory_switch_alone(monkeypatch, tmp_path):
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path)
    (home / ".claude" / _GONE_SWITCH[0]).mkdir()
    assert inst.plan_retired_name_migration(home) == []
    assert (home / ".claude" / _GONE_SWITCH[0]).is_dir()


def test_retired_name_migration_backs_up_without_overwriting(monkeypatch, tmp_path):
    """(e) La copia tiene los bytes originales; una segunda migración no la pisa."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": {_GONE_ENV[0]: "1"}})
    path = home / ".claude" / "settings.json"
    first_bytes = path.read_bytes()
    assert _migrate(home) == 0
    first = home / ".claude" / "settings.json.retired-names.bak"
    assert _backups(home) == [first]
    assert first.read_bytes() == first_bytes

    path.write_bytes(json.dumps({"env": {_GONE_ENV_2[0]: "2"}}).encode("utf-8"))
    second_bytes = path.read_bytes()
    assert _migrate(home) == 0
    backups = _backups(home)
    assert len(backups) == 2
    assert first.read_bytes() == first_bytes, "la segunda migración pisó la primera copia"
    (dated,) = [b for b in backups if b != first]
    assert dated.read_bytes() == second_bytes
    assert dated.name.startswith("settings.json.retired-names.2")


def test_retired_name_migration_three_times_in_a_second_keeps_three_copies(monkeypatch, tmp_path):
    """(l) Fecha en UTC con sufijo de desempate: nunca se pisa una copia, ni en el mismo segundo."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path)
    path = home / ".claude" / "settings.json"
    contents = []
    for n in range(3):
        path.write_bytes(json.dumps({"env": {_GONE_ENV[0]: str(n)}}).encode("utf-8"))
        contents.append(path.read_bytes())
        assert _migrate(home) == 0
    backups = _backups(home)
    assert len(backups) == 3
    assert sorted(b.read_bytes() for b in backups) == sorted(contents)


def test_retired_name_backup_tiebreaks_within_the_same_second(monkeypatch, tmp_path):
    """(l) Con el reloj parado, las copias llevan la misma fecha y el sufijo `-1`, `-2`…"""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": {}})
    path = home / ".claude" / "settings.json"
    names = [inst._retired_names_backup(path, b"%d" % n, "20261021120000").name for n in range(4)]
    assert names == [
        "settings.json.retired-names.bak",
        "settings.json.retired-names.20261021120000.bak",
        "settings.json.retired-names.20261021120000-1.bak",
        "settings.json.retired-names.20261021120000-2.bak",
    ]
    assert [(home / ".claude" / n).read_bytes() for n in names] == [b"0", b"1", b"2", b"3"]


def test_retired_name_migration_keeps_crlf(monkeypatch, tmp_path):
    """(f) Un `settings.json` en CRLF sigue en CRLF."""
    _retired_registry(monkeypatch)
    text = json.dumps({"env": {_GONE_ENV[0]: "1"}}, indent=2).replace("\n", "\r\n")
    home = _settings_home(tmp_path, raw=text.encode("utf-8"))
    assert _migrate(home) == 0
    raw = (home / ".claude" / "settings.json").read_bytes()
    assert b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")
    assert _settings(home)["env"] == {_GONE_ENV[1]: "1"}


def test_retired_name_migration_keeps_the_bom(monkeypatch, tmp_path):
    """(g) Con BOM (PowerShell 5.1 con `-Encoding UTF8`): se migra y lo conserva."""
    _retired_registry(monkeypatch)
    raw = b"\xef\xbb\xbf" + json.dumps({"env": {_GONE_ENV[0]: "1"}}).encode("utf-8")
    home = _settings_home(tmp_path, raw=raw)
    assert _migrate(home) == 0
    after = (home / ".claude" / "settings.json").read_bytes()
    assert after.startswith(b"\xef\xbb\xbf") and not after.startswith(b"\xef\xbb\xbf" * 2)
    assert _settings(home)["env"] == {_GONE_ENV[1]: "1"}


def test_retired_name_migration_leaves_a_live_alias_alone(monkeypatch, tmp_path):
    """(h) Un alias vigente aún funciona: no se migra (control: el retirado sí)."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": {_LIVE_ALIAS[0]: "1", _GONE_ENV[0]: "2"}})
    assert _migrate(home) == 0
    assert _settings(home)["env"] == {_LIVE_ALIAS[0]: "1", _GONE_ENV[1]: "2"}


def test_retired_name_migration_records_one_date_per_name(monkeypatch, tmp_path):
    """(i) Registro con una fecha por nombre, sin valores, y fusión en una segunda migración."""
    _retired_registry(monkeypatch)
    data_dir = tmp_path / "data"
    home = _settings_home(tmp_path, {"env": {_GONE_ENV[0]: "s3cr3t-value"}})
    assert _migrate(home, data_dir) == 0
    record_path = data_dir / inst.RETIRED_NAMES_MIGRATION_FILE
    first = json.loads(record_path.read_text(encoding="utf-8"))
    assert list(first["names"]) == [_GONE_ENV[0]]
    assert "s3cr3t-value" not in record_path.read_text(encoding="utf-8")

    (home / ".claude" / _GONE_SWITCH[0]).write_text("", encoding="utf-8")
    assert _migrate(home, data_dir) == 0
    second = json.loads(record_path.read_text(encoding="utf-8"))["names"]
    assert set(second) == {_GONE_ENV[0], _GONE_SWITCH[0]}
    assert second[_GONE_ENV[0]] == first["names"][_GONE_ENV[0]]
    assert set(inst.read_migration_record(data_dir)) == set(second)


def test_the_real_registry_no_longer_migrates_the_seven_names(tmp_path):
    """REQ-015 con el registro real desde la 0.41.0 (retire-seven-names): las cuatro variables y el
    interruptor viejos ya no se migran; `install`/`update` no los tocan. El control positivo de la
    migración, con un registro sintético, son los tests de `_retired_registry` de arriba."""
    from test_deprecations import SEVEN_RETIRED

    env_old_names = [old for old, _new, surface in SEVEN_RETIRED if surface == "env_var"]
    (switch_old,) = (old for old, _new, surface in SEVEN_RETIRED if surface == "switch_file")
    original_env = {"KEEP": "k", **{old: f"v{i}" for i, old in enumerate(env_old_names)}}
    home = _settings_home(tmp_path, {"hooks": {}, "env": original_env})
    (home / ".claude" / switch_old).write_text("", encoding="utf-8")
    data_dir = tmp_path / "data"

    assert inst.plan_retired_name_migration(home, data_dir) == []
    assert _migrate(home, data_dir) == 0
    assert _settings(home) == {"hooks": {}, "env": original_env}
    assert (home / ".claude" / switch_old).is_file()
    assert not (home / ".claude" / "local-delegate-block-off").exists()


def test_retired_name_migration_never_writes_the_record_in_the_real_log_dir(monkeypatch, tmp_path):
    """(j) HOME simulado y sin `LOCAL_DELEGATE_LOG_DIR`: el `LOG_DIR` real no recibe el registro."""
    from local_delegate import config

    _retired_registry(monkeypatch)
    real_log_dir = tmp_path / "real-log-dir"
    real_log_dir.mkdir()
    monkeypatch.setattr(config, "LOG_DIR", real_log_dir)
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)
    home = _settings_home(tmp_path, {"env": {_GONE_ENV[0]: "1"}})
    assert inst.data_dir_for(home) is None
    lines: list[str] = []
    assert inst.apply(inst.plan_retired_name_migration(home), dry_run=False, out=lines.append) == 0
    assert list(real_log_dir.iterdir()) == []
    assert _settings(home)["env"] == {_GONE_ENV[1]: "1"}, "sin registro, la migración va igual"
    assert any(inst.t("install.migrate.record_skipped") in line for line in lines)
    # Control: con la variable puesta, el directorio de datos es el elegido.
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(real_log_dir))
    assert inst.data_dir_for(home) == real_log_dir


def test_retired_name_migration_without_settings_write_has_no_backup(monkeypatch, tmp_path):
    """(k) `env` ilegible: no escribe, no deja copia, lo dice con el motivo; el interruptor va igual."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, raw=b"{no json " + _GONE_ENV[0].encode())
    before = (home / ".claude" / "settings.json").read_bytes()
    (home / ".claude" / _GONE_SWITCH[0]).write_text("", encoding="utf-8")
    lines: list[str] = []
    assert inst.apply(inst.plan_retired_name_migration(home), dry_run=False, out=lines.append) == 0
    assert (home / ".claude" / "settings.json").read_bytes() == before
    assert _backups(home) == []
    assert (home / ".claude" / _GONE_SWITCH[1]).is_file()
    assert any(inst.t("install.migrate.reason.not_json") in line for line in lines), lines


def test_retired_name_migration_env_not_an_object_is_left_alone(monkeypatch, tmp_path):
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": [_GONE_ENV[0]]})
    before = (home / ".claude" / "settings.json").read_bytes()
    lines: list[str] = []
    assert inst.apply(inst.plan_retired_name_migration(home), dry_run=False, out=lines.append) == 0
    assert (home / ".claude" / "settings.json").read_bytes() == before
    assert any(inst.t("install.migrate.reason.env_not_object") in line for line in lines)


def test_retired_name_migration_is_idempotent(monkeypatch, tmp_path):
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": {_GONE_ENV[0]: "1", _GONE_ENV_2[0]: "2"}})
    (home / ".claude" / _GONE_SWITCH[0]).write_text("", encoding="utf-8")
    plan = inst.plan_retired_name_migration(home)
    assert [a.kind for a in plan] == ["migrate", "migrate"], "todas las claves en una acción"
    assert _migrate(home) == 0
    assert inst.plan_retired_name_migration(home) == []


def test_retired_name_migration_shows_only_names(monkeypatch, tmp_path):
    """REQ-017: la descripción y el literal llevan nombres, nunca valores."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": {_GONE_ENV[0]: "s3cr3t-value", "OTHER": "x"}})
    lines: list[str] = []
    inst.apply(inst.plan_retired_name_migration(home), dry_run=True, out=lines.append)
    text = "\n".join(lines)
    assert f"{_GONE_ENV[0]} -> {_GONE_ENV[1]}" in text
    assert "s3cr3t-value" not in text


def test_retired_name_migration_ignores_the_process_environment(monkeypatch, tmp_path):
    """REQ-017: los viejos en `os.environ` y no en `settings.json` ni en `~/.claude/` → plan vacío."""
    _retired_registry(monkeypatch)
    monkeypatch.setenv(_GONE_ENV[0], "1")
    home = _settings_home(tmp_path, {"env": {"OTHER": "x"}})
    assert inst.plan_retired_name_migration(home) == []
    # Control: el mismo nombre en `env` sí se planifica.
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"env": {_GONE_ENV[0]: "1"}}), encoding="utf-8"
    )
    assert len(inst.plan_retired_name_migration(home)) == 1


def test_retired_name_migration_failure_is_counted(monkeypatch, tmp_path):
    """Si no se puede escribir `settings.json`, la acción falla y cuenta, y no lo deja a medias."""
    _retired_registry(monkeypatch)
    home = _settings_home(tmp_path, {"env": {_GONE_ENV[0]: "1"}})
    before = (home / ".claude" / "settings.json").read_bytes()

    def refuse(self, data):
        raise PermissionError(13, "denied")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_bytes", refuse)
        assert _migrate(home) == 1
    assert (home / ".claude" / "settings.json").read_bytes() == before


def test_install_plans_the_migration_for_claude(monkeypatch, tmp_path):
    """REQ-016: con Claude en el plan, la migración va antes de cualquier acción sobre settings.json."""
    _retired_registry(monkeypatch)
    home = make_home(tmp_path, complete=False)
    settings_path = home / ".claude" / "settings.json"
    settings_path.write_text(
        json.dumps({"env": {_GONE_ENV[0]: "s3cr3t-value", "OTHER": "x"}}), encoding="utf-8"
    )
    actions = inst.plan_install(_opts(home, targets={"claude"}, enable_read_hook=True))
    kinds = [a.kind for a in actions]
    assert "migrate" in kinds and "settings" in kinds
    assert kinds.index("migrate") < kinds.index("settings")

    before = snapshot(tmp_path)
    lines: list[str] = []
    inst.apply(actions, dry_run=True, out=lines.append)
    assert snapshot(tmp_path) == before, "--dry-run escribió algo (¿registro o copia?)"
    assert "s3cr3t-value" not in "\n".join(lines)
    assert any("[migrate]" in line for line in lines)

    assert inst.apply(actions, dry_run=False, out=lambda *a: None) == 0
    data = _settings(home)
    assert data["env"] == {_GONE_ENV[1]: "s3cr3t-value", "OTHER": "x"}
    assert inst.read_hook_registered(home / ".claude"), "la migración pisó el registro de hooks"


def test_install_without_claude_does_not_plan_the_migration(monkeypatch, tmp_path):
    _retired_registry(monkeypatch)
    home = make_home(tmp_path, complete=False)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"env": {_GONE_ENV[0]: "1"}}), encoding="utf-8"
    )
    actions = inst.plan_install(_opts(home, targets={"codex"}))
    assert "migrate" not in [a.kind for a in actions]
    # Control: con Claude, sí.
    actions = inst.plan_install(_opts(home, targets={"claude"}))
    assert "migrate" in [a.kind for a in actions]
