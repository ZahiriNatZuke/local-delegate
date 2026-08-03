"""update.py — `local-delegate update`: revisa, completa, actualiza y deja el daemon arriba.

Reparto de responsabilidades, que es lo que hace que este módulo sea corto:

- **Quién mira** es ``checks.run_all``. Aquí no hay ni un ``probe`` nuevo: el diagnóstico ya
  existe desde el change ``checks-andamiaje`` y duplicarlo sería tener dos definiciones de
  «estar a punto» que se separarían al primer cambio.
- **Quién arregla** es ``install.plan_install`` + ``install.apply``, que ya saben escribir de
  forma idempotente y con ``.bak``.
- **Lo que aporta este módulo** son las dos cosas que ``checks`` dejó deliberadamente fuera:
  decidir *qué* se repara (la tabla :data:`REPAIRS`) y controlar el ciclo de vida del daemon.

Tres reglas duras, todas por seguridad y ninguna negociable:

1. **``unknown`` no repara nunca.** Es la regla que trajo ``checks``: un cliente ausente, un
   fichero sin permisos o un JSON ilegible se reportan ``unknown``, y «arreglarlos» sería
   sobrescribir configuración ajena a ciegas.
2. **El pid sale solo de ``/api/daemon``.** No se lee ``daemon.json``. La forma más fuerte de
   no señalar a un pid reciclado no es leerlo y verificarlo: es no leerlo nunca.
3. **Con ``--home`` simulado no se toca ningún servicio.** El daemon y el backend no viven en
   el HOME, así que un flag documentado como «para pruebas» reiniciaría el daemon de verdad.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from . import checks, config, install

PACKAGE = "local-delegate-mcp"

# Nombres canónicos del servicio en cada sistema. Los mismos que documenta docs/wiki/Daemon.md:
# si estos tres strings y la wiki se separan, `update` buscará un servicio que nadie registró.
TASK_NAME = "LocalDelegateDaemon"  # Windows, tarea programada
LAUNCH_LABEL = "com.local-delegate.daemon"  # macOS, LaunchAgent
SYSTEMD_UNIT = "local-delegate.service"  # Linux, systemd --user

# Mecanismos de arranque, en el orden en que se prueban.
SCHTASKS = "schtasks"
LAUNCHCTL = "launchctl"
SYSTEMD = "systemd"
FALLBACK = "fallback"

MECHANISM_LABEL = {
    SCHTASKS: f"tarea programada {TASK_NAME}",
    LAUNCHCTL: f"LaunchAgent {LAUNCH_LABEL}",
    SYSTEMD: f"unidad {SYSTEMD_UNIT} de systemd --user",
    FALLBACK: "terminar el proceso y relanzar `serve` desacoplado",
}


# --- Ejecución de comandos, inyectable ---------------------------------------
def _default_runner(argv: list[str]) -> subprocess.CompletedProcess:
    """Ejecuta y captura. Nunca lanza: un binario ausente es un returncode, no una excepción."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, returncode=127, stdout="", stderr=str(exc))


Runner = Callable[[list[str]], subprocess.CompletedProcess]


@dataclass
class Options:
    """Lo que pidió el usuario, más los colaboradores que los tests doblan.

    Los colaboradores se declaran ``None`` y se resuelven en ``__post_init__`` en vez de poner
    la función directamente como valor por defecto. Escrito de la otra forma, un análisis
    estático lee ``Options.runner`` como un método y cuenta un ``self`` que en tiempo de
    ejecución no existe —el ``__init__`` del dataclass asigna el default a la instancia—, así
    que la llamada parece tener un argumento de más. Funciona igual, pero la ambigüedad es real
    y CodeQL la reporta como error: mejor no dejarla escrita.
    """

    home: Path
    dry_run: bool = False
    version: str | None = None
    restart_backend: bool = False
    no_restart: bool = False
    runner: Runner | None = None
    daemon_status: Callable[[str, int], dict | None] | None = None
    sleep: Callable[[float], None] | None = None
    clock: Callable[[], float] | None = None
    spawn: Callable[[list[str]], None] | None = None

    def __post_init__(self) -> None:
        if self.runner is None:
            self.runner = _default_runner
        if self.daemon_status is None:
            self.daemon_status = checks._default_daemon_status
        if self.sleep is None:
            self.sleep = time.sleep
        if self.clock is None:
            self.clock = time.monotonic

    @property
    def simulated_home(self) -> bool:
        """True si ``--home`` apunta fuera del HOME real: entonces no se toca ningún servicio.

        La regla vive en ``install`` desde el change ``install-checks-clients``, porque ahí la
        necesita también el instalador para no dejar que el binario ``claude`` escriba fuera del
        árbol simulado. Una sola definición, dos consumidores.
        """
        return install.is_simulated_home(self.home)


# Los checks que miran una entrada MCP. Se enumeran en dos sitios de este módulo —de qué modo
# es la máquina, y qué avisos se silencian—, y tenerlos escritos a mano en ambos es como se
# quedó fuera opencode del primero mientras entraba en el segundo.
_CHECKS_MCP = ("scaffold.mcp_claude", "scaffold.mcp_codex", "scaffold.mcp_opencode")

# --- La tabla de reparaciones -------------------------------------------------
# Marcador para `scaffold.memory`, que escribe en los clientes que existan en la máquina en vez
# de en un conjunto fijo: reinstalar el bloque de Codex en una máquina sin Codex crearía
# `~/.codex/AGENTS.md` de la nada.
PRESENT = "present"


@dataclass(frozen=True)
class Repair:
    """Qué acción de ``install`` arregla un check, y bajo qué estados se aplica."""

    check_id: str
    states: tuple[str, ...]
    components: frozenset[str]
    targets: frozenset[str] | str
    why: str = ""


# Los checks que no aparecen aquí —`cli.path`, `client.presence`, `client.observed`,
# `service.backend`, `service.credential`, `backend.llamaswap`, `backend.llamaserver`— no se
# reparan escribiendo en el HOME: de ellos se imprime su `fix_hint` y ya. `service.daemon` tampoco
# está: lo atiende el control del daemon. `client.observed` además no tiene arreglo posible:
# informa de con qué clientes se ha hablado, y eso no se configura desde aquí.
#
# `service.credential` está fuera por una razón distinta y deliberada: **sí** se sabría reparar
# —reinstalar la entrada MCP en modo `http`, que `_infer_mcp_mode` ya sabe elegir—, pero eso
# cambiaría el **modo de transporte** que el usuario configuró, y eso es una decisión suya, no un
# trozo de andamiaje roto que haya que reponer. Es el mismo criterio que deja fuera el `warn` de
# `scaffold.mcp_codex`: no se pisa configuración escrita por una persona. El aviso dice qué pasa y
# qué comando lo arregla; ejecutarlo es del usuario.
REPAIRS: tuple[Repair, ...] = (
    Repair("scaffold.hook_files", (checks.MISSING,), frozenset({"hooks"}), frozenset({"claude"})),
    Repair(
        "scaffold.hook_settings",
        # `warn` aquí significa «hooks de una instalación anterior»: son nuestros y están
        # viejos, así que reinstalarlos es exactamente lo correcto.
        (checks.MISSING, checks.WARN),
        frozenset({"hooks"}),
        frozenset({"claude"}),
        why="hooks en formato de instalación anterior",
    ),
    Repair(
        "scaffold.hook_orphans",
        # `warn` aquí significa «scripts nuestros de una instalación anterior, sueltos en la raíz
        # de ~/.claude/hooks/». Son nuestros y sobran, igual que los otros dos casos que reparan
        # en `warn`. `plan_install` con components={"hooks"} emite la copia del árbol **y** el
        # retirado; la deduplicación por (kind, target) evita que se dupliquen si `hook_files`
        # también pide reparación.
        (checks.WARN,),
        frozenset({"hooks"}),
        frozenset({"claude"}),
        why="scripts de hooks de una instalación anterior",
    ),
    Repair(
        "scaffold.skill",
        # `warn` = el directorio existe sin SKILL.md. También es nuestro y está incompleto.
        (checks.MISSING, checks.WARN),
        frozenset({"skill"}),
        # `PRESENT` y no `{"claude"}`: la skill se escribe en dos clientes, y fijar uno dejaba la
        # de opencode sin reponer aunque el check la viera faltar. Que `PRESENT` incluya también
        # Codex es inocuo —`plan_install` no emite acción de skill para él, porque no tiene
        # skills—, y es el mismo marcador que ya usa `scaffold.memory` por la misma razón: no
        # crearle a nadie el directorio de un cliente que no tiene instalado.
        PRESENT,
        why="skill incompleta",
    ),
    Repair("scaffold.memory", (checks.MISSING,), frozenset({"memory"}), PRESENT),
    Repair("scaffold.mcp_claude", (checks.MISSING,), frozenset({"mcp"}), frozenset({"claude"})),
    # `scaffold.mcp_codex` NO repara en `warn`, y es la excepción que ordena toda la tabla: ese
    # aviso dice «entrada puesta a mano, sin marcadores», o sea configuración escrita por el
    # usuario. Pisarla sería el fallo contra el que existe la regla de `unknown`.
    Repair("scaffold.mcp_codex", (checks.MISSING,), frozenset({"mcp"}), frozenset({"codex"})),
    # opencode NO tiene un `warn` equivalente al de Codex, y no es un olvido: su entrada se
    # identifica por la clave `mcp["local-delegate"]` y no por marcadores —una clave desconocida
    # impide arrancar el cliente—, así que no hay forma de distinguir la nuestra de una escrita a
    # mano. Es la misma situación que con Claude Code, y se trata igual: solo se repone si falta.
    Repair("scaffold.mcp_opencode", (checks.MISSING,), frozenset({"mcp"}), frozenset({"opencode"})),
)


def _present_targets(home: Path) -> set[str]:
    """Clientes que existen en esta máquina. La definición vive en ``install`` (ver arriba)."""
    return install.present_targets(home)


def _infer_mcp_mode(results: list[tuple[checks.Check, checks.Result]]) -> str:
    """Modo de la entrada MCP que hay que escribir cuando falta en un cliente.

    ``update`` no tiene flag para elegirlo (la spec fija cinco y ninguna es esta), así que se
    deduce de lo que la máquina ya usa: si la entrada del otro cliente es HTTP, o si el daemon
    responde, la máquina trabaja contra el daemon. Si no hay ninguna señal, ``stdio``, que es
    el default de ``install`` y el modo que no depende de un servicio.
    """
    for check, result in results:
        if (
            check.id in _CHECKS_MCP
            and result.status == checks.OK
            # `remote` es como opencode llama a lo que los otros dos llaman `http`.
            and ("http" in result.detail or "remote" in result.detail)
        ):
            return "http"
    for check, result in results:
        if check.id == "service.daemon" and result.status in (checks.OK, checks.WARN):
            return "http"
    return "stdio"


def plan_repairs(
    results: list[tuple[checks.Check, checks.Result]], opts: Options
) -> tuple[list[install.Action], list[str]]:
    """(acciones a ejecutar, avisos de lo que no se repara solo).

    Pura: no toca disco ni red. La idempotencia sale de aquí sin programarla — si la pasada
    anterior arregló todo, los probes responden ``ok``, ningún ``Repair`` casa y la lista de
    acciones queda vacía.
    """
    by_id = {check.id: result for check, result in results}
    mcp_mode = _infer_mcp_mode(results)
    present = _present_targets(opts.home)

    actions: list[install.Action] = []
    for repair in REPAIRS:
        result = by_id.get(repair.check_id)
        if result is None or result.status not in repair.states:
            continue
        targets = present if repair.targets is PRESENT else set(repair.targets) & present
        if not targets:
            continue
        # Una llamada por par (componente, target): `plan_install` es puro y barato, y así
        # reparar Codex no arrastra a Claude.
        for target in sorted(targets):
            actions.extend(
                install.plan_install(
                    install.Options(
                        home=opts.home,
                        components=set(repair.components),
                        targets={target},
                        python_exe=install.default_python(),
                        mcp_mode=mcp_mode,
                        # Con un HOME simulado hay que escribir el fichero a mano: el camino
                        # por CLI (`claude mcp add-json --scope user`) escribe SIEMPRE en el
                        # `~/.claude.json` del usuario real, ignorando `home`. Se descubrió
                        # ejecutando `update --home <tmp>` dos veces: la segunda pasada volvía
                        # a planificar la misma acción —el probe seguía viendo el árbol
                        # simulado vacío— mientras la config de verdad sí se había reescrito.
                        use_cli=not opts.simulated_home,
                    )
                )
            )

    # Deduplicación por (kind, target), y no es cosmética: `plan_install` con
    # components={"hooks"} emite DOS acciones —copiar el árbol y registrar en settings.json— y
    # `_copy_tree_action` hace `shutil.rmtree(dst)` antes de copiar. Con `hook_files` y
    # `hook_settings` los dos en `missing` se planificarían dos borrados del mismo directorio.
    unique: list[install.Action] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        key = (action.kind, str(action.target))
        if key not in seen:
            seen.add(key)
            unique.append(action)

    notes = [
        f"{check.title}: {result.fix_hint}"
        for check, result in results
        if result.fix_hint and check.id not in {r.check_id for r in REPAIRS}
    ]
    return unique, notes


# --- El pin de versión (paridad con el bash) ----------------------------------
def latest_version(timeout: float = 30.0) -> tuple[str | None, str | None]:
    """(última versión publicada, motivo si no se pudo saber).

    Se consulta el **índice simple** y no ``/pypi/<pkg>/json``: ese endpoint se sirve con
    caché y puede tardar en reflejar una release recién publicada — se vio en vivo con la
    0.12.0. Portado tal cual del bash, incluido el porqué.

    Medido el 2026-07-30, por si alguien vuelve a proponer el cambio: el índice simple responde
    con ``cache-control: max-age=600`` y el JSON con ``max-age=900``. O sea que el que ya se usa
    es **el más fresco de los dos**, y cambiar de endpoint empeoraría el síntoma en vez de
    arreglarlo. Los dos se sirven con caché; ninguno da un header ``Age`` con el que saber si lo
    servido está desfasado, y de ahí que la salida de ``update`` lo diga en vez de adivinarlo.
    """
    request = urllib.request.Request(
        f"https://pypi.org/simple/{PACKAGE}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"no se pudo consultar PyPI ({exc})"

    versions = [v for v in data.get("versions", []) if re.fullmatch(r"\d+(\.\d+)*", v)]
    if not versions:
        return None, "PyPI no devolvió ninguna versión utilizable"
    # Ordena por número y no alfabéticamente: "0.9.0" es MENOR que "0.11.0".
    return max(versions, key=lambda v: [int(p) for p in re.findall(r"\d+", v)]), None


PYPI_SOURCE = "índice simple de PyPI, que se sirve con caché"


def version_lines(version: str | None, reason: str | None, *, from_user: bool) -> list[str]:
    """Las líneas que `update` imprime sobre la versión, con su procedencia.

    Antes esto era un ``if/else`` de dos ramas que decía *«Última versión publicada: X»* incluso
    cuando la X la había escrito el usuario en ``--version``: el mensaje afirmaba algo que nadie
    había comprobado.

    Y añade el aviso que da nombre a este cambio. Justo después de publicar, ``update`` anuncia
    como «última» la **anterior**, y el usuario no tiene forma de saber si es que PyPI todavía
    sirve caché o si la publicación no terminó. No se puede distinguir desde aquí — pero sí se
    puede detectar la **firma** del caso, que es exacta y no una heurística: al publicar la
    0.17.0 desde el repo, la instalación local **es** 0.17.0 y PyPI todavía dice 0.16.0. O sea,
    la instalada más nueva que la publicada.
    """
    if from_user:
        return [f"Versión pedida con --version: {version}"]
    if version is None:
        # Sin red no se puede resolver el pin, pero completar y reiniciar sí se puede: se avisa
        # y se sigue. No es un error (edge case de la spec).
        return [f"Aviso: {reason}. Se sigue sin tocar los pines."]

    lines = [f"Última versión publicada: {version} ({PYPI_SOURCE})"]
    installed = checks._installed_version()
    # `_compare_versions` devuelve None si alguna no es comparable; ahí se calla en vez de
    # inventarse un aviso, que es la misma regla que gobierna todo el registro de checks.
    if installed and checks._compare_versions(installed, version) == 1:
        lines += [
            f"  Ojo: la instalada ({installed}) es MÁS NUEVA que la que anuncia PyPI.",
            "  Suele significar que la publicación aún no se propagó (o no ha terminado).",
            f"  Si es la que quieres fijar: local-delegate update --version {installed}",
        ]
    return lines


_PIN_RE = re.compile(re.escape(PACKAGE) + r"==[\d.]+")


def current_pin(path: Path) -> str | None:
    """Versión fijada en el fichero, ``"sin-pin"`` si está la entrada sin ``==``, o None."""
    text, _reason = checks.read_text(path)
    if text is None or PACKAGE not in text:
        return None
    match = re.search(re.escape(PACKAGE) + r"==([\d.]+)", text)
    return match.group(1) if match else "sin-pin"


def plan_pin(opts: Options, version: str) -> list[install.Action]:
    """Acciones que cambian el pin donde exista. Sin pin no hay nada que cambiar."""
    actions: list[install.Action] = []
    for path in (opts.home / ".claude.json", opts.home / ".codex" / "config.toml"):
        current = current_pin(path)
        if current is None or current == "sin-pin" or current == version:
            continue

        def _run(path=path, current=current) -> str:
            text, _ = checks.read_text(path)
            # `install._write_text` ya deja `.bak` y conserva el terminador de línea del
            # fichero: en Windows, escribir con el de la plataforma convertiría a CRLF un
            # `.claude.json` guardado en LF y el usuario vería el fichero entero modificado.
            install._write_text(path, _PIN_RE.sub(f"{PACKAGE}=={version}", text or ""))
            return f"{current} -> {version} (copia en {path.name}.bak)"

        actions.append(install.Action("pin", path, f"fija {PACKAGE}=={version}", _run))
    return actions


# --- Instalación editable (PEP 610) -------------------------------------------
def editable_origin() -> Path | None:
    """Directorio del que se sirve el paquete si la instalación es **editable**, o None.

    Por PEP 610: ``direct_url.json`` con ``dir_info.editable`` verdadero. Importa porque en una
    instalación editable reiniciar el daemon **no cambia la versión** —el código sale del
    repo—, y quien actualiza esperaría lo contrario.
    """
    try:
        distribution = metadata.Distribution.from_name(PACKAGE)
        raw = distribution.read_text("direct_url.json")
    except Exception:  # PackageNotFoundError o metadatos ausentes: no es editable que sepamos
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get("dir_info", {}).get("editable"):
        return None
    url = str(data.get("url", ""))
    if url.startswith("file://"):
        from urllib.parse import unquote, urlparse

        path = unquote(urlparse(url).path)
        if sys.platform == "win32" and re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return Path(path)
    return Path(url) if url else None


# --- Cómo está instalado esto -------------------------------------------------
EDITABLE = "editable"  # el código sale de un repo clonado
UV_TOOL = "uv-tool"  # instalado con `uv tool install`
OTHER = "other"  # pip, pipx, conda… no lo sabemos, y no lo adivinamos

UV_TOOL_UPGRADE = f"uv tool upgrade {PACKAGE}"
GENERIC_UPGRADE = f"actualiza {PACKAGE} con el gestor con el que lo instalaste"


def install_kind() -> str:
    """Cómo está instalado el paquete **que se está ejecutando**.

    El matiz de «que se está ejecutando» es el importante: en una máquina pueden convivir la
    instalación de ``uv tool`` y una editable del repo, y de hecho conviven en la de desarrollo.
    Responder por la que no corre sería el mismo falso diagnóstico que ya costó caro aquí con el
    backend en 401.

    ``uv tool`` deja un ``uv-receipt.toml`` en la raíz del entorno; el ``.venv`` de un repo no lo
    tiene. Se mira ese fichero y no ``uv tool dir``, ni ``UV_TOOL_DIR``, ni una ruta por sistema
    operativo: es una lectura local que responde igual en los tres, sin depender de que ``uv``
    esté en el PATH de este proceso.
    """
    if editable_origin():
        # Gana sobre cualquier otra cosa: es lo que gobierna de dónde sale el código.
        return EDITABLE
    try:
        # `sys.prefix` se lee AQUÍ y no en una constante del módulo: capturado al importar, un
        # test no podría doblarlo y estaría comprobando la máquina en la que corre.
        receipt = Path(sys.prefix) / "uv-receipt.toml"
        text = receipt.read_text(encoding="utf-8", errors="replace")
    except Exception:  # no existe, no se puede leer, sys.prefix raro… nada que afirmar
        return OTHER
    # Basta con que nombre nuestro paquete: parsear el TOML sería precisión que no hace falta
    # para responder «¿este entorno es el nuestro?». `local-delegate-mcp` es distintivo de sobra;
    # con un nombre corto esta comparación por subcadena daría falsos positivos.
    return UV_TOOL if PACKAGE in text else OTHER


def upgrade_command() -> str:
    """El comando que actualiza **esta** instalación, o el genérico si no se reconoce."""
    kind = install_kind()
    if kind == EDITABLE:
        origin = editable_origin()
        return f"git -C {origin} pull && uv sync --project {origin}"
    return UV_TOOL_UPGRADE if kind == UV_TOOL else GENERIC_UPGRADE


def uv_tool_lines(version: str | None) -> list[str]:
    """Aviso de que el CLI de ``uv tool`` se queda atrás, y qué hacer.

    ``update`` actualiza el pin, el andamiaje y el daemon, pero **no** el ejecutable de
    ``uv tool``: son dos pasos donde el usuario espera uno y el segundo no lo decía nadie.

    Y no lo ejecuta él a propósito. Probado en Windows el 2026-07-30 con un paquete de prueba:
    ``uv tool install <pkg>@latest --force`` lanzado desde el Python de ese mismo entorno falla
    con ``Acceso denegado`` al borrar ``Scripts/`` —el proceso lo tiene bloqueado— pero **ya ha
    borrado el paquete**, así que deja la instalación destruida: ``uv tool list`` pasa a decir
    «Failed find package» y el ejecutable revienta con ``ModuleNotFoundError``.
    """
    installed = checks._installed_version()
    if not version or not installed or install_kind() != UV_TOOL:
        return []
    if checks._compare_versions(installed, version) != -1:
        # Al día (o por delante): un aviso que sale siempre deja de leerse.
        return []
    # Sin línea en blanco delante: esto devuelve **el aviso**, no su maquetación. La separación
    # la pone quien imprime, que es el que sabe qué hay encima.
    return [
        f"El CLI está instalado como `uv tool` en la versión {installed}.",
        "  `update` no puede actualizarlo: reinstalaría el entorno desde el que se está",
        "  ejecutando, y eso deja la instalación rota. Hazlo tú, en otra terminal:",
        f"    {UV_TOOL_UPGRADE}",
    ]


# --- Control del daemon -------------------------------------------------------
def _launch_target() -> str:
    """Dominio del LaunchAgent. ``os.getuid`` no existe en Windows, y el camino de macOS
    tiene que poder **probarse** desde cualquier sistema: sin esto, doblar el runner no
    alcanza porque la excepción salta antes de llegar a él."""
    uid = getattr(os, "getuid", lambda: 0)()
    return f"gui/{uid}/{LAUNCH_LABEL}"


def detect_mechanism(opts: Options) -> str:
    """Mecanismo registrado en ESTA máquina.

    No basta con ``sys.platform``: estar en Windows no implica que la tarea exista. Se pregunta
    de verdad, y si nadie la tiene registrada se cae al fallback.
    """
    if sys.platform == "win32":
        done = opts.runner(["schtasks", "/Query", "/TN", TASK_NAME])
        return SCHTASKS if done.returncode == 0 else FALLBACK
    if sys.platform == "darwin":
        done = opts.runner(["launchctl", "print", _launch_target()])
        return LAUNCHCTL if done.returncode == 0 else FALLBACK
    done = opts.runner(["systemctl", "--user", "cat", SYSTEMD_UNIT])
    return SYSTEMD if done.returncode == 0 else FALLBACK


def _stop_start_commands(mechanism: str) -> tuple[list[list[str]], list[list[str]]]:
    """(comandos para parar, comandos para arrancar) de cada mecanismo.

    Están separados porque el de Windows lo necesita: entre parar y arrancar hay que comprobar
    que el proceso murió de verdad. `launchctl kickstart -k` y `systemctl restart` hacen las dos
    cosas en un solo comando y por eso no tienen fase de parada.
    """
    if mechanism == SCHTASKS:
        return ([["schtasks", "/End", "/TN", TASK_NAME]], [["schtasks", "/Run", "/TN", TASK_NAME]])
    if mechanism == LAUNCHCTL:
        return ([], [["launchctl", "kickstart", "-k", _launch_target()]])
    if mechanism == SYSTEMD:
        return ([], [["systemctl", "--user", "restart", SYSTEMD_UNIT]])
    return ([], [])


def _spawn_detached(opts: Options, argv: list[str]) -> None:
    """Relanza ``serve`` sin quedarse atado al proceso actual."""
    if opts.spawn is not None:
        opts.spawn(argv)
        return
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def _serve_argv() -> list[str]:
    return [sys.executable, "-m", "local_delegate", "serve", "--log-level", "warning"]


def wait_until_up(
    opts: Options, *, other_than: int | None = None, timeout: float = 20.0
) -> dict | None:
    """Espera a que ``/api/daemon`` responda. Con ``other_than`` exige que el pid sea distinto.

    El reloj y el ``sleep`` son inyectables porque si no los tests esperarían de verdad.
    """
    host, port = checks.daemon_host_port()
    deadline = opts.clock() + timeout
    while True:
        status = opts.daemon_status(host, port)
        if status and (other_than is None or status.get("pid") != other_than):
            return status
        if opts.clock() >= deadline:
            return None
        opts.sleep(0.5)


def _terminate(opts: Options, pid: int | None, out) -> None:
    """Señal al pid **confirmado por /api/daemon**. Nunca a un pid leído de un fichero."""
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        out(f"    aviso: no se pudo terminar el pid {pid}: {exc}")
    opts.sleep(1.0)


def _sigue_sirviendo(opts: Options, pid: int, espera: float = 6.0) -> bool:
    """True si tras parar el servicio ese mismo pid **sigue** respondiendo en el puerto."""
    host, port = checks.daemon_host_port()
    deadline = opts.clock() + espera
    while opts.clock() < deadline:
        status = opts.daemon_status(host, port)
        if status is None or status.get("pid") != pid:
            return False
        opts.sleep(0.5)
    return True


def restart_daemon(opts: Options, out=print) -> int:
    """Reinicia (o levanta) el daemon y **verifica** que quedó arriba. Devuelve fallos."""
    host, port = checks.daemon_host_port()
    before = opts.daemon_status(host, port)
    # REQ-008: el único pid que se maneja es el que devuelve /api/daemon en ESTA ejecución. Un
    # pid reciclado no puede llegar aquí, porque nunca se lee `daemon.json`.
    previous_pid = before.get("pid") if before else None
    mechanism = detect_mechanism(opts)

    if before:
        out(f"Reiniciando el daemon (pid {previous_pid}) por {MECHANISM_LABEL[mechanism]}…")
    else:
        out(f"El daemon no responde; se levanta por {MECHANISM_LABEL[mechanism]}…")

    if mechanism == FALLBACK:
        _terminate(opts, previous_pid, out)
        _spawn_detached(opts, _serve_argv())
    else:
        stop_commands, start_commands = _stop_start_commands(mechanism)
        for argv in stop_commands:
            done = opts.runner(argv)
            if done.returncode != 0:
                out(f"    aviso: `{' '.join(argv)}` falló ({done.stderr.strip() or 'sin detalle'})")

        # Parar el SERVICIO no siempre para el PROCESO, y esto se descubrió ejecutándolo: en
        # Windows la tarea lanza `conhost -> powershell -> launcher`, y el launcher crea el
        # daemon con `Start-Process`, o sea **desacoplado**. `schtasks /End` termina la cadena
        # de la tarea y el nieto sobrevive con el puerto tomado; el `/Run` siguiente arranca una
        # instancia que no puede escuchar, y el reinicio se da por fallido con el daemon viejo
        # todavía sirviendo. Por eso, si el mismo pid sigue ahí, se le manda la señal — y es
        # legítimo porque ese pid lo confirmó `/api/daemon`, no un fichero de estado.
        if stop_commands and previous_pid and _sigue_sirviendo(opts, previous_pid):
            out(f"    el servicio paró pero el pid {previous_pid} sigue sirviendo (launcher")
            out("    desacoplado): se le manda la señal al proceso confirmado.")
            _terminate(opts, previous_pid, out)

        for argv in start_commands:
            done = opts.runner(argv)
            if done.returncode != 0:
                out(
                    f"    aviso: `{' '.join(argv)}` falló ({done.stderr.strip() or done.returncode})"
                )
                out("    se cae al fallback: terminar y relanzar")
                _terminate(opts, previous_pid, out)
                _spawn_detached(opts, _serve_argv())
                break

    status = wait_until_up(opts, other_than=previous_pid)
    if status is None:
        out("ERROR: el daemon no volvió a responder dentro del margen de espera.")
        return 1
    out(f"    daemon {status.get('version')} arriba · pid {status.get('pid')}")
    # REQ-013: el backend es un proceso aparte y no se ha tocado.
    out("    el backend de inferencia no se ha tocado: los modelos siguen en VRAM.")
    return 0


# --- El backend, solo bajo petición explícita ---------------------------------
_PORT_OWNER_RE = re.compile(r"\s(\d+)\s*$")


def _port_owner(opts: Options, port: int) -> int | None:
    """Pid de quien escucha en el puerto, por el mecanismo de cada sistema."""
    if sys.platform == "win32":
        done = opts.runner(["netstat", "-ano", "-p", "TCP"])
        for line in done.stdout.splitlines():
            if (
                f":{port} " in line
                and "LISTENING" in line
                and (match := _PORT_OWNER_RE.search(line.rstrip()))
            ):
                return int(match.group(1))
        return None
    done = opts.runner(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"])
    first = done.stdout.strip().splitlines()
    return int(first[0]) if first and first[0].strip().isdigit() else None


def _process_name(opts: Options, pid: int) -> str:
    if sys.platform == "win32":
        done = opts.runner(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"])
        return done.stdout.strip().strip('"').split('","')[0] if done.stdout.strip() else ""
    done = opts.runner(["ps", "-p", str(pid), "-o", "comm="])
    return done.stdout.strip()


def restart_backend(opts: Options, out=print) -> int:
    """Reinicia llama-swap. Solo con ``--restart-backend`` explícito (REQ-012)."""
    origin = config.backend_origin()
    if origin != "local":
        # El caso de la Mac apuntando a la PC por Tailscale: el backend no corre aquí y no hay
        # nada que reiniciar. No es un error.
        out(f"El backend es remoto ({config.backend_host()}): no hay nada que reiniciar aquí.")
        return 0

    _host, port = config._split_host_port(config.BASE_URL)
    port_number = int(str(port).lstrip(":") or 0)
    if not port_number:
        out(f"El backend ({config.BASE_URL}) no declara puerto: no se puede localizar el proceso.")
        return 1
    pid = _port_owner(opts, port_number)
    if not pid:
        out(f"Nadie escucha en el puerto {port_number}; se intenta arrancar el backend.")
    else:
        name = _process_name(opts, pid)
        # Dos confirmaciones antes de señalar, igual que con el daemon: el propio docstring de
        # `backend_origin` avisa de que la heurística del host falla con un túnel.
        if "llama-swap" not in name.lower():
            out(f"El puerto {port_number} lo ocupa '{name}' (pid {pid}), que no es llama-swap.")
            out("No se toca. Revisa qué está escuchando ahí.")
            return 1
        out(f"Terminando llama-swap (pid {pid})…")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            out(f"ERROR: no se pudo terminar el pid {pid}: {exc}")
            return 1
        opts.sleep(2.0)

    from . import autostart

    if autostart.ensure_backend(wait=15.0):
        out("    backend arriba de nuevo.")
        return 0
    out("ERROR: el backend no volvió a responder.")
    return 1


# --- Orquestación --------------------------------------------------------------
def run_update(opts: Options, out=print) -> int:
    """Ejecuta el subcomando completo. Devuelve el código de salida."""
    out(f"local-delegate update — HOME: {opts.home}")
    if opts.simulated_home:
        out("  (--home simulado: se repara ese árbol y NO se toca ningún servicio)")
    out("")

    # 1. Diagnóstico: el mismo que ve `doctor`, sin lógica propia. Con `SKIP_PYPI` porque la
    # última versión publicada la pregunta el paso 2 unas líneas más abajo, y dejar que el check
    # la preguntase otra vez sería consultar dos veces lo mismo en un solo comando.
    ctx = checks.Context(
        home=opts.home, daemon_status=opts.daemon_status, latest_release=checks.SKIP_PYPI
    )
    results = checks.run_all(ctx)

    # 2. La versión: la que pidió el usuario, o la última publicada. Las líneas dicen de dónde
    # salió el dato; el aviso de desfase que puedan traer es informativo y no toca el plan.
    version, reason = (opts.version, None) if opts.version else latest_version()
    for line in version_lines(version, reason, from_user=bool(opts.version)):
        out(line)

    editable = editable_origin()
    if editable:
        out("")
        out(f"Instalación EDITABLE: el código se sirve de {editable}")
        out("  Reiniciar el daemon NO cambia la versión. Para actualizar de verdad:")
        out(f"    git -C {editable} pull")
        out(f"    uv sync --project {editable}")

    # El hermano del bloque de arriba para el otro modo de instalación: `update` tampoco cambia
    # la versión del ejecutable de `uv tool`, y hasta ahora no lo decía nadie.
    if aviso := uv_tool_lines(version):
        out("")
        for line in aviso:
            out(line)

    # 3. Plan: pines + reparaciones del andamiaje.
    actions = plan_pin(opts, version) if version else []
    repairs, notes = plan_repairs(results, opts)
    actions.extend(repairs)

    out("")
    if actions:
        failures = install.apply(actions, dry_run=opts.dry_run, out=out)
    else:
        out("Nada que reparar: el andamiaje está completo y los pines al día.")
        failures = 0

    for note in notes:
        out(f"  aviso — {note}")

    # 4. El daemon, al final de todo.
    if opts.dry_run:
        out("")
        out("--dry-run: no se escribió nada ni se reinició ningún servicio.")
        return 0
    if failures:
        out(f"{failures} acción(es) fallaron.")
        return 1

    out("")
    if opts.no_restart:
        out("--no-restart: no se toca el daemon.")
        return 0
    if opts.simulated_home:
        out("HOME simulado: no se toca el daemon de la máquina.")
        return 0

    daemon_result = _daemon_status_of(results)
    if daemon_result is None or not _daemon_applies(results):
        # El caso `stdio` + `uvx` de la Mac: no hay daemon que reiniciar y no es un error.
        out("No hay daemon que reiniciar: la configuración usa stdio (uvx arranca el MCP).")
        out("Lo que aplica aquí es reiniciar el cliente (Claude Code / Codex).")
        return 0

    code = restart_daemon(opts, out=out)
    if opts.restart_backend:
        out("")
        code = max(code, restart_backend(opts, out=out))
    return code


def _daemon_status_of(results: list[tuple[checks.Check, checks.Result]]) -> checks.Result | None:
    for check, result in results:
        if check.id == "service.daemon":
            return result
    return None


def _daemon_applies(results: list[tuple[checks.Check, checks.Result]]) -> bool:
    """¿La configuración de algún cliente usa el daemon (entrada HTTP), o ya está vivo?"""
    for check, result in results:
        if check.id == "service.daemon" and result.status in (checks.OK, checks.WARN):
            return True
        if (
            check.id in _CHECKS_MCP
            and result.status == checks.OK
            and ("http" in result.detail or "remote" in result.detail)
        ):
            return True
    return False
