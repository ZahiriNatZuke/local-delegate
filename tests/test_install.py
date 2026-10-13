"""Tests del instalador de la integración (hooks, skill, memoria, entrada MCP).

Todo corre contra un HOME de prueba (`tmp_path`); ninguna prueba toca el HOME real.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path, PureWindowsPath

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

    large = tmp_path / "grande.txt"
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
    codex_config.write_text('[mcp_servers.otro]\ncommand = "foo"\n', encoding="utf-8")

    _install(tmp_path)
    assert _uninstall(tmp_path) == 0

    assert not (tmp_path / ".claude" / "hooks" / "local-delegate").exists()
    assert not (tmp_path / ".claude" / "skills" / "local-delegation").exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "~/mio.sh"}]}]}
    assert memory.read_text(encoding="utf-8") == "# Mis reglas\n"
    remaining = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    assert list(remaining["mcp_servers"]) == ["otro"]
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
    (root / "hook_de_terceros.py").write_text("# ajeno\n", encoding="utf-8")
    (root / "__pycache__").mkdir(exist_ok=True)
    (root / "__pycache__" / "algo.pyc").write_bytes(b"\x00")
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

    large = tmp_path / "informe.md"
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

  [projects.proyecto]
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
    assert data["projects"]["proyecto"]["trust_level"] == "trusted"
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
    assert "proyecto" in data["projects"]


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
