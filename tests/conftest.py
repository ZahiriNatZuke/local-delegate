"""Aislamiento global de artefactos runtime durante la suite."""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from local_delegate import config, i18n, install, shell_profiles

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
    _reset_languages()
    yield
    _reset_languages()


def _reset_languages() -> None:
    """El idioma cacheado del paquete y el de `scripts/script_i18n.py`, si algún test lo cargó."""
    i18n.reset()
    script_i18n = sys.modules.get("script_i18n")
    if script_i18n is not None:
        script_i18n.reset()


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


@pytest.fixture(autouse=True)
def real_keychain_unreachable(monkeypatch):
    """Ningún test lee el Llavero real de macOS (SDD claude-plugin-and-mods, macos-keychain).

    En el runner `macos-latest` la resolución de credenciales llamaría a `/usr/bin/security` cada
    vez que falta la variable: el resultado dependería del Llavero de esa máquina y, bloqueado,
    podría abrir un diálogo. Aquí el programa apunta a una ruta que no existe (falla al arrancar,
    que es «sin credencial») y la caché por proceso empieza vacía. Los tests del Llavero ponen su
    propio `security` encima.
    """
    from local_delegate import token_source

    monkeypatch.setattr(
        token_source,
        "SECURITY_COMMAND",
        ("/nonexistent/local-delegate-test/security",),
        raising=False,
    )
    cache = getattr(token_source, "_KEYCHAIN_CACHE", None)
    if cache is not None:
        cache.clear()
    yield
    if cache is not None:
        cache.clear()


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


# --- SDD cli-completion, L3a: ningún test llega al perfil real del usuario ---------------------
#: Marcador del único test que pregunta de verdad a pwsh por la ruta de su perfil (solo lectura).
REAL_PROFILE_QUERY_MARKER = "real_profile_query"
PROFILE_GUARD = pytest.StashKey[bool]()
#: The real HOME, read when conftest is imported: before any test can patch `Path.home` or HOME.
REAL_HOME = Path.home()
#: Real shell profiles that no test may create, write or delete (SDD backlog-minor-leftovers,
#: REQ-006). `.bashrc`/`.bash_profile`/`.zshrc` come from `Path.home()` with no query, so the
#: PowerShell doubles below do not cover them.
REAL_SHELL_PROFILES: tuple[Path, ...] = tuple(
    REAL_HOME / name for name in (".bashrc", ".bash_profile", ".zshrc")
) + ((Path(os.environ["ZDOTDIR"]).expanduser() / ".zshrc",) if os.environ.get("ZDOTDIR") else ())


def _forbidden_profile_lookup(*_args, **_kwargs):
    # `pytest.fail` lanza una excepción que no hereda de `Exception`: ni el `except` de la consulta
    # (`OSError`, `SubprocessError`) ni el del respaldo por `ctypes` pueden tragársela.
    pytest.fail(
        "un test ha llegado a la consulta real del perfil del shell; inyecta `run=`, `query=` o "
        "`known_folder=`, o usa un HOME simulado",
        pytrace=False,
    )


@pytest.fixture(autouse=True)
def real_profiles_untouchable(request, monkeypatch):
    """Sustituye las dos únicas salidas de `shell_profiles` al sistema por dobles que fallan.

    Son el ejecutor por defecto de la consulta a PowerShell (`_default_run`) y el respaldo por la
    carpeta conocida *Documents* (`_documents_folder`). No se sustituye `query_powershell`: los
    tests que le inyectan `run=` siguen funcionando, y solo falla una llamada real. Así ningún test
    puede averiguar —ni por tanto escribir— el `$PROFILE` real, ni siquiera con `Path.home`
    parcheado (`install.is_simulated_home`). El único caso real lo desactiva con el marcador
    `real_profile_query`. `tests/test_profile_guard.py` comprueba que la fixture está activa.

    It also guards the real POSIX profiles (`REAL_SHELL_PROFILES`, SDD backlog-minor-leftovers,
    REQ-006), marker or not: a write through `install.write_profile_edit` or
    `install._atomic_write` fails the test before touching the file, and any other change to
    them (size, modification time, existence) fails it at teardown.
    """
    # The POSIX profiles (REQ-006) are guarded always, also under the marker: no test writes.
    watched = REAL_SHELL_PROFILES
    before = {path: _profile_state(path) for path in watched}
    _guard_profile_writes(monkeypatch)
    if request.node.get_closest_marker(REAL_PROFILE_QUERY_MARKER) is not None:
        request.node.stash[PROFILE_GUARD] = False
    else:
        monkeypatch.setattr(shell_profiles, "_default_run", _forbidden_profile_lookup)
        monkeypatch.setattr(shell_profiles, "_documents_folder", _forbidden_profile_lookup)
        request.node.stash[PROFILE_GUARD] = True
    yield
    # Backstop for any other way in (a deletion, a plain `write_bytes`): the state must not move.
    changed = [str(path) for path in watched if _profile_state(path) != before[path]]
    if changed:
        pytest.fail(f"a test changed a real shell profile: {', '.join(changed)}", pytrace=False)


def _is_guarded_profile(path: Path) -> bool:
    """True if `path` is one of `REAL_SHELL_PROFILES` (read at call time, so a test can point
    the list at a temporary file to check the guard itself)."""
    key = os.path.normcase(os.path.abspath(path))
    return any(os.path.normcase(os.path.abspath(p)) == key for p in REAL_SHELL_PROFILES)


def _forbidden_profile_write(path: Path) -> None:
    # Same exception as `_forbidden_profile_lookup`: `except OSError` in `install` cannot eat it.
    pytest.fail(
        f"a test tried to write the real shell profile {path}; use a simulated HOME (`--home`)",
        pytrace=False,
    )


def _guard_profile_writes(monkeypatch) -> None:
    """Wraps the two writers of `install` that can reach a shell profile (REQ-006)."""
    write_profile_edit = install.write_profile_edit
    atomic_write = install._atomic_write

    def guarded_profile_edit(edit, *args, **kwargs):
        for path in (edit.path, edit.target):
            if _is_guarded_profile(path):
                _forbidden_profile_write(path)
        return write_profile_edit(edit, *args, **kwargs)

    def guarded_atomic_write(path, *args, **kwargs):
        if _is_guarded_profile(path):
            _forbidden_profile_write(path)
        return atomic_write(path, *args, **kwargs)

    monkeypatch.setattr(install, "write_profile_edit", guarded_profile_edit)
    monkeypatch.setattr(install, "_atomic_write", guarded_atomic_write)


def _profile_state(path: Path) -> tuple[int, int] | None:
    """Size and modification time of a profile, or `None` if it does not exist."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


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


# --- SDD claude-plugin-and-mods, F1-delivery-core: the real `claude` never runs (I-3) ----------
#: Names under which the Claude Code CLI can be launched, by OS and package manager.
_CLAUDE_EXECUTABLES = frozenset({"claude", "claude.exe", "claude.cmd", "claude.ps1"})


def _first_program(args) -> str:
    """The program a `Popen` call would start: argv[0], or the first token of a shell string."""
    if isinstance(args, bytes):
        args = args.decode(errors="replace")
    if isinstance(args, str):
        token = args.strip().split(" ", 1)[0] if not args.lstrip().startswith('"') else None
        if token is None:
            token = args.lstrip()[1:].split('"', 1)[0]
        return token
    if isinstance(args, os.PathLike):
        return os.fspath(args)
    try:
        return os.fspath(args[0])
    except (TypeError, IndexError):
        return ""


def _launches_real_claude(program: str, env, allowed_root: Path) -> bool:
    """True if `program` is the Claude Code CLI and not a double a test wrote under its tmp dir."""
    if not program or Path(program).name.lower() not in _CLAUDE_EXECUTABLES:
        return False
    path = env.get("PATH") if isinstance(env, dict) else None
    resolved = program if Path(program).is_absolute() else shutil.which(program, path=path)
    if resolved is None:
        return True  # it would fail anyway, but the test meant to launch the real CLI
    try:
        Path(resolved).resolve().relative_to(allowed_root.resolve())
    except (ValueError, OSError):
        return True
    return False


@pytest.fixture(autouse=True)
def real_claude_cli_forbidden(monkeypatch, tmp_path_factory):
    """No test reaches the real Claude Code configuration (plan, I-3).

    Two halves. The environment: `CLAUDE_CONFIG_DIR` and `CLAUDE_PLUGIN_*` of whoever runs the
    suite are removed, so a test that builds a child environment does not inherit the real config
    folder or the options of an installed plugin. The CLI: any `Popen` (and so `subprocess.run`)
    of the real `claude` raises. The plugin commands run through an injected runner
    (`claude_plugin.Runner`, see `FakeClaude`); a test that needs a fake `claude` executable
    writes it under its tmp dir, which stays allowed.
    """
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    for name in [n for n in os.environ if n.startswith("CLAUDE_PLUGIN_")]:
        monkeypatch.delenv(name, raising=False)
    allowed_root = tmp_path_factory.getbasetemp()
    real_popen = subprocess.Popen

    class GuardedPopen(real_popen):
        def __init__(self, args, *pos, **kwargs):
            program = kwargs.get("executable") or _first_program(args)
            if _launches_real_claude(os.fspath(program), kwargs.get("env"), allowed_root):
                raise RuntimeError(
                    f"test tried to launch the real `claude` ({program!r}): inject a runner"
                )
            super().__init__(args, *pos, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)


class FakeClaude:
    """Double of the Claude Code CLI for `claude_plugin.Runner`: records every call.

    It keeps the state the real CLI keeps (measured with 2.1.307 in an isolated
    `CLAUDE_CONFIG_DIR`): `plugin list --json` returns a list of `{"id", "version", "enabled",
    "scope", …}`, and `marketplace add`/`install` rewrite `settings.json` in their own format
    (`rewrite_settings`), which is why the migration tests compare JSON and not bytes after
    installing.
    """

    BIN = "C:/fake/bin/claude.exe"

    def __init__(
        self,
        *,
        present: bool = True,
        version: str = "2.1.307",
        version_output: str | None = None,
        plugin_version: str = "0.40.0",
        enabled: bool = True,
        listed: bool = True,
        already_installed: bool = False,
        fail: frozenset[str] = frozenset(),
        settings_path: Path | None = None,
        rewrite_settings: bool = True,
    ):
        self.present = present
        self.version_output = version_output or f"{version} (Claude Code)"
        self.plugin_version = plugin_version
        self.enabled = enabled
        self.listed = listed
        self.installed = already_installed
        self.fail = fail
        self.settings_path = settings_path
        self.rewrite_settings = rewrite_settings
        self.calls: list[tuple[list[str], dict | None]] = []
        #: Hook for a test that must observe the disk at the moment of a given step.
        self.on_step: dict[str, object] = {}

    def which(self, name: str) -> str | None:
        return self.BIN if self.present and name == "claude" else None

    @staticmethod
    def step_of(argv: list[str]) -> str:
        rest = argv[1:]
        if rest[:1] == ["--version"]:
            return "version"
        if rest[:3] == ["plugin", "marketplace", "add"]:
            return "marketplace_add"
        if rest[:3] == ["plugin", "marketplace", "remove"]:
            return "marketplace_remove"
        if rest[:2] == ["plugin", "install"]:
            return "install"
        if rest[:2] == ["plugin", "uninstall"]:
            return "uninstall"
        if rest[:2] == ["plugin", "list"]:
            return "list"
        return "other"

    def steps(self) -> list[str]:
        return [self.step_of(argv) for argv, _env in self.calls]

    def _rewrite(self, key: str, value) -> None:
        path = self.settings_path
        if not self.rewrite_settings or path is None or not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        data.setdefault(key, {}).update(value)
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")

    def __call__(self, argv, env=None) -> subprocess.CompletedProcess:
        argv = list(argv)
        self.calls.append((argv, dict(env) if env is not None else None))
        step = self.step_of(argv)
        hook = self.on_step.get(step)
        if callable(hook):
            hook()
        if step in self.fail:
            return subprocess.CompletedProcess(argv, 1, "", f"{step} failed")
        out = ""
        if step == "version":
            out = self.version_output
        elif step == "marketplace_add":
            self._rewrite("extraKnownMarketplaces", {"local-delegate": {"source": "directory"}})
        elif step == "install":
            self.installed = True
            self._rewrite("enabledPlugins", {"local-delegate@local-delegate": True})
            out = json.dumps({"command": "install", "outcome": "ok", "configApplied": True})
        elif step == "uninstall":
            self.installed = False
        elif step == "list":
            entries = []
            if self.installed and self.listed:
                entries.append(
                    {
                        "id": "local-delegate@local-delegate",
                        "version": self.plugin_version,
                        "scope": "user",
                        "enabled": self.enabled,
                    }
                )
            out = json.dumps(entries)
        return subprocess.CompletedProcess(argv, 0, out, "")


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


# --- Guard of the required shells (SDD cli-completion, REQ-037) --------------------------------
#
# A shell listed in `COMPLETION_TEST_REQUIRE_SHELLS` must have at least one test that PASSED. The
# helper `completion_shells.require_or_skip` fails a test whose shell is missing; this guard
# covers what the helper cannot see: every test of that shell deselected (`-k`), never collected
# or skipped for another reason. Under pytest-xdist the controller only sees the NAMES of the
# markers in `report.keywords`, not their arguments, so each worker copies the argument of
# `shell("<name>")` to `user_properties`, which does travel in the report.
_SHELL_PASSES: dict[str, int] = {}


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "shell(name): integration test that launches a real shell (REQ-037)"
    )


def pytest_runtest_setup(item):
    for mark in item.iter_markers("shell"):
        item.user_properties.append(("shell", mark.args[0]))


def pytest_runtest_logreport(report):
    if report.when != "call" or not report.passed:
        return
    for name, value in report.user_properties:  # tuples here, lists after xdist's JSON
        if name == "shell":
            _SHELL_PASSES[value] = _SHELL_PASSES.get(value, 0) + 1


def pytest_sessionfinish(session):
    if hasattr(session.config, "workerinput"):
        return  # an xdist worker: the controller decides with the reports of all of them
    from completion_shells import REQUIRE_ENV, required_shells

    missing = sorted(name for name in required_shells() if not _SHELL_PASSES.get(name))
    if not missing:
        return
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(
            f"{REQUIRE_ENV}: no test passed for the required shell(s): {', '.join(missing)}",
            red=True,
        )
