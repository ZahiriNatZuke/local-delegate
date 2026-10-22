"""checks.py — registro único de las comprobaciones del andamiaje.

Antes de este módulo cada subcomando sabía un pedazo del sistema: ``doctor`` solo miraba el
backend, ``install`` escribía sin verificar y nadie miraba el daemon. Aquí vive **una sola
definición de «estar a punto»**: los treinta y tres elementos del andamiaje, cada uno con un
``probe`` que responde en qué estado está. Los cinco de la entrega por plugin de Claude Code
viven en ``checks_plugin``, pero se registran aquí como los demás.

Tres reglas ordenan el módulo:

1. **``probe`` nunca escribe.** Es lo que permite que ``doctor`` siga siendo de solo lectura;
   hay un test que compara el árbol del HOME simulado byte a byte antes y después.
2. **Lo que no se pudo comprobar es ``unknown``, nunca ``missing``.** Un cliente que no está
   instalado o un fichero ilegible por permisos no significan «falta»: si se reportaran así,
   un ``fix`` posterior sobrescribiría configuración ajena.
3. **Es una lista, no un framework.** Treinta y tres checks son una tupla de objetos con una
   función; no hay registro dinámico, ni entry points, ni herencia. Si hiciera falta algo de eso,
   el diseño se revisa antes de seguir.

Los arreglos no viven aquí: un ``probe`` solo declara en ``fix_hint`` qué comando resuelve lo
que encontró. Ejecutarlos es trabajo de ``update`` e ``install``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import metadata
from itertools import pairwise
from pathlib import Path
from urllib.parse import urlsplit

from . import (
    attribution,
    checks_plugin,
    claude_plugin,
    clients,
    config,
    cost,
    desktop_config,
    failures,
    i18n,
    install,
    install_state,
    legacy_names,
    probes,
    recompute,
    test_windows,
    token_source,
)

# --- Estados -----------------------------------------------------------------
OK = "ok"  # está y como debe estar
MISSING = "missing"  # falta y se puede arreglar
WARN = "warn"  # está, pero no como debería
UNKNOWN = "unknown"  # no se pudo comprobar (no aplica, sin permisos, sin datos)

# Prefijos de la salida, por su clave del catálogo: seis columnas en los dos idiomas.
STATUS_LABEL: dict[str, str] = {
    OK: "doctor.status.ok",
    WARN: "doctor.status.warn",
    MISSING: "doctor.status.missing",
    UNKNOWN: "doctor.status.unknown",
}


def status_label(status: str) -> str:
    """El prefijo de un estado (`[ OK ]`, `[WARN]`…) en el idioma vigente."""
    return i18n.t(STATUS_LABEL[status])


INSTALL_HINT = "local-delegate install"
#: REQ-012: the command that writes the bridge entry of the Claude Desktop chat.
DESKTOP_INSTALL_HINT = "local-delegate install --desktop"
#: The two fixes of `scaffold.shell_completion` (REQ-033): commands, the same in every language.
SHELL_COMPLETION_INSTALL_HINT = "local-delegate install --shell-completion"
SHELL_COMPLETION_UPDATE_HINT = "local-delegate update"


# Las pistas con prosa salen del catálogo al llamarlas: el idioma se resuelve en ejecución.
def update_hooks_hint() -> str:
    return i18n.t("doctor.hint.update_hooks")


def serve_hint() -> str:
    return i18n.t("doctor.hint.serve")


def cli_hint() -> str:
    return i18n.t("doctor.hint.cli")


def restart_hint() -> str:
    return i18n.t("doctor.hint.restart")


def credential_hint() -> str:
    return i18n.t("doctor.hint.credential")


def keychain_hint(service: str) -> str:
    """Cómo guardar una credencial en el Llavero de macOS. `-w` al final la pide por teclado."""
    return i18n.t("doctor.hint.keychain", service=service)


def daemon_token_hint() -> str:
    return i18n.t("doctor.hint.daemon_token")


def _client_name(client: str) -> str:
    """El nombre de producto de un cliente (`claude`, `codex`, `opencode`), igual en los dos idiomas.

    Sale del catálogo y no de un literal porque el guardián de textos (REQ-045) toma «Claude Code»
    por prosa: es un nombre propio que se muestra a personas.
    """
    return i18n.t(f"doctor.client.{client}")


# La variable a la que apunta una cabecera `Bearer`. Cubre las dos sintaxis que escribe `install`:
# `${VAR}` en Claude Code y `{env:VAR}` en opencode. Codex no usa ninguna —da el nombre pelado en
# `bearer_token_env_var`— y por eso el probe lo envuelve antes de llegar aquí, en vez de añadir un
# tercer caso a esta expresión: el vocabulario de cada cliente se traduce una sola vez.
_REFERENCED_VARIABLE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\{env:([A-Z_][A-Z0-9_]*)\}")
# Una sola definición: `install` la usa para conservar la cabecera al reinstalar.
_CODEX_BEARER_RE = install._CODEX_BEARER_RE
# El nombre de la variable, no su valor: el diagnóstico jamás imprime un secreto.
TOKEN_VAR = "LOCAL_DELEGATE_WEB_TOKEN"
# El comando que actualiza el paquete NO se escribe aquí: depende de cómo esté instalado, y esa
# decisión vive en `update.upgrade_command()`, que es de donde la toma `_upgrade_hint`.

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
    group: str  # environment | scaffold | service | backend
    title_key: str  # clave del título en el catálogo (`doctor.check.<id>`)
    probe: Callable[[Context], Result]

    @property
    def title(self) -> str:
        """El título en el idioma vigente (REQ-022); los ids y grupos no cambian con él."""
        return i18n.t(self.title_key, skill=install.SKILL_NAME)


# --- Colaboradores por defecto -----------------------------------------------
# El import de `daemon` es diferido a propósito: arrastra uvicorn y el SDK MCP, que el
# diagnóstico no necesita cargar. Las sondas de versiones y del backend vienen de `probes`, un
# módulo hoja que no importa ni este ni `doctor`: cuando vivían en `doctor`, los dos módulos se
# importaban entre sí. Llamarlas como atributo del módulo (`probes.X()`) y no con `from ...
# import` es lo que permite a los tests doblarlas con monkeypatch sin inyectar nada.
def _default_daemon_status(host: str, port: int) -> dict | None:
    from . import daemon

    return daemon.query_daemon(host, port, timeout=1.0)


def _default_daemon_needs_token(host: str, port: int) -> bool | None:
    """¿El puerto lo sirve un daemon nuestro protegido? Ver ``daemon.daemon_requires_token``."""
    from . import daemon

    return daemon.daemon_requires_token(host, port, timeout=1.0)


def _default_daemon_accepts_token(host: str, port: int, token: str) -> bool | None:
    """¿Entra ese token al puerto? Ver ``daemon.daemon_accepts_token``."""
    from . import daemon

    return daemon.daemon_accepts_token(host, port, token, timeout=1.0)


def _llamaswap_daemon_destination() -> tuple[str, int, dict[str, str]]:
    """Host, puerto y cabecera con que `doctor` pregunta al daemon por llama-swap (T13).

    Función aparte, como `cli._daemon_target`, para que la suite la apunte a un puerto sin
    daemon (`conftest.real_daemon_down`) sin tocar `config.WEB_PORT`.
    """
    host, port = daemon_host_port()
    return host, port, config.web_auth_headers()


def _default_llamaswap_daemon():
    """`(estado, por qué no)` del `GET /api/llamaswap/status` del daemon (ver `llamaswap_api`)."""
    from . import llamaswap_api

    return llamaswap_api.daemon_status(*_llamaswap_daemon_destination())


def NO_LLAMASWAP_DAEMON():
    """Colaborador para los tests: el daemon no contesta por llama-swap y no se sale a la red."""
    return None, i18n.t("doctor.probe.test.no_llamaswap_daemon")


def NO_TOKEN_PROBE(_host: str, _port: int) -> bool | None:
    """Colaborador para los tests: no se pregunta al puerto y no hay veredicto.

    Mismo motivo que :func:`NO_KEY_PROBE`: sin doblarlo la suite saldría a la red, y va en **los
    dos** arneses, no en uno.
    """
    return None


def _default_backend_models() -> failures.BackendView:
    """Lo que se sabe del backend (`failures.BackendView`), preguntando primero al daemon.

    El orden importa y no es una optimización. La clave del backend se lee **del entorno del
    proceso**: el daemon la recibe de su lanzador, pero un `local-delegate doctor` escrito en una
    consola cualquiera no la tiene. Probando por su cuenta, el diagnóstico se llevaba un **401** y
    se quedaba en `unknown` —«está arriba pero rechaza la credencial»— en una máquina donde el
    daemon estaba viendo el backend perfectamente. El dato existía, autenticado, en el mismo
    servicio que el check de al lado ya consulta.

    Si no hay daemon, o no supo responder, se prueba directo como siempre: ese camino sigue siendo
    el correcto cuando nadie más puede mirar por nosotros.
    """
    import httpx2

    from . import daemon

    host, port = daemon_host_port()
    # 1 s para conectar con el daemon, que está en esta máquina; para leer, MÁS que el techo de un
    # sondeo fallido del daemon (REQ-016). Con 1 s de lectura, un fallo lento del backend (VPN,
    # puerto cerrado en Windows) agotaba la consulta y la causa que el daemon ya sabía no llegaba.
    timeout = httpx2.Timeout(
        config.PROBE_CONNECT_TIMEOUT + config.PROBE_READ_TIMEOUT + 1, connect=1.0
    )
    seen = daemon.query_backend(host, port, timeout=timeout)
    if seen is not None:
        if seen.get("available"):
            return failures.BackendView(True, "", None, "daemon")
        # Un daemon de una versión anterior manda `causa`/`detalle` y el valor viejo de la causa
        # (REQ-006): se leen las dos claves y el valor se pasa al formato nuevo.
        cause = legacy_names.new_value(
            legacy_names.CONNECTION_CAUSE_VALUES, legacy_names.read_key(seen, "cause", "causa")
        )
        detail = legacy_names.read_key(seen, "detail", "detalle")
        if isinstance(cause, str) and isinstance(detail, str) and detail:
            return failures.BackendView(False, detail, cause, "daemon")
        # Daemon antiguo, sin causa: el texto de siempre. El daemon SÍ tiene credencial, así
        # que su «no disponible» es un diagnóstico de verdad y no una duda: no cabe el `unknown`.
        return failures.BackendView(
            False, i18n.t("doctor.probe.backend.daemon_down_with_credential"), None, "daemon"
        )
    return probes.backend_probe()


def _default_backend_needs_key() -> tuple[bool | None, str]:
    """¿El backend rechaza a quien no lleva credencial? Ver ``probes.backend_requires_key``."""
    return probes.backend_requires_key()


def NO_KEY_PROBE() -> tuple[bool | None, str]:
    """Colaborador para los tests: no se pregunta al backend y no hay veredicto.

    Existe por el mismo motivo que :func:`NO_CLIENTS`: sin doblarlo, la suite saldría a la red de
    verdad y sería verde en CI —donde no hay backend— y otra cosa en la máquina de quien
    desarrolla. Va en **los dos** arneses, no en uno.
    """
    return None, i18n.t("doctor.probe.test.no_key_probe")


def _default_version_of(component: str, config_path: Path | None) -> tuple[str | None, str | None]:
    """(versión instalada, motivo si no se pudo detectar) del componente del backend."""
    if component == "llama-swap":
        # Sin motivo a propósito: el doctor tampoco lo da hoy para llama-swap, y con motivo la
        # línea perdería el sufijo de la última release en GitHub que arma `_compare_line`.
        return probes.detect_llamaswap_version(), None
    return probes.detect_llamaserver_version(config_path)


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
    return None, i18n.t("doctor.probe.published.skip_pypi")


def _default_clients_seen() -> tuple[list[dict], str | None]:
    """(clientes MCP anotados en el registro, motivo si no se pudo leer).

    Lee ``clients.jsonl`` y **no** ``/api/status``, por dos razones medidas: ese endpoint expone
    ``clients.snapshot()``, que es memoria del proceso del daemon —``doctor`` es otro proceso y
    nunca la vería—, y sobre todo el daemon **no ve a los clientes que importan**: Claude Code y
    Codex hablan por *stdio*, cada uno con su propio proceso, así que sus observaciones no pasan
    por el 9393. El fichero es la única fuente que los ve a todos.

    El import de ``clients`` es a nivel superior y no diferido como el de ``daemon``: aquel
    arrastra uvicorn y el SDK, y ``clients`` no (solo importa ``config``).
    """
    # Se leen TODAS las generaciones, de la más vieja a la más nueva. El registro rota por tamaño
    # desde que tiene techo, y leer solo la viva haría desaparecer del diagnóstico a un cliente
    # perfectamente observado por el mero hecho de que el fichero rotó — o sea, cambiar un
    # crecimiento sin límite por un diagnóstico que miente. La lista vacía es lo normal cuando
    # nadie ha hablado todavía, y eso no es un error.
    observed: list[dict] = []
    for path in clients.paths_to_read():
        text, reason = read_text(path)
        if reason is not None:
            return [], reason
        if text is not None:
            observed.extend(_parse_jsonl(text))
    return observed, None


def _parse_jsonl(text: str) -> list[dict]:
    """Los objetos JSON de un JSONL, saltándose lo que no lo sea.

    Una línea a medio escribir —el proceso murió durante el ``write``— no puede tumbar el
    diagnóstico ni hacer perder las líneas buenas que hay alrededor.
    """
    objects: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            objects.append(item)
    return objects


def NO_CLIENTS() -> tuple[list[dict], str | None]:
    """Colaborador para los tests: el registro no se toca y no hay nada anotado.

    Existe para que la suite no dependa del ``clients.jsonl`` de la máquina donde corra, que haría
    verde en CI y potencialmente otra cosa en la máquina de quien desarrolla.
    """
    return [], None


def _default_claude_which(name: str) -> str | None:
    return shutil.which(name)


def _default_claude_runner(argv, env=None):
    """`claude_plugin.run_subprocess`, looked up when called, with every failure as `OSError`.

    The lookup at call time lets `run_doctor` tests double the module function. Any exception
    (a timeout, the suite's guard against the real CLI) becomes `OSError`, which the callers
    already read as "could not check" and never as "missing".
    """
    try:
        return claude_plugin.run_subprocess(argv, env)
    except Exception as exc:
        raise OSError(f"{type(exc).__name__}: {exc}") from exc


def _default_expected_ld_bin():
    return claude_plugin.resolve_ld_bin()


def _default_bridge_token() -> str:
    return token_source.web_token()


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
    # Los colaboradores van con `default_factory` y no con `= _default_x`: así el dataclass no deja
    # la función como atributo de la CLASE, donde Python la enlazaría como método y le metería
    # `self` delante (CodeQL, `py/call/wrong-arguments`, PR #204). El `f=` fija la función al
    # definirse la clase, como antes: doblar `_default_x` después no cambia el default.
    daemon_status: Callable[[str, int], dict | None] = field(
        default_factory=lambda f=_default_daemon_status: f
    )
    # Solo se consulta cuando `daemon_status` no dio respuesta y el puerto está ocupado: sirve
    # para separar «ahí hay otra cosa» de «ahí está nuestro daemon y a este entorno le falta el
    # token», que llevan a acciones opuestas.
    daemon_needs_token: Callable[[str, int], bool | None] = field(
        default_factory=lambda f=_default_daemon_needs_token: f
    )
    backend_models: Callable[[], failures.BackendView] = field(
        default_factory=lambda f=_default_backend_models: f
    )
    version_of: Callable[[str, Path | None], tuple[str | None, str | None]] = field(
        default_factory=lambda f=_default_version_of: f
    )
    # Al final y con default: las llamadas que no lo pasan siguen funcionando igual. Quien no
    # quiera salir a la red inyecta `SKIP_PYPI` **explícitamente**, y así se ve en su línea.
    latest_release: Callable[[], tuple[str | None, str | None]] = field(
        default_factory=lambda f=_default_latest_release: f
    )
    # Mismo criterio: aditivo y con default. Ojo, este NO deriva de `home` —`config.LOG_DIR` sale
    # de su propia variable de entorno—, así que `doctor --home` seguirá leyendo el registro real
    # de la máquina, igual que ya hacen los checks de servicio y backend.
    clients_seen: Callable[[], tuple[list[dict], str | None]] = field(
        default_factory=lambda f=_default_clients_seen: f
    )
    # Quinto colaborador que habla por red, y como los otros: default real, doblado en los tests.
    # Doblarlo NO es opcional en ninguno de los dos arneses — un colaborador de red sin doblar deja
    # la suite saliendo a internet de verdad, verde en CI y otra cosa en la máquina de quien
    # desarrolla. Ya pasó dos veces el 2026-07-31.
    backend_needs_key: Callable[[], tuple[bool | None, str]] = field(
        default_factory=lambda f=_default_backend_needs_key: f
    )
    # Séptimo, y el único que recibe un secreto: prueba el token que lleva Claude Desktop. Solo se
    # llama si ese fichero existe, así que un HOME simulado sin él no sale a la red por aquí.
    daemon_accepts_token: Callable[[str, int, str], bool | None] = field(
        default_factory=lambda f=_default_daemon_accepts_token: f
    )
    # Dónde están el log de uso, los `attribution-*.json` y `cost-aggregates.json`. Un campo simple
    # y no un colaborador: `None` quiere decir `config.LOG_DIR`, leído al llamar al probe (así lo
    # ve el aislamiento de la suite, que lo cambia por un `tmp_path`).
    log_dir: Path | None = None
    # Octavo colaborador de red (T13): lo que el daemon dice de su llama-swap (`config_path` y su
    # turno), para `backend.residency` y `backend.topology`. Default real, doblado en los tests.
    llamaswap_daemon: Callable[[], tuple] = field(
        default_factory=lambda f=_default_llamaswap_daemon: f
    )
    # The plugin delivery (REQ-009, SDD claude-plugin-and-mods). `claude_which` finds the CLI and
    # `claude_runner` runs it (`claude --version`, `claude plugin list --json`); the default runner
    # never raises, a failure reads as "could not check". Doubled in both test harnesses: the suite
    # forbids launching the real `claude`.
    claude_which: Callable[[str], str | None] = field(
        default_factory=lambda f=_default_claude_which: f
    )
    claude_runner: Callable | None = field(default_factory=lambda f=_default_claude_runner: f)
    # `None` means `os.environ`, read when a probe runs. Only `WSL_DISTRO_NAME` is looked at.
    environ: Mapping[str, str] | None = None
    # The interpreter the plugin hooks should run: the `uv tool` environment of this version.
    expected_ld_bin: Callable[[], object] = field(
        default_factory=lambda f=_default_expected_ld_bin: f
    )
    # The token the Desktop bridge would read (user variable in the registry, then the process).
    # Never printed: it only goes to `daemon_accepts_token`.
    bridge_token: Callable[[], str] = field(default_factory=lambda f=_default_bridge_token: f)

    @property
    def claude_dir(self) -> Path:
        return self.home / ".claude"

    @property
    def claude_desktop_config(self) -> Path:
        """Dónde guarda Claude Desktop su configuración, derivado del HOME como los demás.

        Derivado y no leído de `%APPDATA%`: así `doctor --home` mira el HOME simulado entero y la
        suite no toca el fichero real. En Windows `%APPDATA%` es `<HOME>\\AppData\\Roaming`.
        """
        if sys.platform == "win32":
            base = self.home / "AppData" / "Roaming"
        elif sys.platform == "darwin":
            base = self.home / "Library" / "Application Support"
        else:
            base = self.home / ".config"
        return base / "Claude" / "claude_desktop_config.json"

    @property
    def codex_dir(self) -> Path:
        return self.home / ".codex"

    @property
    def opencode_dir(self) -> Path:
        """Delega en ``install``: opencode NO cuelga del HOME como los otros dos.

        `XDG_CONFIG_HOME` gana sobre `HOME` (medido), así que escribir aquí
        ``self.home / ".config" / "opencode"`` haría que el diagnóstico mirase un fichero distinto
        del que escribe el instalador — y diría que falta la entrada recién puesta.
        """
        return install.opencode_dir(self.home)

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
        return None, i18n.t("doctor.common.cannot_read", path=path, error=exc.strerror or exc)


def read_json(path: Path) -> tuple[dict | None, str | None]:
    """Igual que :func:`read_text`, pero además un JSON ilegible es motivo de ``unknown``.

    Un BOM UTF-8 no lo hace ilegible: PowerShell 5.1 lo pone al guardar con `-Encoding UTF8`
    (REQ-026 de `retire-legacy-aliases`).
    """
    text, reason = read_text(path)
    if text is None:
        return None, reason
    try:
        data = json.loads(text.removeprefix("\ufeff"))
    except ValueError as exc:
        return None, i18n.t("doctor.common.bad_json", path=path, error=exc.msg)
    if isinstance(data, dict):
        return data, None
    return None, i18n.t("doctor.common.not_json_object", path=path)


def _dir_entries(path: Path) -> tuple[list[str] | None, str | None]:
    """Nombres dentro del directorio; motivo si existe pero no se pudo listar."""
    if not path.exists():
        return None, None
    try:
        return sorted(p.name for p in path.iterdir()), None
    except OSError as exc:
        return None, i18n.t("doctor.common.cannot_list", path=path, error=exc.strerror or exc)


def _packaged_hooks() -> dict[str, Path]:
    """Los ``.py`` de hooks que trae el paquete instalado, por nombre. Vacío si no se pueden leer.

    Vacío degrada a mirar solo los nombres de ``_HOOK_EVENTS``, como antes: sin la referencia no
    hay con qué comparar, y un ``warn`` inventado haría que ``update`` reescribiera los hooks en
    cada pasada.
    """
    try:
        return {
            p.name: p for p in (install.resources_dir() / "hooks").iterdir() if p.suffix == ".py"
        }
    except OSError:
        return {}


def _differs(installed: Path, packaged: Path | None) -> bool:
    """True si el script instalado no es byte a byte el del paquete. Sin referencia, no se afirma."""
    if packaged is None:
        return False
    try:
        return installed.read_bytes() != packaged.read_bytes()
    except OSError:
        return False


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
# Los tres clientes y dónde vive cada uno. Una sola tupla para los dos probes que recorren
# clientes (`client.presence` y `scaffold.memory`): tenerla dos veces es como se cuela un cliente
# que se detecta pero al que nadie le comprueba la memoria.
def _client_dirs(ctx: Context) -> tuple[tuple[str, Path], ...]:
    return (
        (_client_name("claude"), ctx.claude_dir),
        (_client_name("codex"), ctx.codex_dir),
        (_client_name("opencode"), ctx.opencode_dir),
    )


def _probe_clients(ctx: Context) -> Result:
    present = [name for name, path in _client_dirs(ctx) if path.is_dir()]
    if not present:
        return Result(UNKNOWN, i18n.t("doctor.probe.clients.none", home=ctx.home))
    return Result(OK, i18n.t("doctor.probe.clients.found", clients=", ".join(present)))


# Las observaciones sin nombre se agrupan bajo una clave propia; el rótulo sale al describirlas.
_UNNAMED = "\0unnamed"

# Lo más antiguo que puede haber: una observación cuyo `ts` falte o no se pueda parsear pierde la
# carrera de «la más reciente» en vez de tumbar el check por una línea mala.
_MIN_TS = datetime.min.replace(tzinfo=UTC)


def _instant(obs: dict) -> datetime:
    """Cuándo se anotó la observación, tolerando que el sello no sirva."""
    ts = obs.get("ts")
    if not isinstance(ts, str):
        return _MIN_TS
    try:
        instant = datetime.fromisoformat(ts)
    except ValueError:
        return _MIN_TS
    # Un sello sin zona compararía como *naive* y lanzaría `TypeError` contra los que sí la traen.
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)


def _cp1252(text: str) -> str:
    """Texto seguro para la consola de Windows.

    El nombre y la versión del cliente son **texto ajeno**: los pone quien se conecta. Un emoji ahí
    mataría el diagnóstico igual que lo mató una flecha «→», pero por un dato que este repo no
    controla, así que se sanea en vez de confiar.
    """
    return text.encode("cp1252", errors="replace").decode("cp1252")


def _describe(name: str, obs: dict) -> str:
    """Una observación en una línea: quién, qué versión, qué protocolo y si sabe preguntar."""
    version = obs.get("version")
    protocol = obs.get("protocol")
    caps = obs.get("caps")
    # `caps` tiene que ser una LISTA antes de preguntar por pertenencia. Si llegara como la cadena
    # "no-elicitation", un `in` daría True por subcadena y el check afirmaría justo lo contrario de
    # la verdad — un falso positivo silencioso.
    can_ask = isinstance(caps, list) and "elicitation" in caps

    parts = [i18n.t("doctor.probe.clients_observed.unnamed") if name == _UNNAMED else name]
    if isinstance(version, str) and version:
        parts.append(version)
    util = isinstance(protocol, str) and protocol
    parts.append(f"[{protocol if util else '?'}]")
    parts.append(
        "elicitation" if can_ask else i18n.t("doctor.probe.clients_observed.no_elicitation")
    )
    return _cp1252(" ".join(parts))


def _probe_clients_observed(ctx: Context) -> Result:
    """¿Con qué clientes MCP ha hablado local-delegate, y pueden responder preguntas?

    **Informativo a propósito: nunca ``warn`` ni ``missing``.** Un cliente que no declara
    ``elicitation`` no está mal configurado —es otro producto, con menos capacidades—, no hay
    ningún comando de este repo que lo arregle (de ahí que no tenga ``fix_hint``), y reportarlo
    como aviso subiría el exit code de una máquina sana. Lo que sí hacía falta es que se vea.

    El registro es histórico y **acumula una línea por cada arranque de proceso** —la
    deduplicación de ``clients.record`` es intra-proceso—, así que aquí se agrupa por nombre y
    se enseña la observación más reciente de cada uno. Sin eso, el mismo cliente saldría repetido
    tantas veces como se haya lanzado.
    """
    observations, reason = ctx.clients_seen()
    if reason is not None:
        return Result(UNKNOWN, reason)
    if not observations:
        return Result(UNKNOWN, i18n.t("doctor.probe.clients_observed.none"))

    latest: dict[str, dict] = {}
    for obs in observations:
        name = obs.get("client")
        # El `client_info` es opcional desde la revisión 2026-07-28: puede haber capabilities sin
        # identidad. Esas observaciones se agrupan aparte, pero no se pierden.
        if not isinstance(name, str) or not name:
            name = _UNNAMED
        previous = latest.get(name)
        if previous is None or _instant(obs) >= _instant(previous):
            latest[name] = obs

    return Result(OK, "; ".join(_describe(name, latest[name]) for name in sorted(latest)))


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
        return Result(MISSING, i18n.t("doctor.probe.cli.missing"), cli_hint())
    installed = _installed_version()
    if installed:
        return Result(OK, i18n.t("doctor.probe.cli.found_version", path=found, version=installed))
    return Result(OK, found)


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

    Los tres modos dan comandos distintos y no intercambiables: en una editable
    ``uv tool upgrade`` no actualiza nada —el código sale del repo clonado—, y a quien instaló con
    ``pip`` mandarlo a ``uv tool upgrade`` es un consejo que falla. La decisión de cuál es cuál
    vive en ``update.install_kind``, en un solo sitio, porque el otro consumidor es el propio
    ``update``.
    """
    from . import update

    return update.upgrade_command()


def _probe_published(ctx: Context) -> Result:
    """¿La versión instalada es la última publicada?

    Sin esto, una instalación vieja pasa el diagnóstico entero sin una sola señal: pasó el
    2026-07-30, con el CLI en 0.16.0, la 0.17.0 publicada y `doctor` diciendo «todo a punto».
    """
    installed = _installed_version()
    if installed is None:
        return Result(UNKNOWN, i18n.t("doctor.probe.published.unknown_installed"))
    latest, reason = ctx.latest_release()
    if latest is None:
        reason = reason or i18n.t("doctor.probe.published.pypi_silent")
        return Result(
            UNKNOWN, i18n.t("doctor.probe.published.no_latest", installed=installed, reason=reason)
        )
    order = _compare_versions(installed, latest)
    if order is None:
        return Result(
            UNKNOWN,
            i18n.t("doctor.probe.published.cannot_compare", installed=installed, latest=latest),
        )
    if order < 0:
        return Result(
            WARN,
            i18n.t("doctor.probe.published.behind", installed=installed, latest=latest),
            _upgrade_hint(),
        )
    if order > 0:
        return Result(
            OK, i18n.t("doctor.probe.published.ahead", installed=installed, latest=latest)
        )
    return Result(OK, i18n.t("doctor.probe.published.latest", installed=installed))


def _claude_absent(ctx: Context) -> Result | None:
    """``unknown`` compartido por los checks que solo aplican a Claude Code."""
    if not ctx.claude_dir.is_dir():
        return Result(
            UNKNOWN,
            i18n.t(
                "doctor.common.client_absent", client=_client_name("claude"), path=ctx.claude_dir
            ),
        )
    return None


def _probe_hook_files(ctx: Context) -> Result:
    if absent := _claude_absent(ctx):
        return absent
    entries, reason = _dir_entries(ctx.hooks_dir)
    if reason:
        return Result(UNKNOWN, reason)
    if checks_plugin.uses_plugin(ctx):
        # REQ-009: the plugin runs `local-delegate hook …`, not these scripts. With the plugin,
        # no folder is right and a script left in it is an orphan nobody runs.
        scripts = [name for name in entries or [] if name.endswith(".py")]
        if scripts:
            return Result(
                WARN,
                i18n.t(
                    "doctor.probe.hook_files.plugin_orphans",
                    n=i18n.format_number(len(scripts)),
                    path=ctx.hooks_dir,
                ),
                checks_plugin.UPDATE_HINT,
            )
        return Result(OK, i18n.t("doctor.probe.hook_files.plugin_none", path=ctx.hooks_dir))
    if entries is None:
        return Result(
            MISSING, i18n.t("doctor.common.does_not_exist", path=ctx.hooks_dir), INSTALL_HINT
        )
    packaged = _packaged_hooks()
    expected = sorted(packaged) or [script for script, _event, _matcher in install._HOOK_EVENTS]
    missing = [name for name in expected if name not in entries]
    if missing:
        return Result(
            WARN,
            i18n.t(
                "doctor.probe.hook_files.missing_scripts",
                path=ctx.hooks_dir,
                scripts=", ".join(missing),
            ),
            INSTALL_HINT,
        )
    # Que estén no basta: hay que mirar que sean LOS DE ESTA VERSIÓN. Actualizar el paquete no
    # toca `~/.claude/hooks/`, y mirando solo los nombres unos hooks de la 0.27 pasaban por buenos
    # con la 0.31.1 instalada —así estuvo la Mac del 2026-09-15 al 2026-09-22, sin el bloqueo ni
    # la telemetría de F1, y `update` respondiendo que no había nada que reparar—.
    stale = [name for name in expected if _differs(ctx.hooks_dir / name, packaged.get(name))]
    if stale:
        return Result(
            WARN,
            i18n.t("doctor.probe.hook_files.stale", path=ctx.hooks_dir, scripts=", ".join(stale)),
            update_hooks_hint(),
        )
    # Se cuentan los `.py`, no las entradas del directorio: en cuanto los hooks se ejecutan una vez,
    # Python deja ahí un `__pycache__/` y el conteo decía «4 script(s)» donde hay 3. No es cosmético
    # —es JUSTO el número que se mira para confirmar que un script retirado desapareció—, y con un
    # directorio de más el check afirmaba lo contrario de lo que había pasado.
    scripts = [name for name in entries if name.endswith(".py")]
    return Result(
        OK,
        i18n.t(
            "doctor.probe.hook_files.ok", n=i18n.format_number(len(scripts)), path=ctx.hooks_dir
        ),
    )


def _probe_hook_orphans(ctx: Context) -> Result:
    """Scripts nuestros sueltos en la raíz de ``~/.claude/hooks/``, de instalaciones anteriores.

    **Ojo con la ruta.** Se mira ``claude_dir/"hooks"`` y no ``ctx.hooks_dir``, que ya es el
    subdirectorio ``hooks/local-delegate/`` — o sea, la instalación **buena**. Confundirlas haría
    que este check reportase como huérfanos los scripts recién instalados y que ``install`` los
    borrara acto seguido, dejando la máquina sin hooks y en bucle.

    No se ejecutan (nadie los registra: ``merge_hook_settings`` desregistra las entradas viejas
    por nombre), pero confunden a quien mire el directorio y a quien diagnostique.
    """
    if absent := _claude_absent(ctx):
        return absent
    root = ctx.claude_dir / "hooks"
    entries, reason = _dir_entries(root)
    if reason:
        return Result(UNKNOWN, reason)
    if entries is None:
        # No hay directorio de hooks: de esa ausencia ya se ocupa `scaffold.hook_files`.
        return Result(OK, i18n.t("doctor.probe.hook_orphans.no_dir", path=root))
    orphans = install.orphan_hook_scripts(ctx.claude_dir)
    if not orphans:
        return Result(OK, i18n.t("doctor.probe.hook_orphans.none", path=root))
    return Result(
        WARN,
        i18n.t(
            "doctor.probe.hook_orphans.found",
            n=i18n.format_number(len(orphans)),
            path=root,
            scripts=", ".join(p.name for p in orphans),
        ),
        INSTALL_HINT,
    )


def _probe_hook_settings(ctx: Context) -> Result:
    if absent := _claude_absent(ctx):
        return absent
    path = ctx.claude_dir / "settings.json"
    data, reason = read_json(path)
    if reason:
        return Result(UNKNOWN, reason)
    if checks_plugin.uses_plugin(ctx):
        # REQ-009: the hooks come from the plugin, so none of ours in settings is the right state,
        # and any of ours here runs twice. Before this branch, `update` would have put them back.
        ours = checks_plugin.our_settings_hooks(data, ctx.hooks_dir)
        if ours:
            return Result(
                WARN,
                i18n.t(
                    "doctor.probe.hook_settings.plugin_duplicated",
                    n=i18n.format_number(len(ours)),
                    path=path,
                ),
                checks_plugin.UPDATE_HINT,
            )
        return Result(OK, i18n.t("doctor.probe.hook_settings.plugin_none", path=path))
    if data is None:
        return Result(MISSING, i18n.t("doctor.common.does_not_exist", path=path), INSTALL_HINT)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return Result(
            MISSING, i18n.t("doctor.probe.hook_settings.no_hooks", path=path), INSTALL_HINT
        )

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
        return Result(
            MISSING, i18n.t("doctor.probe.hook_settings.none_ours", path=path), INSTALL_HINT
        )
    if legacy:
        # El formato `{"command": "python", "args": [...]}` es el *exec form* del schema de
        # Claude Code y **sí se ejecuta** — verificado en vivo el 2026-07-29 y otra vez el
        # 2026-07-30, viendo disparar `suggest_lint_summary.py`. No es un hook muerto: es una
        # instalación anterior, con los scripts fuera de `hooks/local-delegate/`. Por eso es
        # `warn` y no `missing` ni `ok`, y por eso el detalle dice que funcionan.
        return Result(
            WARN,
            i18n.t(
                "doctor.probe.hook_settings.legacy",
                legacy=i18n.format_number(legacy),
                total=i18n.format_number(len(registered)),
                path=ctx.hooks_dir,
            ),
            INSTALL_HINT,
        )
    return Result(
        OK,
        i18n.t(
            "doctor.probe.hook_settings.ok",
            n=i18n.format_number(len(registered)),
            hooks=", ".join(registered),
        ),
    )


def _probe_skill(ctx: Context) -> Result:
    """La skill ``local-delegation`` en cada cliente que sepa cargarla.

    Recorre clientes por lo mismo que ``_probe_memory``, y no por simetría: ``plan_install``
    escribe la skill **también** en el directorio de opencode, así que mirar solo la de Claude Code
    daba un ``ok`` con la de opencode borrada —un falso OK, no un hueco de cobertura— y dejaba a
    ``update`` sin nada que reponer.

    Codex no aparece: no tiene mecanismo de skills y ``plan_install`` tampoco se la escribe.
    Reportarlo como «falta» sería inventarle a ese cliente un componente que no soporta.

    Que opencode cargue **además** la de ``~/.claude/skills/`` está medido, pero no vale como
    respuesta aquí: es apagable (``OPENCODE_DISABLE_EXTERNAL_SKILLS``) y no existe en una máquina
    sin Claude Code. Dar por buena la de allí sería decir ``ok`` de un fichero que este cliente
    puede no estar viendo.
    """
    subruta = {
        _client_name("claude"): Path("skills") / install.SKILL_NAME,
        _client_name("opencode"): Path(install.OPENCODE_SKILL_SUBDIR) / install.SKILL_NAME,
    }
    statuses: list[str] = []
    details: list[str] = []
    for label, client_dir in _client_dirs(ctx):
        if label not in subruta:
            continue
        if not client_dir.is_dir():
            # Igual que en `_probe_memory`: un cliente que no está en la máquina no arrastra el
            # estado del check. Solo si no aplica ninguno el resultado es `unknown`.
            details.append(i18n.t("doctor.common.client_not_installed", client=label))
            continue
        skill_dir = client_dir / subruta[label]
        entries, reason = _dir_entries(skill_dir)
        if reason:
            statuses.append(UNKNOWN)
            details.append(f"{label}: {reason}")
        elif entries is None:
            statuses.append(MISSING)
            details.append(
                i18n.t("doctor.common.client_path_missing", client=label, path=skill_dir)
            )
        elif "SKILL.md" not in entries:
            statuses.append(WARN)
            details.append(i18n.t("doctor.probe.skill.no_skill_md", client=label, path=skill_dir))
        else:
            statuses.append(OK)
            details.append(i18n.t("doctor.probe.skill.installed", client=label, path=skill_dir))
    status = _worst(statuses) if statuses else UNKNOWN
    return Result(status, " · ".join(details), INSTALL_HINT if is_warning(status) else "")


def _probe_memory(ctx: Context) -> Result:
    """Bloque de la regla de delegación en la memoria global de cada cliente.

    El bloque presente se compara con los empaquetados (`install.packaged_memory_blocks()`, uno
    por idioma admitido), con los saltos de línea normalizados y sin espacio al final: si no
    coincide con ninguno, `warn` («desfasado») y `update` lo repone. Antes solo se miraba que
    estuvieran los marcadores, y así la 0.35.0 habría dejado el bloque nombrando una skill ya
    borrada (D12). La contrapartida es deliberada: lo que el usuario edite **dentro** de los
    marcadores también da aviso, y `update` lo sobrescribe dejando el `.bak`; fuera de ellos no se
    toca nada.
    """
    files = {
        _client_name("claude"): "CLAUDE.md",
        _client_name("codex"): "AGENTS.md",
        _client_name("opencode"): "AGENTS.md",
    }
    targets = tuple((name, folder, folder / files[name]) for name, folder in _client_dirs(ctx))
    statuses: list[str] = []
    details: list[str] = []
    for label, client_dir, path in targets:
        if not client_dir.is_dir():
            # Un cliente que no está en la máquina no arrastra el estado del check: no falta
            # nada, simplemente no aplica. Solo si no aplica ninguno el resultado es `unknown`.
            details.append(i18n.t("doctor.common.client_not_installed", client=label))
            continue
        text, reason = read_text(path)
        if reason:
            statuses.append(UNKNOWN)
            details.append(f"{label}: {reason}")
        elif text is None:
            statuses.append(MISSING)
            details.append(i18n.t("doctor.common.client_path_missing", client=label, path=path))
        elif _has_block(text, install.MD_BEGIN, install.MD_END):
            if install.memory_block_is_current(text):
                statuses.append(OK)
                details.append(i18n.t("doctor.probe.memory.current", client=label, path=path))
            else:
                statuses.append(WARN)
                details.append(i18n.t("doctor.probe.memory.stale", client=label, path=path))
        else:
            statuses.append(MISSING)
            details.append(i18n.t("doctor.probe.memory.no_block", client=label, path=path))
    status = _worst(statuses) if statuses else UNKNOWN
    return Result(status, " · ".join(details), INSTALL_HINT if is_warning(status) else "")


# El modo de una entrada MCP se deriva en UN solo sitio por cliente: lo miran el probe de la
# entrada y el de la credencial, y dos definiciones de «esta entrada es stdio» son exactamente la
# clase de verdad repartida que ya costó caro en este repo.
def _entry_mode(entry: dict) -> str:
    """Modo de la entrada de Claude Code. Sin ``type`` es stdio, que es el default histórico."""
    return str(entry.get("type") or "stdio")


def _codex_mode(section: str) -> str:
    """Modo del bloque de Codex: el TOML no lleva ``type``, lo delata tener ``url``."""
    return "http" if "url = " in section else "stdio"


def _claude_mcp_entry(ctx: Context) -> dict | None:
    """La entrada MCP de Claude Code, o ``None`` si no se pudo leer o no está."""
    data, _ = read_json(ctx.home / ".claude.json")
    if data is None:
        return None
    servers = data.get("mcpServers")
    entry = servers.get(install.SERVER_NAME) if isinstance(servers, dict) else None
    return entry if isinstance(entry, dict) else None


def _codex_mcp_section(ctx: Context) -> str | None:
    """El bloque ``[mcp_servers.local-delegate]`` de Codex, o ``None`` si no se pudo leer."""
    text, _ = read_text(ctx.codex_dir / "config.toml")
    if text is None:
        return None
    section = install._CODEX_SECTION_RE.search(text)
    return section.group(0) if section else None


def _entry_timeouts(entry: dict, target: str) -> dict:
    """Los plazos puestos a mano en una entrada JSON (Claude Code u opencode)."""
    return {k: entry[k] for k in install.TIMEOUT_KEYS[target] if entry.get(k) is not None}


def _timeouts_text(timeouts: dict) -> str:
    """``, plazo tool_timeout_sec = 900`` para el detalle, o nada si no hay plazo puesto.

    Se enseña porque `install` y `update` lo conservan: así se ve, sin abrir el fichero, que el
    plazo que subiste sigue ahí.
    """
    if not timeouts:
        return ""
    return i18n.t("doctor.probe.mcp.timeout", timeouts=install._describe_timeouts(timeouts))


def _probe_mcp_claude(ctx: Context) -> Result:
    path = ctx.home / ".claude.json"
    if not ctx.claude_dir.is_dir() and not path.exists():
        return Result(
            UNKNOWN,
            i18n.t(
                "doctor.common.client_absent", client=_client_name("claude"), path=ctx.claude_dir
            ),
        )
    data, reason = read_json(path)
    if reason:
        return Result(UNKNOWN, reason)
    if data is None:
        return Result(MISSING, i18n.t("doctor.common.does_not_exist", path=path), INSTALL_HINT)
    servers = data.get("mcpServers")
    entry = servers.get(install.SERVER_NAME) if isinstance(servers, dict) else None
    if not isinstance(entry, dict):
        return Result(
            MISSING,
            i18n.t("doctor.probe.mcp.not_in_file", server=install.SERVER_NAME, path=path),
            INSTALL_HINT,
        )
    kind = _entry_mode(entry)
    where = entry.get("url") or entry.get("command") or ""
    timeouts = _timeouts_text(_entry_timeouts(entry, "claude"))
    details = f"{kind}{' ' + str(where) if where else ''}{timeouts}"
    return Result(OK, i18n.t("doctor.probe.mcp.registered", path=path, details=details))


def _probe_mcp_codex(ctx: Context) -> Result:
    if not ctx.codex_dir.is_dir():
        return Result(
            UNKNOWN,
            i18n.t("doctor.common.client_absent", client=_client_name("codex"), path=ctx.codex_dir),
        )
    path = ctx.codex_dir / "config.toml"
    text, reason = read_text(path)
    if reason:
        return Result(UNKNOWN, reason)
    if text is None:
        return Result(MISSING, i18n.t("doctor.common.does_not_exist", path=path), INSTALL_HINT)
    section = install._CODEX_SECTION_RE.search(text)
    if not section:
        return Result(
            MISSING,
            i18n.t("doctor.probe.mcp_codex.no_section", server=install.SERVER_NAME, path=path),
            INSTALL_HINT,
        )
    kind = _codex_mode(section.group(0))
    kind += _timeouts_text(dict(install._CODEX_TIMEOUT_RE.findall(section.group(0))))
    if install.TOML_BEGIN not in text:
        return Result(WARN, i18n.t("doctor.probe.mcp_codex.by_hand", details=kind, path=path))
    # El de apertura basta para saber que es nuestra. Si falta el de cierre es que otro programa
    # reescribió el fichero —así lo dejó el plugin de JetBrains—: Codex la carga igual, e `install`
    # la reescribe entera sin emparejar marcadores, así que no hay nada roto que avisar.
    if not _has_block(text, install.TOML_BEGIN, install.TOML_END):
        return Result(
            OK, i18n.t("doctor.probe.mcp_codex.closing_marker_lost", path=path, details=kind)
        )
    return Result(OK, i18n.t("doctor.probe.mcp_codex.managed", path=path, details=kind))


def _opencode_mcp_entry(ctx: Context) -> tuple[dict | None, Path | None, str | None]:
    """(entrada, en qué fichero, motivo por el que no se pudo leer alguno).

    Mira **los dos** ficheros porque opencode los lee y los fusiona: quedarse con el primero daría
    por ausente una entrada puesta en el otro. Un fichero ilegible o mal formado es motivo de
    ``unknown`` aunque el otro no tenga la entrada — lo no comprobable nunca es ``missing``.
    """
    reason: str | None = None
    for path in install.opencode_config_paths(ctx.home):
        data, read_error = install.read_opencode_config(path)
        if read_error and reason is None:
            reason = read_error
        if not isinstance(data, dict):
            continue
        servers = data.get("mcp")
        entry = servers.get(install.SERVER_NAME) if isinstance(servers, dict) else None
        if isinstance(entry, dict):
            return entry, path, None
    return None, None, reason


def _probe_mcp_opencode(ctx: Context) -> Result:
    if not ctx.opencode_dir.is_dir():
        return Result(
            UNKNOWN,
            i18n.t(
                "doctor.common.client_absent",
                client=_client_name("opencode"),
                path=ctx.opencode_dir,
            ),
        )
    entry, path, reason = _opencode_mcp_entry(ctx)
    if entry is None:
        if reason:
            return Result(UNKNOWN, reason)
        names = f" {i18n.t('doctor.nor')} ".join(install.OPENCODE_CONFIG_NAMES)
        return Result(
            MISSING,
            i18n.t(
                "doctor.probe.mcp_opencode.not_in_files",
                server=install.SERVER_NAME,
                files=names,
                path=ctx.opencode_dir,
            ),
            INSTALL_HINT,
        )
    kind = str(entry.get("type") or "?")
    where = entry.get("url") or entry.get("command") or ""
    timeouts = _timeouts_text(_entry_timeouts(entry, "opencode"))
    details = f"{kind}{' ' + str(where) if where else ''}{timeouts}"
    return Result(OK, i18n.t("doctor.probe.mcp.registered", path=path, details=details))


def _probe_mcp_credential(ctx: Context) -> Result:
    """¿Podrá autenticarse contra el backend el proceso MCP que arranca el cliente?

    Nace de una avería real que **ningún check veía** (2026-07-31): en una máquina con el backend
    exigiendo API key, las entradas MCP estaban en modo ``stdio``, el secreto vivía solo en el
    lanzador del daemon (DPAPI) y toda tool ``local_*`` llevaba un día devolviendo 401. `doctor`
    daba **todo OK**, backend incluido, porque desde el PR #100 le pregunta al daemon — que sí
    tiene credencial. El diagnóstico quedó bien y el camino real quedó roto.

    De ahí que aquí no se pregunte «¿está sano el backend?» sino «¿está abierto para quien no
    lleva la key?». La distinción es todo el check: sin ella se vuelve a mirar por el camino
    equivocado.

    El entorno de este proceso se usa como testigo del que verá el cliente: los dos salen del
    entorno de usuario. No es exacto —alguien puede lanzar el cliente desde una consola con la
    variable cargada— y por eso el aviso nombra el síntoma comprobable (401 en las tools) en vez
    de afirmar que la máquina está rota.
    """
    requires, reason = ctx.backend_needs_key()
    if requires is None:
        return Result(UNKNOWN, reason)
    if not requires:
        return Result(OK, i18n.t("doctor.probe.credential.open"))
    in_env = bool(token_source.environment_value(token_source.API_KEY_VARIABLE))
    if token_source.is_macos():
        # En macOS el entorno de este proceso NO es testigo del de los clientes: `doctor` corre en
        # un shell, y Claude Desktop abierto desde el Dock (o una sesión de Code cuyo entorno de
        # login no se resolvió) solo tiene el de launchd (issue #409). El Llavero sí lo ven todos.
        service = token_source.KEYCHAIN_SERVICES[token_source.API_KEY_VARIABLE]
        in_keychain = token_source.read_keychain(service) is not None
        if in_keychain:
            key = (
                "doctor.probe.credential.in_env_and_keychain"
                if in_env
                else "doctor.probe.credential.in_keychain"
            )
            return Result(OK, i18n.t(key, service=service))
        if in_env:
            return Result(
                WARN, i18n.t("doctor.probe.credential.shell_only"), keychain_hint(service)
            )
    elif in_env:
        return Result(OK, i18n.t("doctor.probe.credential.in_env"))

    entries: list[tuple[str, str]] = []
    entry = _claude_mcp_entry(ctx)
    if entry is not None:
        entries.append((_client_name("claude"), _entry_mode(entry)))
    section = _codex_mcp_section(ctx)
    if section is not None:
        entries.append((_client_name("codex"), _codex_mode(section)))
    oc_entry, _path, _reason = _opencode_mcp_entry(ctx)
    if oc_entry is not None:
        # `remote` es el `http` de opencode y `local` su `stdio`: se normaliza aquí para que la
        # comparación de abajo —«¿habla por el daemon?»— siga siendo una sola, en vez de tener que
        # conocer el vocabulario de cada cliente.
        entries.append(
            (_client_name("opencode"), "http" if oc_entry.get("type") == "remote" else "stdio")
        )
    if not entries:
        return Result(UNKNOWN, i18n.t("doctor.probe.credential.no_entries"))

    # `--api-key-env` no salva a una entrada stdio aquí: reenvía `${LOCAL_DELEGATE_API_KEY}`, que
    # sale del mismo entorno que acabamos de ver vacío. Por eso el único arreglo que se ofrece es
    # el daemon, que tiene el secreto por otra vía.
    blind = [client for client, mode in entries if mode != "http"]
    if not blind:
        return Result(OK, i18n.t("doctor.probe.credential.via_daemon"))
    key = (
        "doctor.probe.credential.blind_one"
        if len(blind) == 1
        else "doctor.probe.credential.blind_many"
    )
    clients = f" {i18n.t('doctor.and')} ".join(blind)
    # En macOS el daemon (LaunchAgent) tampoco tiene la clave si no está en el Llavero, así que el
    # arreglo de `credential_hint` (pasar por el daemon) no lo es: lo es guardarla en el Llavero.
    hint = (
        keychain_hint(token_source.KEYCHAIN_SERVICES[token_source.API_KEY_VARIABLE])
        if token_source.is_macos()
        else credential_hint()
    )
    return Result(WARN, i18n.t(key, clients=clients), hint)


# --- Probes de servicios y backend --------------------------------------------
def daemon_host_port() -> tuple[str, int]:
    """Dónde preguntar por el daemon: con 0.0.0.0 configurado se pregunta por loopback.

    Pública porque ``update`` necesita saber a dónde preguntar para reiniciarlo, y esa
    respuesta debe salir del mismo sitio que la del diagnóstico: dos derivaciones del host
    y el puerto es exactamente la clase de verdad duplicada que ya costó caro en este repo.
    """
    host = config.WEB_HOST
    return ("127.0.0.1" if host in ("0.0.0.0", "::", "") else host), config.WEB_PORT


def _entry_auth(client: str, mode: str, credential: str | None) -> tuple:
    """Normaliza «¿esta entrada puede entrar al puerto del daemon?» para los tres clientes.

    Devuelve `(client, state)` donde estado es `"ok"`, `"no_credential"` o el nombre de la
    variable de entorno que referencia. Se normaliza aquí y no en cada rama porque los tres
    clientes escriben la autenticación distinta —`headers.Authorization` en Claude Code y
    opencode, `bearer_token_env_var` en Codex— y comparar tres vocabularios en el sitio de la
    decisión es cómo se cuela un cliente sin contar.
    """
    if mode != "http":
        return (client, "stdio")
    if not credential:
        return (client, "no_credential")
    reference = _REFERENCED_VARIABLE.search(credential)
    if reference is None:
        # Un token escrito a pelo en la config: se puede autenticar, aunque sea mala idea. El
        # check dice si PUEDE entrar, no si el secreto está bien guardado.
        return (client, "ok")
    # La expresión tiene dos alternativas y por tanto dos grupos: el que no casa viene en None.
    return (client, reference.group(1) or reference.group(2))


def _probe_mcp_daemon_auth(ctx: Context) -> Result:
    """¿Podrán los clientes ENTRAR al puerto del daemon, si ese puerto exige token?

    Hermano de :func:`_probe_mcp_credential` un piso más arriba, y no un solapamiento: aquel mira
    la puerta del **backend** (¿tiene el proceso MCP la API key?) y este la del **daemon** (¿puede
    el cliente autenticarse en el 9393?). Son dos puertas del mismo camino y se cierran por
    separado — el 2026-08-18 la del backend estaba bien y la del daemon no.

    Nace de una avería real: `install` sin `--web-token-env` escribe la entrada HTTP **sin**
    cabecera y, de paso, borra la que hubiera. Contra un daemon con token, Claude Code cae al flujo
    OAuth y responde «Dynamic Client Registration rejected (HTTP 401)»; las once tools desaparecen.
    `doctor` decía **todo a punto**, porque `_probe_mcp_claude` sólo comprueba que la entrada
    exista. Es la tercera vez que el mismo patrón muerde, y las tres veces el diagnóstico miraba
    por un camino distinto del roto.

    En `service` y no en `scaffold` por el mismo motivo que `service.credential`: pregunta al
    puerto, y `scaffold` no sale a la red por contrato.
    """
    host, port = daemon_host_port()
    requires = ctx.daemon_needs_token(host, port)
    if requires is None:
        return Result(UNKNOWN, i18n.t("doctor.probe.daemon_auth.unknown", host=host, port=port))
    if not requires:
        return Result(OK, i18n.t("doctor.probe.daemon_auth.open"))

    entries: list[tuple] = []
    entry = _claude_mcp_entry(ctx)
    if entry is not None:
        header = (entry.get("headers") or {}).get("Authorization")
        entries.append(_entry_auth(_client_name("claude"), _entry_mode(entry), header))
    section = _codex_mcp_section(ctx)
    if section is not None:
        found = _CODEX_BEARER_RE.search(section)
        # Codex referencia la variable por nombre, sin `${...}`: se envuelve para que la
        # comprobación de «¿está en el entorno?» sea una sola para los tres clientes.
        token = "${" + found.group(1) + "}" if found else None
        entries.append(_entry_auth(_client_name("codex"), _codex_mode(section), token))
    oc_entry, _path, _reason = _opencode_mcp_entry(ctx)
    if oc_entry is not None:
        header = (oc_entry.get("headers") or {}).get("Authorization")
        mode = "http" if oc_entry.get("type") == "remote" else "stdio"
        entries.append(_entry_auth(_client_name("opencode"), mode, header))

    if not entries:
        return Result(UNKNOWN, i18n.t("doctor.probe.daemon_auth.no_entries"))

    blind = [client for client, state in entries if state == "no_credential"]
    if blind:
        many = len(blind) > 1
        key = (
            "doctor.probe.daemon_auth.blind_many" if many else "doctor.probe.daemon_auth.blind_one"
        )
        clients = f" {i18n.t('doctor.and')} ".join(blind)
        return Result(WARN, i18n.t(key, clients=clients), daemon_token_hint())

    # Segundo camino al mismo 401, y de fuerza distinta: la cabecera está pero la variable a la
    # que apunta puede expandir a vacío. El entorno de este proceso es un TESTIGO del que verá el
    # cliente —los dos salen del entorno de usuario— y no una prueba: alguien puede haber lanzado
    # el cliente desde otra consola. Por eso se nombra el síntoma y no se dicta el veredicto.
    suspicious = [
        (client, state)
        for client, state in entries
        if state not in {"ok", "stdio", "no_credential"} and not os.environ.get(state)
    ]
    if suspicious:
        detail = ", ".join(
            i18n.t("doctor.probe.daemon_auth.uses_variable", client=client, variable=var)
            for client, var in suspicious
        )
        return Result(
            WARN,
            i18n.t("doctor.probe.daemon_auth.variable_not_in_env", detail=detail),
            daemon_token_hint(),
        )
    return Result(OK, i18n.t("doctor.probe.daemon_auth.ok"))


# `${VAR}` es la única sintaxis que expande `mcp-remote` en sus cabeceras (medido en su fuente).
_MCP_REMOTE_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _desktop_connection(entry: dict) -> tuple[str | None, str | None]:
    """(URL, valor de `Authorization`) de la entrada, en cualquiera de sus dos formas.

    La de hoy va por `mcp-remote` como proceso stdio y lleva URL y cabecera dentro de `args`; la
    forma `{url, headers}` se acepta también para no dar por stdio una entrada que habla HTTP.
    """
    if isinstance(entry.get("url"), str):
        return entry["url"], (entry.get("headers") or {}).get("Authorization")
    args = [a for a in entry.get("args") or [] if isinstance(a, str)]
    url = next((a for a in args if a.startswith(("http://", "https://"))), None)
    header = None
    for previous, value in pairwise(args):
        name, sep, rest = value.partition(":")
        if previous == "--header" and sep and name.strip().lower() == "authorization":
            header = rest.strip()
    return url, header


def desktop_fix_hint() -> str:
    """REQ-012: the bridge entry that `install --desktop` writes; outside Windows there is none."""
    if sys.platform == "win32":
        return DESKTOP_INSTALL_HINT
    return i18n.t("doctor.probe.desktop_auth.fix_no_bridge")


def _probe_desktop_bridge(ctx: Context, entry: dict) -> Result:
    """The bridge entry: its executable exists and the token the bridge reads opens the port."""
    command = entry.get("command") or ""
    if not Path(command).is_file():
        return Result(
            WARN,
            i18n.t("doctor.probe.desktop_auth.bridge_missing", command=command),
            DESKTOP_INSTALL_HINT,
        )
    host, port = daemon_host_port()
    requires = ctx.daemon_needs_token(host, port)
    if requires is None:
        return Result(UNKNOWN, i18n.t("doctor.probe.daemon_auth.unknown", host=host, port=port))
    if not requires:
        return Result(OK, i18n.t("doctor.probe.desktop_auth.bridge_open"))
    token = ctx.bridge_token()
    if not token:
        return Result(
            WARN,
            i18n.t("doctor.probe.desktop_auth.bridge_no_token", variable=TOKEN_VAR),
            daemon_token_hint(),
        )
    accepts = ctx.daemon_accepts_token(host, port, token)
    if accepts is None:
        return Result(
            UNKNOWN, i18n.t("doctor.probe.desktop_auth.cannot_test", host=host, port=port)
        )
    if not accepts:
        return Result(
            WARN,
            i18n.t("doctor.probe.desktop_auth.bridge_rejected", variable=TOKEN_VAR),
            daemon_token_hint(),
        )
    return Result(OK, i18n.t("doctor.probe.desktop_auth.bridge_ok"))


def _probe_desktop_auth(ctx: Context) -> Result:
    """¿Puede la entrada de Claude Desktop entrar al puerto del daemon, y sin el token a la vista?

    Claude Desktop es el cliente que `install` no tocaba: su entrada estaba puesta a mano, va por
    `mcp-remote` y lleva el token **literal**. Si se rota el token del puerto, `install` arregla
    los tres clientes registrados y este se queda en 401 sin que nada lo diga — pasó en la 0.22.1
    con `doctor` diciendo que todo estaba bien. `service.daemon_auth` no lo ve porque solo mira los
    tres registrados; este check no escribe nada, solo convierte ese fallo mudo en un aviso.

    Por eso no le basta con ver la cabecera, como a su hermano: un token literal viejo tiene la
    misma forma que uno bueno. Lo prueba contra el puerto, y el secreto no sale nunca en el texto.

    REQ-012 (0.40): Desktop no pasa su entorno a los MCP ni expande `${VAR}` (medido el
    2026-10-21). Así que, aunque el daemon lo acepte, un token escrito en la entrada (en la cabecera
    o en su `env`) es `warn`, y un `${…}` también. La entrada buena es la del puente
    (`local-delegate desktop-bridge`), que lee el token él mismo: se prueba ese token.
    """
    path = ctx.claude_desktop_config
    data, reason = read_json(path)
    if data is None:
        return Result(UNKNOWN, reason or i18n.t("doctor.probe.desktop_auth.not_configured"))
    servers = data.get("mcpServers")
    entry = servers.get(install.SERVER_NAME) if isinstance(servers, dict) else None
    if not isinstance(entry, dict):
        return Result(
            UNKNOWN, i18n.t("doctor.probe.desktop_auth.no_entry", server=install.SERVER_NAME)
        )

    # Without the token: a `Bearer <value>` or a token variable with a value in `env` is found
    # anyway, and the secret is only read where the bridge would read it.
    report = desktop_config.check_entry(path, None)
    if desktop_config.is_bridge_entry(entry):
        connection = _probe_desktop_bridge(ctx, entry)
    else:
        connection = _desktop_connection_result(ctx, entry, path)
    if connection.status == WARN:
        return connection  # already broken: that comes first
    if report.literal_token:
        return Result(
            WARN, i18n.t("doctor.probe.desktop_auth.literal_token", path=path), desktop_fix_hint()
        )
    if report.unexpanded_variable:
        return Result(
            WARN, i18n.t("doctor.probe.desktop_auth.unexpanded", path=path), desktop_fix_hint()
        )
    return connection


def _desktop_connection_result(ctx: Context, entry: dict, path: Path) -> Result:
    """The `mcp-remote` (or `{url, headers}`) entry: does its token open the daemon's port?"""
    url, header = _desktop_connection(entry)
    if url is None:
        return Result(UNKNOWN, i18n.t("doctor.probe.desktop_auth.stdio"))
    host, port = daemon_host_port()
    try:
        target = urlsplit(url)
        target_port = target.port
    except ValueError:
        return Result(UNKNOWN, i18n.t("doctor.probe.desktop_auth.bad_url"))
    if target.hostname not in _LOCAL_HOSTS | {host} or target_port != port:
        # Probar su token contra NUESTRO puerto diría algo de un servidor al que no habla.
        return Result(
            UNKNOWN,
            i18n.t(
                "doctor.probe.desktop_auth.other_target",
                target=f"{target.hostname}:{target_port}",
                daemon=f"{host}:{port}",
            ),
        )

    requires = ctx.daemon_needs_token(host, port)
    if requires is None:
        return Result(UNKNOWN, i18n.t("doctor.probe.daemon_auth.unknown", host=host, port=port))
    if not requires:
        return Result(OK, i18n.t("doctor.probe.desktop_auth.open"))

    fix = i18n.t("doctor.probe.desktop_auth.fix", path=path, variable=TOKEN_VAR)
    if not header:
        return Result(WARN, i18n.t("doctor.probe.desktop_auth.no_header"), fix)
    token = header.removeprefix("Bearer ").strip()
    reference = _MCP_REMOTE_VARIABLE.search(token)
    literal = reference is None
    if reference is not None:
        variable = reference.group(1)
        # `mcp-remote` la toma de su propio entorno: el `env` de la entrada o el que herede. El de
        # este proceso es un testigo del segundo, no una prueba — como en `service.daemon_auth`.
        value = (entry.get("env") or {}).get(variable) or os.environ.get(variable)
        if not value:
            return Result(
                WARN,
                i18n.t("doctor.probe.desktop_auth.variable_not_in_env", variable=variable),
                desktop_fix_hint(),
            )
        token = _MCP_REMOTE_VARIABLE.sub(value, token)
        # Y otra vez aquí, después de expandir: la forma que recomienda `mcp-remote` —y la de la
        # Mac— es `Authorization:${AUTH_HEADER}` con el `Bearer` DENTRO de la variable. Quitarlo
        # solo antes de expandir dejaba `Bearer xxx` como token, la prueba mandaba
        # `Bearer Bearer xxx`, el daemon respondía 401 y el check culpaba a un token que era bueno.
        token = token.removeprefix("Bearer ").strip()

    accepts = ctx.daemon_accepts_token(host, port, token)
    if accepts is None:
        return Result(
            UNKNOWN, i18n.t("doctor.probe.desktop_auth.cannot_test", host=host, port=port)
        )
    if not accepts:
        return Result(WARN, i18n.t("doctor.probe.desktop_auth.rejected"), fix)
    form = i18n.t(
        "doctor.probe.desktop_auth.literal" if literal else "doctor.probe.desktop_auth.by_variable"
    )
    return Result(OK, i18n.t("doctor.probe.desktop_auth.ok", form=form))


def _probe_daemon(ctx: Context) -> Result:
    host, port = daemon_host_port()
    status = ctx.daemon_status(host, port)
    if status:
        version = status.get("version") or "?"
        pid = status.get("pid") or "?"
        detail = f"local-delegate {version} · pid {pid} · {status.get('mcp_url', '')}"
        installed = _installed_version()
        if installed and version != "?" and version != installed:
            # Que difieran no dice CUÁL de las dos está atrasada, y son dos averías distintas con
            # arreglos distintos. Comparar con `!=` y asumir siempre que el viejo es el daemon
            # mandaba a reiniciarlo cuando el atrasado era el CLI — un arreglo que no arregla.
            # Visto en producción tras publicar la 0.18.0: daemon del venv editable en 0.18.0 y
            # CLI de `uv tool` en 0.17.0.
            order = _compare_versions(version, installed)
            if order is None:
                # Sin poder ordenarlas, se avisa de la diferencia y NO se ofrece arreglo: cualquiera
                # de los dos que se sugiriera podría ser el equivocado.
                return Result(
                    WARN,
                    i18n.t(
                        "doctor.probe.daemon.cannot_compare", detail=detail, installed=installed
                    ),
                )
            if order < 0:
                # El daemon es un proceso largo: sigue sirviendo el código con el que arrancó. Tras
                # actualizar, los clientes hablan con la versión vieja y nada lo dice — el síntoma
                # es «actualicé y el arreglo no está».
                return Result(
                    WARN,
                    i18n.t("doctor.probe.daemon.daemon_behind", detail=detail, installed=installed),
                    restart_hint(),
                )
            # Al revés: el daemon corre código más nuevo que el paquete instalado. Pasa con una
            # instalación editable mientras el CLI publicado va por detrás. Reiniciar el daemon no
            # cambiaría nada; lo que hay que subir es la instalación.
            return Result(
                WARN,
                i18n.t("doctor.probe.daemon.install_behind", detail=detail, installed=installed),
                _upgrade_hint(),
            )
        return Result(OK, detail)
    if _port_taken(host, port):
        # Desde que el puerto puede exigir token hay DOS motivos para no obtener respuesta, y
        # llevan a acciones opuestas: matar un proceso ajeno, o poner una variable de entorno.
        # Decir «no es nuestro daemon» cuando sí lo es era el diagnóstico correcto solo hasta que
        # existió esta segunda causa, y un mensaje que se quedó viejo miente igual que uno falso.
        if ctx.daemon_needs_token(host, port):
            return Result(
                WARN,
                i18n.t("doctor.probe.daemon.no_token", host=host, port=port),
                i18n.t("doctor.probe.daemon.export_token", variable=TOKEN_VAR),
            )
        return Result(WARN, i18n.t("doctor.probe.daemon.foreign", host=host, port=port))
    return Result(MISSING, i18n.t("doctor.probe.daemon.nobody", host=host, port=port), serve_hint())


def _probe_backend_models(ctx: Context) -> Result:
    view = ctx.backend_models()
    if view.healthy:
        return Result(OK, i18n.t("doctor.probe.backend.answers", url=config.BASE_URL))
    # REQ-016: la severidad sale de la causa y de quién la vio, no de un prefijo del texto.
    hint = failures.hint(
        view.cause,
        origin=config.backend_origin(),
        source=view.source,
        host=config.backend_host(),
    )
    detail = f"{config.BASE_URL}/models: {view.detail or i18n.t('doctor.probe.backend.no_answer')}"
    if view.cause == failures.ConnectionCause.CREDENTIAL.value and view.source == "direct":
        # El backend está vivo; lo que falta es la credencial en **esta** consola. Decir «caído»
        # mandaría a arrancar un servicio que ya corre. Si el 401 lo vio el daemon, que sí tiene
        # su clave, es un problema de verdad: WARN, con la pista que manda a su lanzador.
        return Result(UNKNOWN, detail, hint)
    return Result(WARN, detail, hint)


def _version_result(ctx: Context, component: str) -> Result:
    """Envuelve la comparación de versiones del doctor sin reescribirla.

    El texto lo sigue armando ``probes._compare_line`` —incluida la consulta opcional a
    GitHub y la política de soak— y aquí solo se le quita el prefijo, que lo pone el
    renderizador con el resto de los checks.
    """
    installed, reason = ctx.version_of(component, ctx.config_path)
    if installed is None and reason:
        recommended = probes.RECOMMENDED_VERSIONS[component]
        return Result(
            UNKNOWN,
            i18n.t("doctor.probe.version.not_detected", recommended=recommended, reason=reason),
        )
    line, warn = probes._compare_line(component, installed, ctx.online)
    _prefix, _, text = line.partition("] ")
    detail = text.split(": ", 1)[1] if ": " in text else text
    if warn:
        return Result(WARN, detail)
    return Result(UNKNOWN if installed is None else OK, detail)


def _probe_llamaswap(ctx: Context) -> Result:
    return _version_result(ctx, "llama-swap")


def _probe_llamaserver(ctx: Context) -> Result:
    return _version_result(ctx, "llama-server")


def residency_hint() -> str:
    return i18n.t("doctor.probe.residency.hint")


def _probe_residency(ctx: Context) -> Result:
    """REQ-036: la residencia de la config de llama-swap.

    La config sale como en el CLI: `--config` de `doctor`, si no `LLAMASWAP_CONFIG` de este shell,
    si no la que usa el daemon (`config_path` de `/api/llamaswap/status`). El detalle dice de dónde.

    OK con «sin residente». Un residente (TTL efectivo 0) es una elección, la de `--pin`: también
    OK, con la VRAM que retiene en el detalle (aclaración de REQ-036 del 2026-10-07: no hay estado
    informativo y un aviso subiría el exit code de una máquina configurada así a propósito). WARN
    con un grupo `persistent` con TTL mayor que 0: `persistent` no lo mantiene cargado y el dueño
    de la config cree que sí (la config del 2026-09-15). Import diferido: `residency` trae PyYAML.
    """
    from . import residency, topology

    path, source = ctx.config_path, i18n.t("doctor.probe.residency.this_shell")
    if path is None:
        status, why = ctx.llamaswap_daemon()
        if status is None or not status.config_path:
            reason = why or i18n.t("doctor.probe.residency.daemon_silent")
            return Result(
                UNKNOWN,
                i18n.t(
                    "doctor.probe.residency.no_config",
                    reason=topology.reason_text(topology.NO_CONFIG),
                    why=reason,
                ),
            )
        path, source = Path(status.config_path), i18n.t("doctor.probe.residency.daemon_config")
    try:
        loaded = residency.load(path)
    except (residency.ResidencyError, OSError) as e:
        return Result(
            UNKNOWN, i18n.t("doctor.probe.residency.cannot_read", path=path, source=source, error=e)
        )
    photo = loaded.snapshot
    if isinstance(photo, topology.NoTopology):
        detail = f": {photo.detail}" if photo.detail else ""
        return Result(
            UNKNOWN,
            i18n.t(
                "doctor.probe.residency.unreadable",
                reason=topology.reason_text(photo.reason),
                detail=detail,
                source=source,
            ),
        )
    return _with_stale_affinity(_residency_result(photo, loaded, source), photo)


def _residency_result(photo, loaded, source: str) -> Result:
    """El veredicto de residencia de una config ya leída (REQ-036)."""
    from . import residency

    view = residency.view(photo, loaded.data)
    persistent = [
        i18n.t("doctor.probe.residency.persistent_entry", model=f.model, group=f.group, ttl=f.ttl)
        for f in view.rows
        if f.persistent and f.ttl > 0
    ]
    if persistent:
        return Result(
            WARN,
            i18n.t(
                "doctor.probe.residency.persistent_ttl",
                verdict=view.verdict,
                models=", ".join(persistent),
                source=source,
            ),
            residency_hint(),
        )
    if not view.residents:
        return Result(OK, i18n.t("doctor.probe.residency.ok", verdict=view.verdict, source=source))
    try:
        figures = residency.vram_figures(loaded.data, view.residents, {})
        vram = "; ".join(
            i18n.t(
                "doctor.probe.residency.holds_vram", model=m, gb=i18n.format_number(figures[m], 2)
            )
            for m in view.residents
        )
    except residency.ResidencyError:
        vram = i18n.t("doctor.probe.residency.no_vram_figure")
    return Result(
        OK,
        i18n.t("doctor.probe.residency.opt_in", verdict=view.verdict, vram=vram, source=source),
        residency_hint(),
    )


def affinity_hint() -> str:
    return i18n.t("doctor.probe.affinity.hint")


def _is_file(path: object) -> bool:
    return isinstance(path, str) and bool(path) and Path(path).is_file()


def _stale_affinity_cells(photo) -> tuple[list[str], int]:
    """Las celdas aprobadas de la afinidad que no valen con esta config (REQ-010, T15).

    Devuelve (avisos, celdas medidas en otra máquina). Una celda cuyo modelo no está en la config
    no aplica. Si la config apunta a otro GGUF:

    - y los dos ficheros, el medido y el de la config, existen aquí: **otro GGUF bajo el id en
      esta máquina**, aviso;
    - si no: la celda se midió en **otra máquina** (sus rutas no existen aquí). No es una avería,
      pero la afinidad queda inerte y el detalle lo dice, sin `[WARN]`.

    Con el GGUF medido, avisan también otro modelo en el rol por variable (la celda se comparó
    contra otro) y cualquier diferencia de la huella (`-ncmoe`, contexto, tamaño, prompt).
    Import diferido: `server` trae el SDK de MCP.
    """
    from . import config as configuration
    from . import matrix, server

    roles = configuration.models_by_role()
    language = i18n.response_language().value
    stale: list[str] = []
    elsewhere = 0
    for cell in matrix.CELLS:
        if not matrix.applies_to_language(cell, language):
            continue  # its prompt is the one of another language: no base to lose here
        model_cfg = server._model_config(photo, cell.alternative)
        prompt = server._affinity_prompt(cell.tool)
        if model_cfg is None or prompt is None:
            continue
        current = matrix.current_footprint(model_cfg, prompt)
        measured, configured = cell.footprint.get("path"), current.get("path")
        if configured != measured and not (_is_file(measured) and _is_file(configured)):
            elsewhere += 1
            continue
        changes: list[str] = []
        if configured != measured:
            changes.append(i18n.t("doctor.probe.affinity.other_gguf", path=configured))
        role = roles.get("code" if cell.tool == matrix.COMMIT_TOOL else "mechanical")
        if cell.compared_role != role:
            changes.append(
                i18n.t(
                    "doctor.probe.affinity.other_role_model", role=role, measured=cell.compared_role
                )
            )
        changes += [c for c in matrix.footprint_differences(cell, current) if c != "path"]
        if changes:
            stale.append(f"`{cell.tool}` → `{cell.alternative}` ({', '.join(changes)})")
    return stale, elsewhere


def _with_stale_affinity(result: Result, photo) -> Result:
    """Añade al resultado el aviso de las celdas «sin base» (un OK pasa a WARN) o, si se midieron
    en otra máquina, la nota de que aquí la afinidad está inerte (sin cambiar el estado)."""
    stale, elsewhere = _stale_affinity_cells(photo)
    if not stale:
        if not elsewhere:
            return result
        note = i18n.t(
            "doctor.probe.affinity.inert", detail=result.detail, n=i18n.format_number(elsewhere)
        )
        return Result(result.status, note, result.fix_hint)
    detail = i18n.t("doctor.probe.affinity.stale", detail=result.detail, cells="; ".join(stale))
    if result.status == OK:
        return Result(WARN, detail, affinity_hint())
    return Result(result.status, detail, result.fix_hint)


def _no_turn_is_fine(reason: str) -> bool:
    """Motivos de «sin turno» que no son una avería: el daemon va sin turno, como antes."""
    from . import server, topology

    return reason in (topology.NO_CONFIG, topology.MATRIX, server.NO_TURN_REMOTE_BACKEND)


def _probe_topology(ctx: Context) -> Result:
    """REQ-036 y REQ-002: si el daemon reparte el backend por turno y, si no, por qué.

    Si el daemon contesta, manda lo que dice de su propio turno (es él quien lo usa, con su
    `LLAMASWAP_CONFIG` y su backend). Si no, se lee la config de este shell (`--config` o
    `LLAMASWAP_CONFIG`) con el lector de topología, y el detalle lo dice. Sin config, con backend
    remoto o con `matrix` no hay nada roto y es `unknown`; una config que no se puede leer o que
    `load.go` rechazaría es `warn`. Import diferido de `server`: el resto del diagnóstico no lo
    necesita.
    """
    from . import server, topology

    status, why = ctx.llamaswap_daemon()
    if status is not None and status.turn_active is not None:
        if status.turn_active:
            return Result(
                OK, i18n.t("doctor.probe.topology.active_daemon", clashes=status.turn_detail)
            )
        detail = f": {status.turn_detail}" if status.turn_detail else ""
        text = i18n.t(
            "doctor.probe.topology.none_daemon",
            reason=topology.reason_text(status.turn_reason),
            detail=detail,
        )
        return Result(UNKNOWN if _no_turn_is_fine(status.turn_reason) else WARN, text)
    source = i18n.t(
        "doctor.probe.topology.source", why=why or i18n.t("doctor.probe.topology.daemon_silent")
    )
    if not server._backend_on_loopback():
        return Result(
            UNKNOWN,
            i18n.t(
                "doctor.probe.topology.none_remote",
                reason=server.NO_TURN_REMOTE_BACKEND,
                host=config.backend_host(),
                source=source,
            ),
        )
    if ctx.config_path is None:
        return Result(
            UNKNOWN,
            i18n.t(
                "doctor.probe.topology.none",
                reason=topology.reason_text(topology.NO_CONFIG),
                source=source,
            ),
        )
    photo = topology.read(ctx.config_path)
    if isinstance(photo, topology.NoTopology):
        detail = f": {photo.detail}" if photo.detail else ""
        text = i18n.t(
            "doctor.probe.topology.none_detail",
            reason=topology.reason_text(photo.reason),
            detail=detail,
            source=source,
        )
        return Result(UNKNOWN if _no_turn_is_fine(photo.reason) else WARN, text)
    clashes = server._clashes_by_groups(photo)
    return Result(OK, i18n.t("doctor.probe.topology.active", clashes=clashes, source=source))


def _probe_fallback(ctx: Context) -> Result:
    """Las cadenas de respaldo solo pueden nombrar roles o modelos del catálogo de texto.

    Lo que no, se ignora al delegar (REQ-014), y un error de tecleo en la variable dejaría a un rol
    sin el respaldo que su dueño cree haber configurado. Import diferido: `chains` importa `config`
    y `topology`, y no hace falta cargarlos para el resto del diagnóstico.
    """
    from . import chains
    from . import config as config_module

    resolved = [chains.resolve(role) for role in chains.TEXT_ROLES]
    # Los dos avisos van en el mismo resultado: `residente,foo` tiene un nombre que se ignora y otro
    # obsoleto (REQ-022), y arreglar uno no debe esconder el otro.
    details: list[str] = []
    fixes: list[str] = []
    warnings = [
        i18n.t(
            "doctor.probe.fallback.names",
            variable=f"LOCAL_DELEGATE_FALLBACK_{chain.role.upper()}",
            names=", ".join(chain.ignored),
        )
        for chain in resolved
        if chain.ignored
    ]
    if warnings:
        details.append(i18n.t("doctor.probe.fallback.ignored", warnings="; ".join(warnings)))
        fixes.append(i18n.t("doctor.probe.fallback.use_roles", loaded=chains.LOADED))
    obsolete = [
        i18n.t(
            "doctor.probe.fallback.uses",
            variable=f"LOCAL_DELEGATE_FALLBACK_{chain.role.upper()}",
            names=", ".join(chain.obsolete),
        )
        for chain in resolved
        if chain.obsolete
    ]
    if obsolete:
        details.append(
            i18n.t(
                "doctor.probe.fallback.obsolete", warnings="; ".join(obsolete), loaded=chains.LOADED
            )
        )
        fixes.append(i18n.t("doctor.probe.fallback.rename", loaded=chains.LOADED))
    if details:
        return Result(WARN, " | ".join(details), "; ".join(fixes))
    if not config_module.FALLBACK:
        return Result(OK, i18n.t("doctor.probe.fallback.off"))
    return Result(OK, i18n.t("doctor.probe.fallback.valid", residents=chains.residents_text()))


#: Cuántos días de la cola de la telemetría de hooks mira `doctor` buscando nombres obsoletos.
DEPRECATED_TAIL_DAYS = 7
_TAIL_BLOCK = 64 * 1024


def deprecated_names_in_hook_telemetry(
    path: Path | None,
    *,
    now: datetime | None = None,
    days: int = DEPRECATED_TAIL_DAYS,
    migrated: Mapping[str, datetime] | None = None,
) -> set[str]:
    """Nombres viejos que los hooks dicen haber leído (`deprecated_names`) en los últimos `days`.

    `migrated` es el registro de la migración (`install.read_migration_record`): un evento con
    `ts` anterior o igual a la fecha en que se migró **ese** nombre no cuenta (REQ-012).

    Lee el fichero **desde el final**, por bloques, y para en cuanto encuentra un evento más viejo
    que el corte: la telemetría crece sin freno (31 691 líneas en la máquina de referencia) y un
    check no puede recorrerla entera. Nunca lanza: sin fichero, o ilegible, no hay nada que avisar.
    """
    if path is None:
        return set()
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    found: set[str] = set()
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            position = stream.tell()
            tail = b""
            while position > 0:
                step = min(_TAIL_BLOCK, position)
                position -= step
                stream.seek(position)
                tail = stream.read(step) + tail
                lines = tail.split(b"\n")
                # La primera línea puede estar cortada: se guarda para el bloque siguiente.
                tail = lines[0] if position > 0 else b""
                complete = lines[1:] if position > 0 else lines
                older = False
                for raw in reversed(complete):
                    try:
                        event = json.loads(raw)
                        ts = datetime.fromisoformat(str(event["ts"]))
                    except (ValueError, KeyError, TypeError):
                        continue
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    if ts < cutoff:
                        older = True
                        break
                    names = event.get("deprecated_names")
                    if isinstance(names, list):
                        found.update(
                            n
                            for n in names
                            if isinstance(n, str)
                            and not (migrated and n in migrated and ts <= migrated[n])
                        )
                if older:
                    break
    except OSError:
        return set()
    return found


def _probe_deprecated_names(ctx: Context) -> Result:
    """Nombres obsoletos que siguen en uso: variables renombradas o retiradas e interruptores viejos.

    Sustituye a `config.rol_retirado` (REQ-003) y lo generaliza: la lista sale del registro único
    `deprecations.DEPRECATED_NAMES`, así que cada alias que añada una ola se avisa aquí sin tocar
    el probe. Desde la 0.41.0 el registro está vacío (retire-seven-names): da `OK` hasta el próximo
    renombrado.

    Retirar algo tiene dos mitades y la segunda se olvida siempre: quitar el código es fácil, y
    quien tenía el nombre viejo en su entorno se queda creyendo que configura algo que ya no lo
    lee nadie. Una variable no falla nunca por sí sola. De ahí este aviso.

    Mira tres sitios, y ninguno sale a la red, así que vive en `environment`: el entorno de la shell
    donde corre `doctor`, el bloque `env` de `~/.claude/settings.json` (de donde heredan los hooks)
    y la existencia de los ficheros interruptor con nombre viejo. Lo que solo ve el daemon lo
    cuenta `local_status`. Y desde la ola A2, lo que los hooks dicen haber leído: con la telemetría
    encendida cada evento lleva `deprecated_names`, y aquí se mira la cola de los últimos 7 días.

    Los lectores del registro van por clase efectiva (`deprecations.effective_kind`), así que un
    retirado con sucesor sale en su superficie (variable o interruptor) y lleva la pista `rename`.
    """
    from . import config as config_module
    from . import deprecation_notices, deprecations

    warnings: list[str] = []
    seen: list[deprecations.DeprecatedName] = []

    def _note(where: str, item: deprecations.DeprecatedName) -> None:
        warnings.append(f"{where}: {deprecation_notices.warning_text(item)}")
        if item not in seen:
            seen.append(item)

    for env_name, env_value in config_module.DEPRECATED_ENV_VALUES.items():
        if env_value is not None and (entry := deprecations.find(env_name)) is not None:
            _note(i18n.t("doctor.probe.deprecated_names.in_shell"), entry)

    settings, reason = read_json(ctx.claude_dir / "settings.json")
    if reason is not None:
        # Antes se callaba y podía decir `OK` con nombres viejos dentro (desviación 9).
        warnings.append(i18n.t("doctor.probe.deprecated_names.settings_unreadable", reason=reason))
    env = settings.get("env") if settings else None
    if isinstance(env, dict):
        for entry in deprecations.env_vars():
            if entry.old in env:
                _note(i18n.t("doctor.probe.deprecated_names.in_settings_env"), entry)

    for entry in deprecations.switch_files():
        if (ctx.claude_dir / entry.old).exists():
            _note(i18n.t("doctor.probe.deprecated_names.in_claude_dir"), entry)

    # El registro de la migración se lee de donde lo escribe (REQ-012, REQ-015).
    data_dir = ctx.log_dir if ctx.log_dir is not None else install.data_dir_for(ctx.home)
    migrated = install.read_migration_record(data_dir)
    telemetry = deprecated_names_in_hook_telemetry(
        config_module.HOOK_TELEMETRY_LOG, migrated=migrated
    )
    for name in sorted(telemetry):
        if (entry := deprecations.find(name)) is not None and entry not in seen:
            _note(
                i18n.t("doctor.probe.deprecated_names.read_by_hooks", days=DEPRECATED_TAIL_DAYS),
                entry,
            )

    if not warnings:
        return Result(OK, i18n.t("doctor.probe.deprecated_names.none"))
    # Con sucesor (alias o retirado) se pide renombrar; quitar, solo si no hay a qué renombrar.
    hints = [
        i18n.t("doctor.probe.deprecated_names.remove", old=e.old)
        if e.new is None
        else i18n.t("doctor.probe.deprecated_names.rename", old=e.old, new=e.new)
        for e in seen
    ]
    return Result(WARN, " | ".join(warnings), "; ".join(hints))


def _migration_backups(claude_dir: Path) -> list[Path]:
    """The copies the retired-names migration left next to `settings.json`, by name only.

    The names are the ones `install._retired_names_backup` writes: `….retired-names.bak`, and when
    that one exists `….<stamp>.bak` or `….<stamp>-N.bak`. Only their existence is looked at:
    they may hold `env` keys, so their content is never opened.
    """
    try:
        candidates = claude_dir.glob(f"{install.RETIRED_NAMES_BACKUP}*.bak")
        return sorted(path for path in candidates if path.is_file())
    except OSError:
        return []


def _probe_claude_settings(ctx: Context) -> Result:
    """`~/.claude/settings.json` in UTF-8, and no copy of the migration left behind.

    A check of its own (REQ-012 and REQ-013 of `backlog-minor-leftovers`) and not a change to
    `read_text`: that reader decodes with `errors="replace"` on purpose, and a dozen probes rely on
    it to read what they can of a file instead of going `unknown`. So the strict decoding is done
    here, only for this file, from the raw bytes; the other checks keep reading it as before. And
    not inside `scaffold.hook_settings` either: a `warn` there makes `update` rewrite the hooks,
    which would not fix the encoding and would happen on every run.

    UTF-8 with a BOM is valid (REQ-026 of `retire-legacy-aliases`): the BOM bytes decode as UTF-8.
    """
    if absent := _claude_absent(ctx):
        return absent
    statuses: list[str] = []
    details: list[str] = []
    hints: list[str] = []

    path = ctx.claude_dir / "settings.json"
    raw: bytes | None = None
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        # No file is not a problem of this check: there is nothing to decode.
        raw = None
    except OSError as exc:
        statuses.append(UNKNOWN)
        details.append(i18n.t("doctor.common.cannot_read", path=path, error=exc.strerror or exc))
    if raw is not None:
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            statuses.append(WARN)
            details.append(
                i18n.t(
                    "doctor.probe.claude_settings.not_utf8",
                    path=path,
                    byte=f"0x{raw[exc.start]:02X}",
                    position=exc.start,
                )
            )
            hints.append(i18n.t("doctor.probe.claude_settings.not_utf8_hint"))

    backups = _migration_backups(ctx.claude_dir)
    if backups:
        statuses.append(WARN)
        details.append(
            i18n.t(
                "doctor.probe.claude_settings.backup",
                paths=", ".join(str(backup) for backup in backups),
            )
        )
        hints.append(i18n.t("doctor.probe.claude_settings.backup_hint"))

    if not statuses:
        if raw is None:
            return Result(OK, i18n.t("doctor.common.does_not_exist", path=path))
        return Result(OK, i18n.t("doctor.probe.claude_settings.ok", path=path))
    return Result(_worst(statuses), " | ".join(details), "; ".join(hints))


RECOMPUTE_HINT = "local-delegate recompute-cost"
# Margen del aviso de relleno: salta con la pendiente más antigua a `H` − 10 días (REQ-075).
_BACKFILL_MARGIN = timedelta(days=10)


def _oldest_pending(log_dir: Path, *, now: datetime, period_days: int) -> tuple[int, int]:
    """(cuántas delegaciones `pendiente` pasan de `H` − 10 días, días de la más vieja).

    Solo los ficheros del log que pueden tener filas dentro del plazo, y cada uno ENTERO: la clave
    de una línea sin `tool_use_id` lleva su ordinal en el fichero (`cost.merge`).
    """
    first_month = (now - timedelta(days=period_days)).strftime("%Y%m")
    threshold = timedelta(days=period_days) - _BACKFILL_MARGIN
    count, oldest = 0, timedelta(0)
    for path, month in recompute._log_files(log_dir):
        if month < first_month:
            continue
        for row in cost.merge(recompute._read_log(path), log_dir=log_dir):
            if cost.segment(row, now=now, cleanup_days=period_days) != "pending":
                continue
            age = now - cost._instant(row.get("ts"))
            if age > threshold:
                count += 1
                oldest = max(oldest, age)
    return count, oldest.days


def _probe_cost(ctx: Context) -> Result:
    """¿Se puede fiar uno de la cifra de coste, y se está perdiendo el histórico?

    Lee **solo** `cost-aggregates.json` (o el viejo `coste-agregados.json`), el log de uso y los
    `attribution-*.json` (más `cleanupPeriodDays` de `settings.json`): nunca los transcripts, que son
    cosa del comando que lanza el usuario (REQ-073). Gana la primera regla que se cumple (REQ-015): relleno pendiente,
    cotejo fallido, cotejo bueno, sin cotejo. Si se cumplen las dos primeras, dice las dos.

    El aviso del relleno mira la pendiente más antigua, no la fecha del último relleno: así salta
    también con el comando nunca lanzado, que es justo cuando más histórico se pierde (REQ-075).
    Sin `~/.claude/projects` no hay transcripts que rellenar y no aplica.
    """
    log_dir = ctx.log_dir if ctx.log_dir is not None else config.LOG_DIR
    now = datetime.now(UTC)
    warnings: list[str] = []

    if (ctx.claude_dir / "projects").is_dir():
        period = attribution.cleanup_period_days(ctx.claude_dir)
        count, days = _oldest_pending(log_dir, now=now, period_days=period)
        if count:
            warnings.append(
                i18n.t(
                    "doctor.probe.cost.backfill_pending",
                    n=i18n.format_number(count),
                    days=i18n.format_number(days),
                    period=i18n.format_number(period),
                    command=RECOMPUTE_HINT,
                )
            )

    aggregates = recompute.read_aggregates(log_dir) or {}
    # `read_aggregates` entrega el formato nuevo aunque en disco solo esté el viejo (REQ-006).
    check = aggregates.get("check")
    if not isinstance(check, dict):
        check = None
    date = str((check or {}).get("date") or "?")
    if check is not None and check.get("verdict") == "fail":
        unpriced = [str(m) for m in check.get("unpriced") or []]
        parts = []
        if unpriced:
            parts.append(i18n.t("doctor.probe.cost.unpriced", models=", ".join(unpriced)))
        if check.get("outside"):
            parts.append(
                i18n.t("doctor.probe.cost.outside", n=i18n.format_number(check["outside"]))
            )
        detail = "; ".join(parts) or i18n.t("doctor.probe.cost.no_detail")
        warnings.append(i18n.t("doctor.probe.cost.check_failed", date=date, parts=detail))

    if warnings:
        return Result(WARN, i18n.t("doctor.probe.cost.and").join(warnings), RECOMPUTE_HINT)
    if check is not None and check.get("verdict") == "pass":
        judged = check.get("judged")
        return Result(
            OK,
            i18n.t(
                "doctor.probe.cost.check_passed",
                date=date,
                judged=i18n.format_number(judged) if isinstance(judged, int) else "?",
                table=check.get("table_version") or "?",
            ),
        )
    return Result(
        UNKNOWN, i18n.t("doctor.probe.cost.no_check", path=log_dir, command=RECOMPUTE_HINT)
    )


def _probe_test_windows(ctx: Context) -> Result:
    """¿Hay ventanas de prueba que se estén comiendo datos sin querer? (test-windows-out-of-metrics,
    REQ-019).

    Nunca es un fallo: una ventana mal puesta no rompe el MCP, solo aparta filas del panel. Avisa si
    el fichero es ilegible, si hay entradas ignoradas o si una ventana lleva abierta más de
    `OPEN_WARN_HOURS` horas (casi seguro, una que se olvidó cerrar).
    """
    log_dir = ctx.log_dir if ctx.log_dir is not None else config.LOG_DIR
    windows = test_windows.load(log_dir)
    path = test_windows.path_for(log_dir)
    if windows.error:
        return Result(
            WARN,
            i18n.t("doctor.probe.test_windows.unreadable", path=path, error=windows.error),
            i18n.t("doctor.probe.test_windows.fix_unreadable"),
        )
    warnings: list[str] = []
    if windows.ignored:
        warnings.append(
            i18n.t(
                "doctor.probe.test_windows.ignored",
                n=i18n.format_number(windows.ignored),
                path=path,
            )
        )
    stale = windows.stale()
    for w in stale:
        warnings.append(
            i18n.t(
                "doctor.probe.test_windows.stale",
                id=w.id,
                start=test_windows.format_instant(w.start),
                hours=i18n.format_number(test_windows.OPEN_WARN_HOURS, None),
            )
        )
    if warnings:
        hint = " · ".join(f"local-delegate test-window stop {w.id}" for w in stale) or i18n.t(
            "doctor.probe.test_windows.fix_entries"
        )
        return Result(WARN, "; ".join(warnings), hint)
    if not windows.windows:
        return Result(OK, i18n.t("doctor.probe.test_windows.none"))
    open_count = len(windows.open_windows())
    if open_count:
        state = i18n.t("doctor.probe.test_windows.open", n=i18n.format_number(open_count))
    else:
        state = i18n.t("doctor.probe.test_windows.none_open")
    return Result(
        OK,
        i18n.t(
            "doctor.probe.test_windows.ok", n=i18n.format_number(len(windows.windows)), state=state
        ),
    )


# --- Shell completion (SDD cli-completion, REQ-033) ----------------------------------------------
#: Profile problems of `install.upsert_profile_block` that mean «could not read it», not «the block
#: is gone»: those are `unknown`, never a reason to reinstall over the file.
_PROFILE_UNREADABLE = frozenset({"unreadable", "nul_bytes", "broken_link"})


def _probe_shell_completion(ctx: Context) -> Result:
    """The completion that `install --shell-completion` left: files and load blocks (REQ-033).

    Reads the manifest (REQ-043) and the files of the completion directory, and never launches a
    shell. Each listed file is compared with `render(shell, lang=<language of the manifest>)`, not
    with the language of the session: a file installed in `es` is `ok` from a `doctor` in `en`, the
    same verdict in both languages. Each listed profile must still carry the complete block that
    loads its file; looking only at the files gave a false `ok` with the block deleted.

    `completion` (and, through `render`, `cli`) is imported here and not at the top: `cli` imports
    this module for `install`, and a machine without the completion never pays for building the
    parser. With no manifest and no files nothing is rendered.
    """
    from . import completion, shell_profiles
    from .version import get_version

    directory = shell_profiles.completion_dir(ctx.home)
    try:
        manifest = completion.read_manifest(directory)
    except completion.ManifestUnreadableError:
        path = completion.manifest_path(directory)
        return Result(
            UNKNOWN, i18n.t("doctor.probe.shell_completion.manifest_unreadable", path=path)
        )
    entries = (manifest or {}).get("shells", [])
    listed = {Path(entry["file"]) for entry in entries}
    loose = [
        file
        for file in (shell_profiles.completion_file(directory, s) for s in shell_profiles.SHELLS)
        if file.exists() and file not in listed
    ]
    if not entries and not loose:
        return Result(OK, i18n.t("doctor.probe.shell_completion.not_installed"))

    statuses: list[str] = []
    details: list[str] = []
    needs_install = False
    if loose:
        statuses.append(WARN)
        needs_install = True
        files = ", ".join(str(file) for file in loose)
        details.append(i18n.t("doctor.probe.shell_completion.loose", files=files))
    lang = (manifest or {}).get("lang", "")
    for entry in entries:
        shell, file = entry["shell"], Path(entry["file"])
        problems: list[str] = []
        try:
            current = file.read_bytes()
        except FileNotFoundError:
            statuses.append(WARN)
            needs_install = True
            problems.append(i18n.t("doctor.probe.shell_completion.file_missing", path=file))
        except OSError as exc:
            statuses.append(UNKNOWN)
            problems.append(i18n.t("doctor.common.cannot_read", path=file, error=exc))
        else:
            if current != completion.render(shell, lang=lang).encode("utf-8"):
                statuses.append(WARN)
                found = completion.header_version(current.decode("utf-8", errors="replace"))
                installed = get_version()
                if found and found != installed:
                    problems.append(
                        i18n.t(
                            "doctor.probe.shell_completion.stale_version",
                            path=file,
                            found=found,
                            installed=installed,
                        )
                    )
                else:
                    problems.append(
                        i18n.t("doctor.probe.shell_completion.content_differs", path=file)
                    )
        block = shell_profiles.load_block(shell, file)
        for profile in entry["profiles"]:
            path = Path(profile["path"])
            edit = install.upsert_profile_block(path, block)
            if edit.reason in _PROFILE_UNREADABLE:
                statuses.append(UNKNOWN)
                reason = i18n.t(install.PROFILE_SKIP_REASONS[edit.reason])
                problems.append(f"{path}: {reason}")
            elif edit.reason or edit.changed:
                statuses.append(WARN)
                needs_install = True
                problems.append(i18n.t("doctor.probe.shell_completion.no_block", path=path))
        if problems:
            details.extend(f"{shell}: {problem}" for problem in problems)
            continue
        statuses.append(OK)
        profiles = ", ".join(profile["path"] for profile in entry["profiles"])
        if profiles:
            details.append(
                i18n.t(
                    "doctor.probe.shell_completion.current",
                    shell=shell,
                    lang=lang,
                    profiles=profiles,
                )
            )
        else:
            details.append(
                i18n.t("doctor.probe.shell_completion.current_no_profiles", shell=shell, lang=lang)
            )
    status = _worst(statuses)
    hint = ""
    if needs_install:
        hint = SHELL_COMPLETION_INSTALL_HINT
    elif status == WARN:
        hint = SHELL_COMPLETION_UPDATE_HINT
    return Result(status, " · ".join(details), hint)


# --- Entrega por plugin de Claude Code (F1-doctor) ----------------------------
def _plugin_settings(ctx: Context) -> tuple[Path, dict | None, str | None]:
    path = ctx.claude_dir / "settings.json"
    data, reason = read_json(path)
    return path, data, reason


def _plugin_not_applicable(ctx: Context) -> Result | None:
    """``ok`` when the plugin is not the delivery here (WSL or settings), else ``None``."""
    if checks_plugin.in_wsl(ctx):
        return Result(OK, i18n.t("doctor.probe.plugin.wsl"))
    if not checks_plugin.uses_plugin(ctx):
        return Result(OK, i18n.t("doctor.probe.plugin.not_used"))
    return None


def _claude_cli_missing(ctx: Context) -> Result:
    return Result(UNKNOWN, i18n.t("doctor.probe.claude_version.no_cli"))


# Las cinco sondas de REQ-009. Viven aquí y no en `checks_plugin`, que solo lee: si estuvieran allí,
# ese módulo tendría que importar este para construir `Result` (ciclo, CodeQL, PR #400).
def _probe_delivery(ctx):
    if absent := _claude_absent(ctx):
        return absent
    if checks_plugin.in_wsl(ctx):
        return Result(OK, i18n.t("doctor.probe.claude_delivery.wsl"))
    current = checks_plugin.state(ctx)
    found = install_state.delivery(current)
    path = install_state.path(ctx.home, ctx.log_dir)
    if found in (claude_plugin.PLUGIN, claude_plugin.SETTINGS):
        return Result(
            OK,
            i18n.t(
                "doctor.probe.claude_delivery.recorded",
                delivery=found,
                version=(current or {}).get("version") or "?",
                path=path,
            ),
        )
    return Result(UNKNOWN, i18n.t("doctor.probe.claude_delivery.no_state", path=path or "-"))


def _probe_claude_version(ctx):
    if checks_plugin.in_wsl(ctx):
        return Result(OK, i18n.t("doctor.probe.plugin.wsl"))
    claude_bin = ctx.claude_which("claude")
    if not claude_bin or ctx.claude_runner is None:
        return _claude_cli_missing(ctx)
    env = claude_plugin.child_env(ctx.home)
    version, _raw = claude_plugin.claude_version(claude_bin, ctx.claude_runner, env)
    minimum = claude_plugin.MIN_CLAUDE_PLUGIN_VERSION
    if version is None:
        return Result(UNKNOWN, i18n.t("doctor.probe.claude_version.unknown"))
    if not claude_plugin.version_at_least(version, minimum):
        return Result(
            WARN,
            i18n.t("doctor.probe.claude_version.below", found=version, minimum=minimum),
            i18n.t("doctor.hint.claude_update"),
        )
    return Result(OK, i18n.t("doctor.probe.claude_version.ok", found=version, minimum=minimum))


def _plugin_listed(ctx):
    """``(entry, None)`` from ``claude plugin list --json``, or ``(None, an unknown Result)``."""
    claude_bin = ctx.claude_which("claude")
    if not claude_bin or ctx.claude_runner is None:
        return None, _claude_cli_missing(ctx)
    argv = claude_plugin.list_argv(claude_bin)
    try:
        done = ctx.claude_runner(argv, claude_plugin.child_env(ctx.home))
    except Exception as exc:  # the CLI did not start or did not finish: nothing to claim
        return None, Result(
            UNKNOWN, i18n.t("doctor.probe.plugin_installed.list_failed", detail=exc)
        )
    if done.returncode != 0:
        detail = ((done.stderr or done.stdout or "").strip() or str(done.returncode))[:200]
        return None, Result(
            UNKNOWN, i18n.t("doctor.probe.plugin_installed.list_failed", detail=detail)
        )
    return claude_plugin.listed_entry(done.stdout), None


def _probe_plugin_installed(ctx):
    if absent := _claude_absent(ctx):
        return absent
    if skip := _plugin_not_applicable(ctx):
        return skip
    entry, failure = _plugin_listed(ctx)
    if failure is not None:
        return failure
    if entry is None:
        return Result(
            MISSING,
            i18n.t("doctor.probe.plugin_installed.not_listed", plugin=claude_plugin.PLUGIN_ID),
            checks_plugin.UPDATE_HINT,
        )
    problems: list[str] = []
    hint = ""
    if entry.get("enabled") is not True:
        problems.append(i18n.t("doctor.probe.plugin_installed.disabled"))
        hint = i18n.t("doctor.hint.plugin_enable", plugin=claude_plugin.PLUGIN_ID)
    expected = _installed_version()
    found = entry.get("version")
    if expected and found != expected:
        problems.append(
            i18n.t("doctor.probe.plugin_installed.version", found=found or "?", expected=expected)
        )
        hint = hint or checks_plugin.UPDATE_HINT
    _path, settings, _reason = _plugin_settings(ctx)
    language = checks_plugin.plugin_options(settings).get("language")
    current = i18n.lang()
    if isinstance(language, str) and language != current:
        problems.append(
            i18n.t("doctor.probe.plugin_installed.language", found=language, current=current)
        )
        hint = hint or INSTALL_HINT
    if problems:
        return Result(WARN, " · ".join(problems), hint)
    return Result(
        OK,
        i18n.t(
            "doctor.probe.plugin_installed.ok",
            plugin=claude_plugin.PLUGIN_ID,
            version=found or "?",
            language=language if isinstance(language, str) else "-",
        ),
    )


def _probe_ld_bin(ctx):
    if absent := _claude_absent(ctx):
        return absent
    if skip := _plugin_not_applicable(ctx):
        return skip
    path, settings, reason = _plugin_settings(ctx)
    if reason:
        return Result(UNKNOWN, reason)
    value = checks_plugin.plugin_options(settings).get("ld_bin")
    if not isinstance(value, str) or not value.strip():
        return Result(MISSING, i18n.t("doctor.probe.ld_bin.not_set", path=path), INSTALL_HINT)
    if not Path(value).is_file():
        return Result(MISSING, i18n.t("doctor.probe.ld_bin.not_found", ld_bin=value), INSTALL_HINT)
    expected = ctx.expected_ld_bin()
    expected_path = getattr(expected, "path", None)
    if expected_path is None:
        return Result(
            OK,
            i18n.t(
                "doctor.probe.ld_bin.not_compared",
                ld_bin=value,
                reason=getattr(expected, "reason", None) or "-",
            ),
        )
    if not checks_plugin.same_path(value, expected_path):
        return Result(
            WARN,
            i18n.t("doctor.probe.ld_bin.other_env", ld_bin=value, expected=expected_path),
            INSTALL_HINT,
        )
    return Result(OK, i18n.t("doctor.probe.ld_bin.ok", ld_bin=value))


def _probe_hook_duplicates(ctx):
    if absent := _claude_absent(ctx):
        return absent
    path, settings, reason = _plugin_settings(ctx)
    if reason:
        return Result(UNKNOWN, reason)
    ours = checks_plugin.our_settings_hooks(settings, ctx.hooks_dir)
    if ours and checks_plugin.plugin_enabled(settings):
        return Result(
            WARN,
            i18n.t(
                "doctor.probe.hook_duplicates.found",
                n=i18n.format_number(len(ours)),
                path=path,
                plugin=claude_plugin.PLUGIN_ID,
            ),
            checks_plugin.UPDATE_HINT,
        )
    return Result(OK, i18n.t("doctor.probe.hook_duplicates.none"))


def _probe_mod_loaded(ctx):
    """F2-mod-core (REQ-009): did the mod load? Its heartbeat, written at each session's start."""
    if absent := _claude_absent(ctx):
        return absent
    if skip := _plugin_not_applicable(ctx):
        return skip
    hint = i18n.t("doctor.hint.mod_session")
    found = checks_plugin.latest_heartbeat(ctx)
    if found is None:
        return Result(
            WARN,
            i18n.t("doctor.probe.mod_loaded.none", path=checks_plugin.heartbeat_dir(ctx)),
            hint,
        )
    path, beat, error, age_days = found
    if beat is None:
        return Result(WARN, i18n.t("doctor.probe.mod_loaded.unreadable", path=path, detail=error))
    if age_days > checks_plugin.HEARTBEAT_MAX_AGE_DAYS:
        days = i18n.format_number(int(age_days))
        return Result(WARN, i18n.t("doctor.probe.mod_loaded.stale", days=days, path=path), hint)
    pieces = beat.get("pieces") if isinstance(beat.get("pieces"), dict) else {}
    where = {"session": beat.get("session_id") or path.stem, "at": beat.get("at") or "?"}
    failed = sorted(name for name, state in pieces.items() if state == "failed")
    if failed:
        return Result(
            WARN, i18n.t("doctor.probe.mod_loaded.failed", failed=", ".join(failed), **where), hint
        )
    listed = ", ".join(f"{name} {state}" for name, state in sorted(pieces.items())) or "-"
    return Result(
        OK,
        i18n.t(
            "doctor.probe.mod_loaded.ok", version=beat.get("version") or "?", pieces=listed, **where
        ),
    )


# --- El registro --------------------------------------------------------------
# Treinta y tres elementos, en orden de grupo. Una tupla: si esto necesitara alguna vez cargarse
# solo, el problema no sería el registro sino el diseño.
#
# El número se dice en cinco sitios de este módulo y llegó a decir «once» con doce checks ya
# dentro: `cli.path` entró después y nadie actualizó el texto. Hay un test que compara los
# cinco contra `len(CHECKS)`, porque un comentario que miente sobre el propio registro es lo
# que hace que alguien planifique sobre un dato falso.
CHECKS: tuple[Check, ...] = (
    Check("cli.path", "environment", "doctor.check.cli.path", _probe_cli),
    Check("cli.published", "environment", "doctor.check.cli.published", _probe_published),
    Check("client.presence", "environment", "doctor.check.client.presence", _probe_clients),
    Check(
        "client.observed", "environment", "doctor.check.client.observed", _probe_clients_observed
    ),
    Check("config.fallback", "environment", "doctor.check.config.fallback", _probe_fallback),
    Check(
        "config.deprecated_names",
        "environment",
        "doctor.check.config.deprecated_names",
        _probe_deprecated_names,
    ),
    # In `environment`: it only reads `~/.claude`, and `install` (which runs this group too) shows
    # the copy its own migration has just left.
    Check(
        "config.claude_settings",
        "environment",
        "doctor.check.config.claude_settings",
        _probe_claude_settings,
    ),
    # En `environment`: lee ficheros locales del log y de `~/.claude`, no sale a la red.
    Check("config.cost", "environment", "doctor.check.config.cost", _probe_cost),
    Check(
        "metrics.test_windows",
        "environment",
        "doctor.check.metrics.test_windows",
        _probe_test_windows,
    ),
    # REQ-009: reads `install-state.json` only, so `install` shows it too.
    Check(
        "claude.delivery",
        "environment",
        "doctor.check.claude.delivery",
        _probe_delivery,
    ),
    Check("scaffold.hook_files", "scaffold", "doctor.check.scaffold.hook_files", _probe_hook_files),
    Check(
        "scaffold.hook_orphans",
        "scaffold",
        "doctor.check.scaffold.hook_orphans",
        _probe_hook_orphans,
    ),
    Check(
        "scaffold.hook_settings",
        "scaffold",
        "doctor.check.scaffold.hook_settings",
        _probe_hook_settings,
    ),
    Check("scaffold.skill", "scaffold", "doctor.check.scaffold.skill", _probe_skill),
    Check("scaffold.memory", "scaffold", "doctor.check.scaffold.memory", _probe_memory),
    Check("scaffold.mcp_claude", "scaffold", "doctor.check.scaffold.mcp_claude", _probe_mcp_claude),
    Check("scaffold.mcp_codex", "scaffold", "doctor.check.scaffold.mcp_codex", _probe_mcp_codex),
    Check(
        "scaffold.mcp_opencode",
        "scaffold",
        "doctor.check.scaffold.mcp_opencode",
        _probe_mcp_opencode,
    ),
    # Optional: with nothing installed it is `ok`. In `scaffold` because it only reads the HOME,
    # so the report of `install` (which runs only that group) also sees it.
    Check(
        "scaffold.shell_completion",
        "scaffold",
        "doctor.check.scaffold.shell_completion",
        _probe_shell_completion,
    ),
    # REQ-009 and 008 c: they read `settings.json`, without launching `claude`.
    Check("plugin.ld_bin", "scaffold", "doctor.check.plugin.ld_bin", _probe_ld_bin),
    Check(
        "hooks.duplicates",
        "scaffold",
        "doctor.check.hooks.duplicates",
        _probe_hook_duplicates,
    ),
    # F2-mod-core (REQ-009): reads the heartbeat file the mod writes, without launching `claude`.
    Check("mod.loaded", "scaffold", "doctor.check.mod.loaded", _probe_mod_loaded),
    Check("service.daemon", "service", "doctor.check.service.daemon", _probe_daemon),
    Check("service.backend", "service", "doctor.check.service.backend", _probe_backend_models),
    # En `service` y no en `scaffold` aunque lea las entradas MCP: sale a la red, y el grupo
    # `scaffold` no sale a la red por contrato — es lo que permite a `install` correr su reporte
    # sin tocar nada externo (ver `_SCAFFOLD_GROUPS` en cli.py). Además se lee junto al backend,
    # que es de lo que habla.
    Check(
        "service.credential", "service", "doctor.check.service.credential", _probe_mcp_credential
    ),
    # Misma razón que el de arriba para estar en `service`: pregunta al puerto. Y no es el
    # mismo check con otro nombre — aquel mira la puerta del backend y este la del daemon, que
    # se cierran por separado.
    Check(
        "service.daemon_auth", "service", "doctor.check.service.daemon_auth", _probe_mcp_daemon_auth
    ),
    # Claude Desktop no está en el registro de clientes y aquel check es ciego para él. Aparte y
    # no dentro de aquel porque este sí prueba el token contra el puerto: el suyo va literal.
    Check(
        "service.desktop_auth", "service", "doctor.check.service.desktop_auth", _probe_desktop_auth
    ),
    # REQ-009: in `service` because they launch `claude` (`--version`, `plugin list --json`), and
    # the report of `install` (`environment` and `scaffold`) launches nothing.
    Check(
        "claude.version",
        "service",
        "doctor.check.claude.version",
        _probe_claude_version,
    ),
    Check(
        "plugin.installed",
        "service",
        "doctor.check.plugin.installed",
        _probe_plugin_installed,
    ),
    Check("backend.llamaswap", "backend", "doctor.check.backend.llamaswap", _probe_llamaswap),
    Check("backend.llamaserver", "backend", "doctor.check.backend.llamaserver", _probe_llamaserver),
    # REQ-036: leen la config de llama-swap (`--config` de `doctor` o `LLAMASWAP_CONFIG`) y no
    # salen a la red.
    Check("backend.residency", "backend", "doctor.check.backend.residency", _probe_residency),
    Check("backend.topology", "backend", "doctor.check.backend.topology", _probe_topology),
)


def run_all(ctx: Context, *, groups: tuple[str, ...] | None = None) -> list[tuple[Check, Result]]:
    """Corre los treinta y tres probes. Un probe que falle es ``unknown``, nunca tumba el diagnóstico.

    Con ``groups`` se corren solo los de esos grupos, en el mismo orden del registro. Lo pide
    ``install``: su reporte final habla del andamiaje que acaba de escribir, y correr también
    ``service`` y ``backend`` saldría a la red y lanzaría los binarios de llama-swap por el
    simple hecho de haber instalado unos hooks. El filtro no toca ni el registro ni los probes:
    sin el argumento, el comportamiento es exactamente el de antes.
    """
    results: list[tuple[Check, Result]] = []
    for check in CHECKS:
        if groups is not None and check.group not in groups:
            continue
        try:
            result = check.probe(ctx)
        except Exception as exc:  # un check roto no debe impedir ver los otros treinta y dos
            result = Result(UNKNOWN, i18n.t("doctor.probe.failed", error=exc))
        results.append((check, result))
    return results
