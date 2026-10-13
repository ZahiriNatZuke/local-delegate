"""Utilidades stdlib para hooks de local-delegate.

Hay dos caminos, y la diferencia es el corazon de F1: ``emit()`` **sugiere** y ``deny()``
**bloquea**. Cuatro mediciones seguidas dijeron que sugerir no cambia la conducta —la ultima con
el aviso acertando ya el tipo de fichero—, asi que lo que tenga que delegarse se decide por regla
y no por consejo.

La telemetria es opt-in y nunca escribe prompts, comandos ni paths: solo evento, categoria,
tamaño y banda. El log se activa con ``LD_HOOK_TELEMETRY_LOG``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path


def enabled() -> bool:
    """Interruptor del EXPERIMENTO, no el de encendido de un hook. La diferencia importa.

    `LD_HOOK_ENABLED=0` es lo que pone una sesion en rama baseline de un A/B: ni sugiere ni
    registra, para que el log de la rama piloto sea solo del piloto. Por eso apaga tambien la
    telemetria, que en cualquier otro contexto seria un error.

    **Solo puede apagar, nunca encender.** Que un hook este activo lo decide el registro
    (`settings.json`), y de ahi no se sale: cuando la unica puerta era una variable de entorno,
    `install --enable-read-hook` registro el script sin ponerla y el hook quedo instalado e
    inerte, en silencio. Esa es la historia que hay detras de `is_enabled()` en
    `suggest_delegate_read.py`, y la razon de que ningun hook nuevo deba mirar aqui para saber
    si nacio encendido.
    """
    return os.environ.get("LD_HOOK_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def new_id() -> str:
    """Identificador corto de un aviso o un bloqueo, para poder cruzarlo con lo que pase despues.

    Es lo que hace medible el «aceptado» de la telemetria: el hook y el servidor MCP son procesos
    distintos que escriben en ficheros distintos, y hasta ahora la unica forma de saber si un aviso
    acabo en delegacion era cruzarlos a mano.
    """
    return uuid.uuid4().hex[:12]


def version_de(script: str) -> str:
    """Huella del script que REALMENTE corrio: los ocho primeros hex de su sha256.

    Es un numero de version que nadie tiene que acordarse de subir, y sobre todo no es una segunda
    fuente de verdad —el defecto que mas veces ha mordido en este repo—. Lo que hace falta saber al
    leer una medicion no es que release estaba instalada, sino si el script que corrio era el nuevo
    o el viejo, y eso lo dice el contenido.

    Devuelve `""` si el fichero no se puede leer: un evento sin huella es peor que ninguno, pero
    romperle la lectura al usuario por un hash es mucho peor.
    """
    try:
        return hashlib.sha256(Path(script).read_bytes()).hexdigest()[:8]
    except OSError:
        return ""


def context_of(payload: dict, script: str) -> dict:
    """Los campos que lleva TODO evento: que script corrio y en que sesion.

    Sin esto una medicion no se puede leer: el 2026-09-09 catorce lecturas se comportaron con el
    umbral viejo despues de cambiarlo, porque una sesion ya abierta hereda el entorno del lanzador,
    y la muestra mezclo dos politicas sin que se notara.

    La hora de arranque de la sesion no se inventa aqui: con ``session_id`` en cada evento, el
    primer evento de esa sesion en el log ya dice cuando empezo, y agrupar por sesion evita mezclar
    dos politicas en la misma muestra.
    """
    return {"version": version_de(script), "session_id": str(payload.get("session_id") or "")}


def record(event: str, **metadata: object) -> None:
    if not enabled():
        return
    destination = os.environ.get("LD_HOOK_TELEMETRY_LOG", "").strip()
    if not destination:
        return
    payload = {"ts": datetime.now(UTC).isoformat(), "event": event, **metadata}
    if DEPRECATED_SEEN:
        # Nombres viejos que esta invocacion leyo (REQ-003). Solo viaja con la telemetria
        # encendida; `doctor` los cuenta desde la cola de este mismo fichero.
        payload["deprecated_names"] = sorted(DEPRECATED_SEEN)
    try:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        # La telemetría es best-effort y corre dentro de un hook del agente: si el destino no se
        # puede crear o escribir (permisos, disco lleno, ruta inválida en LD_HOOK_TELEMETRY_LOG),
        # perder una línea de log es preferible a romperle la operación al usuario.
        pass


def emit(event: str, context: str, **metadata: object) -> None:
    """Camino CONSULTIVO: le pasa un texto al modelo y el modelo hace lo que quiera con el."""
    if not enabled():
        return
    record(event, suggested=True, **metadata)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )


def deny(event: str, message: str, **metadata: object) -> None:
    """Camino que BLOQUEA: la tool no llega a ejecutarse y el modelo lee ``message``.

    El contrato es el de ``PreToolUseHookSpecificOutput``: ``permissionDecision`` acepta
    ``allow``, ``deny``, ``ask`` y ``defer``, y ``permissionDecisionReason`` —aqui ``message``— es
    el texto que ve quien recibe el bloqueo. Se llama asi, y no ``reason``, porque ``reason`` es el
    campo con el que la telemetria de los hooks etiqueta cada decision y los dos viajan juntos
    (antes ``motivo``; ver `FILE_NAMES` y `legacy_names`). Ese texto **tiene que nombrar la
    salida**: una regla que dice «no» sin decir por donde se pasa es una regla que se acaba
    apagando.

    No se usa ``updatedInput``, que seria la forma de reescribir la llamada en vez de rechazarla:
    el permiso del usuario se evalua sobre la entrada original, asi que cambiarla por debajo
    ejecuta algo distinto de lo que se autorizo. Esa puerta se cerro con datos en la 0.27.0.
    """
    if not enabled():
        return
    record(event, suggested=True, blocked=True, **metadata)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": message,
                }
            },
            ensure_ascii=False,
        )
    )


# --- Nombres en disco (REQ-012) -----------------------------------------------------------------
#
# `(viejo, nuevo)` de cada fichero que comparten los hooks y el daemon. Se ESCRIBE solo el nuevo; el
# viejo se sigue LEYENDO porque un hook de una version anterior puede seguir instalado (y
# escribiendo) y porque el interruptor viejo apaga el bloqueo mientras viva su alias. Es la copia minima de
# `local_delegate.legacy_names.FILE_NAMES`; `tests/test_hook_legacy_names.py` exige que sean iguales.
FILE_NAMES: dict[str, tuple[str, str]] = {
    "switch_file": ("local-delegate-bloqueo-apagado", "local-delegate-block-off"),
    "block_notes": ("local-delegate-bloqueos.jsonl", "local-delegate-blocks.jsonl"),
    "call_notes_dir": ("local-delegate-llamadas", "local-delegate-calls"),
    "health_prefix": ("local-delegate-salud-", "local-delegate-health-"),
    # En `LOG_DIR`: lo escribe el daemon (los dos, mientras viva su `legacy_write`) y lo lee
    # `cooled_model`. Gana el nuevo; el viejo cubre un daemon de una version anterior.
    "cooldown_state": ("enfriamiento.json", "cooldown.json"),
}

#: Claves viejas -> nuevas del estado de enfriamiento. Copia de
#: `local_delegate.legacy_names.FORMATS["cooldown_state"]["keys"]` (mismo test de igualdad).
COOLDOWN_STATE_KEYS: dict[str, str] = {
    "fallos": "failures",
    "espera_s": "wait_s",
    "hasta": "until",
    "reentradas": "reentries",
}


# --- Salud del backend ------------------------------------------------------------------------
#
# Una regla que bloquea una lectura tiene que saber si hay a donde delegar: si el backend local no
# responde, bloquear deja al agente sin forma de leer el fichero, y eso se apaga el primer dia.
#
# El dato NO puede salir de las delegaciones anteriores, aunque seria lo barato. Seria un circulo
# cerrado: sin delegaciones no hay marca fresca, sin marca fresca no se bloquea, y sin bloqueo no
# hay delegaciones. Con adopcion cero medida cuatro veces, la regla no arrancaria nunca. Asi que el
# hook se lo pregunta el mismo al backend, y guarda la respuesta un rato para no pagarlo en cada
# lectura.


def _health_path() -> Path:
    """Un fichero por endpoint, no uno global.

    Con uno solo, la marca de un backend valdria para otro: basta cambiar
    `LOCAL_DELEGATE_BASE_URL` —o correr un test contra un puerto muerto— para heredar el «esta
    vivo» del anterior. Lo caza un test de instalacion que apuntaba a un puerto donde no hay nadie
    y recibia un bloqueo, porque la marca del backend de verdad seguia fresca.
    """
    base = os.environ.get("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9292/v1")
    digest = hashlib.sha256(base.encode("utf-8", "replace")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"{FILE_NAMES['health_prefix'][1]}{digest}.json"


def _probe(timeout_s: float) -> bool:
    """¿Contesta alguien en el endpoint? Un GET a /models con un plazo muy corto.

    La pregunta es si el backend **esta escuchando**, no si nos autoriza a nosotros: quien delega
    es el servidor MCP, que si tiene la credencial. Por eso un 401 o un 403 cuentan como «si
    esta»: alguien contesto. El hook casi nunca tiene la clave —la tiene el lanzador del daemon,
    y el hook hereda el entorno del cliente—, asi que tratar el 401 como «no hay backend» dejaria
    el bloqueo permanentemente apagado en cualquier maquina con el backend protegido. Medido en
    vivo: aqui `GET /v1/models` sin credencial responde 401, y el backend estaba perfectamente.

    Solo es «no esta» lo que no llega a haber respuesta: conexion rechazada, plazo agotado, o una
    URL que ni siquiera se puede construir.
    """
    base = os.environ.get("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9292/v1").rstrip("/")
    api_key = os.environ.get("LOCAL_DELEGATE_API_KEY", "").strip()
    try:
        # El `Request` se construye DENTRO del try: con una `LOCAL_DELEGATE_BASE_URL` mal escrita
        # lanza `ValueError` en el constructor, no al abrir, y eso reventaria el hook entero y con
        # el la lectura del usuario.
        request = urllib.request.Request(f"{base}/models", method="GET")
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status < 500
    except urllib.error.HTTPError:
        # 401, 403, 404... da igual cual: hubo respuesta, luego hay alguien escuchando.
        return True
    except Exception:
        # Cualquier cosa: conexion rechazada, plazo agotado, 401, una URL invalida en la variable.
        # Ninguna es motivo para romperle la lectura al usuario, y todas significan lo mismo aqui.
        return False


def backend_available(*, ttl_s: float = 60.0, timeout_s: float = 0.3, marker: Path | None = None):
    """¿Hay a donde delegar ahora mismo? Ante la duda, **False**, que es lo que no bloquea.

    La respuesta se cachea ``ttl_s`` segundos en un fichero, asi que el sondeo se paga como mucho
    una vez por minuto y no una vez por lectura. Una marca ilegible, corrupta o vieja no se
    interpreta: se vuelve a preguntar.
    """
    marker_file = marker or _health_path()
    now = time.time()
    try:
        data = json.loads(marker_file.read_text(encoding="utf-8"))
        if now - float(data["ts"]) < ttl_s:
            return bool(data["ok"])
    except (OSError, ValueError, KeyError, TypeError):
        pass

    available = _probe(timeout_s)
    try:
        marker_file.write_text(json.dumps({"ts": now, "ok": available}), encoding="utf-8")
    except OSError:
        # Sin cache se sondea mas a menudo; es lento, no incorrecto.
        pass
    return available


# --- Estado del bloqueo (REQ-F1-11) ---------------------------------------------------------------
#
# El apagado en caliente no puede ser una variable de entorno: una sesion abierta hereda el entorno
# del lanzador (medido: catorce lecturas con el umbral viejo), asi que el unico freno que funciona
# sin cerrar nada es algo que el hook lea en cada invocacion y que el usuario pueda tocar a mano.
# Un fichero cumple las dos cosas. La variable sigue siendo la que ENCIENDE; el fichero gana y apaga.

TRUTHY = {"1", "true", "yes", "on"}

# Nombres viejos que los hooks siguen leyendo, como `(kind, old, new)`. Es la copia minima del
# registro `local_delegate.deprecations` (los hooks no importan el paquete);
# `tests/test_deprecations.py` exige que sea igual a `deprecations.hook_names()`.
DEPRECATED_HOOK_NAMES = (
    ("env_var", "LD_HOOK_READ_BLOQUEAR", "LD_HOOK_READ_BLOCK"),
    ("env_var", "LD_HOOK_READ_INTERRUPTOR", "LD_HOOK_READ_SWITCH_FILE"),
    ("switch_file", "local-delegate-bloqueo-apagado", "local-delegate-block-off"),
)

# Nombres viejos leidos con valor en esta invocacion (REQ-003).
DEPRECATED_SEEN: set[str] = set()


def env_alias(new: str, old: str, default: str = "") -> str:
    """Lee una variable renombrada: gana la nueva; si solo esta la vieja, vale la vieja y se anota
    en `DEPRECATED_SEEN`. Es el equivalente de `config._env_alias` para los hooks."""
    value = os.environ.get(new)
    if value is not None:
        return value
    old_value = os.environ.get(old)
    if old_value is not None:
        DEPRECATED_SEEN.add(old)
        return old_value
    return default


def switch_path() -> Path:
    """Donde vive el fichero que apaga el bloqueo. Fuera de `~/.claude/hooks/local-delegate/`, que
    el instalador reescribe y poda."""
    target = env_alias("LD_HOOK_READ_SWITCH_FILE", "LD_HOOK_READ_INTERRUPTOR").strip()
    return Path(target) if target else Path.home() / ".claude" / FILE_NAMES["switch_file"][1]


def legacy_switch_path() -> Path:
    """El interruptor con su nombre viejo, que sigue apagando mientras viva su alias (REQ-012)."""
    return Path.home() / ".claude" / FILE_NAMES["switch_file"][0]


def switch_on() -> bool:
    """¿Esta puesto el fichero que apaga el bloqueo? El nuevo o, si no se eligio otra ruta, el
    viejo; el viejo se anota en `DEPRECATED_SEEN` para que `doctor` pueda avisar."""
    if switch_path().exists():
        return True
    configured = env_alias("LD_HOOK_READ_SWITCH_FILE", "LD_HOOK_READ_INTERRUPTOR").strip()
    if not configured and legacy_switch_path().exists():
        DEPRECATED_SEEN.add(FILE_NAMES["switch_file"][0])
        return True
    return False


def block_state() -> str:
    """`on`, `off_file` u `off_variable` (antes `encendido`, `apagado_fichero` y
    `apagado_variable`). Va en cada evento, para que una medicion sepa en que estado estaba la regla
    cuando decidio."""
    if switch_on():
        return "off_file"
    if env_alias("LD_HOOK_READ_BLOCK", "LD_HOOK_READ_BLOQUEAR", "0").strip().lower() in TRUTHY:
        return "on"
    return "off_variable"


# --- El modelo del resumen en enfriamiento (REQ-F1-10) -------------------------------------------
#
# Bloquear hacia un modelo que el servidor no va a llamar deja al agente peor que antes. El estado lo
# escribe el servidor en `LOG_DIR/cooldown.json`; el hook es stdlib y no puede importar `config`,
# asi que lleva su copia de los defectos, y `tests/test_f1_conformance.py` la ata a `config.py`. Con
# un `LOCAL_DELEGATE_MODEL_*` distinto en el lanzador del daemon y no en el cliente, el hook mira el
# defecto: ante la duda no se entera del enfriamiento y sigue bloqueando, como antes de esta guarda.

DEFAULT_MODELS = {"long": "gemma4-26b-a4b", "mechanical": "gemma3-4b"}
LONG_THRESHOLD_CHARS = 6000


def log_dir() -> Path:
    """`LOG_DIR` como lo resuelve `config.py` (`platformdirs.user_data_dir`, sin autor)."""
    target = os.environ.get("LOCAL_DELEGATE_LOG_DIR", "").strip()
    if target:
        return Path(target)
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            / "local-delegate"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "local-delegate"
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(base) if base else Path.home() / ".local" / "share") / "local-delegate"


def summary_model(size: int) -> str:
    """El modelo al que iria `local_summarize` con un fichero de `size` bytes (`_role_for_size`)."""
    try:
        threshold = int(
            os.environ.get("LOCAL_DELEGATE_LONG_INPUT_CHARS", "").strip() or LONG_THRESHOLD_CHARS
        )
    except ValueError:
        threshold = LONG_THRESHOLD_CHARS
    role = "long" if size > threshold else "mechanical"
    return (
        os.environ.get(f"LOCAL_DELEGATE_MODEL_{role.upper()}", "").strip() or DEFAULT_MODELS[role]
    )


def _cooldown_until(name: str, model: str, key: str) -> object:
    """El vencimiento del modelo en un fichero de estado, o None si no se puede leer."""
    try:
        data = json.loads((log_dir() / name).read_text(encoding="utf-8"))
        return data[model][key]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cooled_model(model: str) -> bool:
    """¿Esta ese modelo enfriandose ahora? Ante cualquier duda, False: la guarda solo puede quitar
    un bloqueo con un dato legible y vigente, nunca por un fichero roto.

    Lee `cooldown.json` y, si no existe, `enfriamiento.json` con su clave vieja (un daemon de una
    version anterior). Si existe el nuevo, manda el nuevo aunque no tenga el modelo."""
    old_name, new_name = FILE_NAMES["cooldown_state"]
    new_key = COOLDOWN_STATE_KEYS["hasta"]
    if (log_dir() / new_name).exists():
        until = _cooldown_until(new_name, model, new_key)
    else:
        until = _cooldown_until(old_name, model, "hasta")
    try:
        return isinstance(until, (int, float)) and float(until) > time.time()
    except (OverflowError, ValueError):
        return False


# --- Cruce entre el bloqueo y la delegacion que venga despues -----------------------------------
#
# El hook y el servidor MCP son procesos distintos que escriben en ficheros distintos, asi que
# hasta ahora «cuantos avisos acabaron en delegacion» solo se podia responder cruzando los dos
# logs a mano. Aqui el hook deja una nota con el identificador del bloqueo y una huella de la
# ruta, y el servidor la recoge cuando le llega una tool con ese mismo `path`.
#
# El identificador NO viaja por el agente: pedirle que lo pase seria depender de que obedezca, y
# lo que se quiere medir es justamente cuanto obedece.
#
# Se guarda la HUELLA de la ruta, no la ruta: este fichero hereda la regla de la telemetria de
# hooks, que nunca escribe rutas ni contenido.

#: Cuantas notas se conservan. Son el rastro de los ultimos bloqueos, no un historial.
MAX_NOTES = 200


def path_digest(path: str) -> str:
    """Huella estable de una ruta, para poder cruzarla sin guardarla.

    Normaliza may/minusculas y separadores porque Windows da la misma ruta de varias formas y el
    hook la recibe del cliente mientras que el servidor la recibe del agente.
    """
    normal = os.path.normcase(os.path.abspath(path))
    return hashlib.sha256(normal.encode("utf-8", "replace")).hexdigest()[:16]


def block_notes_path() -> Path:
    return Path(tempfile.gettempdir()) / FILE_NAMES["block_notes"][1]


def legacy_block_notes_path() -> Path:
    """Las notas que escribe un hook de una version anterior: el daemon las lee tambien."""
    return Path(tempfile.gettempdir()) / FILE_NAMES["block_notes"][0]


def record_block(block_id: str, path: str, notes: Path | None = None) -> None:
    """Deja la nota del bloqueo. Best-effort: si falla, se pierde la medicion, no la sesion."""
    notes_file = notes or block_notes_path()
    line = json.dumps(
        {"id": block_id, "sha": path_digest(path), "ts": time.time()},
        ensure_ascii=False,
    )
    try:
        previous = notes_file.read_text(encoding="utf-8").splitlines()[-(MAX_NOTES - 1) :]
    except OSError:
        previous = []
    try:
        notes_file.write_text("\n".join([*previous, line]) + "\n", encoding="utf-8")
    except OSError:
        # Best-effort a proposito: perder esta nota cuesta una correlacion en la medicion;
        # romperle la lectura al usuario por no poder escribir un fichero cuesta mucho mas.
        pass


# --- Notas de atribucion: quien pidio cada delegacion (coste-api-y-cuota, REQ-002) ---------------
#
# El hook `record_call.py` (antes `anotar_llamada.py`) deja, por cada `tools/call` de
# local-delegate, una nota con lo que solo trae la entrada del hook (`agent_id`, `agent_type`,
# `effort`) y el `transcript_path`, que es donde el servidor busca despues el modelo. El servidor la recoge por `tool_use_id`
# (`attribution.read_note`): el formato vive en dos sitios y lo ata un test de ida y vuelta.
#
# UNA nota por fichero, y no un fichero con todas como el de los bloqueos: los subagentes llaman en
# paralelo, y dos hooks que reescriben el mismo fichero se pisan. Cada nota se escribe en un
# temporal del mismo directorio y se mueve con `os.replace`, que es atomico: el servidor nunca lee
# una a medias.
#
# Guarda `transcript_path` aunque la telemetria de hooks nunca escribe rutas: esto no es
# telemetria, vive en el temporal y caduca a los diez minutos.

#: Pasado este rato una nota ya no cuenta (REQ-003) y el hook la borra.
NOTE_TTL_S = 600.0

#: Forma de un `tool_use_id`. Se valida ANTES de construir la ruta: el id acaba en un nombre de
#: fichero, y uno con `..` o separadores escribiria fuera del directorio.
TOOL_USE_ID_PATTERN = re.compile(r"^toolu_[A-Za-z0-9_-]{1,64}$")


def call_notes_dir() -> Path:
    """Junto a `block_notes_path()`: el temporal del usuario, que comparten el hook y el daemon."""
    return Path(tempfile.gettempdir()) / FILE_NAMES["call_notes_dir"][1]


def legacy_call_notes_dir() -> Path:
    """Donde deja sus notas un hook `anotar_llamada.py` de una version anterior."""
    return Path(tempfile.gettempdir()) / FILE_NAMES["call_notes_dir"][0]


def _effort_of(hook_input: dict) -> str | None:
    """`effort.level` de la entrada del hook. NUNCA `CLAUDE_EFFORT`: esa variable se hereda del
    proceso padre y no dice el esfuerzo de esta llamada (medido: `--effort low` y el hook vio
    `high`)."""
    effort = hook_input.get("effort")
    level = effort.get("level") if isinstance(effort, dict) else None
    return level if isinstance(level, str) and level else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _prune_notes(directory: Path, now: float) -> None:
    """Borra, best-effort, las notas que ya no cuentan. Sin esto el directorio solo creceria."""
    try:
        stale = [p for p in directory.iterdir() if now - p.stat().st_mtime > NOTE_TTL_S]
    except OSError:
        return
    for stale_note in stale:
        try:
            stale_note.unlink()
        except OSError:
            pass  # otro hook la borro antes, o esta abierta: se intentara la proxima vez


def record_call(hook_input: dict, directory: Path | None = None) -> bool:
    """Escribe la nota de esta llamada. Devuelve si la escribio. Nunca lanza."""
    try:
        tool_use_id = hook_input.get("tool_use_id")
        if not isinstance(tool_use_id, str) or not TOOL_USE_ID_PATTERN.match(tool_use_id):
            return False
        target = directory or call_notes_dir()
        now = time.time()
        note = {
            "tool_use_id": tool_use_id,
            "ts": now,
            "agent_id": _text(hook_input.get("agent_id")),
            "agent_type": _text(hook_input.get("agent_type")),
            "effort": _effort_of(hook_input),
            "transcript_path": _text(hook_input.get("transcript_path")),
        }
        target.mkdir(parents=True, exist_ok=True)
        descriptor, tmp_name = tempfile.mkstemp(dir=target, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(note, stream, ensure_ascii=False)
            os.replace(tmp_name, target / f"{tool_use_id}.json")
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                # Limpieza de mejor esfuerzo: un hook nunca lanza, y el fallo ya se comunica
                # devolviendo False justo debajo.
                pass
            return False
        _prune_notes(target, now)
        return True
    except Exception:
        # Best-effort a proposito: perder la nota deja la delegacion para el relleno; romperle la
        # llamada al usuario por un fichero temporal costaria mucho mas.
        return False
