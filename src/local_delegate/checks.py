"""checks.py — registro único de las comprobaciones del andamiaje.

Antes de este módulo cada subcomando sabía un pedazo del sistema: ``doctor`` solo miraba el
backend, ``install`` escribía sin verificar y nadie miraba el daemon. Aquí vive **una sola
definición de «estar a punto»**: los trece elementos del andamiaje, cada uno con un ``probe``
que responde en qué estado está.

Tres reglas ordenan el módulo:

1. **``probe`` nunca escribe.** Es lo que permite que ``doctor`` siga siendo de solo lectura;
   hay un test que compara el árbol del HOME simulado byte a byte antes y después.
2. **Lo que no se pudo comprobar es ``unknown``, nunca ``missing``.** Un cliente que no está
   instalado o un fichero ilegible por permisos no significan «falta»: si se reportaran así,
   un ``fix`` posterior sobrescribiría configuración ajena.
3. **Es una lista, no un framework.** Trece checks son una tupla de objetos con una función;
   no hay registro dinámico, ni entry points, ni herencia. Si hiciera falta algo de eso, el
   diseño se revisa antes de seguir.

Los arreglos no viven aquí: un ``probe`` solo declara en ``fix_hint`` qué comando resuelve lo
que encontró. Ejecutarlos es trabajo de ``update`` e ``install``.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
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
CLI_HINT = "uv tool install local-delegate-mcp  (deja `local-delegate` en el PATH)"
RESTART_HINT = "reinicia el daemon para que sirva la versión instalada"
UPGRADE_HINT = "uv tool upgrade local-delegate-mcp"

# Cuánto se espera a PyPI. Corto a propósito: la comparación con lo publicado corre en **toda**
# ejecución de `doctor`, y un diagnóstico que se cuelga es peor que uno que dice «no pude».
PYPI_TIMEOUT = 2.0


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


def _default_backend_models() -> tuple[bool, str]:
    from . import doctor

    return doctor.backend_probe()


def _default_version_of(component: str, config_path: Path | None) -> tuple[str | None, str | None]:
    """(versión instalada, motivo si no se pudo detectar) del componente del backend."""
    from . import doctor

    if component == "llama-swap":
        # Sin motivo a propósito: el doctor tampoco lo da hoy para llama-swap, y con motivo la
        # línea perdería el sufijo de la última release en GitHub que arma `_compare_line`.
        return doctor.detect_llamaswap_version(), None
    return doctor.detect_llamaserver_version(config_path)


def _default_latest_release() -> tuple[str | None, str | None]:
    """(última versión publicada en PyPI, motivo si no se pudo saber).

    Delega en ``update.latest_version`` en vez de reimplementar la consulta: «cuál es la última
    publicada» tiene **una sola** definición en el repo, con su porqué escrito (se consulta el
    índice simple y no el JSON, que se vio desfasado en vivo con la 0.12.0). El import es
    diferido porque ``update`` importa este módulo y a nivel superior sería un ciclo.
    """
    from . import update

    return update.latest_version(timeout=PYPI_TIMEOUT)


def SKIP_PYPI() -> tuple[str | None, str | None]:
    """Colaborador para quien corre el registro y **no** quiere salir a la red.

    Lo inyectan ``install`` (instalar unos hooks no es motivo para consultar PyPI) y ``update``
    (que ya pregunta por su cuenta, y dos consultas en el mismo comando serían una de más).
    """
    return None, "no se consulta PyPI en este comando"


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

    Los cuatro colaboradores —tres que hablan por red y uno que lanza procesos— tienen un
    default que delega en el módulo real; doblarlos es lo que hace los tests deterministas sin
    salir a la red ni ejecutar binarios.
    """

    home: Path
    config_path: Path | None = None
    online: bool = False
    daemon_status: Callable[[str, int], dict | None] = _default_daemon_status
    backend_models: Callable[[], tuple[bool, str]] = _default_backend_models
    version_of: Callable[[str, Path | None], tuple[str | None, str | None]] = _default_version_of
    # Al final y con default: las llamadas que no lo pasan siguen funcionando igual. Quien no
    # quiera salir a la red inyecta `SKIP_PYPI` **explícitamente**, y así se ve en su línea.
    latest_release: Callable[[], tuple[str | None, str | None]] = _default_latest_release

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


def _installed_version() -> str | None:
    """Versión del paquete instalado, o None si no se puede saber.

    Nunca lanza: si la versión no se puede averiguar, quien la use simplemente no compara. El
    diagnóstico no puede caerse por no saber un dato accesorio.
    """
    try:
        return metadata.version("local-delegate-mcp")
    except Exception:  # PackageNotFoundError y cualquier metadato roto o ausente
        return None


def _probe_cli(ctx: Context) -> Result:
    """¿Se puede escribir `local-delegate` a secas, desde cualquier carpeta?

    Toda la documentación —y los `fix_hint` de este mismo registro— dicen «corre
    `local-delegate <algo>`». Si el paquete se instaló con `uvx`, ese comando **no existe**:
    `uvx` monta un entorno efímero y lo borra al terminar. Un CLI que se documenta como comando
    global y no comprueba serlo deja al usuario buscando por qué «no se encuentra el comando».
    """
    found = shutil.which("local-delegate")
    if not found:
        return Result(
            MISSING,
            "el comando `local-delegate` no está en el PATH (¿instalado con `uvx`, que es efímero?)",
            CLI_HINT,
        )
    installed = _installed_version()
    return Result(OK, f"{found}{f' (versión {installed})' if installed else ''}")


def _version_key(version: str) -> list[int]:
    """Componentes numéricos de una versión, para compararla como número y no como texto."""
    return [int(part) for part in re.findall(r"\d+", version)]


def _compare_versions(installed: str, latest: str) -> int | None:
    """-1, 0 o 1. ``None`` si alguna de las dos no tiene ni un número que comparar."""
    left, right = _version_key(installed), _version_key(latest)
    if not left or not right:
        return None
    # A la misma longitud antes de comparar: sin esto `0.17` saldría **menor** que `0.17.0` y el
    # check avisaría de una actualización que no existe.
    width = max(len(left), len(right))
    left += [0] * (width - len(left))
    right += [0] * (width - len(right))
    return (left > right) - (left < right)


def _upgrade_hint() -> str:
    """Qué comando actualiza **esta** instalación.

    En una instalación editable ``uv tool upgrade`` no actualiza nada, porque el código se sirve
    del repo clonado. Y el caso no es teórico: es el de una segunda máquina que se quedó por
    detrás de un release hecho desde otra.
    """
    from . import update

    origin = update.editable_origin()
    if origin:
        return f"git -C {origin} pull && uv sync --project {origin}"
    return UPGRADE_HINT


def _probe_published(ctx: Context) -> Result:
    """¿La versión instalada es la última publicada?

    Sin esto, una instalación vieja pasa el diagnóstico entero sin una sola señal: pasó el
    2026-07-30, con el CLI en 0.16.0, la 0.17.0 publicada y `doctor` diciendo «todo a punto».
    """
    installed = _installed_version()
    if installed is None:
        return Result(UNKNOWN, "no se pudo saber qué versión del paquete está instalada")
    latest, reason = ctx.latest_release()
    if latest is None:
        return Result(UNKNOWN, f"instalada {installed}; {reason or 'PyPI no respondió'}")
    order = _compare_versions(installed, latest)
    if order is None:
        return Result(UNKNOWN, f"no se pudieron comparar '{installed}' y '{latest}'")
    if order < 0:
        return Result(
            WARN,
            f"instalada {installed}, publicada {latest}: la instalación está atrasada",
            _upgrade_hint(),
        )
    if order > 0:
        return Result(OK, f"instalada {installed}, por delante de la publicada {latest}")
    return Result(OK, f"{installed} (la última publicada)")


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
        # El formato `{"command": "python", "args": [...]}` es el *exec form* del schema de
        # Claude Code y **sí se ejecuta** — verificado en vivo el 2026-07-29 y otra vez el
        # 2026-07-30, viendo disparar `suggest_lint_summary.py`. No es un hook muerto: es una
        # instalación anterior, con los scripts fuera de `hooks/local-delegate/`. Por eso es
        # `warn` y no `missing` ni `ok`, y por eso el detalle dice que funcionan.
        return Result(
            WARN,
            f"{legacy} de {len(registered)} vienen de una instalación anterior "
            f"(formato 'args' y scripts fuera de {ctx.hooks_dir}); funcionan, pero reinstalar "
            f"los deja como los pone la versión actual",
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
def daemon_host_port() -> tuple[str, int]:
    """Dónde preguntar por el daemon: con 0.0.0.0 configurado se pregunta por loopback.

    Pública porque ``update`` necesita saber a dónde preguntar para reiniciarlo, y esa
    respuesta debe salir del mismo sitio que la del diagnóstico: dos derivaciones del host
    y el puerto es exactamente la clase de verdad duplicada que ya costó caro en este repo.
    """
    host = config.WEB_HOST
    return ("127.0.0.1" if host in ("0.0.0.0", "::", "") else host), config.WEB_PORT


def _probe_daemon(ctx: Context) -> Result:
    host, port = daemon_host_port()
    status = ctx.daemon_status(host, port)
    if status:
        version = status.get("version") or "?"
        pid = status.get("pid") or "?"
        detail = f"local-delegate {version} · pid {pid} · {status.get('mcp_url', '')}"
        installed = _installed_version()
        if installed and version != "?" and version != installed:
            # El daemon es un proceso largo: sigue sirviendo el código con el que arrancó. Tras
            # actualizar, los clientes hablan con la versión vieja y nada lo dice — el síntoma es
            # «actualicé y el arreglo no está».
            return Result(
                WARN,
                f"{detail} — pero la versión instalada es {installed}: el daemon sirve la vieja",
                RESTART_HINT,
            )
        return Result(OK, detail)
    if _port_taken(host, port):
        return Result(WARN, f"alguien escucha en {host}:{port} pero no es nuestro daemon")
    return Result(MISSING, f"nadie escucha en {host}:{port}", SERVE_HINT)


def _probe_backend_models(ctx: Context) -> Result:
    healthy, reason = ctx.backend_models()
    if healthy:
        return Result(OK, f"{config.BASE_URL}/models responde")
    if reason.startswith(("responde 401", "responde 403")):
        # El backend está vivo; lo que falta es la credencial en **este** entorno. Decir
        # «caído» mandaría a arrancar un servicio que ya corre.
        return Result(UNKNOWN, f"{config.BASE_URL}/models {reason}")
    return Result(
        WARN,
        f"{config.BASE_URL}/models {reason or 'no responde'} (backend caído)",
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
# Trece elementos, en orden de grupo. Una tupla: si esto necesitara alguna vez cargarse solo,
# el problema no sería el registro sino el diseño.
#
# El número se dice en cuatro sitios de este módulo y llegó a decir «once» con doce checks ya
# dentro: `cli.path` entró después y nadie actualizó el texto. Hay un test que compara los
# cuatro contra `len(CHECKS)`, porque un comentario que miente sobre el propio registro es lo
# que hace que alguien planifique sobre un dato falso.
CHECKS: tuple[Check, ...] = (
    Check("cli.path", "entorno", "CLI local-delegate", _probe_cli),
    Check("cli.published", "entorno", "versión publicada", _probe_published),
    Check("client.presence", "entorno", "clientes", _probe_clients),
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


def run_all(ctx: Context, *, groups: tuple[str, ...] | None = None) -> list[tuple[Check, Result]]:
    """Corre los trece probes. Un probe que falle es ``unknown``, nunca tumba el diagnóstico.

    Con ``groups`` se corren solo los de esos grupos, en el mismo orden del registro. Lo pide
    ``install``: su reporte final habla del andamiaje que acaba de escribir, y correr también
    ``servicio`` y ``backend`` saldría a la red y lanzaría los binarios de llama-swap por el
    simple hecho de haber instalado unos hooks. El filtro no toca ni el registro ni los probes:
    sin el argumento, el comportamiento es exactamente el de antes.
    """
    results: list[tuple[Check, Result]] = []
    for check in CHECKS:
        if groups is not None and check.group not in groups:
            continue
        try:
            result = check.probe(ctx)
        except Exception as exc:  # un check roto no debe impedir ver los otros doce
            result = Result(UNKNOWN, f"la comprobación falló: {exc}")
        results.append((check, result))
    return results
