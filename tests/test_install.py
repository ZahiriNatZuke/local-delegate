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

from conftest import snapshot

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


def _comando_del_hook_de_read(home: Path) -> str | None:
    """El comando de Read tal y como quedó escrito en settings.json, o None si no hay."""
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for grupo in settings.get("hooks", {}).get("PreToolUse", []):
        if grupo.get("matcher") == "Read":
            return grupo["hooks"][0]["command"]
    return None


def test_enable_read_hook_deja_el_hook_REALMENTE_encendido(tmp_path, monkeypatch):
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

    comando = _comando_del_hook_de_read(tmp_path)
    assert comando is not None, "el hook de Read no quedó registrado"

    grande = tmp_path / "grande.txt"
    grande.write_text("x" * 40_000, encoding="utf-8")  # 39 KB: por encima de la banda «strong»
    entrada = json.dumps({"tool_input": {"file_path": str(grande)}})

    # Se respeta el comando escrito, cambiando SOLO el intérprete: el registrado es un nombre
    # resuelto por PATH ("python"/"python3") que en el runner puede no ser el de la suite.
    argv = shlex.split(comando)
    argv[0] = sys.executable
    entorno = {**os.environ, "PYTHONPATH": str(tmp_path / ".claude" / "hooks" / "local-delegate")}
    entorno.pop("LD_HOOK_READ_ENABLED", None)

    salida = subprocess.run(argv, input=entrada, capture_output=True, text=True, env=entorno).stdout

    assert "additionalContext" in salida, (
        f"instalado con --enable-read-hook y sin la variable, el hook no sugirió nada.\n"
        f"comando registrado: {comando!r}\nsalida: {salida!r}"
    )


def test_sin_la_bandera_el_hook_de_read_no_se_registra_ni_sugiere(tmp_path, monkeypatch):
    """Control negativo del test de arriba.

    Sin él, el anterior pasaría igual con un hook que sugiriera **siempre**, que es el fallo
    opuesto y peor: ruido en cada lectura de quien nunca pidió el experimento.
    """
    monkeypatch.delenv("LD_HOOK_READ_ENABLED", raising=False)
    _install(tmp_path)
    assert _comando_del_hook_de_read(tmp_path) is None


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
    # Una acción puede ocupar varias líneas: la suya, y debajo indentado el literal que va a
    # escribir. Lo que este test defiende es que NINGUNA línea anuncia una escritura de verdad.
    assert lines and all(line.startswith(("[dry-run]", "          ")) for line in lines)
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".codex").exists()


def test_dry_run_enseña_el_comando_literal_de_cada_hook(tmp_path):
    """No basta con «registra 2 hook(s)»: el defecto puede vivir en el string generado.

    Es exactamente lo que pasó el 2026-07-30 en Windows — un comando de shell sin comillas dejó
    los hooks registrados y muertos, y el plan del `--dry-run` decía que todo iba bien porque solo
    contaba cuántos eran. Un resumen no es revisable; el comando sí.
    """
    lines: list[str] = []
    inst.apply(inst.plan_install(_opts(tmp_path)), dry_run=True, out=lines.append)
    salida = "\n".join(lines)
    for script, _event, _matcher in inst._HOOK_EVENTS:
        assert script in salida, f"el plan no enseña el comando de {script}"
    # Y la entrada MCP, por el mismo motivo: es lo otro que se escribe generado y no copiado.
    assert '"command": "uvx"' in salida or 'command = "uvx"' in salida


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


def test_sin_pedirlo_la_entrada_http_no_lleva_cabecera():
    """El default no cambia: quien no usa token sigue con la entrada de siempre."""
    entry = inst.mcp_entry("http", None, api_key_env=False, version=None)
    assert "headers" not in entry
    assert "bearer_token_env_var" not in inst.codex_mcp_block(entry)


def test_el_token_del_puerto_se_referencia_y_nunca_se_escribe():
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
    servidor = data["mcp_servers"]["local-delegate"]
    assert servidor["bearer_token_env_var"] == "LOCAL_DELEGATE_WEB_TOKEN"
    assert servidor["url"].endswith("/mcp")
    # Lo que NO puede aparecer: la sintaxis que TOML no expande, y cualquier clave de secreto.
    assert "${" not in block
    assert "bearer_token =" not in block


def test_el_token_del_puerto_no_se_cuela_en_una_entrada_stdio():
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


def _con_huerfanos(home: Path) -> Path:
    """Reproduce el caso real: los huérfanos conviviendo con cosas que NO son nuestras."""
    raiz = home / ".claude" / "hooks"
    raiz.mkdir(parents=True, exist_ok=True)
    for nombre in inst.packaged_hook_names():
        (raiz / nombre).write_text("# instalacion anterior\n", encoding="utf-8")
    (raiz / "telemetry.jsonl").write_text('{"ok": true}\n', encoding="utf-8")
    (raiz / "hook_de_terceros.py").write_text("# ajeno\n", encoding="utf-8")
    (raiz / "__pycache__").mkdir(exist_ok=True)
    (raiz / "__pycache__" / "algo.pyc").write_bytes(b"\x00")
    return raiz


def test_los_nombres_de_hooks_salen_del_paquete_y_no_de_una_constante(tmp_path):
    """`_SCRIPT_NAMES` no sirve: tiene tres y no incluye `hook_common.py`, que es huérfano real."""
    nombres = inst.packaged_hook_names()
    assert "hook_common.py" in nombres
    assert set(inst._SCRIPT_NAMES) <= nombres
    assert all(n.endswith(".py") for n in nombres), "__pycache__ no debe colarse"


def test_install_retira_los_huerfanos_y_no_toca_nada_mas(tmp_path):
    raiz = _con_huerfanos(tmp_path)
    ajenos_antes = {
        p.name: snapshot(p) if p.is_dir() else p.read_bytes()
        for p in raiz.iterdir()
        if p.name not in inst.packaged_hook_names()
    }

    assert _install(tmp_path) == 0

    for nombre in inst.packaged_hook_names():
        assert not (raiz / nombre).exists(), f"{nombre} debía retirarse de la raíz"
    for nombre, contenido in ajenos_antes.items():
        destino = raiz / nombre
        assert destino.exists(), f"{nombre} NO era nuestro y se borró"
        actual = snapshot(destino) if destino.is_dir() else destino.read_bytes()
        assert actual == contenido, f"{nombre} se modificó"


def test_la_instalacion_buena_sobrevive_al_retirado(tmp_path):
    """El fallo peor posible: borrar `hooks/local-delegate/`, que es lo recién instalado."""
    _con_huerfanos(tmp_path)
    assert _install(tmp_path) == 0
    buenos = tmp_path / ".claude" / "hooks" / inst.HOOKS_SUBDIR
    for nombre in inst.packaged_hook_names():
        assert (buenos / nombre).is_file(), f"{nombre} debía seguir en {buenos}"


def test_dry_run_no_retira_ningun_huerfano(tmp_path):
    _con_huerfanos(tmp_path)
    antes = snapshot(tmp_path)
    inst.apply(inst.plan_install(_opts(tmp_path)), dry_run=True, out=lambda *_a: None)
    assert snapshot(tmp_path) == antes


def test_sin_huerfanos_no_se_planifica_el_retirado(tmp_path):
    """Idempotencia: la segunda pasada no tiene nada que hacer."""
    _con_huerfanos(tmp_path)
    _install(tmp_path)
    assert [a for a in inst.plan_install(_opts(tmp_path)) if a.kind == "prune"] == []


def test_un_directorio_con_nombre_de_script_ni_se_cuenta_ni_se_toca(tmp_path):
    """Se borran ficheros, no lo que casualmente se llame igual.

    La primera versión de este test solo comprobaba que el directorio sobreviviera, y **pasaba
    igual con el `is_file()` quitado**: `unlink` sobre un directorio lanza `OSError` y el
    `except` del retirado se lo traga. O sea que no probaba nada. Lo caza la aserción de
    abajo — sin `is_file()`, el directorio entra en la lista y el `doctor` avisaría de un
    huérfano que no existe.
    """
    raiz = tmp_path / ".claude" / "hooks"
    raiz.mkdir(parents=True)
    (raiz / "hook_common.py").mkdir()

    assert inst.orphan_hook_scripts(tmp_path / ".claude") == [], "un directorio no es un script"

    _install(tmp_path)
    assert (raiz / "hook_common.py").is_dir(), "un directorio homónimo no es nuestro script"
