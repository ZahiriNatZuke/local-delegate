"""Aislamiento global de artefactos runtime durante la suite."""

from __future__ import annotations

import contextlib
import importlib
import json
import socket
import struct
import sys
import threading
from pathlib import Path

import pytest

from local_delegate import config, i18n, install

#: Idioma con el que corre la suite (REQ-043): los asserts en español valen en cualquier máquina.
#: Los tests de inglés y los de detección lo sobrescriben con su `monkeypatch`.
SUITE_LANGUAGE = "es"


@pytest.fixture(scope="session", autouse=True)
def env_without_package_variables():
    """Corre la suite como si NINGUNA variable del paquete estuviera definida.

    La suite tiene que dar el mismo resultado en la máquina de quien la escribe, en la de quien
    tiene el daemon instalado y en CI. Antes no lo daba: con `LOCAL_DELEGATE_WEB_TOKEN` puesta
    —lo normal en cualquier máquina con el daemon andando— cuatro tests del daemon esperaban 200
    y recibían 401, y el fallo parecía del cambio que estuvieras haciendo. En CI nunca se veía,
    porque allí esa variable no existe.

    Se recarga el módulo en vez de reasignar constantes una por una a propósito: los defaults
    viven en `config.py` y copiarlos aquí crearía una segunda fuente que se desactualiza sola.
    La lista de nombres tampoco se escribe a mano — `config.ENVIRONMENT_VARIABLES` se alimenta de
    las lecturas reales del módulo, así que una opción nueva queda cubierta sin tocar esto.
    """
    with pytest.MonkeyPatch.context() as mp:
        for name in config.ENVIRONMENT_VARIABLES:
            mp.delenv(name, raising=False)
        # La única que se fija en vez de quitarse: sin ella, el idioma saldría del sistema de quien
        # corre la suite (REQ-043).
        mp.setenv("LOCAL_DELEGATE_LANG", SUITE_LANGUAGE)
        importlib.reload(config)
        yield
    importlib.reload(config)  # deja el proceso como estaba para lo que venga después


@pytest.fixture(autouse=True)
def isolate_runtime_logs(tmp_path, monkeypatch):
    """Evita que mocks de tests contaminen los logs reales del usuario.

    También en el entorno (REQ-043 b): los hooks lanzados como subproceso resuelven su directorio
    de datos por su cuenta (`hook_common.log_dir`), y sin la variable leerían el `language.json`
    real del usuario. Y se olvida el idioma cacheado, que depende de `config.LOG_DIR`.
    """
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path))
    i18n.reset()
    yield
    i18n.reset()


@pytest.fixture(autouse=True)
def no_saved_model_list():
    """Vacía la última lista buena de `/v1/models` que el sondeo guarda por URL (REQ-021).

    Sin esto, un test que sondea con éxito dejaría su lista a los siguientes, y un «backend caído»
    devolvería modelos de otro test. Se mira en `sys.modules` en vez de importar `server`: si nadie
    lo ha importado todavía, no hay nada guardado.
    """

    def clear() -> None:
        lists = getattr(sys.modules.get("local_delegate.server"), "_LAST_GOOD_LISTS", None)
        if lists is not None:
            lists.clear()

    clear()
    yield
    clear()


@pytest.fixture(autouse=True)
def turn_and_topology_zeroed():
    """Cada test empieza sin nadie en el turno del daemon y sin foto de topología en caché.

    El turno es un estado único del proceso (`server._turn`): sin esto, una operación que un test
    dejara en `activos` o en la cola haría esperar a las del siguiente. Y la caché de `topology`
    va por (ruta, mtime, tamaño): dos `tmp_path` distintos pueden coincidir en las tres. Como en
    `no_saved_model_list`, se mira `sys.modules` para no importar nada que nadie usa.
    """

    def clear() -> None:
        topology = sys.modules.get("local_delegate.topology")
        if topology is not None:
            topology._forget()
        reset = getattr(sys.modules.get("local_delegate.server"), "_reset_turn", None)
        if reset is not None:
            reset()

    clear()
    yield
    clear()


# --- T11: la consulta del CLI al daemon nunca llega al daemon real -----------------------------
DEAD_PORT = pytest.StashKey[int]()
CUT_DAEMON = pytest.StashKey["RejectingServer"]()


class RejectingServer:
    """Acepta cada conexión y la cierra en el acto con un RST (`SO_LINGER` a 0).

    Es el «daemon apagado» de la suite, y rápido: en Windows conectar a un puerto cerrado tarda
    ~2,1 s en dar `ConnectError` (el sistema reintenta el SYN), y esto da un `ReadError` en ~0,02 s.
    Cuenta las conexiones, para que un test compruebe que la consulta llegó aquí y no a otro sitio.
    """

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self._thread = threading.Thread(target=self._serve, daemon=True, name="daemon-cut")
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return  # cerrado al terminar la sesión
            self.accepted += 1
            with contextlib.suppress(OSError):
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            conn.close()

    def close(self) -> None:
        self.sock.close()
        self._thread.join(timeout=5)


@pytest.fixture(scope="session")
def _rejecting_server():
    server = RejectingServer()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def real_daemon_down(request, monkeypatch, _rejecting_server):
    """El CLI y `doctor` preguntan al daemon (puerto y token web, los de `doctor`) por la config y
    el estado de llama-swap. En la suite esa consulta va a un servidor local que corta cada conexión
    (`RejectingServer`): sin esto, un test de `llamaswap residency` sin `--config` leería la ruta
    del daemon de verdad y podría acabar escribiendo en la config real de llama-swap.

    Se parchean `cli._daemon_target` y `checks._llamaswap_daemon_destination`, y no
    `config.WEB_PORT`: este último lo comparan con las entradas de los clientes otros tests
    (`test_checks.py`), y cambiarlo para todos los rompería. El puerto queda en
    `request.node.stash[DEAD_PORT]` para que un test compruebe que la fixture se aplicó sin
    pedirla (si dejara de ser autouse, no habría puerto guardado).
    """
    port = _rejecting_server.port
    request.node.stash[DEAD_PORT] = port
    request.node.stash[CUT_DAEMON] = _rejecting_server
    monkeypatch.setattr("local_delegate.cli._daemon_target", lambda: ("127.0.0.1", port, {}))
    monkeypatch.setattr(
        "local_delegate.checks._llamaswap_daemon_destination", lambda: ("127.0.0.1", port, {})
    )


@pytest.fixture
def browser_locale() -> str:
    """`locale` del navegador de los tests del panel (REQ-043): el panel elige idioma por el
    navegador (REQ-020), no por la variable. Los tests de inglés lo sobrescriben con `en-US`."""
    return "es-ES"


@pytest.fixture
def new_page(browser_locale):
    """`browser.new_page(...)` con el `locale` del fixture de arriba, salvo que se pase otro."""

    def make(browser, **kwargs):
        kwargs.setdefault("locale", browser_locale)
        return browser.new_page(**kwargs)

    return make


@pytest.fixture
def reload_config(tmp_path):
    """Recarga `config` con variables de entorno REALES, y lo deja todo como estaba al terminar.

    Hace falta cuando lo que se prueba depende de lo que `config` calcula al importar: parchear una
    constante en caliente no recalcula lo que se derivó de ella, y el test saldría verde con el
    defecto vivo (F3, tarea 25). Apunta el backend a `http://test-backend/v1`.

    La recarga deshace el aislamiento de logs de `isolate_runtime_logs` (`LOG_DIR` y `USAGE_LOG`
    volverían a las rutas reales del usuario), así que se vuelve a aplicar después de cada recarga.
    """
    mp = pytest.MonkeyPatch()

    def isolate_logs() -> None:
        config.LOG_DIR = tmp_path
        config.USAGE_LOG = tmp_path / "usage.jsonl"

    def apply(**variables: str) -> None:
        mp.setenv("LOCAL_DELEGATE_BASE_URL", "http://test-backend/v1")
        for name, value in variables.items():
            mp.setenv(name, value)
        importlib.reload(config)
        isolate_logs()

    yield apply
    mp.undo()
    importlib.reload(config)
    isolate_logs()


# --- HOME simulado, compartido por test_checks.py y test_doctor.py ------------
def make_home(tmp_path: Path, *, claude=True, codex=True, opencode=True, complete=True) -> Path:
    """Arma un HOME de mentira. Con ``complete=False`` los clientes existen pero vacíos.

    Lo escribe con las funciones del propio ``install`` (no con literales) para que el HOME
    «completo» sea el que produce el instalador de verdad y no una idea de cómo debería ser.
    """
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # El bloque empaquetado y no un texto cualquiera: desde D12 `scaffold.memory` da `warn` con
    # un bloque que no sea uno de los de `install.packaged_memory_blocks()`.
    memory_block = install.packaged_memory_blocks()[0]
    if claude:
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True)
        if complete:
            hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
            hooks_dir.mkdir(parents=True)
            # Los scripts de verdad, byte a byte: `scaffold.hook_files` compara contra los del
            # paquete, y un «# hook» de relleno contaría como hooks de otra versión.
            for script in (install.resources_dir() / "hooks").glob("*.py"):
                (hooks_dir / script.name).write_bytes(script.read_bytes())
            entries = [
                (event, matcher, install.hook_command(hooks_dir, script, "python"))
                for script, event, matcher in install._HOOK_EVENTS
            ]
            settings, _removed = install.merge_hook_settings({}, entries, hooks_dir)
            (claude_dir / "settings.json").write_text(
                json.dumps(settings, indent=2), encoding="utf-8"
            )
            skill_dir = claude_dir / "skills" / install.SKILL_NAME
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# skill\n", encoding="utf-8")
            (claude_dir / "CLAUDE.md").write_text(
                install.upsert_block("", memory_block, install.MD_BEGIN, install.MD_END),
                encoding="utf-8",
            )
            (home / ".claude.json").write_text(
                json.dumps({"mcpServers": {install.SERVER_NAME: {"type": "http", "url": "u"}}}),
                encoding="utf-8",
            )
    if codex:
        codex_dir = home / ".codex"
        codex_dir.mkdir(parents=True)
        if complete:
            (codex_dir / "AGENTS.md").write_text(
                install.upsert_block("", memory_block, install.MD_BEGIN, install.MD_END),
                encoding="utf-8",
            )
            block = install.codex_mcp_block({"type": "http", "url": "http://127.0.0.1:9393/mcp"})
            (codex_dir / "config.toml").write_text(
                install.upsert_codex_mcp("", block), encoding="utf-8"
            )
    if opencode:
        # `opencode_dir` y no `home / ".config" / "opencode"`: la ruta la decide `install`, y un
        # HOME de prueba que la calculara por su cuenta dejaría de probar lo que hace el paquete.
        oc_dir = install.opencode_dir(home)
        oc_dir.mkdir(parents=True)
        if complete:
            (oc_dir / "AGENTS.md").write_text(
                install.upsert_block("", memory_block, install.MD_BEGIN, install.MD_END),
                encoding="utf-8",
            )
            oc_skill = oc_dir / install.OPENCODE_SKILL_SUBDIR / install.SKILL_NAME
            oc_skill.mkdir(parents=True)
            (oc_skill / "SKILL.md").write_text("# skill\n", encoding="utf-8")
            entry = install.opencode_mcp_entry("http", None, False, None)
            (oc_dir / "opencode.json").write_text(
                json.dumps(
                    {"$schema": install.OPENCODE_SCHEMA, "mcp": {install.SERVER_NAME: entry}}
                ),
                encoding="utf-8",
            )
    return home


def write_claude_desktop(
    home: Path, servers: dict | None = None, *, raw: str | None = None
) -> Path:
    """Escribe el `claude_desktop_config.json` del HOME, con la forma real: MCP y preferencias.

    Aparte de `make_home` a propósito: `install` no escribe ese fichero, así que un HOME «como lo
    deja el instalador» no lo lleva. La ruta la decide `checks.Context`, no este helper.
    """
    from local_delegate import checks

    path = checks.Context(home=home).claude_desktop_config
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        raw = json.dumps({"mcpServers": servers or {}, "preferences": {"sidebarMode": "chat"}})
    path.write_text(raw, encoding="utf-8")
    return path


def desktop_mcp_remote_entry(header: str | None = None, url: str = "http://127.0.0.1:9393/mcp"):
    """La entrada de Claude Desktop tal como está en uso: `npx mcp-remote` con `--header`."""
    args = ["-y", "mcp-remote@latest", url]
    if header is not None:
        args += ["--header", header]
    return {"command": "npx", "args": args}


def snapshot(root: Path) -> dict[str, bytes | None]:
    """Árbol completo con el contenido de cada fichero: la prueba de que nadie escribió."""
    return {
        str(path.relative_to(root)): (path.read_bytes() if path.is_file() else None)
        for path in sorted(root.rglob("*"))
    }


# --- Una instalación de la 0.34.0, para la ola A6 (REQ-012, D12) -------------
OLD_SKILL_NAME = "delegacion-local"


def downgrade_to_0_34(home: Path) -> None:
    """Deja un HOME armado por ``make_home`` como lo dejaba la 0.34.0.

    La skill con su nombre viejo en los dos destinos y los bloques de memoria nombrándola. El
    bloque de la 0.34.0 es el empaquetado de hoy con el nombre viejo: en A6 solo cambió eso.
    """
    roots = (
        home / ".claude" / "skills",
        install.opencode_dir(home) / install.OPENCODE_SKILL_SUBDIR,
    )
    for skills_root in roots:
        current = skills_root / install.SKILL_NAME
        if current.is_dir():
            current.rename(skills_root / OLD_SKILL_NAME)
    for md in live_memory_files(home):
        if md.is_file():
            text = md.read_text(encoding="utf-8").replace(install.SKILL_NAME, OLD_SKILL_NAME)
            md.write_text(text, encoding="utf-8")


def live_memory_files(home: Path) -> list[Path]:
    """Los ficheros de memoria con bloque gestionado de los tres clientes."""
    return [
        home / ".claude" / "CLAUDE.md",
        home / ".codex" / "AGENTS.md",
        install.opencode_dir(home) / "AGENTS.md",
    ]
