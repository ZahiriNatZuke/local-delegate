"""checks.py — registro único de las comprobaciones del andamiaje.

Antes de este módulo cada subcomando sabía un pedazo del sistema: ``doctor`` solo miraba el
backend, ``install`` escribía sin verificar y nadie miraba el daemon. Aquí vive **una sola
definición de «estar a punto»**: los once elementos del andamiaje, cada uno con un ``probe``
que responde en qué estado está.

Tres reglas ordenan el módulo:

1. **``probe`` nunca escribe.** Es lo que permite que ``doctor`` siga siendo de solo lectura;
   hay un test que compara el árbol del HOME simulado byte a byte antes y después.
2. **Lo que no se pudo comprobar es ``unknown``, nunca ``missing``.** Un cliente que no está
   instalado o un fichero ilegible por permisos no significan «falta»: si se reportaran así,
   un ``fix`` posterior sobrescribiría configuración ajena.
3. **Es una lista, no un framework.** Once checks son una tupla de objetos con una función;
   no hay registro dinámico, ni entry points, ni herencia. Si hiciera falta algo de eso, el
   diseño se revisa antes de seguir.

Los arreglos no viven aquí: un ``probe`` solo declara en ``fix_hint`` qué comando resuelve lo
que encontró. Ejecutarlos es trabajo de ``update`` e ``install``.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import config, install

# --- Estados -----------------------------------------------------------------
OK = "ok"  # está y como debe estar
MISSING = "missing"  # falta y se puede arreglar
WARN = "warn"  # está, pero no como debería
UNKNOWN = "unknown"  # no se pudo comprobar (no aplica, sin permisos, sin datos)

# Prefijos de la salida: los tres primeros son los que el doctor ya imprimía.
STATUS_LABEL: dict[str, str] = {
    OK: "[ OK ]",
    WARN: "[WARN]",
    MISSING: "[FALT]",
    UNKNOWN: "[ -- ]",
}

INSTALL_HINT = "local-delegate install"
SERVE_HINT = "local-delegate serve  (o arranca la tarea programada del daemon)"


def is_warning(status: str) -> bool:
    """True si el estado cuenta como aviso para el exit code (``unknown`` no cuenta)."""
    return status in (WARN, MISSING)


@dataclass(frozen=True)
class Result:
    """Lo que devuelve un probe: un estado, una línea legible y qué lo arregla."""

    status: str
    detail: str
    fix_hint: str = ""


@dataclass(frozen=True)
class Check:
    """Un elemento del andamiaje que sabe comprobarse a sí mismo."""

    id: str
    group: str  # cliente | andamiaje | servicio | backend
    title: str
    probe: Callable[[Context], Result]


# --- Colaboradores por defecto -----------------------------------------------
# Los imports de `daemon` y `doctor` son diferidos a propósito: `daemon` arrastra uvicorn y el
# SDK MCP (que el diagnóstico no necesita cargar) y `doctor` importa este módulo, así que a
# nivel superior sería un ciclo. Resolverlos en tiempo de ejecución también es lo que permite
# a los tests doblarlos con monkeypatch sin inyectar nada.
def _default_daemon_status(host: str, port: int) -> dict | None:
    from . import daemon

    return daemon.query_daemon(host, port, timeout=1.0)


def _default_backend_models() -> bool:
    from . import doctor

    return doctor._backend_up()


def _default_version_of(component: str, config_path: Path | None) -> tuple[str | None, str | None]:
    """(versión instalada, motivo si no se pudo detectar) del componente del backend."""
    from . import doctor

    if component == "llama-swap":
        # Sin motivo a propósito: el doctor tampoco lo da hoy para llama-swap, y con motivo la
        # línea perdería el sufijo de la última release en GitHub que arma `_compare_line`.
        return doctor.detect_llamaswap_version(), None
    return doctor.detect_llamaserver_version(config_path)


def _port_taken(host: str, port: int) -> bool:
    """True si alguien escucha en el puerto (sea o no nuestro daemon)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


@dataclass(frozen=True)
class Context:
    """Lo que los probes necesitan, **inyectado** y no descubierto.

    Los tres colaboradores —dos que hablan por red y uno que lanza procesos— tienen un default
    que delega en el módulo real; doblarlos es lo que hace los tests deterministas sin salir a
    la red ni ejecutar binarios.
    """

    home: Path
    config_path: Path | None = None
    online: bool = False
    daemon_status: Callable[[str, int], dict | None] = _default_daemon_status
    backend_models: Callable[[], bool] = _default_backend_models
    version_of: Callable[[str, Path | None], tuple[str | None, str | None]] = _default_version_of

    @property
    def claude_dir(self) -> Path:
        return self.home / ".claude"

    @property
    def codex_dir(self) -> Path:
        return self.home / ".codex"

    @property
    def hooks_dir(self) -> Path:
        return self.claude_dir / "hooks" / install.HOOKS_SUBDIR


# --- Lecturas tolerantes ------------------------------------------------------
def read_text(path: Path) -> tuple[str | None, str | None]:
    """Contenido del fichero y, si no se pudo leer, el motivo.

    Distingue las dos cosas que un probe **no** debe confundir: que el fichero no exista
    (``(None, None)`` — eso sí es una ausencia real) y que exista pero no se pueda leer
    (``(None, motivo)`` — eso es ``unknown``, nunca ``missing``).
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"no se pudo leer {path}: {exc.strerror or exc}"


def read_json(path: Path) -> tuple[dict | None, str | None]:
    """Igual que :func:`read_text`, pero además un JSON ilegible es motivo de ``unknown``."""
    text, reason = read_text(path)
    if text is None:
        return None, reason
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"{path} no es JSON válido ({exc.msg}); no se puede comprobar"
    return (data, None) if isinstance(data, dict) else (None, f"{path} no contiene un objeto JSON")


def _dir_entries(path: Path) -> tuple[list[str] | None, str | None]:
    """Nombres dentro del directorio; motivo si existe pero no se pudo listar."""
    if not path.exists():
        return None, None
    try:
        return sorted(p.name for p in path.iterdir()), None
    except OSError as exc:
        return None, f"no se pudo listar {path}: {exc.strerror or exc}"


def _has_block(text: str, begin: str, end: str) -> bool:
    """True si el bloque gestionado está delimitado y en orden."""
    start = text.find(begin)
    return start != -1 and text.find(end, start + len(begin)) != -1


def _worst(statuses: list[str]) -> str:
    """Estado agregado de un check que mira varios clientes a la vez."""
    for candidate in (MISSING, WARN, UNKNOWN):
        if candidate in statuses:
            return candidate
    return OK


# --- Probes del andamiaje -----------------------------------------------------
def _probe_clients(ctx: Context) -> Result:
    present = [
        name
        for name, path in (("Claude Code", ctx.claude_dir), ("Codex", ctx.codex_dir))
        if path.is_dir()
    ]
    if not present:
        return Result(UNKNOWN, f"no hay ~/.claude ni ~/.codex bajo {ctx.home}")
    return Result(OK, "detectados: " + ", ".join(present))


def _claude_absent(ctx: Context) -> Result | None:
    """``unknown`` compartido por los checks que solo aplican a Claude Code."""
    if not ctx.claude_dir.is_dir():
        return Result(UNKNOWN, f"Claude Code no está instalado ({ctx.claude_dir} no existe)")
    return None


def _probe_hook_files(ctx: Context) -> Result:
    if absent := _claude_absent(ctx):
        return absent
    entries, reason = _dir_entries(ctx.hooks_dir)
    if reason:
        return Result(UNKNOWN, reason)
    if entries is None:
        return Result(MISSING, f"no existe {ctx.hooks_dir}", INSTALL_HINT)
    expected = [script for script, _event, _matcher in install._HOOK_EVENTS]
    faltan = [name for name in expected if name not in entries]
    if faltan:
        return Result(WARN, f"faltan scripts en {ctx.hooks_dir}: {', '.join(faltan)}", INSTALL_HINT)
    return Result(OK, f"{len(entries)} script(s) en {ctx.hooks_dir}")


def _probe_hook_settings(ctx: Context) -> Result:
    if absent := _claude_absent(ctx):
        return absent
    path = ctx.claude_dir / "settings.json"
    data, reason = read_json(path)
    if reason:
        return Result(UNKNOWN, reason)
    if data is None:
        return Result(MISSING, f"no existe {path}", INSTALL_HINT)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return Result(MISSING, f"{path} no registra ningún hook", INSTALL_HINT)

    # `_is_ours` es de install a propósito: un hook del usuario en otra ruta nunca debe
    # contarse como nuestro, y ese criterio ya está escrito (y probado) una vez.
    registered: list[str] = []
    legacy = 0
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []):
                if isinstance(hook, dict) and install._is_ours(hook, ctx.hooks_dir):
                    matcher = group.get("matcher")
                    registered.append(f"{event}{'/' + matcher if matcher else ''}")
                    if isinstance(hook.get("args"), list):
                        legacy += 1
    if not registered:
        return Result(MISSING, f"ningún hook de local-delegate en {path}", INSTALL_HINT)
    if legacy:
        # El formato heredado `{"command": "python", "args": [...]}` sigue en el archivo pero
        # Claude Code no lo ejecuta: son entradas muertas. Decir «ok» aquí sería el falso ok
        # más caro del registro, porque el usuario cree que la delegación está sugiriéndose.
        return Result(
            WARN,
            f"{legacy} de {len(registered)} en el formato heredado con 'args', "
            f"que Claude Code no ejecuta ({path})",
            INSTALL_HINT,
        )
    return Result(OK, f"{len(registered)} registrado(s): {', '.join(registered)}")


def _probe_skill(ctx: Context) -> Result:
    if absent := _claude_absent(ctx):
        return absent
    skill_dir = ctx.claude_dir / "skills" / install.SKILL_NAME
    entries, reason = _dir_entries(skill_dir)
    if reason:
        return Result(UNKNOWN, reason)
    if entries is None:
        return Result(MISSING, f"no existe {skill_dir}", INSTALL_HINT)
    if "SKILL.md" not in entries:
        return Result(WARN, f"{skill_dir} existe pero no tiene SKILL.md", INSTALL_HINT)
    return Result(OK, f"instalada en {skill_dir}")


def _probe_memory(ctx: Context) -> Result:
    """Bloque de la regla de delegación en la memoria global de cada cliente.

    Solo se comprueba que los marcadores estén: lo que el usuario haya editado dentro del
    bloque es asunto suyo y compararlo literalmente sería pelearse con ediciones legítimas.
    """
    targets = (
        ("Claude", ctx.claude_dir, ctx.claude_dir / "CLAUDE.md"),
        ("Codex", ctx.codex_dir, ctx.codex_dir / "AGENTS.md"),
    )
    statuses: list[str] = []
    details: list[str] = []
    for label, client_dir, path in targets:
        if not client_dir.is_dir():
            # Un cliente que no está en la máquina no arrastra el estado del check: no falta
            # nada, simplemente no aplica. Solo si no aplica ninguno el resultado es `unknown`.
            details.append(f"{label}: cliente no instalado")
            continue
        text, reason = read_text(path)
        if reason:
            statuses.append(UNKNOWN)
            details.append(f"{label}: {reason}")
        elif text is None:
            statuses.append(MISSING)
            details.append(f"{label}: no existe {path}")
        elif _has_block(text, install.MD_BEGIN, install.MD_END):
            statuses.append(OK)
            details.append(f"{label}: bloque presente en {path}")
        else:
            statuses.append(MISSING)
            details.append(f"{label}: sin bloque gestionado en {path}")
    status = _worst(statuses) if statuses else UNKNOWN
    return Result(status, " · ".join(details), INSTALL_HINT if is_warning(status) else "")


def _probe_mcp_claude(ctx: Context) -> Result:
    path = ctx.home / ".claude.json"
    if not ctx.claude_dir.is_dir() and not path.exists():
        return Result(UNKNOWN, f"Claude Code no está instalado ({ctx.claude_dir} no existe)")
    data, reason = read_json(path)
    if reason:
        return Result(UNKNOWN, reason)
    if data is None:
        return Result(MISSING, f"no existe {path}", INSTALL_HINT)
    servers = data.get("mcpServers")
    entry = servers.get(install.SERVER_NAME) if isinstance(servers, dict) else None
    if not isinstance(entry, dict):
        return Result(MISSING, f"'{install.SERVER_NAME}' no está en {path}", INSTALL_HINT)
    kind = str(entry.get("type") or "stdio")
    where = entry.get("url") or entry.get("command") or ""
    return Result(OK, f"registrado en {path} ({kind}{' ' + str(where) if where else ''})")


def _probe_mcp_codex(ctx: Context) -> Result:
    if not ctx.codex_dir.is_dir():
        return Result(UNKNOWN, f"Codex no está instalado ({ctx.codex_dir} no existe)")
    path = ctx.codex_dir / "config.toml"
    text, reason = read_text(path)
    if reason:
        return Result(UNKNOWN, reason)
    if text is None:
        return Result(MISSING, f"no existe {path}", INSTALL_HINT)
    section = install._CODEX_SECTION_RE.search(text)
    if not section:
        return Result(MISSING, f"sin [mcp_servers.{install.SERVER_NAME}] en {path}", INSTALL_HINT)
    kind = "http" if "url = " in section.group(0) else "stdio"
    managed = _has_block(text, install.TOML_BEGIN, install.TOML_END)
    if not managed:
        return Result(WARN, f"entrada {kind} en {path}, pero puesta a mano (sin marcadores)")
    return Result(OK, f"bloque gestionado en {path} ({kind})")


# --- Probes de servicios y backend --------------------------------------------
def _daemon_host_port() -> tuple[str, int]:
    """Dónde preguntar por el daemon: con 0.0.0.0 configurado se pregunta por loopback."""
    host = config.WEB_HOST
    return ("127.0.0.1" if host in ("0.0.0.0", "::", "") else host), config.WEB_PORT


def _probe_daemon(ctx: Context) -> Result:
    host, port = _daemon_host_port()
    status = ctx.daemon_status(host, port)
    if status:
        version = status.get("version") or "?"
        pid = status.get("pid") or "?"
        return Result(OK, f"local-delegate {version} · pid {pid} · {status.get('mcp_url', '')}")
    if _port_taken(host, port):
        return Result(WARN, f"alguien escucha en {host}:{port} pero no es nuestro daemon")
    return Result(MISSING, f"nadie escucha en {host}:{port}", SERVE_HINT)


def _probe_backend_models(ctx: Context) -> Result:
    if ctx.backend_models():
        return Result(OK, f"{config.BASE_URL}/models responde")
    return Result(
        WARN,
        f"{config.BASE_URL}/models no responde (backend caído)",
        "arranca llama-swap (o revisa LOCAL_DELEGATE_BASE_URL)",
    )


def _version_result(ctx: Context, component: str) -> Result:
    """Envuelve la comparación de versiones del doctor sin reescribirla.

    El texto lo sigue armando ``doctor._compare_line`` —incluida la consulta opcional a
    GitHub y la política de soak— y aquí solo se le quita el prefijo, que lo pone el
    renderizador con el resto de los checks.
    """
    from . import doctor

    installed, reason = ctx.version_of(component, ctx.config_path)
    if installed is None and reason:
        recommended = doctor.RECOMMENDED_VERSIONS[component]
        return Result(UNKNOWN, f"no detectado (probada: {recommended}) — {reason}")
    line, warn = doctor._compare_line(component, installed, ctx.online)
    _prefix, _, text = line.partition("] ")
    detail = text.split(": ", 1)[1] if ": " in text else text
    if warn:
        return Result(WARN, detail)
    return Result(UNKNOWN if installed is None else OK, detail)


def _probe_llamaswap(ctx: Context) -> Result:
    return _version_result(ctx, "llama-swap")


def _probe_llamaserver(ctx: Context) -> Result:
    return _version_result(ctx, "llama-server")


# --- El registro --------------------------------------------------------------
# Once elementos, en orden de grupo. Una tupla: si esto necesitara alguna vez cargarse solo,
# el problema no sería el registro sino el diseño.
CHECKS: tuple[Check, ...] = (
    Check("client.presence", "cliente", "clientes", _probe_clients),
    Check("scaffold.hook_files", "andamiaje", "hooks copiados", _probe_hook_files),
    Check("scaffold.hook_settings", "andamiaje", "hooks registrados", _probe_hook_settings),
    Check("scaffold.skill", "andamiaje", f"skill {install.SKILL_NAME}", _probe_skill),
    Check("scaffold.memory", "andamiaje", "memoria global", _probe_memory),
    Check("scaffold.mcp_claude", "andamiaje", "MCP en Claude Code", _probe_mcp_claude),
    Check("scaffold.mcp_codex", "andamiaje", "MCP en Codex", _probe_mcp_codex),
    Check("service.daemon", "servicio", "daemon", _probe_daemon),
    Check("service.backend", "servicio", "backend", _probe_backend_models),
    Check("backend.llamaswap", "backend", "llama-swap", _probe_llamaswap),
    Check("backend.llamaserver", "backend", "llama-server", _probe_llamaserver),
)


def run_all(ctx: Context) -> list[tuple[Check, Result]]:
    """Corre los once probes. Un probe que falle es ``unknown``, nunca tumba el diagnóstico."""
    results: list[tuple[Check, Result]] = []
    for check in CHECKS:
        try:
            result = check.probe(ctx)
        except Exception as exc:  # un check roto no debe impedir ver los otros diez
            result = Result(UNKNOWN, f"la comprobación falló: {exc}")
        results.append((check, result))
    return results
