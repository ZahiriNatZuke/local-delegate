"""config.py — configuración por variables de entorno, sin rutas hardcodeadas.

local-delegate es un cliente GENÉRICO de cualquier endpoint OpenAI-compatible
(llama-swap, Ollama, LM Studio, vLLM…). Todo se configura por variables de entorno
con defaults sensatos y multiplataforma. El log de uso vive en el directorio de datos
del usuario (vía ``platformdirs``), nunca en una ruta absoluta de una máquina concreta.

Los defaults del catálogo de modelos son solo eso, *defaults documentados*: apuntan a
los ids de un setup de referencia con llama-swap. Cámbialos por env para tu backend
(p. ej. ``LOCAL_DELEGATE_MODEL_MECHANICAL=llama3.1`` con Ollama).
"""

from __future__ import annotations

import ipaddress
import os
import unicodedata
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

from platformdirs import user_data_dir

from . import deprecations, keychain

APP_NAME = "local-delegate"


# Nombres de todas las variables de entorno que este módulo consulta. NO se escribe a mano: la
# alimentan los cuatro helpers de abajo al ser llamados, así que no puede quedarse corta cuando se
# añada una opción nueva. La suite la usa para aislarse del entorno de quien la corre (ver
# `tests/conftest.py`): antes de esto, tener `LOCAL_DELEGATE_WEB_TOKEN` puesta —lo normal en una
# máquina con el daemon instalado— hacía fallar cuatro tests del daemon con 401 en vez de 200.
_READ_VARIABLES: set[str] = set()


def _read(name: str) -> str | None:
    """Única puerta a `os.environ` de este módulo: lee y deja constancia del nombre."""
    _READ_VARIABLES.add(name)
    return os.environ.get(name)


def _env(name: str, default: str) -> str:
    """El valor de la variable, o `default` si no está puesta, está vacía o solo tiene espacios.

    Vacía cuenta como no puesta a propósito: una entrada de cliente con
    `"${LOCAL_DELEGATE_WEB_HOST}"` que expande a nada dejaba `WEB_HOST=""`, y uvicorn lee un host
    vacío como todas las interfaces: el panel y el MCP quedaban abiertos a la red en vez de en
    loopback. Solo cambia algo en las que tienen un defecto no vacío; las de defecto `""` reciben el
    valor tal cual, como antes (alguna lo guarda crudo para su aviso, `output_language`).
    """
    raw = _read(name)
    if raw is None or (default and not raw.strip()):
        return default
    return raw


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = _read(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


# --- Endpoint OpenAI-compatible ---------------------------------------------
BASE_URL = _env("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9292/v1").rstrip("/")
API_KEY = _env("LOCAL_DELEGATE_API_KEY", "")  # opcional; algunos endpoints lo exigen
HTTP_TIMEOUT = _env_float("LOCAL_DELEGATE_TIMEOUT", 180.0)
# Plazos de los sondeos de ESTADO (`/models`, `/running`, `/api/metrics/stats`, `doctor`), no de
# las delegaciones. Constantes y sin variable de entorno a propósito (REQ-013): 3 s para conectar
# porque en Windows un puerto cerrado tarda ~2,1 s en rechazarse, y con un plazo menor llega como
# `ConnectTimeout` y parece una VPN (medido, `research.md` §2); 2 s para leer, como antes.
PROBE_CONNECT_TIMEOUT = 3.0
PROBE_READ_TIMEOUT = 2.0
# Plazo de CONEXIÓN de las delegaciones (REQ-019). Solo el de conexión: la espera de carga de un
# modelo es de lectura y sigue en HTTP_TIMEOUT. Sin él, el kernel decidía (~21 s en Windows, ~75 s
# en macOS) y cada fallo de la Mac con la VPN caída bloqueaba la tool más de un minuto.
DELEGATION_CONNECT_TIMEOUT = 10.0
# Backpressure del proceso MCP. En el daemon singleton este límite se comparte entre
# todos los clientes HTTP; llama-swap sigue siendo la autoridad del routing/VRAM.
MAX_CONCURRENT_REQUESTS = max(1, _env_int("LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS", 2))


def auth_headers() -> dict[str, str]:
    """Headers del backend sin registrar ni exponer el secreto configurado.

    La clave sale de `keychain.credential`: la variable `API_KEY` y, si falta, en macOS el
    Llavero (issue #409). `API_KEY` sigue siendo solo lo que trae el entorno del proceso.
    """
    key, _source = keychain.credential(API_KEY, keychain.API_KEY_SERVICE)
    return {"Authorization": f"Bearer {key}"} if key else {}


# --- Machine of origin (concurrency PC+Mac, step 0) --------------------------
# Every usage-log entry says which machine it came from (`host`), and every request to the backend
# carries it in `X-Local-Delegate-Host`, so llama-swap's `inflight` photo can tell the PC's calls
# from the Mac's. Short host name by default; `LOCAL_DELEGATE_MACHINE_NAME` overrides it (two
# machines with the same name, or a name the user prefers to read in the panel).
HOST_HEADER = "X-Local-Delegate-Host"
MACHINE_NAME_OVERRIDE = _env("LOCAL_DELEGATE_MACHINE_NAME", "")
_MACHINE_NAME_MAX = 64


def clean_machine_name(raw: str) -> str:
    """`raw` reduced to letters, digits, `.`, `_` and `-` (max 64): safe in a header and a log."""
    kept = "".join(c for c in raw.strip() if c.isascii() and (c.isalnum() or c in "._-"))
    return kept[:_MACHINE_NAME_MAX]


def machine_name() -> str:
    """The short name of this machine: the override, else the host name up to the first dot."""
    override = clean_machine_name(MACHINE_NAME_OVERRIDE)
    if override:
        return override
    try:
        import socket

        name = clean_machine_name(socket.gethostname().split(".", 1)[0])
    except OSError:
        name = ""
    return name or "unknown"


def backend_headers() -> dict[str, str]:
    """Headers for every request to the backend: the credential plus the machine of origin.

    `auth_headers()` stays as it was (credential only): the panel and the CLI use it for the
    daemon too, and the origin header is for the backend.
    """
    return {**auth_headers(), HOST_HEADER: machine_name()}


# --- Origen del cómputo: backend en esta máquina vs backend remoto -----------
# El MCP siempre corre en la máquina del cliente (por eso 'path' lee archivos locales),
# pero la INFERENCIA puede ejecutarse en otra máquina (p. ej. Mac -> llama-swap de la PC
# por Tailscale). Se clasifica por el host de BASE_URL: loopback = "local", cualquier otro
# host = "remote". Se registra en cada evento del log para poder separarlo en el dashboard.
#
# La heurística falla con un TÚNEL: `ssh -L 9292:localhost:9292` o un port-forward de
# Tailscale hacen que un backend remoto se vea en 127.0.0.1, y el dashboard reportaría
# CÓMPUTO LOCAL para inferencia que salió de la máquina. Un túnel es transparente por
# diseño, así que no hay forma fiable de detectarlo desde aquí: quien lo monta lo declara
# con LOCAL_DELEGATE_BACKEND_ORIGIN. Se prefiere un override explícito a adivinar, igual
# que los eventos sin el campo se muestran como 'n/d' en vez de asumirlos locales.
BACKEND_ORIGIN_OVERRIDE = _env("LOCAL_DELEGATE_BACKEND_ORIGIN", "auto").strip().lower()


def _split_host_port(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return host, port


def _is_loopback_host(host: str) -> bool:
    if not host:
        return False
    if host.lower() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def backend_origin(url: str | None = None) -> str:
    """'local' si la inferencia corre en esta máquina, 'remote' en otro caso.

    Con LOCAL_DELEGATE_BACKEND_ORIGIN=local|remote se fuerza el valor (caso del túnel);
    'auto' —el default— deduce por el host. Un valor inválido cae a 'auto' en vez de
    reventar: es un dato de presentación y no vale romper el arranque por una errata.
    """
    if BACKEND_ORIGIN_OVERRIDE in {"local", "remote"}:
        return BACKEND_ORIGIN_OVERRIDE
    host, _port = _split_host_port(url if url is not None else BASE_URL)
    return "local" if _is_loopback_host(host) else "remote"


def backend_host(url: str | None = None) -> str:
    """host[:puerto] del endpoint, sin esquema, ruta ni credenciales (apto para el log)."""
    host, port = _split_host_port(url if url is not None else BASE_URL)
    return f"{host}{port}" if host else ""


def remote_panel_url(url: str | None = None) -> str:
    """Panel del daemon de la máquina del backend, o "" si el backend es local.

    Mismo esquema y host que el backend, con el puerto web de este daemon: las dos máquinas corren
    el mismo paquete, y `tailscale serve` publica los dos puertos igual. El puerto del backend
    (llama-swap) no sirve aquí: su `/ui` no enseña la RAM ni la VRAM, que es lo que falta.
    """
    target = url if url is not None else BASE_URL
    if backend_origin(target) != "remote":
        return ""
    parts = urlsplit(target)
    host = parts.hostname or ""
    if not host:
        return ""
    if ":" in host:  # IPv6: urlsplit le quita los corchetes
        host = f"[{host}]"
    return f"{parts.scheme or 'http'}://{host}:{WEB_PORT}/"


# --- Log de uso/ahorro (JSONL) ----------------------------------------------
# Por defecto se rota por mes: usage-YYYYMM.jsonl dentro de LOG_DIR. Si el usuario fija
# LOCAL_DELEGATE_LOG (archivo explícito), se usa ESE archivo tal cual, sin rotación —
# compatibilidad con instalaciones que ya apuntaban a una ruta fija.
def _default_log_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def _default_log() -> Path:
    return _default_log_dir() / "usage.jsonl"


_log_env = _read("LOCAL_DELEGATE_LOG")
USAGE_LOG: Path = Path(_log_env) if _log_env else _default_log()  # legado (sin rotación) o default
LOG_ROTATION_ENABLED: bool = _log_env is None

_log_dir_env = _read("LOCAL_DELEGATE_LOG_DIR")
LOG_DIR: Path = Path(_log_dir_env) if _log_dir_env else _default_log_dir()


# --- Telemetría de los hooks consultivos (opt-in, la escriben los propios hooks) ---------------
# El nombre de la variable NO lleva el prefijo `LOCAL_DELEGATE_` porque no es de este módulo: la
# define el usuario en la configuración de su cliente y la leen los scripts de
# `resources/hooks/`, que son stdlib pura y no importan nada de aquí. Se refleja en este módulo
# solo para que el dashboard sepa **dónde mirar**, y por eso se lee igual que allí.
#
# `None` cuando no está definida, y eso significa «el usuario no activó la telemetría», que es
# distinto de «está activada y no hay eventos». El dashboard tiene que poder decir cuál de las dos.
_hook_log_env = _env("LD_HOOK_TELEMETRY_LOG", "").strip()
HOOK_TELEMETRY_LOG: Path | None = Path(_hook_log_env) if _hook_log_env else None

# Las otras cuatro que ya leían los hooks y no constaban aquí. Las destapó el guardián nuevo de
# `tests/test_environment_isolation.py`, que escanea los scripts en vez de fiarse de una lista a
# mano: el mismo agujero que describe REQ-022 llevaba abierto desde que existe el hook de lectura.
# El valor no se usa desde el paquete; lo que importa es que el nombre entre en el inventario.
HOOK_ENABLED: bool = _env_flag("LD_HOOK_ENABLED", True)
HOOK_READ_ENABLED: bool = _env_flag("LD_HOOK_READ_ENABLED", False)
#: Bajado de 32 a 8 el 2026-09-08 y **medido**, no estimado: sobre las 96 lecturas registradas
#: desde que la telemetría guarda la extensión, el hook callaba por tamaño 24 veces y **las 24 eran
#: `.md`, `.json` o `.txt`** —ni una de código—, 17 de ellas entre 8 y 16 KB. Con 32 KB la franja
#: donde vive la documentación de este repo quedaba muda: el aviso no se ignoraba, no llegaba.
#: El valor tiene que coincidir con el literal del hook, que no puede importar este módulo; los ata
#: `test_el_umbral_del_hook_de_lectura_no_tiene_dos_valores`.
HOOK_READ_SUGGEST_KB: float = _env_float("LD_HOOK_READ_SUGGEST_KB", 8.0)
HOOK_READ_STRONG_KB: float = _env_float("LD_HOOK_READ_STRONG_KB", 100.0)
#: Si la regla puede RECHAZAR una lectura en vez de solo sugerir. Nace apagada: se enciende cuando
#: este escrito el criterio de la quinta medicion, incluido el resultado que la retira. El hook la
#: consulta en cada invocacion —no al arrancar— porque una sesion abierta hereda el entorno del
#: lanzador, y un freno que exige reiniciar la sesion no frena nada.
#: Its old name is retired with no effect since 0.38.0; `doctor` and `local_status` warn about it.
HOOK_READ_BLOCK: bool = _env_flag("LD_HOOK_READ_BLOCK", False)
#: Donde vive el fichero que APAGA el bloqueo en caliente (REQ-F1-11): si existe, no se bloquea
#: aunque `LD_HOOK_READ_BLOCK` diga 1. La variable no sirve de freno porque una sesion abierta
#: hereda el entorno del lanzador; un fichero se lee en cada invocacion. Vacia = el defecto del hook.
#: Its old name is retired with no effect since 0.38.0; `doctor` and `local_status` warn about it.
HOOK_READ_SWITCH_FILE: str = _env("LD_HOOK_READ_SWITCH_FILE", "")


# --- Raíces permitidas para 'path' en las tools (opt-in) ---------------------
# Vacía/ausente = sin restricción (comportamiento actual, documentado). Lista separada
# por ';' de directorios raíz; cualquier 'path' fuera de todos ellos se rechaza.
_allowed_dirs_raw = _env("LOCAL_DELEGATE_ALLOWED_DIRS", "")
ALLOWED_DIRS: list[Path] = [
    Path(p.strip()).resolve() for p in _allowed_dirs_raw.split(";") if p.strip()
]


# --- Catálogo de modelos (roles configurables, defaults documentados) -------
MODEL_MECHANICAL = _env(
    "LOCAL_DELEGATE_MODEL_MECHANICAL", "gemma3-4b"
)  # clasificar, extraer, resumen corto
# Defectos de largo, código y visión: los ganadores de la medición de F2 (P-16, 2026-09-15).
MODEL_LONG = _env("LOCAL_DELEGATE_MODEL_LONG", "gemma4-26b-a4b")  # documentos largos (ctx amplio)
MODEL_CODE = _env("LOCAL_DELEGATE_MODEL_CODE", "qwen36-35b-a3b")  # código / boilerplate
# Rol de visión (imagen->texto). Fuera de ALLOWED_MODELS a propósito: ese set es para el
# escape genérico local_delegate (texto->texto puro), que no arma payload multimodal.
MODEL_VISION = _env("LOCAL_DELEGATE_MODEL_VISION", "gemma4-12b")
ALLOWED_MODELS: set[str] = {MODEL_MECHANICAL, MODEL_LONG, MODEL_CODE}

# --- Variables con nombre obsoleto ------------------------------------------
# Se leen por la puerta registrada (constan en el inventario y la suite las aísla) para que el
# check `config.deprecated_names` de `doctor` pueda AVISAR de que siguen puestas: borrarlas sin
# más las habría vuelto mudas. Los nombres salen del registro único `deprecations.DEPRECATED_NAMES`
# (`deprecations.env_vars()`), no de una lista escrita aquí.
DEPRECATED_ENV_VALUES: dict[str, str | None] = {
    entry.old: _read(entry.old) for entry in deprecations.env_vars()
}

# Umbral para elegir el modelo "largo" vs "mecánico" en tools que enrutan por tamaño.
LONG_INPUT_CHARS = _env_int("LOCAL_DELEGATE_LONG_INPUT_CHARS", 6000)

# local_summarize sigue la estructura del documento cuando tiene títulos Markdown y el rol es
# `long` (SDD resumen-por-secciones). Apagado, resume en prosa como antes, byte a byte. **Apagado
# por defecto**: mejora mucho la salida de la tool (100 % de títulos, con introducción y
# subsecciones), pero en la medición con `claude -p` no redujo las relecturas —Claude releía para
# comprobar, no por lo que faltaba— y el criterio escrito antes de medir era retirarlo. Lo lee el
# daemon al arrancar: para encenderlo hay que ponerlo en el entorno del lanzador y reiniciarlo.
# Its old name is retired with no effect since 0.38.0; `doctor` and `local_status` warn about it.
STRUCTURED_SUMMARY = _env_flag("LOCAL_DELEGATE_STRUCTURED_SUMMARY", False)


# B2e: carpeta LOCAL donde cada operación troceada (map-reduce) deja un JSON con la salida de cada
# paso (map, reagrupado, reduce). Apagado por defecto (vacío): solo se enciende para medir, porque
# esas notas son lo único que separa «el trozo ya lo había perdido» de «se perdió al combinar».
# Nunca sale de la máquina: es un fichero en disco, no va al log de uso ni al panel.
def dump_chunk_notes_dir() -> str | None:
    """Folder of `LOCAL_DELEGATE_DUMP_CHUNK_NOTES`, or None when the dump is off (the default)."""
    return _env("LOCAL_DELEGATE_DUMP_CHUNK_NOTES", "").strip() or None


# Tope de entrada POR ROL (evita desbordar el ctx del backend). Por rol y no por modelo: dos roles
# pueden resolver al mismo modelo (REQ-004), y un dict indexado por nombre de modelo hacía que el
# último rol del literal pisara el tope de los demás sin avisar (F3, tarea 25).
_MAX_CHARS_DEFAULT = 20000
MAX_CHARS_BY_ROLE: dict[str, int] = {
    "mechanical": _env_int("LOCAL_DELEGATE_MAX_CHARS_MECHANICAL", 20000),
    "long": _env_int("LOCAL_DELEGATE_MAX_CHARS_LONG", 48000),
    "code": _env_int("LOCAL_DELEGATE_MAX_CHARS_CODE", 20000),
}


def models_by_role() -> dict[str, str]:
    """Rol -> modelo con la configuración vigente (roles de texto; visión va aparte)."""
    return {
        "mechanical": MODEL_MECHANICAL,
        "long": MODEL_LONG,
        "code": MODEL_CODE,
    }


def max_chars_for_role(role: str) -> int:
    """Tope de entrada de un rol: el que usa el modelo principal de una llamada."""
    return MAX_CHARS_BY_ROLE.get(role, _MAX_CHARS_DEFAULT)


def max_chars_for(model: str) -> int:
    """Tope de un MODELO: el mínimo de los roles que resuelven a él (default si ninguno).

    Es para lo que no tiene rol —validar un candidato de respaldo (REQ-003)—, donde prometer más de
    lo que aguanta el modelo es justo el fallo. El modelo principal de una tool usa
    `max_chars_for_role`, para que dos roles sobre el mismo modelo no se rebajen el uno al otro.
    """
    caps = [
        MAX_CHARS_BY_ROLE[role]
        for role, role_model in models_by_role().items()
        if role_model == model
    ]
    return min(caps) if caps else _MAX_CHARS_DEFAULT


# --- Enfriamiento por modelo (F3: REQ-009 a REQ-014) --------------------------
# Encendido por defecto (D-1). Los números vienen de bajar de escala los de OmniRoute y no están
# medidos (P-4): son configurables, y la tarea 30 escribe el criterio para validarlos.
COOLDOWN = _env_flag("LOCAL_DELEGATE_COOLDOWN", True)
COOLDOWN_FAILURES = max(1, _env_int("LOCAL_DELEGATE_COOLDOWN_FAILURES", 3))
COOLDOWN_S = max(1.0, _env_float("LOCAL_DELEGATE_COOLDOWN_S", 120.0))
COOLDOWN_MAX_S = max(COOLDOWN_S, _env_float("LOCAL_DELEGATE_COOLDOWN_MAX_S", 900.0))

# --- Corte por backend inalcanzable (issue #436, punto 3) ---------------------
# El mismo mecanismo que el enfriamiento, pero para la CONEXIÓN: tras N fallos de conexión seguidos
# (`connection_failure`: dns, refused, connect_timeout…) las `local_*` responden al momento que el
# backend no está, sin llamarlo ni registrar una delegación. Al vencer la espera, la siguiente
# llamada va de verdad (prueba): si conecta, se cierra; si no, vuelve a cortar con la espera doblada
# hasta el tope. Un sondeo bueno de `local_status` o del panel también lo cierra.
BACKEND_BREAKER = _env_flag("LOCAL_DELEGATE_BACKEND_BREAKER", True)
BACKEND_BREAKER_FAILURES = max(1, _env_int("LOCAL_DELEGATE_BACKEND_BREAKER_FAILURES", 3))
BACKEND_BREAKER_S = max(1.0, _env_float("LOCAL_DELEGATE_BACKEND_BREAKER_S", 60.0))
BACKEND_BREAKER_MAX_S = max(
    BACKEND_BREAKER_S, _env_float("LOCAL_DELEGATE_BACKEND_BREAKER_MAX_S", 600.0)
)


# --- Respaldo entre modelos (F3: REQ-002, REQ-004, REQ-014) ------------------
# Encendido por defecto (D-1), hasta 2 saltos (D-3). La cadena de cada rol la resuelve `chains.py`
# con la configuración vigente.
FALLBACK = _env_flag("LOCAL_DELEGATE_FALLBACK", True)
FALLBACK_MAX_HOPS = max(0, _env_int("LOCAL_DELEGATE_FALLBACK_MAX_HOPS", 2))
#: Cadena sobrescrita por rol: `None` es la de la spec; `""` o `none` desactivan el respaldo de ese
#: rol; si no, roles (`mechanical`, `long`, `code`, `loaded`) o ids separados por comas
#: (`residente` y `resident` se aceptan como sinónimos obsoletos de `loaded`, con aviso de `doctor`).
FALLBACK_CHAINS: dict[str, str | None] = {
    role: _read(f"LOCAL_DELEGATE_FALLBACK_{role.upper()}")
    for role in ("mechanical", "long", "code")
}


# --- Turno por conjunto de modelos compatibles (daemon-reparte-el-backend, REQ-007) -----------
# Red de seguridad del turno: la cabeza de la cola se concede forzada si lleva este tiempo
# esperando Y el daemon lleva este tiempo sin ninguna llamada al backend en vuelo.
TURN_MAX_S = _env_float("LOCAL_DELEGATE_TURN_MAX_S", 600.0)
# Concurrency PC+Mac (REQ-030): an operation that has held the turn this long yields it between two
# chunks when the head of the queue has waited this long for a model that clashes with its own; it
# goes back to the end of the queue. Bounds how long a long operation keeps a clashing one waiting
# (REQ-031). `0` disables yielding (the wait then depends on the longest operation, as before).
TURN_YIELD_S = max(0.0, _env_float("LOCAL_DELEGATE_TURN_YIELD_S", 120.0))
# Concurrency PC+Mac, lot 3 (REQ-010..017): the daemon's turn endpoint (`/api/turn/*`), through
# which a process whose backend is THIS machine's (the Mac) joins the same turn. A lease expires
# after this many seconds without an `acquire` or a `heartbeat` (REQ-012).
TURN_LEASE_S = max(3.0, _env_float("LOCAL_DELEGATE_TURN_LEASE_S", 30.0))
# At most this many live leases in total (REQ-017); 8 per host on top of that.
TURN_MAX_LEASES = max(1, _env_int("LOCAL_DELEGATE_TURN_MAX_LEASES", 16))
# Kill switch of the endpoint (`off`: 404, as an old daemon), the rollback that needs no release.
TURN_SERVER = _env_flag("LOCAL_DELEGATE_TURN_SERVER", True)

# --- Aborted delegations and a saturated queue (issue #476) ----------------------------------
# The daemon's own budget for ONE tool call, queue included: past it the call is cancelled with
# `cancel_reason: "deadline"` and logged as a failure. A client that gives up (Claude Code's idle
# or total timeout) does not always tell the daemon, which kept going for many minutes and left no
# trace in the usage log. 1800 s is also when the panel drops an in-flight entry as orphaned
# (`_INFLIGHT_STALE_S`). `0` disables it.
CALL_MAX_S = max(0.0, _env_float("LOCAL_DELEGATE_CALL_MAX_S", 1800.0))
# How long a call waiting for the turn or for a slot tolerates the queue NOT moving (no backend
# call ended, no slot or turn changed hands); not the length of the wait, so a slow queue that
# moves never fails the one behind it. Past it the call fails at once with
# `error: "queue_saturated"` and a clear message, instead of using up the client's budget in the
# queue. Above `TURN_MAX_S`, so the turn's safety net acts first; below `CALL_MAX_S`, so the clear
# message arrives before the deadline. A call alone, without a queue, never waits. `0` disables it.
QUEUE_MAX_WAIT_S = max(0.0, _env_float("LOCAL_DELEGATE_QUEUE_MAX_WAIT_S", 900.0))

# --- Progress while a call waits or works (issue #479) ---------------------------------------
# Every this many seconds a live tool call sends `notifications/progress` (when the request
# carried a `progressToken`), with its phase: queue position, slot wait, piece k/N. Claude Code cuts
# a call that sends "no response or progress for 300s", so a call queued behind others or in a long
# inference was cut while the daemon kept working for nobody. `0` disables it.
PROGRESS_INTERVAL_S = max(0.0, _env_float("LOCAL_DELEGATE_PROGRESS_INTERVAL_S", 20.0))

# --- Espera frente a lentitud (daemon-reparte-el-backend, REQ-025) ----------------------------
# Una llamada es `slow` si genera a menos de esta fracción de la velocidad normal de su modelo
# (`pace_rel` < umbral). 0,5 por defecto, decisión del usuario.
SLOW_THRESHOLD = _env_float("LOCAL_DELEGATE_SLOW_THRESHOLD", 0.5)

# --- Afinidad (daemon-reparte-el-backend, REQ-013, T15) ---------------------------------------
# Un alternativo ya cargado cuenta «con margen» si le quedan al menos estos segundos de TTL. 5 s
# por defecto: T2 (b) midió la ventana decisión-llegada con p99 de 3,1 ms, así que no se subió.
AFFINITY_MARGIN_S = _env_float("LOCAL_DELEGATE_AFFINITY_MARGIN_S", 5.0)


# --- llama-swap: autoarranque, doctor y residente -----------------------------
# Se leen al LLAMAR y no al importar, como siempre se leyeron: el autoarranque y los tests las fijan
# en caliente. Antes las leían `autostart.py`, `doctor.py` y `server.py` con `os.environ` directo,
# fuera del inventario de abajo, y por esa rendija la suite heredaba el entorno de la máquina.
def llamaswap_config_path() -> str:
    return (_read("LLAMASWAP_CONFIG") or "").strip()


def llamaswap_exe() -> str:
    return (_read("LLAMASWAP_EXE") or "").strip()


def llamaswap_listen() -> str:
    return _env("LLAMASWAP_LISTEN", "127.0.0.1:9292")


def llamaswap_watch_config() -> bool:
    return _env_flag("LLAMASWAP_WATCH_CONFIG", False)


# --- Idioma del mensaje de `local_commit_msg` (daemon-reparte-el-backend, REQ-044) --------------
# Texto libre y corto: `es`, `en`, `fr`… o un nombre (`español`). Vacío = el idioma predominante de
# los textos del diff. Se lee al LLAMAR, como las de llama-swap: así un test lo fija con
# `monkeypatch.setenv` sin recargar el módulo, y el constructor del corpus de afinidad puede
# capturar el prompt con el idioma que tendrá la máquina en producción.
def commit_language() -> str:
    return _env("LOCAL_DELEGATE_COMMIT_LANGUAGE", "").strip()


# --- Idioma de la interfaz (REQ-018/REQ-019) ------------------------------------------------------
# La lee y la valida `hook_common.resolve_language`, la única implementación de la regla; aquí solo
# se registra para que entre en `ENVIRONMENT_VARIABLES` y la suite la aísle (REQ-043).
def language_variable() -> str:
    return _env("LOCAL_DELEGATE_LANG", "")


# --- Idioma de respuesta del modelo local (REQ-028, enmienda del 2026-10-14, issue #260) ---------
# Fija SOLO el idioma en que `local_summarize`, `local_lint_summary`, `local_explain_code` y
# `local_describe_image` piden responder; la usa `server.py` (B2b). Se lee al LLAMAR, como
# `commit_language`. Vacía = seguir al idioma vigente. Un valor no válido se ignora y se avisa: el
# aviso es un código (`problem`) y su texto está en el catálogo (`common.output_language.*`).
OUTPUT_LANGUAGE_MAX_CHARS = 40
# Control (`Cc`), formato invisible (`Cf`) y separadores de línea y párrafo (`Zl`, `Zp`).
_OUTPUT_LANGUAGE_REJECTED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


class OutputLanguage(NamedTuple):
    value: str  # "" = sin poner o no válida: se sigue al idioma vigente
    problem: str | None  # None | "control_chars" | "too_long"
    raw: str  # el valor tal cual, para el aviso


def output_language() -> OutputLanguage:
    raw = _env("LOCAL_DELEGATE_OUTPUT_LANGUAGE", "")
    value = raw.strip()
    if not value:
        return OutputLanguage("", None, raw)
    if any(unicodedata.category(ch) in _OUTPUT_LANGUAGE_REJECTED_CATEGORIES for ch in value):
        return OutputLanguage("", "control_chars", raw)
    if len(value) > OUTPUT_LANGUAGE_MAX_CHARS:
        return OutputLanguage("", "too_long", raw)
    return OutputLanguage(value, None, raw)


# --- Parámetros por rol al backend (SDD backend-extra-params, REQ-008) ----------------------------
# Override puntual del fichero `LOG_DIR/backend-params.json`, con el formato `role.key=value;…`. Se
# lee al LLAMAR, como `output_language`. Aquí solo se lee y se acota: la gramática y la validación
# son de `backend_params.parse_override`. Si pasa del tope se ignora entera (`value=None`) y el
# aviso es un código (`problem`), cuyo texto está en el catálogo
# (`common.backend_params.warning.override_too_long`).
BACKEND_PARAMS_OVERRIDE_MAX_CHARS = 2048


class BackendParamsOverride(NamedTuple):
    value: str | None  # None = sin poner, vacía o ignorada por larga
    problem: str | None  # None | "override_too_long"
    raw: str | None  # el valor tal cual; el aviso solo usa rol y clave, nunca lo que va tras `=`


def backend_params_override() -> BackendParamsOverride:
    raw = _env("LOCAL_DELEGATE_BACKEND_PARAMS", "")
    if not raw.strip():
        return BackendParamsOverride(None, None, raw or None)
    if len(raw) > BACKEND_PARAMS_OVERRIDE_MAX_CHARS:
        return BackendParamsOverride(None, "override_too_long", raw)
    return BackendParamsOverride(raw, None, raw)


# Una lectura al importar, solo para que estos nombres entren en `ENVIRONMENT_VARIABLES`.
for _reader in (
    llamaswap_config_path,
    llamaswap_exe,
    llamaswap_listen,
    llamaswap_watch_config,
    commit_language,
    language_variable,
    output_language,
    backend_params_override,
):
    _reader()


# --- Chunking de salida (local_translate / local_delegate) -------------------
# Las tools que TRANSFORMAN el texto completo (traducir, reescribir) producen una salida tan
# larga como la entrada, así que una sola llamada choca contra max_tokens y devuelve el
# documento cortado. Para esas tools el input se parte por límites naturales (headers
# Markdown -> párrafos -> líneas) en trozos de CHUNK_CHARS, cada trozo se traduce en su
# propia llamada con CHUNK_MAX_TOKENS, y los resultados se concatenan en orden.
# CHUNK_CHARS por defecto (3500) deja margen: 3500 chars ≈ 875-1200 tokens de salida contra
# un techo de 2048, suficiente incluso cuando el idioma destino "infla" el texto.
CHUNK_CHARS = max(500, _env_int("LOCAL_DELEGATE_CHUNK_CHARS", 3500))
CHUNK_MAX_TOKENS = max(256, _env_int("LOCAL_DELEGATE_CHUNK_MAX_TOKENS", 2048))
# Un trozo por debajo de este tamaño ya no se vuelve a partir aunque el modelo trunque:
# evita una recursión infinita si el backend responde corto por otra razón.
CHUNK_MIN_CHARS = max(200, _env_int("LOCAL_DELEGATE_CHUNK_MIN_CHARS", 400))


# --- response_format json_schema en local_extract ----------------------------
# "auto" (default): pide JSON con schema; si el backend responde 400, reintenta sin schema.
# "on": exige schema, propaga el error si el backend no lo soporta. "off": nunca lo pide.
_json_schema_raw = _env("LOCAL_DELEGATE_JSON_SCHEMA", "auto").strip().lower()
JSON_SCHEMA_MODE = _json_schema_raw if _json_schema_raw in {"auto", "on", "off"} else "auto"


# --- Tope de tamaño de imagen para local_describe_image (F6) -----------------
MAX_IMAGE_MB = _env_int("LOCAL_DELEGATE_MAX_IMAGE_MB", 8)


# --- Web de métricas embebida -----------------------------------------------
WEB_ENABLED = _env_flag("LOCAL_DELEGATE_WEB", True)
WEB_HOST = _env("LOCAL_DELEGATE_WEB_HOST", "127.0.0.1")
WEB_PORT = _env_int("LOCAL_DELEGATE_WEB_PORT", 9393)
# Nombres extra que el puerto admite en la cabecera `Host`, separados por comas (`web/host_guard.py`).
# Por defecto solo loopback y el propio WEB_HOST: es lo que cierra el DNS rebinding. Hace falta
# añadir el nombre con el que llega un proxy delante (`tailscale serve`: `own-pc.tailXXXX.ts.net`);
# `*` desactiva la comprobación.
WEB_ALLOWED_HOSTS: list[str] = [
    h.strip() for h in _env("LOCAL_DELEGATE_WEB_ALLOWED_HOSTS", "").split(",") if h.strip()
]
# Tipografía de marca desde Google Fonts: único recurso externo del dashboard y puramente
# cosmético (sin red cae al stack del sistema). `0` la desactiva y deja la página con cero
# peticiones a terceros. Chart.js se sirve siempre desde el propio paquete.
WEB_FONTS = _env_flag("LOCAL_DELEGATE_WEB_FONTS", True)
CHARS_PER_TOKEN = 4  # aproximación del modelo LOCAL: tokens ~ chars / 4 (nunca tokens de Claude)
# REQ-023 (SDD backend-extra-params): the per-call context check counts the input at
# CHARS_PER_TOKEN / REASONING_CONTEXT_MARGIN chars per token (2), the dense worst case measured
# for code and Spanish. Fixed on purpose: a short estimate costs a 400 (REQ-015 then drops the
# sampling too); a long one only drops the reasoning of that call.
REASONING_CONTEXT_MARGIN = 2

# Respaldo de modelo para valorar una delegación sin `caller_model` (coste-api-y-cuota, REQ-008):
# `modelo` o `modelo:main|subagent`. Vacío = el declarado en `cost.py` (Opus 5.5 en subagente).
# Un valor inválido no rompe nada: se usa el declarado y la fila lo dice (`respaldo_invalido`).
# Its old name is retired with no effect since 0.38.0; `doctor` and `local_status` warn about it.
COST_FALLBACK = _env("LOCAL_DELEGATE_COST_FALLBACK", "")

# Token del puerto del daemon. Vacío = sin autenticación, que es el comportamiento histórico y
# sigue siendo el default: exigirlo siempre rompería toda instalación existente el día que se
# actualiza. Con un valor, TODO el puerto lo exige — el endpoint MCP, el dashboard y `/api/*`.
#
# Por qué hace falta, medido y no supuesto: un proxy inverso delante del daemon (`tailscale
# serve`, nginx, ngrok, un port-forward) alcanza el puerto desde la propia máquina, así que ni la
# IP de origen ni `WEB_HOST` delatan que el daemon dejó de estar en loopback. Y la protección
# anti-DNS-rebinding del SDK **no** es control de acceso: rechaza un `Host` ajeno con 421, pero se
# salta mandando `Host: 127.0.0.1:9393` a mano. Quien llegue a ese puerto puede delegar con la
# credencial del backend que tiene el daemon, así que la única defensa real es un secreto.
#
# El secreto se lee del entorno y NUNCA se escribe en un fichero de configuración: los clientes lo
# referencian por el nombre de la variable.
WEB_TOKEN = _env("LOCAL_DELEGATE_WEB_TOKEN", "").strip()

# Cuánto dura la sesión del navegador, en días. Solo afecta al navegador: los clientes MCP y el CLI
# mandan el token en cada llamada y no reciben cookie.
#
# Existe porque Basic —la única credencial que un navegador sabe mandar sin una pantalla de login—
# se olvida al cerrar la ventana y no se comparte entre `127.0.0.1` y `localhost`, así que el panel
# pedía el token varias veces al día. Un año por defecto, renovándose en cada visita: la protección
# que se pide todo el tiempo es la que se termina quitando.
#
# `0` desactiva la sesión y deja la puerta exigiendo cabecera en cada petición, que es el
# comportamiento anterior a esto.
WEB_SESSION_DAYS = max(0, _env_int("LOCAL_DELEGATE_WEB_SESSION_DAYS", 365))
WEB_SESSION_SECONDS = WEB_SESSION_DAYS * 24 * 3600


def web_auth_headers() -> dict[str, str]:
    """Cabecera para hablar con el propio daemon, vacía si no hay token configurado.

    La usan los clientes *internos* del daemon (el singleton al comprobar si ya hay uno vivo, y el
    diagnóstico al preguntarle por el backend). Sin esto, poner el token dejaría al CLI incapaz de
    hablar con su propio daemon, que es la clase de rotura que no se ve hasta que se despliega.
    """
    # El mismo token que protege el puerto (`token_source.daemon_token`): entorno y, en macOS,
    # el Llavero. Dos fuentes distintas aquí y en el daemon serían un 401 contra uno mismo.
    token, _source = keychain.credential(WEB_TOKEN, keychain.WEB_TOKEN_SERVICE)
    return {"Authorization": f"Bearer {token}"} if token else {}


# --- Auto-arranque del backend (opt-in, específico de llama-swap) -----------
AUTOSTART = _env_flag("LOCAL_DELEGATE_AUTOSTART", False)

# --- Preguntar al usuario en vez de fallar seco (elicitation del MCP) -------
# Activado por defecto: preguntar es más seguro que fallar, porque el usuario siempre puede decir
# que no y entonces el comportamiento es exactamente el de antes. El peor caso está medido y hay
# que nombrarlo: un cliente que declare la capability y NO atienda las preguntas verá cada fallo
# tardar ASK_TIMEOUT de más. Por eso el plazo es corto y la variable existe.
ASK_ENABLED = _env_flag("LOCAL_DELEGATE_ASK", True)
ASK_TIMEOUT = _env_int("LOCAL_DELEGATE_ASK_TIMEOUT", 30)

# --- Feedback de ahorro en el propio texto de respuesta (awareness) ---------
FEEDBACK_ENABLED = _env_flag("LOCAL_DELEGATE_FEEDBACK", True)


# --- Variables de la entrega por plugin y del puente de Desktop (SDD claude-plugin-and-mods) ---
# Las leen otros módulos (`claude_plugin`, `install_state`, el puente), no este; se declaran aquí
# solo para que entren en `ENVIRONMENT_VARIABLES` y la suite no las herede de quien la corre: con
# `CLAUDE_CONFIG_DIR` puesta, un `claude plugin …` lanzado por un test escribiría en esa config.
# Lista cerrada en el plan (ola 1); `LD_HOOK_READ_ENABLED`, `LD_HOOK_READ_BLOCK` y
# `LOCAL_DELEGATE_WEB_TOKEN` ya estaban declaradas más arriba.
PLUGIN_ENVIRONMENT_VARIABLES: tuple[str, ...] = (
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PLUGIN_DATA",
    "CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED",
    "WSL_DISTRO_NAME",
)
for _name in PLUGIN_ENVIRONMENT_VARIABLES:
    _read(_name)


# --- Inventario de variables de entorno -------------------------------------
# Se congela AQUÍ, al final, cuando ya se han evaluado todas las constantes de arriba y por tanto
# se ha llamado a los helpers con todos los nombres. Va después a propósito: declararla antes
# dejaría fuera lo que se lea más abajo, que es justo el fallo que esto viene a impedir.
ENVIRONMENT_VARIABLES: frozenset[str] = frozenset(_READ_VARIABLES)
