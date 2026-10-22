"""Utilidades stdlib para hooks de local-delegate.

Hay dos caminos, y la diferencia es el corazon de F1: ``emit()`` **sugiere** y ``deny()``
**bloquea**. Cuatro mediciones seguidas dijeron que sugerir no cambia la conducta —la ultima con
el aviso acertando ya el tipo de fichero—, asi que lo que tenga que delegarse se decide por regla
y no por consejo.

La telemetria es opt-in y nunca escribe prompts, comandos ni paths: solo evento, categoria,
tamaño y banda. El log se activa con ``LD_HOOK_TELEMETRY_LOG``.
"""

from __future__ import annotations

import contextlib
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
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple


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


#: El clasificador unico de lectura (REQ-019), junto a los scripts.
CLASSIFIER_FILE = "read_classifier.py"
#: Hooks cuyas reglas de lectura viven en el clasificador: su huella lo incluye, asi que cambiar una
#: regla abre un tramo nuevo de P-4 aunque el script no cambie. El clasificador no estampa eventos,
#: asi que no entra en `HASHED_HOOKS` (`tests/test_hook_boundaries.py`).
CLASSIFIER_HOOKS = frozenset({"suggest_delegate_read.py", "suggest_delegate_shell.py"})


def version_de(script: str) -> str:
    """Huella del script que REALMENTE corrio: los ocho primeros hex de su sha256.

    Es un numero de version que nadie tiene que acordarse de subir, y sobre todo no es una segunda
    fuente de verdad —el defecto que mas veces ha mordido en este repo—. Lo que hace falta saber al
    leer una medicion no es que release estaba instalada, sino si el script que corrio era el nuevo
    o el viejo, y eso lo dice el contenido.

    Para los hooks de `CLASSIFIER_HOOKS` la huella es la del script **mas** `read_classifier.py`:
    las reglas que deciden estan alli.

    Devuelve `""` si el fichero no se puede leer: un evento sin huella es peor que ninguno, pero
    romperle la lectura al usuario por un hash es mucho peor.
    """
    try:
        path = Path(script)
        data = path.read_bytes()
        if path.name in CLASSIFIER_HOOKS:
            data += (path.parent / CLASSIFIER_FILE).read_bytes()
        return hashlib.sha256(data).hexdigest()[:8]
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


# --- Decisiones del mod de lectura (`hook record-read`, plan Ola 5) ------------------------------
#
# Cuando el mod de lectura actua, el hook se aparta, pero la serie de P-4 no puede cortarse: el mod
# llama `hook record-read` y se escribe la MISMA linea que habria escrito el hook, mas `decision`
# y `source: "mod"` para poder separar las dos fuentes al medir.

#: Decision del mod -> (`suggested`, `blocked`, `reason`) de la linea del hook equivalente.
#: Los valores son los que manda `mod/read.js`. Un resumen sustituye a la lectura: cuenta como el
#: bloqueo del hook. Leer entero, cerrar el dialogo o un resumen fallido dejan pasar la lectura.
MOD_DECISIONS: dict[str, tuple[bool, bool, str]] = {
    "summarized": (True, True, "large_prose"),  # con dialogo: eligio resumir con el modelo local
    "auto_summarized": (True, True, "large_prose"),  # sin dialogo: el mod resume solo
    "read_whole": (True, False, "large_prose"),  # con dialogo: eligio leer entero
    "dismissed": (True, False, "large_prose"),  # cerro el dialogo sin elegir: la lectura pasa
    "summary_failed": (True, False, "summary_failed"),  # el resumen fallo: la lectura pasa
    "warned": (True, False, "unclassifiable"),  # via no clasificable: solo aviso
}
_MOD_DECISION_NAME = re.compile(r"^[a-z_]{1,32}$")


def mod_decision_fields(decision: object) -> dict:
    """Los campos de decision de una linea de `record-read`. Una decision desconocida se registra
    igual (con `reason: mod_decision`): perder la linea cortaria la serie en silencio."""
    name = str(decision or "")
    if name in MOD_DECISIONS:
        suggested, blocked, reason = MOD_DECISIONS[name]
    else:
        suggested, blocked, reason = False, False, "mod_decision"
        name = name if _MOD_DECISION_NAME.match(name) else "other"
    fields: dict = {"suggested": suggested, "reason": reason, "decision": name, "source": "mod"}
    if blocked:
        fields["blocked"] = True
    return fields


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
# viejo se sigue LEYENDO porque un hook o un daemon de una version anterior puede seguir instalado
# (y escribiendo). Es la copia minima de `local_delegate.legacy_names.FILE_NAMES`;
# `tests/test_hook_legacy_names.py` exige que sean iguales.
FILE_NAMES: dict[str, tuple[str, str]] = {
    "block_notes": ("local-delegate-bloqueos.jsonl", "local-delegate-blocks.jsonl"),
    "call_notes_dir": ("local-delegate-llamadas", "local-delegate-calls"),
    "health_prefix": ("local-delegate-salud-", "local-delegate-health-"),
    # En `LOG_DIR`: lo escribe solo el daemon, con el nombre nuevo, y lo lee `cooled_model`. Gana
    # el nuevo; el viejo cubre un daemon de una version anterior.
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
    # Una marca ausente, ilegible, corrupta o con campos raros no se interpreta: se ignora y se
    # vuelve a sondear (son exactamente las excepciones que puede dar leerla y parsearla).
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
        data = json.loads(marker_file.read_text(encoding="utf-8"))
        if now - float(data["ts"]) < ttl_s:
            return bool(data["ok"])

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

#: El fichero que apaga el bloqueo, en `~/.claude/`. Desde la 0.38.0 los hooks leen solo los
#: nombres nuevos: ni aplican ni detectan los viejos; de avisar se encarga `doctor`.
SWITCH_FILE_NAME = "local-delegate-block-off"


def switch_path() -> Path:
    """Donde vive el fichero que apaga el bloqueo. Fuera de `~/.claude/hooks/local-delegate/`, que
    el instalador reescribe y poda."""
    target = os.environ.get("LD_HOOK_READ_SWITCH_FILE", "").strip()
    return Path(target) if target else Path.home() / ".claude" / SWITCH_FILE_NAME


def switch_on() -> bool:
    """¿Esta puesto el fichero que apaga el bloqueo?"""
    return switch_path().exists()


def block_state() -> str:
    """`on`, `off_file` u `off_variable` (antes `encendido`, `apagado_fichero` y
    `apagado_variable`). Va en cada evento, para que una medicion sepa en que estado estaba la regla
    cuando decidio."""
    if switch_on():
        return "off_file"
    if os.environ.get("LD_HOOK_READ_BLOCK", "0").strip().lower() in TRUTHY:
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


# --- Idioma de la salida (REQ-018, REQ-019, REQ-047; plan D7) ------------------------------------
#
# La regla vive UNA sola vez y aqui: el paquete importa este modulo e `install` lo copia con los
# hooks, que no pueden importar el paquete. El guardian de aislamiento falla si `LANG`, `LC_*`,
# `LANGUAGE` o la API de idioma de Windows aparecen fuera de las tres funciones de abajo.
#
# Los avisos salen como codigos `(codigo, detalle)`, sin prosa: el texto lo pone quien los muestra
# (`doctor`, `local_status`) desde el catalogo, en el idioma que corresponda.

LANGUAGES = ("es", "en")
LANGUAGE_PREFERENCE_FILE = "language.json"
LANGUAGE_GRAMMAR = re.compile(r"^(es|en)([-_]([A-Za-z]{2}|[0-9]{3}))?$", re.IGNORECASE)
# Locales que no declaran idioma, tras quitar `.codificacion` y `@modificador` (`C.UTF-8`, `C.utf8`).
UNDECLARED_LOCALE_NAMES = frozenset({"", "c", "posix"})
_SPANISH = re.compile(r"^es(?![a-z])", re.IGNORECASE)
# Idioma primario de un LANGID de Windows (los 10 bits bajos), por si `windows_locale` no lo trae.
_WINDOWS_PRIMARY_LANGUAGES = {0x0A: "es", 0x09: "en"}

# Textos de los hooks (REQ-030/031). Los hooks no pueden importar el paquete, asi que su catalogo
# vive aqui. En ASCII (i18n, punto 1e): una consola de Windows en cp1252 convertia la raya del
# motivo del bloqueo en basura. `tests/test_i18n_parity.py` exige las mismas claves, marcadores e
# identificadores entre comillas invertidas en los dos idiomas. Las frases "y es prosa" y "de prosa
# al contexto" (y sus equivalentes en ingles) las busca `scripts/_claude_bench.py` para reconocer
# un bloqueo en un transcript: no se cambian sin cambiar alli `BLOCK_MARKERS`.
HOOK_TEXTS: dict[str, dict[str, str]] = {
    "es": {
        "prompt.mechanical": (
            "Oportunidad mecanica detectada ({category}). Antes de leer contenido grande, evalua "
            "usar la tool local_* especifica con path. Conserva en Claude cualquier parte que "
            "exija criterio, varias fuentes, tools externas o acciones de riesgo."
        ),
        "read.block": (
            "Este archivo pesa {size_kb} KB y es prosa. Pasalo por una tool local con "
            '`path="{path}"`: `local_summarize` para el contenido, `local_extract` para campos '
            "concretos, `local_translate` o `local_explain_code`. Asi no entra al contexto.\n\n"
            "Si de verdad necesitas el texto literal (lineas exactas para citar o editar), "
            "leelo por franjas con `offset` y `limit`, que no se bloquean."
        ),
        "read.suggest": (
            "{strength}: este archivo pesa {size_kb} KB. Si necesitas una transformacion global "
            "(resumen, campos, traduccion o explicacion), usa {target} para que no entre al "
            "contexto. Leelo directamente si necesitas lineas exactas para razonar o editar."
        ),
        "read.strength.strong": "Recomendacion fuerte",
        "read.strength.suggest": "Sugerencia",
        "read.target.any": "una tool local_* con path",
        "read.target.data": "local_extract con path, si lo que buscas son campos concretos",
        "shell.block": (
            "Este comando vuelca {size_kb} KB de prosa al contexto. Pasalo por una tool local "
            'con `path="{path}"`: `local_summarize` para el contenido, `local_extract` para '
            "campos concretos.\n\n"
            "Si necesitas el texto literal, pide solo el trozo que te hace falta (`sed -n`, "
            "`head -n`, `Get-Content -TotalCount`), que no se bloquean."
        ),
    },
    "en": {
        "prompt.mechanical": (
            "Mechanical task detected ({category}). Before reading large content, consider the "
            "specific local_* tool with path. Keep in Claude any part that needs judgment, "
            "several sources, external tools or risky actions."
        ),
        "read.block": (
            "This file is {size_kb} KB and it is prose. Pass it to a local tool with "
            '`path="{path}"`: `local_summarize` for the content, `local_extract` for specific '
            "fields, `local_translate` or `local_explain_code`. That way it does not enter the "
            "context.\n\n"
            "If you really need the literal text (exact lines to quote or edit), read it in "
            "ranges with `offset` and `limit`, which are not blocked."
        ),
        "read.suggest": (
            "{strength}: this file is {size_kb} KB. If you need a global transformation "
            "(summary, fields, translation or explanation), use {target} so that it does not "
            "enter the context. Read it directly if you need exact lines to reason or edit."
        ),
        "read.strength.strong": "Strong recommendation",
        "read.strength.suggest": "Suggestion",
        "read.target.any": "a local_* tool with path",
        "read.target.data": "local_extract with path, if what you need are specific fields",
        "shell.block": (
            "This command dumps {size_kb} KB of prose into the context. Pass it to a local tool "
            'with `path="{path}"`: `local_summarize` for the content, `local_extract` for '
            "specific fields.\n\n"
            "If you need the literal text, ask only for the part you need (`sed -n`, "
            "`head -n`, `Get-Content -TotalCount`), which are not blocked."
        ),
    },
}


def hook_language() -> str:
    """El idioma de los textos del hook: la regla del paquete con el mismo `LOG_DIR` que el daemon."""
    return resolve_language(log_dir()).lang


def hook_text(key: str, /, lang: str | None = None, **values: object) -> str:
    """El texto de `key` en `lang` (por defecto, el vigente), interpolado con nombre.

    Los valores se insertan tal cual: una ruta con llaves no se vuelve a interpretar.
    """
    texts = HOOK_TEXTS.get(lang or hook_language()) or HOOK_TEXTS["en"]
    return texts[key].format(**values)


class LanguageResolution(NamedTuple):
    lang: str  # "es" | "en"
    source: str  # "variable" | "preference" | "system" | "fallback"
    pref_path: Path  # el `language.json` consultado, exista o no (REQ-047)
    warnings: tuple[tuple[str, str], ...]  # (codigo, detalle)
    # Con origen "preference": el origen que `install` guardo en `language.json` ("variable",
    # "system" o "fallback"), o None si no lo guardo. `doctor` lo usa para el remedio de D11.
    stored_source: str | None = None


def parse_language(value: str | None) -> str | None:
    """Un valor de REQ-019 (`es`, `en_US`, `es-419`...) como `es`/`en`; `None` si no es valido."""
    if value is None:
        return None
    match = LANGUAGE_GRAMMAR.match(value.strip())
    return match.group(1).lower() if match else None


def resolve_language(
    data_dir: Path,
    env: Mapping[str, str] = os.environ,
    platform: str = sys.platform,
    ui_lang: str | None = None,
) -> LanguageResolution:
    """El idioma vigente del proceso: variable, preferencia, sistema y reserva, en ese orden."""
    pref_path = Path(data_dir) / LANGUAGE_PREFERENCE_FILE
    warnings: list[tuple[str, str]] = []

    raw = env.get("LOCAL_DELEGATE_LANG", "")
    if raw.strip():
        lang = parse_language(raw)
        if lang:
            return LanguageResolution(lang, "variable", pref_path, tuple(warnings))
        warnings.append(("invalid_variable", raw))

    try:
        data = json.loads(pref_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        warnings.append(("unreadable_preference", str(pref_path)))
    else:
        stored = data.get("lang") if isinstance(data, dict) else None
        lang = parse_language(stored) if isinstance(stored, str) else None
        if lang:
            source = data.get("source")
            stored = source if source in ("variable", "system", "fallback") else None
            return LanguageResolution(lang, "preference", pref_path, tuple(warnings), stored)
        warnings.append(("invalid_preference", str(pref_path)))

    declared = _system_language(env, platform, ui_lang)
    if declared is None:
        return LanguageResolution("en", "fallback", pref_path, tuple(warnings))
    lang = "es" if _SPANISH.match(declared) else "en"
    return LanguageResolution(lang, "system", pref_path, tuple(warnings))


def _system_language(env: Mapping[str, str], platform: str, ui_lang: str | None) -> str | None:
    """Paso 3 de REQ-018: lo que declara el sistema, o `None` si no declara nada o falla."""
    if platform == "win32":
        # En Windows manda el idioma de la INTERFAZ; `LANG` y `LC_*` los ponen Git Bash y MSYS.
        return ui_lang if ui_lang is not None else _windows_ui_language()
    effective = ""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        effective = env.get(name, "").strip()
        if effective:
            break
    base = effective.split(".", 1)[0].split("@", 1)[0].strip().lower()
    if base in UNDECLARED_LOCALE_NAMES:
        return None
    for item in env.get("LANGUAGE", "").split(":"):
        if item.strip():
            return item.strip()
    return effective


def _windows_ui_language(kernel32: object = None) -> str | None:
    """Idioma de la interfaz de Windows (`GetUserDefaultUILanguage`), nunca el formato regional.

    `kernel32` solo existe para que los tests inyecten uno falso. Cualquier fallo da `None`.
    """
    try:
        import locale

        if kernel32 is None:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        langid = int(kernel32.GetUserDefaultUILanguage())  # type: ignore[attr-defined]
        return locale.windows_locale.get(langid) or _WINDOWS_PRIMARY_LANGUAGES.get(langid & 0x3FF)
    except Exception:
        return None


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


#: Prefix of the session key, so the key is never the plain hash of an id someone else hashes.
SESSION_KEY_PREFIX = "local-delegate-session:"


def session_key(session_id: object) -> str | None:
    """One-way key of a Claude Code session (claude-plugin-and-mods, REQ-017), or `None`.

    The note and the log line carry this key and never the id itself (REQ-003 and REQ-072 of
    coste-api-y-cuota). `/api/stats?session=<id>` hashes the id it receives the same way, so the
    mod's status line can ask for the savings of its own session.
    """
    if not isinstance(session_id, str) or not session_id:
        return None
    digest = hashlib.sha256(f"{SESSION_KEY_PREFIX}{session_id}".encode())
    return digest.hexdigest()[:32]


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
            "session_key": session_key(hook_input.get("session_id")),
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
