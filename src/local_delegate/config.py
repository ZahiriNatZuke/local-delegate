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
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_dir

APP_NAME = "local-delegate"


# Nombres de todas las variables de entorno que este módulo consulta. NO se escribe a mano: la
# alimentan los cuatro helpers de abajo al ser llamados, así que no puede quedarse corta cuando se
# añada una opción nueva. La suite la usa para aislarse del entorno de quien la corre (ver
# `tests/conftest.py`): antes de esto, tener `LOCAL_DELEGATE_WEB_TOKEN` puesta —lo normal en una
# máquina con el daemon instalado— hacía fallar cuatro tests del daemon con 401 en vez de 200.
_VARIABLES_LEIDAS: set[str] = set()


def _leer(name: str) -> str | None:
    """Única puerta a `os.environ` de este módulo: lee y deja constancia del nombre."""
    _VARIABLES_LEIDAS.add(name)
    return os.environ.get(name)


def _env(name: str, default: str) -> str:
    raw = _leer(name)
    return default if raw is None else raw


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = _leer(name)
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
# Backpressure del proceso MCP. En el daemon singleton este límite se comparte entre
# todos los clientes HTTP; llama-swap sigue siendo la autoridad del routing/VRAM.
MAX_CONCURRENT_REQUESTS = max(1, _env_int("LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS", 2))


def auth_headers() -> dict[str, str]:
    """Headers del backend sin registrar ni exponer el secreto configurado."""
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


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


# --- Log de uso/ahorro (JSONL) ----------------------------------------------
# Por defecto se rota por mes: usage-YYYYMM.jsonl dentro de LOG_DIR. Si el usuario fija
# LOCAL_DELEGATE_LOG (archivo explícito), se usa ESE archivo tal cual, sin rotación —
# compatibilidad con instalaciones que ya apuntaban a una ruta fija.
def _default_log_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def _default_log() -> Path:
    return _default_log_dir() / "usage.jsonl"


_log_env = _leer("LOCAL_DELEGATE_LOG")
USAGE_LOG: Path = Path(_log_env) if _log_env else _default_log()  # legado (sin rotación) o default
LOG_ROTATION_ENABLED: bool = _log_env is None

_log_dir_env = _leer("LOCAL_DELEGATE_LOG_DIR")
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
MODEL_LONG = _env("LOCAL_DELEGATE_MODEL_LONG", "llama31-8b")  # documentos largos (ctx amplio)
MODEL_CODE = _env("LOCAL_DELEGATE_MODEL_CODE", "qwen25-coder-14b")  # código / boilerplate
MODEL_FAST = _env("LOCAL_DELEGATE_MODEL_FAST", "qwen35-2b")  # ultrarrápido / trivial
# Rol de visión (imagen->texto). Fuera de ALLOWED_MODELS a propósito: ese set es para el
# escape genérico local_delegate (texto->texto puro), que no arma payload multimodal.
MODEL_VISION = _env("LOCAL_DELEGATE_MODEL_VISION", "qwen3-vl-8b")
ALLOWED_MODELS: set[str] = {MODEL_MECHANICAL, MODEL_LONG, MODEL_CODE, MODEL_FAST}

# Umbral para elegir el modelo "largo" vs "mecánico" en tools que enrutan por tamaño.
LONG_INPUT_CHARS = _env_int("LOCAL_DELEGATE_LONG_INPUT_CHARS", 6000)

# Tope de entrada por modelo (evita desbordar el ctx del backend).
_MAX_CHARS_DEFAULT = 20000
MAX_CHARS: dict[str, int] = {
    MODEL_MECHANICAL: _env_int("LOCAL_DELEGATE_MAX_CHARS_MECHANICAL", 20000),
    MODEL_LONG: _env_int("LOCAL_DELEGATE_MAX_CHARS_LONG", 48000),
    MODEL_CODE: _env_int("LOCAL_DELEGATE_MAX_CHARS_CODE", 20000),
    MODEL_FAST: _env_int("LOCAL_DELEGATE_MAX_CHARS_FAST", 12000),
}


def max_chars_for(model: str) -> int:
    """Tope de caracteres de entrada para un modelo (default si no está en el catálogo)."""
    return MAX_CHARS.get(model, _MAX_CHARS_DEFAULT)


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
# Tipografía de marca desde Google Fonts: único recurso externo del dashboard y puramente
# cosmético (sin red cae al stack del sistema). `0` la desactiva y deja la página con cero
# peticiones a terceros. Chart.js se sirve siempre desde el propio paquete.
WEB_FONTS = _env_flag("LOCAL_DELEGATE_WEB_FONTS", True)
CHARS_PER_TOKEN = 4  # aproximación: tokens ~ chars / 4

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
    return {"Authorization": f"Bearer {WEB_TOKEN}"} if WEB_TOKEN else {}


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


# --- Inventario de variables de entorno -------------------------------------
# Se congela AQUÍ, al final, cuando ya se han evaluado todas las constantes de arriba y por tanto
# se ha llamado a los helpers con todos los nombres. Va después a propósito: declararla antes
# dejaría fuera lo que se lea más abajo, que es justo el fallo que esto viene a impedir.
VARIABLES_DE_ENTORNO: frozenset[str] = frozenset(_VARIABLES_LEIDAS)
