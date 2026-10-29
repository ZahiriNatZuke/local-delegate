"""local-delegate — servidor MCP stdio.

Expone un endpoint LLM local OpenAI-compatible (llama-swap, Ollama, LM Studio, vLLM…)
como herramientas texto->texto para que Claude Code delegue pasos acotados (resumir,
clasificar, extraer, boilerplate) y conserve cuota de la suscripción. Los modelos locales
NO usan tool-calling: el server arma el prompt + guardrails, hace POST al endpoint y
devuelve SOLO texto.

summarize/extract/… pueden leer el archivo del lado del servidor (vía 'path') para que el
input grande NUNCA entre al contexto de Claude.
"""

from __future__ import annotations

import ast
import base64
import contextvars
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection, Generator, Iterable, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
from filelock import FileLock, Timeout
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import (
    attribution,
    autostart,
    backend_params,
    cancellation,
    chains,
    clients,
    config,
    cooldown,
    cost,
    failures,
    i18n,
    json_state,
    legacy_names,
    lint_patterns,
    llamaswap_api,
    llamaswap_config,
    matrix,
    pace,
    questions,
    sections,
    test_windows,
    topology,
    turn,
)
from .version import get_version

# --- Versión del paquete ------------------------------------------------------
# Vive en `version.py`, un módulo hoja que no importa nada del paquete, y este alias se conserva
# porque `daemon`, `web/metrics` y los tests ya lo llaman por aquí. El porqué de sacarlo está en
# el docstring de aquel: el `--version` del CLI necesitaba el mismo dato, y `cli` importando
# `server` cerraba un ciclo (`server.main()` importa `cli` en cuanto hay argumentos).
_get_version = get_version

#: Prefijo de contrato de los errores (no se traduce, REQ-023).
ERROR_PREFIX = "[local-delegate error] "
#: Marcadores de aviso, respaldo y entrada truncada (REQ-010, desde la 0.36.0): valores de
#: máquina en inglés que no cambian con el idioma; el texto que va DETRÁS sí sale del catálogo.
WARNING_MARKER = sections.WARNING_MARKER
FALLBACK_MARKER = "[local-delegate fallback: "
INPUT_TRUNCATED_MARKER = "[local-delegate: input truncated — "


def _machine(value: float, decimals: int | None = 0) -> str:
    """Una cifra de una salida MCP: sin separador de miles y con punto decimal (REQ-026)."""
    return i18n.format_number(value, decimals, machine=True)


# `version=` declara la versión **del paquete**. Sin ella el SDK reporta la suya propia en el
# handshake `initialize`, de modo que un cliente no tenía forma de saber qué local-delegate corre.
#: REQ-027: la descripción del servidor y los títulos de las tools solo en inglés, literales y
#: fuera del catálogo: no dependen de `LOCAL_DELEGATE_LANG` (los ve el cliente MCP, que además
#: los cachea por sesión).
SERVER_DESCRIPTION = (
    "Delegates mechanical text and image tasks to a local model through an "
    "OpenAI-compatible endpoint, to save subscription quota."
)
TOOL_TITLES: dict[str, str] = {
    "local_summarize": "Summarize text or file",
    "local_classify": "Classify into one label",
    "local_extract": "Extract fields as JSON",
    "local_boilerplate": "Generate boilerplate code",
    "local_delegate": "Delegate a generic task",
    "local_lint_summary": "Summarize lint or test output",
    "local_commit_msg": "Draft a commit message",
    "local_translate": "Translate text or file",
    "local_explain_code": "Explain code",
    "local_describe_image": "Describe an image",
    "local_status": "Local backend diagnostics",
}

mcp = MCPServer(
    "local-delegate",
    title="Local Delegate",
    description=SERVER_DESCRIPTION,
    website_url="https://github.com/ZahiriNatZuke/local-delegate",
    version=_get_version(),
    # El SDK los aplica outermost-first, y el orden es deliberado: «observar primero, habilitar
    # después». Hoy son independientes —el observador solo lee, el otro solo deja el contexto al
    # alcance de las capas de abajo—, pero se fija para que nadie lo cambie creyendo que da igual.
    # El de cancelación (`cancellation.middleware`) va el último, pegado al handler; se añade
    # junto a `_log_cancelled`, que es quien apunta la llamada cancelada.
    middleware=[clients.observe_client, questions.remember_context],
)


def _annotations(title: str, *, writes: bool = False) -> ToolAnnotations:
    """Anotaciones de las tools. Casi todas son de la misma naturaleza; una no.

    `read_only_hint`: por defecto ninguna tool modifica nada del entorno de quien llama. Escriben
    en el log de uso, pero eso es contabilidad interna del propio servidor —lo que alimenta el
    dashboard—, no un efecto sobre los datos del usuario.

    `writes=True` es la excepción, y existe porque `local_boilerplate` **sí** escribe un archivo
    en el disco de quien llama. Anunciarla como read-only sería mentir en el hint que un cliente
    MCP usa para decidir si pide permiso, así que ahí se declara lo que hace de verdad:

    - `destructive_hint=False`: se niega a pisar un archivo existente salvo `overwrite=True`
      explícito, así que la operación por defecto solo crea.
    - `idempotent_hint=False`: repetirla no da lo mismo —el modelo genera otro texto y la segunda
      llamada además choca con el archivo que dejó la primera—.

    Para el resto, esos dos hints se omiten a propósito: el protocolo solo les da sentido cuando
    `read_only_hint` es falso, y ponerlos ahí sería ruido que se contradice con lo anterior.

    `open_world_hint` en falso: el dominio es cerrado y conocido —el endpoint configurado en
    `LOCAL_DELEGATE_BASE_URL` y los archivos bajo las raíces permitidas—. Ninguna tool sale a
    buscar a un mundo abierto, y para un cliente eso es la diferencia entre delegar a tu GPU o a
    algo que puede tocar internet.
    """
    if writes:
        return ToolAnnotations(
            title=title,
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    return ToolAnnotations(title=title, read_only_hint=True, open_world_hint=False)


# --- Cliente httpx2 module-level (keep-alive entre delegaciones) -------------
_client: httpx2.Client | None = None
_client_lock = threading.Lock()
_chat_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_REQUESTS)
# Issue #476: how many calls are waiting for a slot right now, for the saturated queue's message.
_slot_waiters = 0
_slot_waiters_lock = threading.Lock()


def _new_client() -> httpx2.Client:
    # REQ-019: solo el plazo de CONEXIÓN baja a 10 s (o al total, si es menor). La espera de carga
    # de un modelo es de lectura y sigue en HTTP_TIMEOUT. Sin esto el kernel decidía: ~21 s en
    # Windows y ~75 s en macOS por cada fallo de la VPN.
    return httpx2.Client(
        timeout=httpx2.Timeout(
            config.HTTP_TIMEOUT,
            connect=min(config.DELEGATION_CONNECT_TIMEOUT, config.HTTP_TIMEOUT),
        )
    )


def _get_client() -> httpx2.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _new_client()
    return _client


#: El cliente propio de UN envío que se puede cortar (una `tools/call`, ver `_send`). Fuera de
#: ahí, `None`: se usa el compartido con keep-alive.
_SEND_CLIENT: contextvars.ContextVar[httpx2.Client | None] = contextvars.ContextVar(
    "local_delegate_send_client", default=None
)


def _cut_client(client: httpx2.Client) -> None:
    """Corta en el acto las conexiones de `client` (un envío cancelado) y lo cierra.

    `close()` solo no basta: en Linux y macOS cerrar un socket no despierta al hilo bloqueado en
    `recv` ni manda el FIN, y el backend seguiría generando. `shutdown` sí, en los tres sistemas;
    llama.cpp ve el cierre y para. El acceso al pool es interno de httpx2/httpcore2: si cambia,
    queda el `close()`.
    """
    try:
        pool = getattr(getattr(client, "_transport", None), "_pool", None)
        for connection in list(getattr(pool, "connections", ()) or ()):
            inner = getattr(connection, "_connection", None)
            stream = getattr(inner, "_network_stream", None)
            sock = stream.get_extra_info("socket") if stream is not None else None
            if isinstance(sock, socket.socket):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # ya cerrado
    except Exception:
        pass  # cortar es una ayuda; el `close()` de abajo va igual
    try:
        client.close()
    except Exception:
        # El hilo del envío puede estar cerrándolo a la vez; si falla, ya no hay nada que cortar.
        pass


# --- Delegaciones en curso (visibilidad multi-proceso vía archivo compartido) ----------------
# El estado vive en LOG_DIR/inflight.json (mismo directorio de datos que el log de uso), no
# solo en memoria: así CUALQUIER proceso MCP que sirva la web (metrics.py) ve las delegaciones
# en curso de TODAS las sesiones de Claude activas en esta máquina, no solo la suya. El
# contador local (_inflight_lock/_inflight_next_id) solo genera ids únicos por proceso; nunca
# toca disco.
_inflight_lock = threading.Lock()
_inflight_next_id = 0
_INFLIGHT_STALE_S = 1800  # red de seguridad: entrada huérfana (proceso muerto a media escritura)


def _inflight_file() -> Path:
    return config.LOG_DIR / "inflight.json"


def _pid_alive(pid: int) -> bool:
    """Best-effort: True si el proceso con ese PID sigue vivo. Nunca lanza."""
    if pid == os.getpid():
        return True
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            # restype/argtypes explícitos: sin ellos ctypes asume c_int y TRUNCA el HANDLE de
            # 64 bits, con lo que CloseHandle recibe un handle inválido y el daemon acaba
            # filtrando un handle por cada sondeo (el dashboard llama a esto cada 2 s).
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


# La lectura y la escritura atómica viven en `json_state`, compartidas con el estado de
# enfriamiento (F3, tarea 26). Se conservan estos nombres porque el resto del módulo y los tests
# los usan.
_read_inflight_data = json_state.read_json
_atomic_write_json = json_state.write_json_atomic


def _inflight_mutate(mutate_fn, *, write_on_timeout: bool = True) -> None:
    """Aplica mutate_fn(dict) al archivo compartido de inflight bajo lock exclusivo.

    Solo escribe si mutate_fn cambió algo: el dashboard sondea cada 2 s y antes reescribía el
    archivo en cada sondeo, generando contención inútil con las delegaciones reales.

    Best-effort como el resto del logging: nunca bloquea ni rompe una delegación. Si no
    consigue el lock a tiempo, `write_on_timeout=True` (alta/baja de una delegación) aplica
    igual sin lock —el peor caso es una entrada duplicada que se autolimpia por TTL/pid-muerto—
    y `write_on_timeout=False` (solo lectura/poda) se salta la escritura para no pisar con
    datos viejos una entrada que otro proceso acaba de registrar.
    """
    path = _inflight_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(path) + ".lock", timeout=2)
        try:
            with lock:
                data = _read_inflight_data(path)
                before = json.dumps(data, sort_keys=True)
                mutate_fn(data)
                if json.dumps(data, sort_keys=True) != before:
                    _atomic_write_json(path, data)
        except Timeout:
            data = _read_inflight_data(path)
            before = json.dumps(data, sort_keys=True)
            mutate_fn(data)
            if write_on_timeout and json.dumps(data, sort_keys=True) != before:
                _atomic_write_json(path, data)
    except OSError:
        pass  # el tracking de inflight es best-effort; jamás rompe una delegación


def _inflight_start(
    *, tool: str, model: str, source: str, chars_in: int, chunks: int | None = None
) -> int:
    global _inflight_next_id
    with _inflight_lock:
        _inflight_next_id += 1
        entry_id = _inflight_next_id
    pid = os.getpid()
    key = f"{pid}:{entry_id}"
    entry = {
        "tool": tool,
        "model": model,
        "source": source,
        "chars_in": chars_in,
        "started_at": time.time(),
        "pid": pid,
        "backend": config.backend_origin(),
    }
    if chunks:
        entry["chunks"] = int(chunks)
        entry["chunk"] = 1
    # Issue #442: which session asked for it, as its one-way key (never the id), so the mod's band
    # of THAT session alone says «delegating». Absent when unknown (no hook note, not Claude Code).
    session_key = _caller_session_key()
    if session_key is not None:
        entry["caller_session_key"] = session_key
    token = cancellation.current()
    if token is not None and token.entry is None:
        # Si la llamada se cancela, su evento de uso sale de aquí (`_log_cancelled`).
        token.entry = {"tool": tool, "model": model, "source": source, "chars_in": chars_in}
        if chunks:
            # Issue #476: an aborted chunked call is logged with the pieces it announced.
            token.entry["pieces"] = int(chunks)

    def _add(data: dict) -> None:
        data[key] = entry

    _inflight_mutate(_add)
    return entry_id


def _caller_session_key() -> str | None:
    """The asking session's one-way key, or `None`. Observation: it never breaks a delegation."""
    try:
        from . import attribution

        return attribution.current_session_key()
    except Exception:
        return None


def _inflight_progress(entry_id: int, chunk: int) -> None:
    """Marca en qué trozo va una delegación por chunks (visible en el panel 'En curso').

    A new piece is back in the map phase: it drops any `phase` left by a retry (issue #454).
    """
    key = f"{os.getpid()}:{entry_id}"

    def _update(data: dict) -> None:
        entry = data.get(key)
        if isinstance(entry, dict):
            entry["chunk"] = int(chunk)
            entry.pop("phase", None)

    _inflight_mutate(_update)


_INFLIGHT_PHASES = frozenset({"map", "reduce", "retry"})


def _inflight_phase(entry_id: int, phase: str) -> None:
    """Publish the phase of a chunked delegation for the panel (issue #454). Best-effort.

    `map` (the default, stored as absence), `reduce` (reduce and regroup: combining the pieces)
    or `retry` (a truncated piece being split again).
    """
    if phase not in _INFLIGHT_PHASES:
        return
    key = f"{os.getpid()}:{entry_id}"

    def _update(data: dict) -> None:
        entry = data.get(key)
        if not isinstance(entry, dict):
            return
        if phase == "map":
            entry.pop("phase", None)
        else:
            entry["phase"] = phase

    _inflight_mutate(_update)


def _inflight_local_wait(entry_id: int, reason: str | None) -> None:
    """Publica (o, con `None`, borra) la espera DENTRO de local-delegate de una delegación.

    REQ-022: mientras una llamada espera aquí —hoy, plaza en `_chat_slots`— el panel la pinta «en
    cola local» y no «esperando turno», que es de llama-swap. El motivo entra como argumento para
    que otra espera local futura (el turno por grupo de `daemon-reparte-el-backend`) reutilice
    esto sin tocar el panel: un motivo que el panel no conoce se pinta tal cual.
    """
    key = f"{os.getpid()}:{entry_id}"

    def _update(data: dict) -> None:
        entry = data.get(key)
        if not isinstance(entry, dict):
            return
        if reason is None:
            entry.pop("local_wait", None)
        else:
            entry["local_wait"] = reason

    _inflight_mutate(_update)


def _inflight_turn(entry_id: int, in_use: Iterable[str] | None, position: int | None) -> None:
    """Publica (o, con `None`, borra) los datos de una espera de turno (REQ-008).

    `turn_in_use` (modelos de `activos`) y `turn_position` (puesto en la cola) son datos aparte:
    no deciden ninguna fila del panel. Lo que decide la fila es `local_wait: "turn"`, que escribe
    `_inflight_local_wait`, el ayudante de siempre.
    """
    key = f"{os.getpid()}:{entry_id}"

    def _update(data: dict) -> None:
        entry = data.get(key)
        if not isinstance(entry, dict):
            return
        if in_use is None:
            entry.pop("turn_in_use", None)
            entry.pop("turn_position", None)
        else:
            entry["turn_in_use"] = list(in_use)
            entry["turn_position"] = int(position or 0)

    _inflight_mutate(_update)


def _inflight_end(entry_id: int) -> None:
    key = f"{os.getpid()}:{entry_id}"

    def _remove(data: dict) -> None:
        data.pop(key, None)

    _inflight_mutate(_remove)


def inflight_snapshot() -> list[dict]:
    """Delegaciones en curso de TODOS los procesos MCP activos, con `elapsed_s`.

    Lee/limpia el archivo compartido de inflight (ver _inflight_mutate). Descarta entradas
    huérfanas (TTL vencido o proceso ya muerto) en la misma pasada, así no hace falta un hilo
    de housekeeping aparte. Usada por /api/inflight (web de métricas).
    """
    now = time.time()
    result: list[dict] = []

    def _collect_and_prune(data: dict) -> None:
        result.clear()  # el fallback sin lock puede reejecutar esta función
        stale = []
        for key, v in data.items():
            if not isinstance(v, dict):
                stale.append(key)
                continue
            age = now - v.get("started_at", 0)
            pid = v.get("pid")
            if age > _INFLIGHT_STALE_S or (pid is not None and not _pid_alive(pid)):
                stale.append(key)
                continue
            entry = {
                "id": key,
                "tool": v.get("tool"),
                "model": v.get("model"),
                "source": v.get("source"),
                "chars_in": v.get("chars_in"),
                "backend": v.get("backend"),
                "elapsed_s": round(age, 1),
            }
            if v.get("chunks"):
                entry["chunks"] = v.get("chunks")
                entry["chunk"] = v.get("chunk")
                # Issue #454: reduce/retry, so the panel does not stay on «piece n/n».
                if v.get("phase"):
                    entry["phase"] = v.get("phase")
            # REQ-022: la espera DENTRO de local-delegate, solo cuando la hay. Sin copiarla aquí
            # el panel no la vería nunca, aunque esté escrita en el fichero.
            if v.get("local_wait"):
                entry["local_wait"] = v.get("local_wait")
            # REQ-008: con qué modelos y en qué puesto espera turno. Datos aparte, solo cuando están.
            if "turn_in_use" in v:
                entry["turn_in_use"] = v.get("turn_in_use")
            if "turn_position" in v:
                entry["turn_position"] = v.get("turn_position")
            # Issue #442: the asking session's key, only when known. `/api/inflight` uses it to
            # tell a session its own delegations and never hands it out.
            if v.get("caller_session_key"):
                entry["caller_session_key"] = v.get("caller_session_key")
            result.append(entry)
        for key in stale:
            data.pop(key, None)

    # write_on_timeout=False: sondear el panel jamás debe reescribir el archivo con una
    # foto vieja; si hay contención se pospone la poda al siguiente sondeo.
    _inflight_mutate(_collect_and_prune, write_on_timeout=False)
    result.sort(key=lambda e: -e["elapsed_s"])
    return result


# --- Helpers ----------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(UTC)


def _current_log_path() -> Path:
    """Archivo de log activo: fijo si LOCAL_DELEGATE_LOG está seteado, si no rota por mes UTC."""
    if not config.LOG_ROTATION_ENABLED:
        return config.USAGE_LOG
    return config.LOG_DIR / f"usage-{_utcnow():%Y%m}.jsonl"


def _check_allowed_dir(path: str) -> None:
    """Si LOCAL_DELEGATE_ALLOWED_DIRS está seteado, rechaza rutas fuera de esas raíces."""
    if not config.ALLOWED_DIRS:
        return
    resolved = Path(path).resolve()
    if not any(resolved.is_relative_to(root) for root in config.ALLOWED_DIRS):
        roots = "; ".join(str(r) for r in config.ALLOWED_DIRS)
        raise ValueError(i18n.t("mcp.input.outside_allowed", roots=roots, path=path))


def _validate_target(target: str, overwrite: bool) -> Path:
    """Valida la ruta de salida ANTES de gastar backend. Devuelve el Path ya resuelto.

    El orden importa: si el destino es inválido se falla sin llamar al modelo. Al revés se
    pagaría la inferencia para tirar el resultado, que es el peor de los dos errores posibles.

    Exige ruta **absoluta** porque el servidor corre con su propio directorio de trabajo —el del
    daemon, no el de quien llama—, así que una ruta relativa aterrizaría en un sitio que nadie
    eligió. Y se niega a pisar lo que ya está salvo permiso explícito.
    """
    if not target or not target.strip():
        raise ValueError(i18n.t("mcp.input.target_required"))
    p = Path(target)
    if not p.is_absolute():
        raise ValueError(i18n.t("mcp.input.target_not_absolute", target=target))
    _check_allowed_dir(target)
    if p.is_dir():
        raise ValueError(i18n.t("mcp.input.target_is_dir", target=target))
    if p.exists() and not overwrite:
        raise ValueError(i18n.t("mcp.input.target_exists", target=target))
    return p


def _write_target(p: Path, content: str, *, event: dict) -> str:
    """Escribe el contenido y devuelve el recibo corto, que es lo único que entra al contexto.

    `event` es la fila en curso ya fundida (`cost.in_flight_row`): el recibo dice los caracteres
    y los tokens de **Claude** que no entraron (REQ-035).
    """
    # Salto final garantizado: `_post_chat` y `_strip_fences` hacen `.strip()`, así que el texto
    # llega aquí sin él y el archivo saldría sin newline al final — cosa que la mitad de los
    # linters marca y que ensucia el diff de la primera línea que alguien añada después.
    if content and not content.endswith("\n"):
        content += "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    # newline explícito: el separador del archivo generado no debe depender de en qué sistema
    # operativo corra el daemon.
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    receipt = i18n.t(
        "mcp.receipt.written",
        path=p,
        lines=_machine(content.count("\n")),
        chars=_machine(len(content)),
    )
    if config.FEEDBACK_ENABLED:
        tokens = claude_tokens(len(content), kind="output", event=event)
        receipt += i18n.t("mcp.receipt.written_tokens", tokens=_machine(tokens))
    return receipt


# Techo simbólico para leer una entrada COMPLETA: las tools de reducción deciden después si
# el contenido cabe en el modelo o si toca map-reduce, y para eso necesitan el texto entero.
_NO_TRUNCATE = 2**31


def _read_input(text: str | None, path: str | None, max_chars: int) -> tuple[str, bool, int]:
    """Devuelve (contenido, truncado, raw_len). Si viene 'path', lo lee server-side."""
    if path:
        _check_allowed_dir(path)
        p = Path(path)
        if not p.is_file():
            raise ValueError(i18n.t("mcp.input.missing_file", path=path))
        content = p.read_text(encoding="utf-8", errors="replace")
    elif text is not None:
        content = text
    else:
        raise ValueError(i18n.t("mcp.input.text_or_path"))
    raw_len = len(content)
    truncated = raw_len > max_chars
    if truncated:
        content = content[:max_chars] + "\n[...contenido truncado...]"
    return content, truncated, raw_len


def _truncation_prefix(content: str, truncated: bool, raw_len: int) -> str:
    """Aviso visible cuando _read_input truncó la entrada (antes era un truncado silencioso)."""
    if not truncated:
        return ""
    counts = i18n.t(
        "mcp.receipt.input_truncated_counts",
        processed=_machine(len(content)),
        total=_machine(raw_len),
    )
    return f"{INPUT_TRUNCATED_MARKER}{counts}]\n"


def _append_log_line(log_path: Path, line: str) -> None:
    """Escribe una línea al log con lock de archivo (Desktop + Code escribiendo a la vez).

    Si no se consigue el lock en 1s, escribe igual sin él (best-effort: nunca bloquea ni
    rompe la tool por contención).
    """
    lock = FileLock(str(log_path) + ".lock", timeout=1)
    try:
        with lock, log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Timeout:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)


#: Cuanto vale una nota de bloqueo. Pasado ese rato, la delegacion ya no se le atribuye: el agente
#: hizo otra cosa por el camino y contarla seria inflar la adopcion.
BLOCK_WINDOW_S = 600.0


def _recent_block_id(path: str) -> str | None:
    """El identificador del bloqueo que provoco esta lectura, si lo hubo.

    Las notas las deja el hook (`hook_common.record_block`), que es stdlib pura y no puede
    importar este modulo: el formato vive en dos sitios y por eso hay un test de ida y vuelta que
    escribe con el hook y lee con esto. Es la misma cautela que el espejo JS del panel.

    Nunca lanza: perder la correlacion estropea una medicion, romper la tool estropea el trabajo.
    """
    try:
        from .resources.hooks import hook_common
    except ImportError:
        return None
    try:
        digest = hook_common.path_digest(path)
    except (OSError, ValueError):
        return None
    # El nombre nuevo y el viejo (REQ-012): un hook de una version anterior puede seguir
    # instalado y escribiendo en `local-delegate-bloqueos.jsonl`. Gana la nota mas reciente.
    lines: list[str] = []
    for notes in (hook_common.block_notes_path(), hook_common.legacy_block_notes_path()):
        try:
            lines += notes.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError):
            continue

    now = _utcnow().timestamp()
    best: tuple[float, str] | None = None
    for line in lines:
        try:
            note = json.loads(line)
            ts = float(note["ts"])
            fresh = note["sha"] == digest and now - ts <= BLOCK_WINDOW_S
            if fresh and (best is None or ts >= best[0]):
                best = (ts, str(note["id"]))
        except (ValueError, KeyError, TypeError):
            continue
    return best[1] if best else None


# --- Espera frente a lentitud (daemon-reparte-el-backend, REQ-024 a REQ-028) -----------------


def _timings_of(data: Any) -> dict | None:
    """Los `timings` de una respuesta de llama-server, o `None` si no vienen (REQ-024)."""
    timings = data.get("timings") if isinstance(data, dict) else None
    return dict(timings) if isinstance(timings, dict) else None


def _timing_sum(timed: Sequence[dict], key: str) -> float | None:
    """La suma de `key` sobre las llamadas con `timings`; `None` si a alguna le falta el dato.

    Un `timings` incompleto omite los campos que dependen de él, nunca los da a medias.
    """
    total = 0.0
    for timings in timed:
        value = timings.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            return None
        total += float(value)
    return total


#: La velocidad normal por modelo (REQ-025): una sola referencia, sin tramos (T3). Se siembra una
#: vez por origen de la siembra (el mes en curso y el anterior, o el log fijo entero) y se alimenta
#: con cada evento.
_pace_lock = threading.Lock()


@dataclass
class _PaceCache:
    """La siembra vigente: de dónde salió y sus referencias (`None` hasta la primera)."""

    entry: tuple[tuple[str, Path], pace.References] | None = None


_pace_cache = _PaceCache()


def _pace_source() -> tuple[str, Path]:
    """De dónde se siembra: el directorio de logs rotados, o el fichero del log fijo."""
    if config.LOG_ROTATION_ENABLED:
        return ("rotated", Path(config.LOG_DIR))
    return ("fixed", Path(config.USAGE_LOG))


def _pace_references() -> pace.References:
    """Las referencias del proceso, sembradas la primera vez que hacen falta (aclaración T14).

    Van atadas a lo que se siembra: si cambia (otro `LOCAL_DELEGATE_LOG_DIR`, otro
    `LOCAL_DELEGATE_LOG`, o un test con su `tmp_path`), se siembran de nuevo desde ahí.
    """
    source = _pace_source()
    with _pace_lock:
        if _pace_cache.entry is not None and _pace_cache.entry[0] == source:
            return _pace_cache.entry[1]
        references = pace.References()
        kind, location = source
        if kind == "rotated":
            pace.seed_from_log(references, location, _utcnow())
        else:
            # Log fijo: no hay meses que leer, se siembra con el fichero entero.
            try:
                references.seed(location.read_text(encoding="utf-8", errors="replace").splitlines())
            except Exception:
                pass  # sembrar es una mejora: sin siembra, la ventana se llena con los eventos
        _pace_cache.entry = (source, references)
        return references


def _slowness_fields(
    attempts: Sequence[Attempt],
    *,
    model: str,
    latency_ms: int,
    ok: bool,
    tokens_in: int | None,
    tokens_out: int | None,
    local_backend: bool,
) -> dict[str, Any]:
    """Los campos de espera y ritmo de un evento (REQ-024 a REQ-026). Puede lanzar: lo envuelve
    `_log_event` (REQ-028).

    `inference_ms` y `wait_ms` suman **todas** las llamadas reales de la operación, saltos
    incluidos; una llamada sin `timings` (un timeout, un 500) cuenta entera como espera. Los ritmos
    (`tok_s`, `prefill_tok_s`) salen solo de las llamadas del modelo **del evento**, el que
    respondió: con un salto, mezclar la velocidad de dos modelos daría un `slow` falso y
    contaminaría la ventana del respaldo (aclaración T14). Sin `timings` en ninguna llamada, `{}`:
    los campos se omiten, nunca valen 0. La referencia se mide **antes** de registrar el evento,
    para que una llamada no se compare consigo misma.
    """
    timed = [a.timings for a in attempts if isinstance(a.timings, dict)]
    if not timed:
        return {}
    fields: dict[str, Any] = {}
    prompt_ms = _timing_sum(timed, "prompt_ms")
    predicted_ms = _timing_sum(timed, "predicted_ms")
    if prompt_ms is not None and predicted_ms is not None:
        inference_ms = round(prompt_ms + predicted_ms)
        fields["inference_ms"] = inference_ms
        fields["wait_ms"] = max(0, int(latency_ms) - inference_ms)
    own = [a.timings for a in attempts if a.model == model and isinstance(a.timings, dict)]
    if own:
        own_predicted_ms = _timing_sum(own, "predicted_ms")
        own_predicted_n = _timing_sum(own, "predicted_n")
        if own_predicted_n is not None and own_predicted_ms:
            fields["tok_s"] = round(own_predicted_n * 1000 / own_predicted_ms, 2)
        own_prompt_ms = _timing_sum(own, "prompt_ms")
        own_prompt_n = _timing_sum(own, "prompt_n")
        if own_prompt_n is not None and own_prompt_ms:
            fields["prefill_tok_s"] = round(own_prompt_n * 1000 / own_prompt_ms, 2)
    if ok and "tok_s" in fields and tokens_out is not None:
        fields.update(
            _pace_references().measure(
                model,
                fields["tok_s"],
                tokens_in,
                threshold=config.SLOW_THRESHOLD,
                tokens_out=tokens_out,
            )
        )
    if fields.get("slow") and local_backend:
        from .web import sysinfo

        ram = sysinfo.ram_stats()
        if ram and ram.get("free_gb") is not None:
            fields["free_ram_mb"] = round(float(ram["free_gb"]) * 1024)
    return fields


def _describe_pace() -> str:
    """REQ-027: la velocidad de referencia de cada modelo y cuántas muestras la forman."""
    rows = _pace_references().summary()
    if not rows:
        return i18n.t("mcp.status.pace.none")
    parts = []
    for row in rows:
        median = row["median"]
        speed = (
            f"{_machine(median, 1)} tok/s"
            if median is not None
            else i18n.t("mcp.status.pace.no_reference")
        )
        parts.append(
            i18n.t("mcp.status.pace.model", model=row["model"], speed=speed, samples=row["samples"])
        )
    return i18n.t("mcp.status.pace.line", parts="; ".join(parts))


def _log_event(
    *,
    tool: str,
    model: str,
    source: str,
    chars_in: int,
    chars_out: int,
    latency_ms: int,
    ok: bool,
    chars_out_raw: int | None = None,
    error: str | None = None,
    finish_reason: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    truncated_in: bool = False,
    truncated_out: bool = False,
    raw_len: int | None = None,
    path: str | None = None,
    json_schema: str | None = None,
    chunks: int | None = None,
    pieces: int | None = None,
    input_unit: str = "chars",
    output_to_file: bool = False,
    model_requested: str | None = None,
    fallback_reason: str | None = None,
    fallback_class: str | None = None,
    error_class: str | None = None,
    num_sections: int | None = None,
    focus: bool = False,
    connection_failure: str | None = None,
    turn_wait_ms: int | None = None,
    turn: str | None = None,
    routing: str | None = None,
    affinity_foreign_flight: int | None = None,
    affinity_failed: bool | None = None,
    affinity_dropped: str | None = None,
    affinity_dropped_class: str | None = None,
    attempts: Sequence[Attempt] = (),
    steps: Sequence[dict] | None = None,
    backend_params: dict | None = None,
    backend_params_rejected: bool = False,
    reasoning_skipped: str | None = None,
    cancel_reason: str | None = None,
    slot_wait_ms: int | None = None,
    exception_type: str | None = None,
) -> None:
    """Escribe una línea JSONL en el log activo (rotado por mes o fijo). Nunca rompe una tool.

    Los campos del respaldo (F3, REQ-013) son aditivos: `model` sigue siendo el modelo que
    RESPONDIÓ, así que un evento sin salto se escribe igual que antes y el histórico se lee igual.

    `attempts` son las llamadas reales de la operación: de sus `timings` salen la espera, la
    inferencia y el ritmo (REQ-024 a REQ-026), y de sus `reasoning_chars` el del evento (REQ-018).

    `backend_params`, `backend_params_rejected` and `reasoning_skipped` (REQ-018) come from
    `_backend_params_log_fields`; like `reasoning_chars`, each one is omitted when it does not apply.
    """
    try:
        rec: dict = {
            "ts": _utcnow().isoformat(timespec="seconds"),
            "tool": tool,
            "model": model,
            "source": source,  # "path" = leído server-side (no entró al contexto de Claude)
            "chars_in": int(chars_in),
            "chars_out": int(chars_out),
            "latency_ms": int(latency_ms),
            "ok": bool(ok),
            # dónde corrió la INFERENCIA: "local" (backend en esta máquina) o "remote"
            # (p. ej. esta Mac usando el llama-swap de la PC). El MCP y la lectura de 'path'
            # son siempre locales; esto separa el cómputo, no el origen del archivo.
            "backend": config.backend_origin(),
            "backend_host": config.backend_host(),
            # La versión del paquete (desde F1). REQ-041 decide con ella la frontera de medición
            # (`scripts/measurement_boundaries.py`): era el `package_version` propuesto por la spec.
            "v": _get_version(),
        }
        # Quién pidió la delegación. Sin esto el panel no puede distinguir un mes de smoke tests
        # de un mes de trabajo real: es el hueco que dejó la medición de adopción del 3-ago, donde
        # las 20 líneas de una prueba sólo se separaron cruzando a mano contra los transcripts.
        # Se omite cuando no hay identidad (benchmark, arranque, cliente que no manda clientInfo):
        # una firma inventada sería peor que ninguna. Y va envuelto porque el logging entero es
        # best-effort y observar no puede romper una tool.
        try:
            caller = clients.current_client()
        except Exception:
            caller = None
        if caller:
            rec["client"] = caller
        # Quién pidió la delegación por dentro: el `tool_use_id` que manda Claude Code y, con la
        # nota del hook y la cola del transcript, el modelo, el hilo y el esfuerzo de quien llama
        # (coste-api-y-cuota, REQ-001 y REQ-003). Su propio `try ... except Exception`: el general
        # de abajo solo atrapa `OSError`, y un fallo de la resolución no puede llevarse la línea
        # ni salir de esta función. Nunca se escribe el id de sesión.
        try:
            tool_use_id = clients.current_tool_use_id()
            if tool_use_id:
                rec["tool_use_id"] = tool_use_id
                from . import attribution

                rec.update(attribution.current_call())
        except Exception:
            # Silencio intencionado: la atribución es observación. Si falla, la línea se escribe
            # igual sin esos campos; registrar aquí podría fallar otra vez, y observar nunca
            # puede romper la tool que se está anotando.
            pass
        # `chunks` es el número REAL de llamadas al backend, no el de trozos: una operación
        # troceada gasta la GPU N veces y esta es la única huella que queda de ello. Se omite
        # cuando vale 1, así que quien agregue debe leerlo como `chunks or 1`.
        if chunks is not None and chunks > 1:
            rec["chunks"] = int(chunks)
            # Issue #454: the pieces announced to the panel, next to the calls (`chunks`), so
            # «3 pieces · 4 calls» can be told apart. Only on chunked events.
            if pieces is not None and pieces >= 1:
                rec["pieces"] = int(pieces)
        # `chars_in` no siempre son caracteres de texto: en local_describe_image son BYTES de un
        # binario, y estimar tokens dividiéndolos entre 4 da un número disparatado (×46 medido).
        # Solo se escribe cuando NO es texto, para no engordar cada línea del log.
        if input_unit != "chars":
            rec["input_unit"] = input_unit
        if error is not None:
            rec["error"] = error
        if finish_reason is not None:
            rec["finish_reason"] = finish_reason
        if tokens_in is not None:
            rec["tokens_in"] = int(tokens_in)
        if tokens_out is not None:
            rec["tokens_out"] = int(tokens_out)
        if truncated_in:
            rec["truncated_in"] = True
        if truncated_out:
            rec["truncated_out"] = True
        if raw_len is not None:
            rec["raw_len"] = int(raw_len)
        # What the model generated, in characters, BEFORE the post-processing (`_strip_think`,
        # `sections.complete`) and the notices; summed over the calls of a chunked operation.
        # Never the text (the usage log keeps no content). Without it httpcore2 (B2d-2) could not
        # be diagnosed: ~2000 tokens generated and 752 chars delivered, with no way to tell
        # whether they went in the cut, in degenerate whitespace or in hidden reasoning.
        if chars_out_raw is not None:
            rec["chars_out_raw"] = int(chars_out_raw)
        # Una llamada cancelada (`error: "cancelled"`): por qué. `notification` (el cliente mandó
        # `notifications/cancelled`), `disconnect` (cortó la conexión) o `aborted` (se cerró la
        # sesión u otra cancelación del SDK).
        if cancel_reason is not None:
            rec["cancel_reason"] = cancel_reason
        # Issue #476: an aborted call — how long it waited for a slot (only if it waited) and,
        # for an unexpected error, the exception's type (never its message: it may carry content).
        if slot_wait_ms is not None and slot_wait_ms > 0:
            rec["slot_wait_ms"] = int(slot_wait_ms)
        if exception_type is not None:
            rec["exception_type"] = exception_type
        # B2e: each step of a chunked operation (map, regroup, reduce) with what it generated and
        # why it stopped, never its text. Without it a summary that lost something could not tell
        # whether a chunk note had already dropped it or whether the reduce was cut.
        if steps:
            rec["steps"] = [
                {
                    "kind": str(s["kind"]),
                    "chars_out": int(s["chars_out"]),
                    "finish_reason": s.get("finish_reason"),
                    # #455: a step cut by `length` and replaced by its split retry.
                    **({"retried": True} if s.get("retried") else {}),
                }
                for s in steps
            ]
        # REQ-018: the per-role parameters the operation carried (`source` only lists the keys
        # from the variable), how much it reasoned over every real call (failed ones included;
        # never the text), and whether the backend refused the parameters (REQ-015) or a call
        # went without reasoning because it did not fit in the context (REQ-023).
        if backend_params is not None:
            rec["backend_params"] = backend_params
        reasoning_chars = sum(a.reasoning_chars or 0 for a in attempts)
        if reasoning_chars > 0:
            rec["reasoning_chars"] = reasoning_chars
        if backend_params_rejected:
            rec["backend_params_rejected"] = True
        if reasoning_skipped is not None:
            rec["reasoning_skipped"] = reasoning_skipped
        if source == "path" and path is not None:
            rec["path"] = path
            # Si esta lectura viene de un bloqueo del hook, el evento se queda con su
            # identificador. Es lo que convierte «se ofrecio» y «se acepto» en dos numeros
            # comparables sin cruzar dos logs a mano.
            block_id = _recent_block_id(path)
            if block_id:
                rec["block_id"] = block_id
        if json_schema is not None:
            rec["json_schema"] = json_schema
        # La SALIDA se escribió a un archivo, así que tampoco entró al contexto de quien llama.
        # Se omite cuando es falso: es el caso de casi todos los eventos y engordaría el log.
        if output_to_file:
            rec["output_to_file"] = True
        # Hubo salto: qué modelo se pidió y por qué respondió otro. Es lo que deja a una medición
        # saber si la contaminó un swap ajeno (REQ-013).
        if model_requested is not None:
            rec["model_requested"] = model_requested
        if fallback_reason is not None:
            rec["fallback_reason"] = fallback_reason
        if fallback_class is not None:
            rec["fallback_class"] = fallback_class
        # La clase del fallo como causa propia: una de configuración tiene que verse para que
        # alguien la arregle (REQ-019).
        if error_class is not None:
            rec["error_class"] = error_class
        # Por qué no se pudo conectar (REQ-017): `dns`, `connect_timeout`… Solo en los
        # `connect_error`, para no engordar cada línea; `error` sigue siendo `connect_error`.
        if connection_failure is not None:
            rec["connection_failure"] = connection_failure
        # Resumen estructurado (SDD resumen-por-secciones): cuántas secciones del nivel
        # estructural tenía el documento, y si se pidió un enfoque. Nunca el texto del enfoque
        # ni los títulos: el log no guarda contenido.
        if num_sections is not None:
            rec["sections"] = int(num_sections)
        if focus:
            rec["focus"] = True
        # Turno del daemon (REQ-008): cuánto esperó la operación a que le tocara, solo si esperó,
        # y si se le concedió forzado por la red de seguridad (REQ-007).
        if turn_wait_ms is not None and turn_wait_ms > 0:
            rec["turn_wait_ms"] = int(turn_wait_ms)
        if turn is not None:
            rec["turn"] = turn
        # Afinidad (REQ-016): respondió un alternativo ya cargado en lugar del modelo del rol
        # (`model_requested`). No es un respaldo ni lleva aviso. `affinity_foreign_flight`: las
        # peticiones de otros clientes contra ese modelo en la foto; `affinity_failed`, sin
        # ninguna y con una espera de backend de 3 s o más en la primera llamada (tuvo que cargar).
        if routing is not None:
            rec["routing"] = routing
        if affinity_foreign_flight is not None:
            rec["affinity_foreign_flight"] = int(affinity_foreign_flight)
        if affinity_failed:
            rec["affinity_failed"] = True
        # La afinidad eligió este alternativo, pero un salto la apagó (respondió el rol o su
        # cadena): no es `routing: "affinity"`, y sin esto el evento no diría que se probó.
        if affinity_dropped is not None:
            rec["affinity_dropped"] = affinity_dropped
        if affinity_dropped_class is not None:
            rec["affinity_dropped_class"] = affinity_dropped_class
        # Espera frente a lentitud (REQ-024 a REQ-026). Su propio `try`: el general de abajo solo
        # atrapa `OSError`, y observar no puede romper una tool (REQ-028). Si algo falla, el
        # evento se escribe sin ninguno de estos campos.
        with suppress(Exception):
            rec.update(
                _slowness_fields(
                    attempts,
                    model=model,
                    latency_ms=latency_ms,
                    ok=ok,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    local_backend=rec["backend"] == "local",
                )
            )
        log_path = _current_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _append_log_line(log_path, json.dumps(rec, ensure_ascii=False) + "\n")
        # Después de medir: el evento entra en la ventana de su modelo (REQ-025).
        if "tok_s" in rec:
            # Registrar la velocidad también es observar: si falla, el evento ya está escrito y la
            # ventana se queda sin él (REQ-028).
            with suppress(Exception):
                _pace_references().record(rec)
    except OSError:
        pass  # el logging es best-effort; jamás propaga


_CLAUDE_TOKEN_KINDS = ("text", "returned", "output", "image")


def claude_tokens(amount: int, *, kind: str, event: dict) -> int:
    """Convierte lo ahorrado o lo devuelto a tokens de **Claude**. Única conversión del paquete.

    `_accounting` (y su espejo JS `claudeTokens`) pasan por aquí para `saved`, `returned` y `net`.
    `event` es la fila **fundida** del log (`cost.merge`, coste-api-y-cuota REQ-006): trae en
    `density[kind]` el `[c100, origen]` ya resuelto por `cost.resolve_density`. Esta función
    no resuelve nada, solo divide (REQ-033):

    - `image`, o una fila sin `density[kind]` (una imagen, o una fila sin fundir): 0. Una fusión
      olvidada da un 0 visible, nunca una cifra con una densidad inventada.
    - si no, `amount × 100 // c100` (`c100` = caracteres por token de Claude, en centésimas).

    Los tokens del modelo LOCAL (`tokens_in`, `tokens_out`, coste local) no pasan por aquí.
    """
    if kind not in _CLAUDE_TOKEN_KINDS:
        raise ValueError(f"unknown_conversion_kind: {kind!r}; valid: {_CLAUDE_TOKEN_KINDS}")
    if kind == "image":
        return 0
    density = event.get("density")
    cell = density.get(kind) if isinstance(density, dict) else None
    if not cell:
        return 0
    return amount * 100 // int(cell[0])


def _accounting(row: dict) -> dict:
    """Contabilidad normalizada de UN evento. Única fuente de las cuentas del panel.

    Implementa letra a letra la «Regla de contabilidad» de la spec `panel-cuentas-y-estados-
    honestos`, que su espejo JS `acct` (en `web/metrics.py`) sigue igual; el test de paridad las
    ata. Separa tres magnitudes:

    - **ahorro bruto** (`saved`): lo que NO entró al contexto de Claude. Es el contenido leído
      server-side contado **una vez**, aunque se troceara (el trabajo extra de trocear lo pagó la
      GPU local, no el contexto), más la salida escrita a un fichero.
    - **devuelto** (`returned`) y **neto** (`net = saved − returned`): lo que la tool sí devolvió
      al contexto en las delegaciones que reclaman ahorro de entrada. El neto puede ser negativo.
    - **coste** (`tokens_in`/`tokens_out`, `backend_calls`): lo que gastó de verdad el backend,
      con el prompt de sistema repetido en cada trozo.

    Un **fallo** (`ok` exactamente `False`) no ahorra, no devuelve, no se estima y no genera: solo
    cuenta sus llamadas y los tokens que reportó el backend (la GPU los gastó). El ahorro y el
    devuelto se convierten a tokens de Claude **solo** con `claude_tokens`; el coste local sigue
    con `CHARS_PER_TOKEN` como respaldo cuando falta el `usage` real (y entonces `estimated`).
    El desglose en caracteres (`chars_saved_text`, `bytes_saved_image`, `chars_saved_output`,
    `chars_returned`) es el contrato con `coste-api-y-cuota`: no depende de la conversión.
    """
    failed = row.get("ok") is False
    chars_in = int(row.get("chars_in", 0) or 0)
    chars_out = int(row.get("chars_out", 0) or 0)
    # `chunks` es el número REAL de llamadas al backend y se omite cuando vale 1 (ver
    # `_log_event`). Lo ha sido desde el commit que introdujo el chunking, así que esto
    # contabiliza bien también el histórico ya grabado. También en los fallos: se gastaron.
    # Salvo en un fallo de CONEXIÓN (`connection_failure`: `dns`, `refused`…, issue #436): la
    # petición no llegó al backend, así que no gastó ninguna llamada. Si una troceada cae a mitad,
    # `chunks` cuenta las que sí se hicieron antes (`len(attempts)`), y esas se mantienen; omitido
    # (≤ 1) se lee como 0, que es el caso del backend inalcanzable desde el primer intento.
    connection_failed = failed and bool(row.get("connection_failure"))
    chunks = int(row.get("chunks") or 0)
    backend_calls = chunks if connection_failed else (chunks or 1)

    raw_in = row.get("tokens_in")
    raw_out = row.get("tokens_out")

    # `chars_in` no siempre son caracteres: en local_describe_image son BYTES de la imagen.
    # Los eventos anteriores al campo `input_unit` se reconocen por el nombre de la tool.
    unit = row.get("input_unit") or (
        "bytes" if row.get("tool") == "local_describe_image" else "chars"
    )
    estimable = unit == "chars"

    # Coste del modelo LOCAL: no pasa por `claude_tokens`.
    if failed:
        # Solo lo que reportó el backend: estimar sobre el texto de un error inventaría
        # generación, y un fallo no es una estimación.
        tokens_in = int(raw_in) if raw_in is not None else 0
        tokens_out = int(raw_out) if raw_out is not None else 0
        estimated = False
    else:
        tokens_in = (
            int(raw_in)
            if raw_in is not None
            else (chars_in // config.CHARS_PER_TOKEN if estimable else 0)
        )
        tokens_out = int(raw_out) if raw_out is not None else chars_out // config.CHARS_PER_TOKEN
        estimated = raw_in is None or raw_out is None

    from_path = row.get("source") == "path"
    to_file = bool(row.get("output_to_file"))

    chars_saved_text = bytes_saved_image = chars_saved_output = chars_returned = 0
    saved = returned = 0
    if not failed:
        # Desglose en caracteres (la imagen, en bytes: es lo que guarda el log).
        if from_path and estimable:
            chars_saved_text = chars_in
        if from_path and not estimable:
            bytes_saved_image = chars_in
        if to_file:
            # Ahorro de SALIDA: el texto se escribió en un fichero y quien llamó recibió solo un
            # recibo de dos líneas, cuyo tamaño no se registra (se toma 0 de devuelto).
            chars_saved_output = chars_out
        # Reclama ahorro de entrada si leyó algo server-side: texto con caracteres, o una imagen
        # con token real (sin él no hay bruto, así que tampoco se descuenta la descripción).
        claims = (
            from_path
            and not to_file
            and ((estimable and chars_in > 0) or (not estimable and int(raw_in or 0) > 0))
        )
        if claims:
            chars_returned = chars_out

        # Tokens de Claude: SOLO con `claude_tokens`.
        if from_path and estimable:
            saved += claude_tokens(chars_saved_text, kind="text", event=row)
        if from_path and not estimable:
            saved += claude_tokens(bytes_saved_image, kind="image", event=row)
        if to_file:
            saved += claude_tokens(chars_saved_output, kind="output", event=row)
        returned = claude_tokens(chars_returned, kind="returned", event=row)

    return {
        "backend_calls": backend_calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "saved": saved,
        "returned": returned,
        "net": saved - returned,  # puede ser negativo: no se recorta
        "estimated": estimated,
        # F3, tarea 29: si respondió un respaldo, y la causa (la del fallo, o la del salto). Un
        # evento anterior a esos campos da `False` y `None`: se lee igual que siempre.
        # T15 (REQ-016): la afinidad también lleva `model_requested`, pero no es un respaldo.
        "fallback": bool(row.get("model_requested")) and row.get("routing") != "affinity",
        # La clase en el formato nuevo aunque la fila sea vieja (REQ-006): el espejo JS traduce
        # igual, con la misma tabla inyectada (`LEGACY_VALUES.failureClass`).
        "cause": legacy_names.new_value(
            legacy_names.FAILURE_CLASS_VALUES,
            row.get("error_class") or row.get("fallback_class") or None,
        ),
        # Contrato con `coste-api-y-cuota`: desglose en caracteres y campos del evento.
        "chars_saved_text": chars_saved_text,
        "bytes_saved_image": bytes_saved_image,
        "chars_saved_output": chars_saved_output,
        "chars_returned": chars_returned,
        "failed": failed,
        # Fallo sin llamada al backend (issue #436): no gasta `backend_calls`.
        "connection_failed": connection_failed,
        "tool": row.get("tool"),
        "model": row.get("model"),
        "source": row.get("source"),
        "unit": unit,
    }


@dataclass
class ChatResult:
    text: str
    ok: bool
    error: str | None = None  # mensaje corto cuando ok=False
    finish_reason: str | None = None  # choices[0].finish_reason
    tokens_in: int | None = None  # usage.prompt_tokens si el backend lo da
    tokens_out: int | None = None  # usage.completion_tokens
    #: La clase del fallo (`failures.FailureClass`) cuando `ok=False`, y `None` cuando salió bien. Es
    #: aditivo: quien solo mire `error` sigue viendo exactamente lo de antes.
    error_class: str | None = None
    #: La causa de un `connect_error` (`failures.ConnectionCause`, como texto), y `None` en cualquier
    #: otro caso. Va al log como `connection_failure` (REQ-017); `error` sigue diciendo `connect_error`.
    connection_failure: str | None = None
    #: Los `timings` de llama-server tal como llegan (`prompt_n`, `prompt_ms`, `predicted_n`,
    #: `predicted_ms`…), o `None` si el backend no los manda (REQ-024).
    timings: dict | None = None
    #: REQ-018: characters of reasoning of the response (`reasoning_content` plus what
    #: `_strip_think` removes from `content`), or `None` without a parsed response. Never the text.
    reasoning_chars: int | None = None


@dataclass(frozen=True)
class Attempt:
    """Una llamada REAL al backend dentro de una llamada lógica: la del modelo pedido o un respaldo.

    `_run_chat` devuelve la lista entera y no solo el último resultado: sin ella, quien cuenta
    llamadas (`chunks` en el log) seguiría viendo una aunque el respaldo hiciera dos.
    """

    model: str
    ok: bool
    error: str | None
    error_class: str | None
    ms: int
    #: Los `timings` de la respuesta (REQ-024): de aquí salen la inferencia y el ritmo del evento.
    #: Fuera de la comparación y del hash: un dict no es hashable.
    timings: dict | None = field(default=None, compare=False)
    #: REQ-018: the reasoning characters of every POST of this call (the REQ-015 probe and the
    #: schema retry included), or `None` when none had a parsed response.
    reasoning_chars: int | None = field(default=None, compare=False)


#: Las clases que permiten saltar (tabla de F3). Capacidad solo al residente (REQ-018).
_HOPPABLE_CLASSES = frozenset({failures.FailureClass.MODEL, failures.FailureClass.CAPACITY})


def _cooldown_error(model: str, cooling: cooldown.ActiveCooldown) -> ChatResult:
    """REQ-009: el modelo está enfriándose y no queda candidato. Falla al momento, sin timeout."""
    until = datetime.fromtimestamp(cooling.until, UTC).strftime("%H:%M:%S UTC")
    return ChatResult(
        text=ERROR_PREFIX
        + i18n.t(
            "mcp.error.cooldown",
            model=model,
            until=until,
            remaining=_machine(cooling.remaining_s),
        ),
        ok=False,
        error="cooldown",
    )


def _fallback_info(
    model: str, result: ChatResult, attempts: list[Attempt], affinity: str | None = None
) -> dict | None:
    """Si respondió un modelo distinto del pedido: cuál, en lugar de cuál y por qué (REQ-007).

    `affinity` es el alternativo que eligió la afinidad para el modelo pedido (T15): que responda
    él **no** es un respaldo (REQ-016), y su fallo es el motivo de un salto posterior.
    """
    if not (result.ok and attempts and attempts[-1].model not in (model, affinity)):
        return None
    first = attempts[0]
    if first.model in (model, affinity):
        reason, error_class = first.error, _class_value(first.error_class)
    else:
        # Valor de máquina, como los demás motivos (decisión 6 de B2): lo viejo, «en
        # enfriamiento», se sigue mostrando tal cual si viene del log (REQ-033).
        reason, error_class = COOLDOWN_REASON, "cooldown"
    return {
        "answered_by": attempts[-1].model,
        "instead_of": model,
        "reason": reason,
        "class": error_class,
    }


#: El motivo de un salto por enfriamiento (`fallback_reason` del log desde la 0.36.0).
COOLDOWN_REASON = "cooldown"


def _class_value(error_class: str | None) -> str | None:
    """La clase como texto plano para el log (`model`, `configuration`…), o None."""
    return failures.FailureClass(error_class).value if error_class else None


def _fallback_notice(info: dict, origin: str | None = None) -> str:
    """La línea de aviso, siempre DETRÁS del contenido y separada de él."""
    extra = f", {origin}" if origin else ""
    reason = info["reason"]
    if reason == COOLDOWN_REASON:
        reason = i18n.t("mcp.fallback.reason.cooldown")
    notice = i18n.t(
        "mcp.warning.answered_instead",
        answered=info["answered_by"],
        instead=info["instead_of"],
        reason=reason,
    )
    return f"\n\n{WARNING_MARKER}{notice}{extra}]"


def _body_failure(
    model: str,
    error_class: failures.FailureClass,
    timings: dict | None = None,
    reasoning_chars: int | None = None,
) -> ChatResult:
    """El error legible de una respuesta que llegó con 200 y aun así no sirve.

    Antes de esto, un `content` nulo reventaba con `AttributeError` a medio `_post_chat` —el tipo
    no estaba en el `except` de abajo— y se llevaba la tool por delante.

    `reasoning_chars` (REQ-018): a model that spent `max_tokens` reasoning failed, and its
    reasoning still counts in the event.
    """
    if error_class is failures.FailureClass.CONFIGURATION:
        return ChatResult(
            text=ERROR_PREFIX + i18n.t("mcp.error.max_tokens_reasoning", model=model),
            ok=False,
            error="config_max_tokens",
            error_class=error_class,
            timings=timings,
            reasoning_chars=reasoning_chars,
        )
    return ChatResult(
        text=ERROR_PREFIX + i18n.t("mcp.error.empty_response", model=model),
        ok=False,
        error="bad_response",
        error_class=error_class,
        timings=timings,
        reasoning_chars=reasoning_chars,
    )


#: Cuánto antes de vencer el plazo de lectura se muestrea `/running` (REQ-018). Tiene que ser mayor
#: que el tope de la consulta más holgura, para que la muestra esté lista cuando llegue el timeout.
_PROBE_MARGIN_S = 3.0
_PROBE_QUERY_CAP_S = 1.0


def _probe_delay() -> float:
    """Segundos desde que se envía la petición hasta que se muestrea, como el plazo de httpx."""
    return max(0.0, config.HTTP_TIMEOUT - _PROBE_MARGIN_S)


def _llamaswap_state(model: str) -> str | None:
    """Estado de `model` en `/running` de llama-swap (`starting`, `ready`…), o None si no se sabe.

    None cubre todo lo que no es llama-swap o no responde a tiempo —Ollama, LM Studio, un 404, un
    llama-swap caído—, y el clasificador lo lee como carga, que no enfría: fuera de llama-swap, D-2
    no se cumple (enmienda de spec aprobada el 2026-09-15).
    """
    base = config.BASE_URL.removesuffix("/v1")
    try:
        with httpx2.Client(timeout=_PROBE_QUERY_CAP_S) as c:
            r = c.get(f"{base}/running", headers=config.auth_headers())
            if not r.is_success:
                return None
            data = r.json()
    except (httpx2.HTTPError, ValueError):
        return None
    entries = data.get("running") if isinstance(data, dict) else None
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("model") == model:
            state = entry.get("state")
            return state if isinstance(state, str) else None
    return None


class _LoadProbe:
    """Muestrea si el modelo estaba cargado justo ANTES de que venza el plazo de lectura.

    Consultar después del `ReadTimeout` vería el estado de después: una carga que termina en ese
    hueco saldría `ready` y el fallo se contaría contra un modelo que solo tardaba en montarse. Un
    temporizador por intento muestrea a `HTTP_TIMEOUT - margen` y el timeout usa esa muestra. En el
    camino feliz la petición acaba antes y el temporizador se cancela sin consultar nada.
    """

    def __init__(
        self,
        model: str,
        *,
        delay_s: float,
        query: Callable[[str], str | None] = _llamaswap_state,
    ) -> None:
        self._model = model
        self._query = query
        self._state: str | None = None
        self._fired = threading.Event()
        self._ready = threading.Event()
        self._timer = threading.Timer(delay_s, self._sample)
        self._timer.daemon = True

    def start(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.cancel()

    def _sample(self) -> None:
        self._fired.set()
        try:
            self._state = self._query(self._model)
        except Exception:  # la sonda nunca puede tumbar la llamada que acompaña
            self._state = None
        finally:
            self._ready.set()

    def model_loaded(self, *, wait_s: float = _PROBE_QUERY_CAP_S) -> bool | None:
        """True si estaba `ready`, False si `starting`; None si no hubo muestra a tiempo."""
        self._timer.cancel()
        if self._timer.is_alive():
            # Si la consulta está en curso, se espera como mucho su tope; si no llega, no se sabe.
            self._timer.join(wait_s)
        if not (self._fired.is_set() and self._ready.is_set()):
            return None
        if self._state == "ready":
            return True
        if self._state == "starting":
            return False
        return None


def _backend_on_loopback() -> bool:
    """¿El host REAL de BASE_URL es de loopback? Lo que pide la regla 7 del clasificador.

    El host va SIN puerto: `config.backend_host()` lo lleva, y `_is_loopback_host("127.0.0.1:9292")`
    da `False`, así que la regla no se aplicaría nunca. Y es el host real, no el override de
    origen: un túnel en loopback hacia una máquina remota rechaza como loopback.
    """
    return config._is_loopback_host(config._split_host_port(config.BASE_URL)[0])


def _log_stopped(token: cancellation.Token, **fields: Any) -> None:
    """The usage event of a call that stopped before writing its own: `ok: false` (issue #476).

    It carries what the call measured until then: its duration, the turn and slot waits, and its
    real backend calls (`chunks`, and `wait_ms`/`inference_ms` from their timings), so the panel
    counts it in Errors and the log says where the time went.
    """
    entry = token.entry or {}
    attempts = list(token.attempts)
    _log_event(
        tool=str(entry.get("tool") or token.tool or ""),
        model=str(entry.get("model") or ""),
        source=str(entry.get("source") or "inline"),
        chars_in=int(entry.get("chars_in") or 0),
        chars_out=0,
        latency_ms=int((time.monotonic() - token.started) * 1000),
        ok=False,
        chunks=len(attempts),
        pieces=entry.get("pieces"),
        attempts=attempts,
        turn_wait_ms=token.turn_wait_ms,
        slot_wait_ms=token.slot_wait_ms,
        **fields,
    )


def _log_cancelled(token: cancellation.Token) -> None:
    """El evento de uso de una llamada cancelada: `ok: false`, `error: "cancelled"` y el motivo.

    La operación no llega a escribir el suyo (sale con `CallCancelled` antes), así que sin esto
    la llamada no constaría, o constaría como éxito si el hilo seguía hasta el final. The daemon's
    own deadline (issue #476) is one more reason: `cancel_reason: "deadline"`.
    """
    _log_stopped(
        token, error="cancelled", cancel_reason=token.reason or cancellation.REASON_ABORTED
    )


def _log_aborted(token: cancellation.Token) -> None:
    """Issue #476: the event of an operation that ended with an exception before writing its own.

    `error: "queue_saturated"` for a wait past `QUEUE_MAX_WAIT_S`; any other exception is
    `error: "exception"` with its type. Before, such a call left no line and the panel showed
    0 % errors with real failures in the same hour.
    """
    failure = token.failure
    if isinstance(failure, QueueSaturated):
        _log_stopped(token, error="queue_saturated")
    else:
        _log_stopped(token, error="exception", exception_type=type(failure).__name__)


class QueueSaturated(ToolError):
    """Issue #476: one wait for the turn or for a slot went past `config.QUEUE_MAX_WAIT_S`.

    A `ToolError`, so the caller gets the message (and the SDK logs one INFO line); the usage
    event is written by `_log_aborted` with `error: "queue_saturated"`.
    """


def _note_failure(exc: BaseException) -> None:
    """Issue #476: an operation that had started ends with `exc` before writing its event.

    Kept in the call's token so `cancellation.middleware` logs it (`_log_aborted`). A
    cancellation is not kept here: `_log_cancelled` already writes it. The first one wins.
    """
    token = cancellation.current()
    if token is None or token.failure is not None:
        return
    if isinstance(exc, cancellation.CallCancelled):
        return
    token.failure = exc


def _queue_limit_s() -> float:
    return max(0.0, float(config.QUEUE_MAX_WAIT_S))


# El último de la cadena, pegado al handler: da a cada `tools/call` su token y lo cancela si el
# cliente deja de esperarla (aviso, sesión cerrada, conexión cortada), o al agotar el plazo propio
# del daemon (`LOCAL_DELEGATE_CALL_MAX_S`, issue #476).
mcp.middleware.append(
    cancellation.middleware(
        _log_cancelled, on_failed=_log_aborted, deadline_s=lambda: config.CALL_MAX_S
    )
)


def _post_chat(model: str, payload: dict) -> ChatResult:
    """POST al endpoint /chat/completions con reintento opcional si el backend está caído."""
    headers = config.auth_headers()
    client = _SEND_CLIENT.get() or _get_client()
    for attempt in (1, 2):
        # Una sonda por intento: el plazo de lectura vuelve a contar en cada envío.
        probe = _LoadProbe(model, delay_s=_probe_delay())
        probe.start()
        try:
            r = client.post(f"{config.BASE_URL}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            # La respuesta pasa por el clasificador ANTES de tocarla: un 200 puede traer
            # `content: null`, o venir de un modelo que gastó `max_tokens` razonando.
            error_class = failures.classify(
                failures.BackendResponse(
                    status=r.status_code,
                    data=data if isinstance(data, dict) else None,
                    text=r.text[:300],
                )
            )
            reasoning_chars = _reasoning_chars_of(data)
            if error_class is not None:
                # Un 200 inservible también ocupó la GPU: su inferencia cuenta en el evento.
                return _body_failure(model, error_class, _timings_of(data), reasoning_chars)
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            return ChatResult(
                text=choice["message"]["content"].strip(),
                ok=True,
                finish_reason=choice.get("finish_reason"),
                tokens_in=usage.get("prompt_tokens"),
                tokens_out=usage.get("completion_tokens"),
                timings=_timings_of(data),
                reasoning_chars=reasoning_chars,
            )
        except httpx2.HTTPError as e:
            token = cancellation.current()
            # Lo cortó `_cut_client` porque la llamada se canceló: no hay backend que ofrecer
            # arrancar. Sale por el error genérico de abajo, y nadie lee ya ese resultado.
            cut = token is not None and token.cancelled
            # Un solo `except` para toda la familia, y la diferencia la marca el clasificador.
            # Antes había tres, y `ConnectTimeout` se colaba por el genérico: no es subclase de
            # `ConnectError` —son ramas hermanas—, así que un plazo de conexión agotado se
            # clasificaba como `http_error` y nadie ofrecía arrancar el backend.
            if isinstance(e, httpx2.ReadTimeout):
                # La señal de REQ-018 es la muestra tomada al vencer, no una consulta ahora.
                error_class = failures.classify(e, model_loaded=probe.model_loaded())
            else:
                error_class = failures.classify(e)
            if failures.is_backend_missing(e) and not cut:
                # REQ-018: un backend REMOTO no se arranca desde aquí, así que ni se pregunta ni
                # se intenta, valga AUTOSTART lo que valga. Con origen local, como siempre.
                local = config.backend_origin() == "local"
                # No hay nadie escuchando. Si el auto-arranque está activo, intenta levantarlo
                # (opt-in, específico de llama-swap) y reintenta una vez.
                if (
                    attempt == 1
                    and local
                    and config.AUTOSTART
                    and autostart.ensure_backend(wait=30)
                ):
                    continue
                # Sin auto-arranque, preguntar antes de rendirse. No contradice el «backend
                # opt-in»: sigue sin arrancar nada sin permiso, solo que ahora ese permiso se
                # puede dar en caliente. Si no hay a quién preguntar, o dicen que no, cae al
                # error de siempre.
                if attempt == 1 and local and not config.AUTOSTART:
                    answer = questions.ask(
                        i18n.t("mcp.question.start_backend.message", host=config.backend_host()),
                        questions.StartBackend,
                    )
                    if answer is not None and answer.start and autostart.ensure_backend(wait=30):
                        continue
                # REQ-017: la causa, con el texto único de `failures`, en vez de suponer que el
                # backend no está corriendo (con una VPN caída, lo está).
                cause = failures.connection_cause(e, loopback=_backend_on_loopback())
                return ChatResult(
                    text=ERROR_PREFIX
                    + i18n.t(
                        "mcp.error.connect",
                        detail=failures.detail(cause, host=config.backend_host(), exception=e),
                    ),
                    ok=False,
                    error="connect_error",
                    error_class=error_class,
                    connection_failure=cause.value,
                )
            if isinstance(e, httpx2.HTTPStatusError):
                return ChatResult(
                    text=ERROR_PREFIX
                    + i18n.t(
                        "mcp.error.http_status",
                        model=model,
                        status=e.response.status_code,
                        body=e.response.text[:300],
                    ),
                    ok=False,
                    error=f"http_{e.response.status_code}",
                    error_class=error_class,
                )
            if isinstance(e, httpx2.ReadTimeout):
                # El backend SÍ aceptó la conexión: lo más probable es que llama-swap esté
                # montando el modelo. Arrancar otro backend no arregla nada aquí.
                return ChatResult(
                    text=ERROR_PREFIX
                    + i18n.t(
                        "mcp.error.read_timeout",
                        model=model,
                        seconds=_machine(config.HTTP_TIMEOUT),
                    ),
                    ok=False,
                    error="read_timeout",
                    error_class=error_class,
                )
            return ChatResult(
                text=ERROR_PREFIX + i18n.t("mcp.error.endpoint", url=config.BASE_URL, error=e),
                ok=False,
                error="http_error",
                error_class=error_class,
            )
        except (KeyError, IndexError, ValueError) as e:
            return ChatResult(
                text=ERROR_PREFIX + i18n.t("mcp.error.unexpected_response", model=model, error=e),
                ok=False,
                error="bad_response",
                error_class=failures.FailureClass.MODEL,
            )
        finally:
            probe.cancel()
    # Aquí había un `retry_exhausted` que no se alcanzaba nunca: los dos intentos terminan
    # siempre en un `return`, porque los dos `continue` viven bajo `attempt == 1`. No se
    # dedujo leyendo, se midió: se enumeraron las 16 formas de terminar el `try` y ninguna
    # llegó hasta aquí, y con la guarda del intento quitada el mismo experimento sí la
    # alcanzaba —control positivo—. Lo que antes prometía esa línea lo garantiza ahora
    # `tests/test_post_chat_paths.py`, que sí se ejecuta. Este `raise` deja escrito ese invariante
    # (y que la función nunca cae al final con un `None` implícito).
    raise AssertionError("_post_chat: unreachable")


_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.IGNORECASE | re.DOTALL)
_THINK_UNCLOSED_RE = re.compile(r"^\s*<think(?:ing)?>.*", re.IGNORECASE | re.DOTALL)


def _strip_think(s: str) -> str:
    """Quita bloques <think>/<thinking> (modelos razonadores tipo Qwen3, R1-distill).

    Cubre también el bloque sin cerrar al inicio (p. ej. truncado por max_tokens a mitad
    del razonamiento): en ese caso no queda contenido útil que rescatar.
    """
    s = _THINK_RE.sub("", s)
    s = _THINK_UNCLOSED_RE.sub("", s)
    return s.strip()


def _think_chars(content: str) -> int:
    """The characters of the `<think>` blocks that `_strip_think` removes (the surrounding
    whitespace it strips is not reasoning, so it does not count)."""
    kept = _THINK_UNCLOSED_RE.sub("", _THINK_RE.sub("", content))
    return len(content) - len(kept)


def _reasoning_chars_of(data: Any) -> int | None:
    """REQ-018: how many characters of reasoning ONE backend response carried, never the text.

    `len(message.reasoning_content)` plus the `<think>` blocks in `content` (Qwen and R1-style
    models that do not split it). `None` when the response has no message to look at.
    """
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(message, dict):
        return None
    reasoning = message.get("reasoning_content")
    content = message.get("content")
    count = len(reasoning) if isinstance(reasoning, str) else 0
    if isinstance(content, str):
        count += _think_chars(content)
    return count


# --- Turno por conjunto de modelos compatibles (daemon-reparte-el-backend, REQ-002 a REQ-009) ---
# Una operación (una llamada a una tool, con todos sus trozos y saltos) pide turno ANTES que la
# plaza y lo conserva de principio a fin; las que usan modelos que chocan en llama-swap esperan a
# que les toque en vez de quitarse el modelo una a otra. El núcleo vive en `turn.py` y la
# relación de choques en `topology.py`; aquí solo se conectan.

#: Motivo de REQ-002 cuando el backend no es de loopback (la Mac contra la PC): sin turno. El valor
#: vive en `topology` para que `topology.reason_text` lo diga en el idioma vigente (B2a).
NO_TURN_REMOTE_BACKEND = topology.REMOTE_BACKEND


def _refresh_topology() -> None:
    """Gancho por tic de cada espera de turno: relee la topología (REQ-009, REQ-003 punto 5).

    Sin esto, una espera ya en cola seguiría con la relación de choques vieja hasta que alguien
    llegara o saliera. `foto()` no toca el disco si la `mtime` y el tamaño no cambian. Nunca
    lanza: un fallo aquí no puede tumbar una espera.
    """
    try:
        _topology()
    except Exception:  # la relectura es una mejora; la espera sigue con la relación que tenía
        pass


def _new_turn() -> turn.Turn:
    # La relación de choques real llega con la primera foto (`_on_snapshot_seen`), antes de que nadie
    # pida turno; la de partida no decide nada.
    return turn.Turn(lambda _a, _b: False, turn_max_s=config.TURN_MAX_S, on_tick=_refresh_topology)


_turn = _new_turn()
_turn_lock = threading.Lock()


@dataclass
class _TurnVersion:
    """La versión de la foto de topología que rige en `_turn` (REQ-009); `None` sin foto aún."""

    value: int | None = None


_turn_version = _TurnVersion()


def _reset_turn() -> None:
    """El estado del turno, a cero, con el `TURN_MAX_S` vigente (lo usan los tests)."""
    global _turn
    with _turn_lock:
        _turn = _new_turn()
        _turn_version.value = None


def _on_snapshot_seen(snapshot: topology.Snapshot) -> None:
    """REQ-009: una foto de versión nueva rige desde la siguiente concesión.

    Solo hacia delante: dos hilos que leen fotos distintas pueden llegar aquí en orden inverso, y
    la más vieja no puede pisar a la nueva.
    """
    with _turn_lock:
        if _turn_version.value is None or snapshot.version > _turn_version.value:
            _turn.topology_change(snapshot.clashes)
            _turn_version.value = snapshot.version


def _topology() -> topology.Snapshot | topology.NoTopology:
    """La foto de topología, o el motivo de que no haya turno (REQ-002).

    Cualquier `NoTopology`, sea cual sea su motivo, es «sin turno». Un backend que no es de
    loopback va sin turno aunque haya config: su llama-swap no es el de `LLAMASWAP_CONFIG`.
    """
    if not _backend_on_loopback():
        return topology.NoTopology(NO_TURN_REMOTE_BACKEND)
    snapshot = topology.snapshot()
    if isinstance(snapshot, topology.Snapshot):
        _on_snapshot_seen(snapshot)
    return snapshot


# --- Afinidad (REQ-010 a REQ-017 y los miembros de `loaded` de REQ-019, T15) -------------------
# Un alternativo con celda aprobada y vigente (`matrix`) que ya está cargado responde en lugar del
# modelo del rol. Solo en local (el turno exige topología y loopback: `_topology`), nunca con modelo
# explícito, y solo en la primera llamada de la operación: los trozos siguientes siguen en él.

#: Lo que puede fallar al tomar la foto de REQ-013: cualquiera deja el dato como «no se sabe».
_AFFINITY_QUERY_ERRORS = (llamaswap_api.QueryError, httpx2.HTTPError, ValueError, OSError)
#: Espera de backend en la primera llamada a partir de la cual, sin vuelo ajeno, la afinidad
#: se apunta como fallida: el modelo tuvo que cargarse (las cargas medidas, de 6 a 14 s; REQ-016).
_AFFINITY_FAILED_WAIT_MS = 3000
#: Tope de cada consulta de la foto de REQ-013, conexión incluida: se hace con la plaza en la mano
#: y REQ-004 solo deja esperar cosas externas con tope (1 s por consulta).
_AFFINITY_QUERY_CAP_S = 1.0

#: Llamadas al backend en vuelo de ESTE daemon, por modelo: la foto de `/api/events` las cuenta
#: también, y `affinity_foreign_flight` solo quiere las de otros clientes (REQ-016).
_own_calls: dict[str, int] = {}
_own_calls_lock = threading.Lock()


@contextmanager
def _own_call(model: str) -> Generator[None, None, None]:
    with _own_calls_lock:
        _own_calls[model] = _own_calls.get(model, 0) + 1
    try:
        yield
    finally:
        with _own_calls_lock:
            _own_calls[model] -= 1


def _own_calls_of(model: str) -> int:
    with _own_calls_lock:
        return _own_calls.get(model, 0)


def _affinity_prompt(tool: str) -> str | None:
    """El prompt de la huella de una tool, construido con el código VIGENTE (REQ-010).

    Los mismos parámetros que usó el corpus de la evaluación (`matrix.PROMPT_INPUTS`) pasan por
    las mismas funciones que usa la tool: si cambia `_guard` o el texto de la tool, cambia la
    huella y la celda queda «sin base». `None` si la tool no tiene celda posible.
    """
    builders: dict[str, Callable[[Any], str]] = {
        "local_translate": _translate_system,
        "local_lint_summary": _lint_system,
        "local_delegate": _guard,
    }
    inputs = matrix.PROMPT_INPUTS.get(tool)
    builder = builders.get(tool)
    if inputs is None or builder is None:
        return None
    return matrix.joined_prompt([builder(value) for value in inputs])


def _model_config(snapshot: topology.Snapshot, model: str) -> dict[str, Any] | None:
    """La entrada de `model` en la config de llama-swap, reducida a lo que mira la huella."""
    if snapshot.resolve(model) is None:
        return None
    return {"cmd": snapshot.cmd(model) or ""}


def _approved_alternatives(
    tool: str | None,
    role_name: str | None,
    role_model: str,
    snapshot: topology.Snapshot,
    size: int = 0,
) -> tuple[str, ...]:
    """Los alternativos de la matriz para esta tool y este rol: aprobados, en una dirección de
    REQ-011, vigentes (huella) y que admiten el tamaño (REQ-014). Sin red: solo config y disco."""
    if tool is None or role_name is None:
        return ()
    roles = config.models_by_role()
    prompt = _affinity_prompt(tool)
    language = i18n.response_language().value
    found: list[str] = []
    for cell in matrix.CELLS:
        if cell.tool != tool or cell.alternative in found or cell.compared_role != role_model:
            continue
        if not matrix.applies_to_language(cell, language):
            continue  # measured with the prompt of another response language
        if not matrix.allowed_direction(cell, role_name, roles):
            continue
        if cell.alternative not in config.ALLOWED_MODELS:
            continue
        if size > config.max_chars_for(cell.alternative):
            continue
        if not matrix.is_current(cell, _model_config(snapshot, cell.alternative), prompt):
            continue
        found.append(cell.alternative)
    return tuple(found)


def _activity_end(row: dict[str, Any] | None) -> float | None:
    """La hora de fin de la última petición (`timestamp` de v255, ISO con zona y truncada al
    segundo: T2 (a)), en segundos del reloj del sistema. `None` si no se puede leer."""
    stamp = row.get("timestamp") if row else None
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None


def _affinity_observe(
    alternatives: Collection[str], snapshot: topology.Snapshot
) -> matrix.Observed:
    """La foto `observado` de REQ-013, con la plaza ya en la mano y tope de 1 s por consulta.

    En orden: `/running`, la foto `inflight` de `/api/events` y, la última y solo si hace falta,
    `/api/metrics/activity` del id real de cada alternativo. Lo que falla queda sin dato y ese
    alternativo no cuenta como cargado con margen. `ahora` sale de `time.time()` (REQ-013).
    """
    backend = llamaswap_api.local_backend()
    cap = _AFFINITY_QUERY_CAP_S

    def real(model: str) -> str:
        return snapshot.resolve(model) or model

    observed = matrix.Observed(
        now=time.time(),
        margin_s=config.AFFINITY_MARGIN_S,
        clashes=snapshot.clashes,
        alias={model: real(model) for model in alternatives},
    )
    try:
        running = llamaswap_api.running(backend, cap_s=cap)
    except _AFFINITY_QUERY_ERRORS:
        return observed
    ttl: dict[str, int] = {}
    for entry in running:
        value = entry["ttl"]
        if value is None or value < 0:
            value = snapshot.effective_ttl(entry["id"])
        if value is not None:
            ttl[real(entry["id"])] = value
    ready = frozenset(real(e["id"]) for e in running if e["state"] == "ready")
    observed = replace(observed, ready=ready, ttl=ttl)
    try:
        counts = llamaswap_api.in_flight(backend, cap_s=cap, connect_s=cap)
    except _AFFINITY_QUERY_ERRORS:
        return observed
    in_flight: dict[str, int] = {}
    for model, count in counts.items():
        in_flight[real(model)] = in_flight.get(real(model), 0) + count
    observed = replace(observed, in_flight=in_flight)
    last_end: dict[str, float] = {}
    for model in alternatives:
        if not observed.needs_activity(model):
            continue
        try:
            end = _activity_end(llamaswap_api.activity(backend, real(model), cap_s=cap))
        except _AFFINITY_QUERY_ERRORS:
            continue
        if end is not None:
            last_end[real(model)] = end
    return replace(observed, last_end=last_end)


def _affinity_loaded_provider(
    tool: str | None,
    has_failed: str,
    own_items: frozenset[str],
    nobody_else: bool,
    role_name: str | None,
) -> tuple[str, ...]:
    """Los miembros de `loaded` (REQ-019): los alternativos aprobados y vigentes para la tool,
    distintos del que falló, que están en `propios` o, si el daemon no tiene a nadie más en
    `activos`, todos (el «cargado con margen» lo decide REQ-012 al conceder, con la plaza y la
    foto). Sin topología no hay celda vigente: `()` sin tocar la red."""
    snapshot = _topology()
    role_model = config.models_by_role().get(role_name or "")
    if not isinstance(snapshot, topology.Snapshot) or role_model is None:
        return ()
    return tuple(
        model
        for model in _approved_alternatives(tool, role_name, role_model, snapshot)
        if model != has_failed and (model in own_items or nobody_else)
    )


chains.register_loaded_provider(_affinity_loaded_provider)


class _OperationTurn:
    """El turno de UNA operación (REQ-003): se pide antes que la plaza y dura toda la operación.

    `ensure(modelo)` va justo antes de pedir la plaza de cada llamada. Si la operación ya tiene
    turno para ese modelo, no hace nada; si no —la primera llamada, o un salto de respaldo—, suelta
    el que tuviera y pide uno al final de la cola (REQ-006). Sin topología, con backend remoto o
    con un modelo que la config no conoce, no pide nada (REQ-002).

    Con afinidad (T15), la primera llamada pide `A = {rol} ∪ alternativos aprobados`; si la
    concesión trae varios, el modelo se elige con la plaza ya en la mano (`pick`, REQ-003
    «Elección» y REQ-012). Un salto a `loaded` pide turno con sus miembros y `direct` vacío
    (`ensure_loaded`).
    """

    def __init__(
        self,
        entry_id: int,
        role_model: str,
        tool: str | None = None,
        *,
        role_name: str | None = None,
        explicit: bool = False,
    ) -> None:
        self.entry_id = entry_id
        #: La tool de la operación: los miembros de `loaded` dependen de ella (REQ-019).
        self.tool = tool
        self.op_id = f"{os.getpid()}:{entry_id}"
        #: El modelo del rol de la operación: decide el de una concesión forzada (REQ-007).
        self.role = role_model
        #: El nombre del rol (`mechanical`…): las direcciones de la afinidad dependen de él.
        self.role_name = role_name
        #: Un modelo pedido por quien llama nunca usa afinidad (REQ-011).
        self.explicit = explicit
        #: El modelo para el que se pidió turno por última vez (o se decidió ir sin él).
        self.model: str | None = None
        self.wait_ms = 0
        self.forced = False
        self._turn: turn.Turn | None = None
        self._snapshot: topology.Snapshot | None = None
        self._chain: tuple[str, ...] = ()
        #: La reserva concedida tiene que reducirse eligiendo con la plaza en la mano.
        self._pending = False
        #: El turno pendiente es el de un salto a `loaded` (REQ-019).
        self._loaded_hop = False
        #: Ya hubo una primera llamada: la afinidad solo se decide en ella.
        self._started = False
        #: El alternativo que eligió la afinidad mientras siga siendo el modelo de la operación.
        self.affinity: str | None = None
        #: El alternativo que eligió la afinidad, aunque después un salto la apagara: el motivo de
        #: un respaldo posterior es su fallo (REQ-015) y el evento deja rastro de él.
        self.affinity_tried: str | None = None
        self.affinity_foreign_flight: int | None = None
        #: La clase con la que falló el alternativo cuando un salto apagó la afinidad.
        self._dropped_class: str | None = None
        self._first_wait_ms: int | None = None

    # --- pedir turno -------------------------------------------------------------------------

    def _on_wait_factory(self) -> tuple[Callable[[int, tuple[str, ...]], None], list[bool]]:
        waiting = [False]

        def on_wait(position: int, in_use: tuple[str, ...]) -> None:
            # Los datos primero: el panel nunca ve `local_wait: "turn"` sin `turn_in_use`.
            _inflight_turn(self.entry_id, in_use, position)
            if not waiting[0]:
                waiting[0] = True
                _inflight_local_wait(self.entry_id, "turn")

        return on_wait, waiting

    def _waiting_for(
        self,
        turn_state: turn.Turn,
        wait: Callable[[turn.OnWait, Callable[[], bool] | None], turn.Grant],
    ) -> turn.Grant:
        """Una espera de turno con su contabilidad: `turn_wait_ms` y las claves del panel.

        Si la llamada se cancela mientras espera, sale de la cola en el acto (`CallCancelled`).
        """
        on_wait_marks, waiting = self._on_wait_factory()
        token = cancellation.current()
        remove = token.on_cancel(turn_state.wake) if token is not None else (lambda: None)
        t0 = time.monotonic()
        # Issue #476: the queue is saturated when this ONE wait goes past `QUEUE_MAX_WAIT_S`.
        limit = _queue_limit_s()
        seen: dict[str, Any] = {"position": None, "in_use": (), "saturated": False}

        def on_wait(position: int, in_use: tuple[str, ...]) -> None:
            seen["position"], seen["in_use"] = position, in_use
            on_wait_marks(position, in_use)

        def stop() -> bool:
            if token is not None and token.is_cancelled():
                return True
            if limit > 0 and time.monotonic() - t0 > limit:
                seen["saturated"] = True
                return True
            return False

        try:
            try:
                grant = wait(on_wait, stop)
            except turn.AbandonedWait:
                cancellation.checkpoint()
                if seen["saturated"]:
                    raise QueueSaturated(
                        i18n.t(
                            "mcp.error.queue_saturated_turn",
                            waited=round(time.monotonic() - t0),
                            position=seen["position"] or 1,
                            models=", ".join(seen["in_use"]) or "-",
                        )
                    ) from None
                raise
        finally:
            remove()
            if waiting[0]:
                # Al conceder (o al salir por error), las tres claves fuera (REQ-008).
                waited_ms = int((time.monotonic() - t0) * 1000)
                self.wait_ms += waited_ms
                if token is not None:
                    token.turn_wait_ms += waited_ms
                _inflight_local_wait(self.entry_id, None)
                _inflight_turn(self.entry_id, None, None)
        if grant.forced:
            self.forced = True
        return grant

    def _reset(self) -> None:
        self.release_slot()
        # `model` se fija solo al conceder o al decidir «sin turno»: si `request` sale con error,
        # la operación no queda creyéndose con un turno que no tiene.
        self.model = None
        self._pending = False
        self._loaded_hop = False

    def ensure(
        self, model: str, chain: Sequence[str] = (), *, hop: bool = False, size: int = 0
    ) -> None:
        if not hop and self.affinity is not None and model == self.role:
            return  # los trozos siguientes siguen en el alternativo que eligió la afinidad
        if hop:
            self.affinity = None
        if self.model == model and not self._pending:
            return
        self._reset()
        snapshot = _topology()
        if not isinstance(snapshot, topology.Snapshot) or snapshot.resolve(model) is None:
            # Sin turno para todo lo que quede con este modelo, también si el motivo era pasajero
            # (un `ilegible` por un `OSError`): REQ-002, cualquier `NoTopology` es «sin turno».
            self.model = model
            return
        acceptable = {model}
        if not hop and not self._started and not self.explicit and model == self.role:
            acceptable.update(
                _approved_alternatives(self.tool, self.role_name, self.role, snapshot, size)
            )
        # Aclarado el 2026-10-07: el destino de un salto entra en `A'` como el rol (`direct`),
        # y `role` sigue siendo el original, que es el que mira una concesión forzada.
        request = turn.PendingRequest(
            self.op_id,
            frozenset(acceptable),
            self.role,
            chain_order=tuple(chain),
            direct=frozenset({model}),
        )
        self._grant(request, snapshot, chain, requested=model)

    def ensure_loaded(self, members: Sequence[str], chain: Sequence[str] = ()) -> bool:
        """El salto a `loaded` (REQ-019): turno con sus miembros y `direct` vacío; el modelo se
        elige al conceder (`pick`). `False` sin topología: entonces el salto va al primer miembro,
        como a un destino suelto (T12)."""
        self.affinity = None
        self._reset()
        snapshot = _topology()
        known = [
            m for m in members if isinstance(snapshot, topology.Snapshot) and snapshot.resolve(m)
        ]
        if not isinstance(snapshot, topology.Snapshot) or not known:
            return False
        request = turn.PendingRequest(
            self.op_id, frozenset(known), self.role, chain_order=tuple(chain)
        )
        self._loaded_hop = True
        self._grant(request, snapshot, chain, requested=None)
        return True

    def _grant(
        self,
        request: turn.PendingRequest,
        snapshot: topology.Snapshot,
        chain: Sequence[str],
        *,
        requested: str | None,
    ) -> None:
        turn_state = _turn
        grant = self._waiting_for(
            turn_state,
            lambda on_wait, stop: turn_state.request(request, on_wait, should_stop=stop),
        )
        self._turn = turn_state
        self._snapshot = snapshot
        self._chain = tuple(chain)
        if grant.model is not None and not self._loaded_hop:
            # Con un solo modelo en `A'`, ese (REQ-003, «Elección»).
            self.model = grant.model
            if requested is not None and grant.model != requested:
                self.affinity = self.affinity_tried = grant.model
        else:
            self._pending = True

    # --- elegir con la plaza en la mano ------------------------------------------------------

    def pick(self) -> tuple[str | None, bool]:
        """El modelo de esta llamada, ya con la plaza (REQ-003, «Elección»; REQ-012).

        `(modelo, False)` para enviar; `(None, False)` si la operación volvió a la cabeza de la
        cola (tras una forzada ajena): quien llama suelta la plaza y espera con `wait_again`;
        `(None, True)` si el salto a `loaded` no tiene ya ningún miembro que cumpla REQ-012: se
        salta sin gastar salto (REQ-019).
        """
        if not self._pending:
            return self.model, False
        assert self._turn is not None and self._snapshot is not None
        state = self._turn.snapshot()
        mine = state.active(self.op_id)
        reserve = mine.reserve if mine is not None else frozenset()
        others = [a for a in state.actives if a.id != self.op_id]
        own = frozenset(a.chosen for a in others if a.chosen is not None)
        observed = None
        if matrix.needs_snapshot(reserve, self.role, own):
            observed = _affinity_observe(reserve - {self.role}, self._snapshot)
        choice = matrix.choose(
            reserve,
            self.role,
            observed,
            own,
            approved=reserve - {self.role},
            chain_order=self._chain,
        )
        if choice is None:
            self._reset()
            return None, True
        candidates = [choice]
        if self.role in reserve and choice != self.role:
            candidates.append(self.role)
        model = self._turn.choose_without_waiting(self.op_id, candidates)
        if model is None:
            return None, False
        self._pending = False
        self.model = model
        if not self._loaded_hop and model != self.role:
            self.affinity = self.affinity_tried = model
            if observed is not None and observed.in_flight is not None:
                in_flight = observed.in_flight.get(observed.real(model), 0)
                self.affinity_foreign_flight = max(0, in_flight - _own_calls_of(model))
        self._loaded_hop = False
        return model, False

    def wait_again(self) -> None:
        """Sin plaza: espera la nueva concesión tras volver a la cabeza (REQ-004)."""
        assert self._turn is not None
        turn_state = self._turn
        self._waiting_for(
            turn_state,
            lambda on_wait, stop: turn_state.wait_for_grant(self.op_id, on_wait, should_stop=stop),
        )

    def note_attempt(self, attempt: Attempt) -> None:
        """La primera llamada al alternativo: su espera de backend decide `affinity_failed`."""
        self._started = True
        if attempt.model == self.affinity_tried and not attempt.ok and self._dropped_class is None:
            self._dropped_class = _class_value(attempt.error_class)
        if self._first_wait_ms is None and attempt.model == self.affinity:
            timings = attempt.timings or {}
            inference = sum(v for v in (timings.get("prompt_ms"), timings.get("predicted_ms")) if v)
            self._first_wait_ms = max(0, int(attempt.ms - inference))

    def release_slot(self) -> None:
        """Sale de `actives`. Idempotente; va en el `finally` de cada operación (REQ-007)."""
        if self._turn is not None:
            self._turn.release_slot(self.op_id)
            self._turn = None

    def log_fields(self) -> dict:
        fields: dict[str, Any] = {
            "turn_wait_ms": self.wait_ms,
            "turn": "forced" if self.forced else None,
        }
        if self.affinity is not None:
            fields["routing"] = "affinity"
            fields["affinity_foreign_flight"] = self.affinity_foreign_flight
            fields["affinity_failed"] = (
                self.affinity_foreign_flight == 0
                and self._first_wait_ms is not None
                and self._first_wait_ms >= _AFFINITY_FAILED_WAIT_MS
            ) or None
        elif self.affinity_tried is not None:
            fields["affinity_dropped"] = self.affinity_tried
            fields["affinity_dropped_class"] = self._dropped_class
        return fields


@contextmanager
def _slot(entry_id: int | None) -> Generator[None, None, None]:
    """Una plaza de `_chat_slots` para UNA llamada, con la marca de REQ-004 mientras se tiene.

    Si no hay plaza libre, la espera se publica como `local_wait: "slot"` y se borra al
    conseguirla (REQ-022). Con plaza libre no se escribe nada de más.
    """
    global _slot_waiters
    slots = _chat_slots
    token = cancellation.current()
    if token is not None:
        # Cada trozo pasa por aquí: una llamada cancelada no manda ni uno más.
        token.check()
    if not slots.acquire(blocking=False):
        if entry_id is not None:
            _inflight_local_wait(entry_id, "slot")
        limit = _queue_limit_s()
        t0 = time.monotonic()
        with _slot_waiters_lock:
            _slot_waiters += 1
        try:
            if token is None and limit <= 0:
                slots.acquire()
            else:
                while not slots.acquire(timeout=cancellation.POLL_S):
                    if token is not None:
                        token.check()
                    if limit > 0 and time.monotonic() - t0 > limit:
                        # Issue #476: the queue does not move; say so now, not at the deadline.
                        with _slot_waiters_lock:
                            others = max(0, _slot_waiters - 1)
                        raise QueueSaturated(
                            i18n.t(
                                "mcp.error.queue_saturated_slot",
                                waited=round(time.monotonic() - t0),
                                busy=getattr(slots, "_initial_value", None)
                                or config.MAX_CONCURRENT_REQUESTS,
                                waiting=others,
                            )
                        )
        finally:
            with _slot_waiters_lock:
                _slot_waiters -= 1
            if token is not None:
                token.slot_wait_ms += int((time.monotonic() - t0) * 1000)
            if entry_id is not None:
                _inflight_local_wait(entry_id, None)
    try:
        if token is not None:
            token.check()
        with turn.slot_taken():
            yield
    finally:
        slots.release()


def _send(model: str, body: dict) -> ChatResult:
    """UN envío al backend, dentro de `in_flight()` y contado como llamada propia.

    En una `tools/call` el envío va por un cliente propio y se puede cortar: si la llamada se
    cancela, `CallCancelled` sale ya (`cancellation.run_abandonable`) y `_cut_client` cierra la
    conexión de ESE envío, para que el backend deje de generar (medido en vivo el 2026-10-22: sin
    el corte, llama-swap no cambiaba de modelo hasta acabar el trozo abandonado, ~30 s). Un cliente
    propio y no el compartido porque cerrar el compartido cortaría los envíos de otras llamadas.
    El contador de vuelo y el de llamadas propias siguen el envío real.
    """
    turn_state = _turn
    token = cancellation.current()
    if token is None:
        with turn_state.in_flight(), _own_call(model):
            return _post_chat(model, body)

    own = _new_client()
    remove = token.on_cancel(lambda: _cut_client(own))

    def post() -> ChatResult:
        _SEND_CLIENT.set(own)
        try:
            with turn_state.in_flight(), _own_call(model):
                return _post_chat(model, body)
        finally:
            remove()
            own.close()

    return cancellation.run_abandonable(post)


def _call_model(
    model: str,
    payload: dict,
    json_schema_fallback: bool,
    role_params: _RoleParams | None = None,
) -> tuple[ChatResult, str | None, int]:
    """Una llamada a UN modelo, con el reintento sin schema de siempre si el backend dio 400.

    Cada envío va dentro de `in_flight()`, también sin turno: el reloj de la red de seguridad no
    corre mientras el daemon tiene alguna llamada al backend en vuelo (REQ-007).

    Layer 2 of REQ-012 is applied here, on a new dict: `payload` is shared by every attempt of the
    operation (fallback, chunks) and is never mutated. Without `role_params` the body is today's.

    REQ-015: the first `http_400` of the operation on a body that carries the role's parameters is
    retried ONCE with the tool's body (no role keys, the tool's `temperature` and `max_tokens`,
    `response_format` kept), before the schema retry. If that works the parameters are off for the
    rest of the operation; if not, nothing is marked and today's flow goes on with them. Both POST
    belong to this one call, so to the same `Attempt`, and so does the `reasoning_chars` of every
    POST (REQ-018), whichever result is returned.
    """
    t0 = time.monotonic()
    request_body = {"model": model, **payload}
    tool_body = request_body
    if role_params is not None:
        request_body = role_params.body_for(model, request_body)
    result = _send(model, request_body)
    responses = [result]
    if (
        not result.ok
        and result.error == "http_400"
        and role_params is not None
        and request_body != tool_body
        and role_params.claim_probe()
    ):
        retry = _send(model, tool_body)
        responses.append(retry)
        if retry.ok:
            role_params.mark_rejected()
            request_body, result = tool_body, retry
    json_schema_status = "used" if "response_format" in request_body else None
    if json_schema_status and not result.ok and result.error == "http_400":
        if json_schema_fallback:
            # El backend no soporta response_format con schema: reintenta en modo libre.
            request_body.pop("response_format", None)
            result = _send(model, request_body)
            responses.append(result)
            json_schema_status = "fallback"
        else:
            json_schema_status = "error"
    counted = [r.reasoning_chars for r in responses if r.reasoning_chars is not None]
    if counted and sum(counted) != result.reasoning_chars:
        result = replace(result, reasoning_chars=sum(counted))
    return result, json_schema_status, int((time.monotonic() - t0) * 1000)


def _attempt(
    model: str,
    payload: dict,
    json_schema_fallback: bool,
    state: cooldown.CooldownState,
    attempts: list[Attempt],
    role_params: _RoleParams | None = None,
) -> tuple[ChatResult, str | None]:
    """UNA llamada y su reintento sin schema, DENTRO de la plaza; anota el intento y el estado."""
    result, schema, ms = _call_model(model, payload, json_schema_fallback, role_params)
    attempt = Attempt(
        model,
        result.ok,
        result.error,
        result.error_class,
        ms,
        result.timings,
        result.reasoning_chars,
    )
    attempts.append(attempt)
    token = cancellation.current()
    if token is not None:
        # Issue #476: if the call is aborted later, its event still has its real backend calls.
        token.attempts.append(attempt)
    if result.ok:
        state.record_success(model)
    elif result.error_class is not None:
        state.record_failure(model, result.error_class)
    _note_backend_reach(result)
    return result, schema


def _note_backend_reach(result: ChatResult) -> None:
    """El corte por backend inalcanzable (issue #436): un fallo de CONEXIÓN suma; cualquier otra
    respuesta (un éxito, un 5xx, un plazo de lectura, un error del modelo) dice que el backend
    responde y lo deja limpio. `record_success` sin entrada no escribe nada."""
    breaker = cooldown.backend_breaker()
    if result.connection_failure:
        breaker.record_failure(cooldown.backend_key(), failures.FailureClass.ENDPOINT)
    else:
        breaker.record_success(cooldown.backend_key())


def _backend_down_text() -> str | None:
    """Con el corte abierto, el error que devuelve la tool AL MOMENTO, sin llamar al backend ni
    registrar una delegación; `None` si hay que llamarlo (cerrado, o vencido: la llamada es la
    prueba). Deja una línea `skip` en `backend-breaker-events.jsonl` para poder contarlas.
    """
    breaker = cooldown.backend_breaker()
    key = cooldown.backend_key()
    cut = breaker.lookup(key)
    if cut is None:
        return None
    breaker.record_skip(key)
    now = time.time()
    since = cut.since if cut.since is not None else now
    return ERROR_PREFIX + i18n.t(
        "mcp.error.backend_down",
        host=config.backend_host(),
        minutes=_machine(max(0.0, now - since) / 60),
        until=datetime.fromtimestamp(cut.until, UTC).strftime("%H:%M:%S UTC"),
        remaining=_machine(cut.remaining_s),
    )


def _next_hop(
    steps: Sequence[str],
    since: int,
    *,
    model: str,
    size: int,
    capacity: bool,
    state: cooldown.CooldownState,
    hops: int,
    last: ChatResult | None,
    loaded_members: Callable[[], Sequence[str]],
    attempted: Collection[str] = (),
) -> tuple[int, tuple[str, ...]] | None:
    """La decisión de saltar, FUERA de la plaza: (índice del paso, destinos), o `None`.

    Los destinos son uno, el del paso, salvo en el paso `loaded`: ahí son todos sus miembros que
    valen, y el salto pide turno con ese conjunto y elige al conceder (REQ-019, T15).

    - tras un salto fallido, solo sigue un fallo del modelo, y nunca tras uno de capacidad;
    - nunca más de `FALLBACK_MAX_HOPS` saltos;
    - con un fallo de capacidad solo vale el paso `loaded` (REQ-021);
    - el paso `loaded` se resuelve aquí, en el momento del salto (`loaded_members`, REQ-019); sin
      miembros que valgan se salta **sin gastar salto**;
    - un candidato fuera del catálogo, enfriado o cuyo tope no admite la entrada se salta sin
      llamarlo (REQ-003), y no gasta salto;
    - un candidato ya intentado en esta llamada (`intentados`: el pedido y cada destino) tampoco se
      vuelve a llamar: un miembro de `loaded` que repite un paso posterior no se llama dos veces.
    """
    if last is not None and (capacity or last.error_class != failures.FailureClass.MODEL):
        return None
    if hops >= config.FALLBACK_MAX_HOPS:
        return None
    for i in range(since, len(steps)):
        step = steps[i]
        if step == chains.LOADED:
            candidates: Sequence[str] = loaded_members()
        elif capacity:
            continue
        else:
            candidates = (step,)
        valid = tuple(
            candidate
            for candidate in candidates
            if not (
                candidate == model
                or candidate in attempted
                or candidate not in config.ALLOWED_MODELS
                or size > config.max_chars_for(candidate)
                or state.lookup(candidate) is not None
            )
        )
        if valid:
            return i, valid
    return None


def _loaded_members(op: _OperationTurn | None, has_failed: str) -> tuple[str, ...]:
    """Los miembros del paso `loaded` para este salto (REQ-019), con lo que el daemon sabe de sí.

    `own_items` son los modelos elegidos por las demás operaciones de este daemon en `actives`, y
    `nobody_else` si no hay ninguna otra. Sin proveedor registrado `chains` devuelve `()` sin
    consultar nada. Con turno, el salto pide turno con el conjunto (`direct` vacío) y elige al
    conceder (`_OperationTurn.ensure_loaded` y `pick`); sin turno va al primero que vale (T12).
    """
    op_id = op.op_id if op is not None else None
    others = [a for a in _turn.snapshot().actives if a.id != op_id]
    own_items = frozenset(a.chosen for a in others if a.chosen is not None)
    tool = op.tool if op is not None else None
    role_name = op.role_name if op is not None else None
    return chains.loaded_members(tool, has_failed, own_items, not others, role_name)


def _first(result: ChatResult | None) -> ChatResult:
    """La primera llamada de una operación nunca es un salto a `loaded`, así que siempre trae
    resultado (`call` vuelve al rol si la afinidad se queda sin modelo). Por si acaso, un error
    limpio en vez de un `AssertionError`."""
    if result is None:
        return ChatResult(
            text=ERROR_PREFIX + i18n.t("mcp.error.no_model_left"),
            ok=False,
            error="no_model",
        )
    return result


def _with_fallback(
    model: str,
    payload: dict,
    *,
    role: str | None,
    explicit: bool,
    size: int,
    json_schema_fallback: bool,
    op: _OperationTurn | None = None,
    entry_id: int | None = None,
    role_params: _RoleParams | None = None,
) -> tuple[ChatResult, str | None, list[Attempt]]:
    """El modelo pedido y, si su fallo lo permite, los candidatos de la cadena de su rol.

    Reglas, en el orden en que se aplican:
    - un modelo explícito se envía aunque esté enfriado, y sin respaldo (REQ-005);
    - el modelo pedido en enfriamiento no se llama: se va directo a la cadena (REQ-009);
    - solo saltan los fallos del modelo y los de capacidad, y estos solo a `loaded` y sin
      segundo salto (REQ-002, REQ-018 de F3 enmendado por REQ-021);
    - el resto de la decisión, en `_next_hop`.

    Cada llamada toma y suelta su propia plaza (`_attempt` va dentro, la decisión fuera). Un salto
    suelta la plaza del intento anterior, cambia el turno de la operación al destino y solo
    después pide plaza (REQ-006, que enmienda REQ-017 de F3). El tope de
    `MAX_CONCURRENT_REQUESTS` se sigue cumpliendo: la plaza es el mismo semáforo.

    La cadena se resuelve aquí, y solo si hace falta: resolverla antes leería la config de
    llama-swap en cada delegación, también en el camino feliz.
    """
    state = cooldown.from_config()
    attempts: list[Attempt] = []
    schema: str | None = None

    def call(
        target_model: str,
        chain: Sequence[str] = (),
        *,
        hop: bool = False,
        members: Sequence[str] = (),
    ) -> ChatResult | None:
        """Una llamada: el turno siempre ANTES que la plaza (REQ-004) y, con varios modelos en la
        reserva, la elección con la plaza en la mano (REQ-003, «Elección»). `None`: el salto a
        `loaded` se queda sin miembro que cumpla REQ-012 y se salta sin gastar salto (REQ-019)."""
        nonlocal schema
        if op is not None:
            if not members:
                op.ensure(target_model, chain, hop=hop, size=size)
            elif not op.ensure_loaded(members, chain):
                op.ensure(members[0], chain, hop=True)
        while True:
            retry_role = False
            with _slot(entry_id):
                if op is None:
                    target, skip = (members[0] if members else target_model), False
                else:
                    target, skip = op.pick()
                if skip and members:
                    return None
                if skip:
                    # La afinidad se quedó sin modelo al elegir (sin el rol en `A'` y sin foto):
                    # fuera de la plaza, la operación pide turno para el rol, sin afinidad.
                    retry_role = True
                elif target is not None:
                    result, schema = _attempt(
                        target, payload, json_schema_fallback, state, attempts, role_params
                    )
                    if op is not None:
                        op.note_attempt(attempts[-1])
                    return result
            assert op is not None
            if retry_role:
                op.ensure(target_model, chain, hop=True, size=size)
                continue
            # Volvió a la cabeza de la cola tras una forzada ajena: sin plaza, a esperar.
            op.wait_again()

    if explicit:
        return _first(call(model)), schema, attempts

    cooling = state.lookup(model)
    original: ChatResult | None = None
    error_class: str | None = None
    served = model
    if cooling is None:
        original = _first(call(model))
        if original.ok or original.error_class not in _HOPPABLE_CLASSES:
            return original, schema, attempts
        error_class = original.error_class
        served = attempts[-1].model if attempts else model

    steps = chains.resolve(role).steps if role and config.FALLBACK else ()
    # El orden de la cadena para una concesión forzada (REQ-007): solo modelos concretos.
    chain = tuple(step for step in steps if step != chains.LOADED)
    if served != model:
        # Falló el alternativo que eligió la afinidad: el primer candidato es el modelo del rol, y
        # después su cadena, con el tope de saltos de siempre (REQ-015).
        steps = (model, *steps)
    hops = 0
    start = 0
    last: ChatResult | None = None
    has_failed = served
    attempted = {served}
    while True:
        next_step = _next_hop(
            steps,
            start,
            model=served,
            size=size,
            # Un fallo de capacidad solo salta a `loaded` (REQ-021), salvo el del alternativo que
            # eligió la afinidad: la eligió el daemon, no quien llama, así que se prueba el rol y
            # su cadena (REQ-015; decisión del usuario del 2026-10-07).
            capacity=error_class == failures.FailureClass.CAPACITY and served == model,
            state=state,
            hops=hops,
            last=last,
            loaded_members=lambda f=has_failed: _loaded_members(op, f),
            attempted=attempted,
        )
        if next_step is None:
            break
        index, targets = next_step
        start = index + 1
        if steps[index] == chains.LOADED:
            result = call(targets[0], chain, hop=True, members=targets)
        else:
            result = call(targets[0], chain, hop=True)
        if result is None:
            continue  # `loaded` sin miembro al conceder: sin gastar salto (REQ-019)
        hop_target = attempts[-1].model
        hops += 1
        has_failed = hop_target
        attempted.add(hop_target)
        last = result
        if last.ok:
            return last, schema, attempts

    base = original if original is not None else _cooldown_error(model, cooling)
    tried = [i for i in attempts if i.model != model]
    if not tried:
        return base, schema, attempts
    # REQ-008: el error del modelo pedido, igual que hoy, y una línea con lo que se probó.
    tried_list = ", ".join(f"{i.model} ({i.error})" for i in tried)
    return (
        ChatResult(
            text=(
                f"{base.text}\n{FALLBACK_MARKER}"
                f"{i18n.t('mcp.fallback.also_failed', models=tried_list)}]"
            ),
            ok=False,
            error=base.error,
            finish_reason=base.finish_reason,
            tokens_in=base.tokens_in,
            tokens_out=base.tokens_out,
            error_class=base.error_class,
            connection_failure=base.connection_failure,
        ),
        schema,
        attempts,
    )


def _run_chat(
    model: str,
    system: str,
    user: str | list[dict],
    max_tokens: int,
    temperature: float,
    *,
    response_format: dict | None = None,
    json_schema_fallback: bool = False,
    role: str | None = None,
    explicit: bool = False,
    size: int | None = None,
    entry_id: int | None = None,
    op: _OperationTurn | None = None,
    role_params: _RoleParams | None = None,
) -> tuple[ChatResult, int, str | None, list[Attempt]]:
    """UNA llamada lógica al endpoint bajo el semáforo de concurrencia, con su respaldo.

    Devuelve (resultado, latency_ms, estado_json_schema, intentos): `attempts` son las llamadas
    reales al backend, en orden. No registra nada en el log ni toca el inflight: de eso se
    encargan _chat (una llamada = un evento) y _chat_chunked (N llamadas = un evento con `chunks`).

    Cada llamada al backend toma su plaza y la suelta al terminar; el salto va FUERA de la plaza
    (REQ-006, que enmienda REQ-017 de F3) y DESPUÉS del reintento sin schema (REQ-002), y el
    mecanismo nunca supera `MAX_CONCURRENT_REQUESTS`. `size` es la entrada que se valida contra
    el tope de cada candidato; sin él, el largo de `user`.

    `entry_id` es la entrada en vuelo de la delegación: si no hay plaza libre, la espera se publica
    en ella como `local_wait: "slot"` y se borra al conseguirla (REQ-022). Con plaza libre no se
    escribe nada de más. `op` es el turno de la operación: se asegura antes de cada plaza. La
    latencia incluye las esperas de turno y de plaza, como incluía la de plaza.

    `role_params` are the per-role backend parameters of the operation (REQ-012), resolved once by
    whoever starts it; this function builds layers 1 and 3 as before and `_call_model` adds layer 2.
    """
    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if size is None:
        size = len(user) if isinstance(user, str) else 0

    t0 = time.monotonic()
    result, json_schema_status, attempts = _with_fallback(
        model,
        payload,
        role=role,
        explicit=explicit,
        size=size,
        json_schema_fallback=json_schema_fallback,
        op=op,
        entry_id=entry_id,
        role_params=role_params,
    )
    return result, int((time.monotonic() - t0) * 1000), json_schema_status, attempts


class _RoleParams:
    """The per-role backend parameters of ONE operation (REQ-009, REQ-012).

    Resolved once, when the operation starts, with the role it started with, and kept apart from
    `_CurrentModel.role` (which becomes `None` after a hop): every real call of the operation
    (attempt, schema retry, fallback, chunk, map/reduce step) carries the same values. The flags
    are REQ-015 (rejection) and REQ-023 (context), and go to the event with
    `_backend_params_log_fields` (REQ-018); the reasoning characters travel in each `Attempt`.
    The chunks and the map/reduce steps run one after the other today; the lock is a cheap
    defence, there is no race to chase.
    """

    def __init__(self, role: str, resolved: backend_params.Effective) -> None:
        self.role = role
        #: The effective values of the role, in catalog order, after REQ-011.
        self.values: dict[str, object] = dict(resolved.values)
        self.source: dict[str, str] = dict(resolved.source)
        self.warnings: list[backend_params.Warning] = list(resolved.warnings)
        thinking = self.values.get("enable_thinking")
        self.thinking: bool | None = thinking if isinstance(thinking, bool) else None
        budget = self.values.get("reasoning_budget_tokens")
        self.budget: int | None = budget if self.thinking is True else None
        #: REQ-015: the call without parameters was already tried in this operation (once, however
        #: it went) and, if it worked, the parameters are off for the rest of the operation.
        self.probed = False
        self.rejected = False
        #: REQ-023: `"context"` once a call of the operation went without reasoning, else `None`.
        self.reasoning_skipped: str | None = None
        self.lock = threading.Lock()

    def body_for(self, model: str, body: dict) -> dict:
        """The body of ONE real call to `model` (the real target: affinity and fallback included).

        After a rejection (REQ-015) it is `body` itself, the tool's. Otherwise layer 2, with the
        reasoning off for this call alone when it does not fit in the context of `model` (REQ-023).
        """
        with self.lock:
            if self.rejected:
                return body
        thinking_allowed = self._reasoning_fits(model, body)
        if not thinking_allowed:
            with self.lock:
                self.reasoning_skipped = "context"
        return self.apply(body, thinking_allowed=thinking_allowed)

    def _reasoning_fits(self, model: str, body: dict) -> bool:
        """REQ-023: `ceil(chars × MARGIN / CHARS_PER_TOKEN) + tool cap + budget ≤ n_ctx`.

        `chars` are the system prompt plus the whole user message. Without reasoning on there is
        nothing to check, and `vision` is left out: its input is an image, not characters.
        """
        if self.budget is None or self.role == "vision":
            return True
        texts = [message.get("content") for message in body.get("messages", ())]
        chars = sum(len(text) for text in texts if isinstance(text, str))
        estimate = math.ceil(chars * config.REASONING_CONTEXT_MARGIN / config.CHARS_PER_TOKEN)
        n_ctx, _estimated = llamaswap_config.model_context_size(model)
        return estimate + body["max_tokens"] + self.budget <= n_ctx

    def claim_probe(self) -> bool:
        """True for the first `http_400` of the operation only (REQ-015: one probe, at most)."""
        with self.lock:
            if self.probed:
                return False
            self.probed = True
            return True

    def mark_rejected(self) -> None:
        """The backend took the call without the parameters: off for the rest of the operation."""
        with self.lock:
            self.rejected = True

    def apply(self, body: dict, *, thinking_allowed: bool = True) -> dict:
        """Layer 2 of REQ-012 on a NEW dict, keeping the key order of `body` (REQ-022).

        `temperature` and `max_tokens` are replaced in place (the role's temperature wins over the
        tool's, REQ-010; the budget is added to the tool's cap, REQ-011); the role's other keys go
        at the end. A key already in `body` is a contract key (layer 3) and is never replaced.
        """
        overrides, extra = backend_params.to_body(
            self.values,
            tool_temperature=body["temperature"],
            tool_max_tokens=body["max_tokens"],
            thinking_allowed=thinking_allowed,
        )
        merged = dict(body)
        for key, value in overrides.items():
            merged[key] = value
        for key, value in extra.items():
            if key not in merged:
                merged[key] = value
        return merged


def _role_params_for(role: str | None, explicit: bool) -> _RoleParams | None:
    """The parameters of one operation, or `None`: then the body is exactly today's (REQ-022).

    `None` with a model chosen by the caller (REQ-013), without a role, or when the role has no
    effective key. Read on every operation; `backend_params` caches by the file's stat and the
    variable, so a change is seen by the next operation without a restart (REQ-009).
    """
    if explicit or role is None:
        return None
    resolved = backend_params.effective(role)
    if not resolved.values:
        return None
    return _RoleParams(role, resolved)


def _backend_params_log_fields(role_params: _RoleParams | None) -> dict:
    """The REQ-018 fields of the event, as `_log_event` keywords; `{}` without parameters.

    `backend_params` lists what the operation was resolved with, also after a rejection (the
    values that were tried). Only accepted values reach `_RoleParams`, so a dropped entry (and its
    value) can never be here (REQ-006).
    """
    if role_params is None:
        return {}
    with role_params.lock:
        rejected = role_params.rejected
        skipped = role_params.reasoning_skipped
    params: dict = {"role": role_params.role, "values": dict(role_params.values)}
    from_env = {
        key: backend_params.SOURCE_ENV
        for key, origin in role_params.source.items()
        if origin == backend_params.SOURCE_ENV and key in role_params.values
    }
    if from_env:
        params["source"] = from_env
    fields: dict = {"backend_params": params}
    if rejected:
        fields["backend_params_rejected"] = True
    if skipped is not None:
        fields["reasoning_skipped"] = skipped
    return fields


class _CurrentModel:
    """El modelo de una operación de varios trozos, que cambia como mucho una vez (REQ-006).

    En cuanto un trozo lo responde un respaldo, los siguientes van directos a ese respaldo y sin
    otra cadena: la salida no alterna modelos y no se vuelve a llamar al que acaba de fallar.
    """

    def __init__(
        self,
        model: str,
        role: str | None,
        explicit: bool,
        entry_id: int | None = None,
        op: _OperationTurn | None = None,
        role_params: _RoleParams | None = None,
    ) -> None:
        #: La entrada en vuelo de la operación, para publicar su espera local (REQ-022).
        self.entry_id = entry_id
        #: The per-role parameters of the operation, resolved once with the role it started with.
        #: Kept apart from `role`, which becomes `None` after a hop (REQ-012).
        self.role_params = role_params
        #: El turno de la operación: tras un salto queda en el destino, que es el que siguen
        #: usando los trozos de después (REQ-006).
        self.op = op
        self.requested = model
        self.model = model
        self.role = None if explicit else role
        self.explicit = explicit
        #: El trozo en curso; `None` fuera de los trozos (la reducción de map-reduce).
        self.chunk: int | None = None
        self.hop: dict | None = None
        #: El estado del schema JSON de la primera llamada que lo pidió (`local_extract` troceado).
        self.json_schema: str | None = None

    def call(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
        *,
        size: int,
        response_format: dict | None = None,
        json_schema_fallback: bool = False,
    ) -> tuple[ChatResult, int, list[Attempt]]:
        result, ms, schema, attempts = _run_chat(
            self.model,
            system,
            user,
            max_tokens,
            temperature,
            response_format=response_format,
            json_schema_fallback=json_schema_fallback,
            role=self.role,
            explicit=self.explicit,
            size=size,
            entry_id=self.entry_id,
            op=self.op,
            role_params=self.role_params,
        )
        if self.json_schema is None:
            self.json_schema = schema
        info = _fallback_info(self.model, result, attempts, self.affinity_tried)
        if info is not None:
            if self.hop is None:
                self.hop = {**info, "instead_of": self.requested, "chunk": self.chunk}
            self.model = info["answered_by"]
            self.role = None
        return result, ms, attempts

    @property
    def affinity(self) -> str | None:
        """El alternativo que eligió la afinidad para el modelo pedido, si sigue vigente (T15)."""
        return self.op.affinity if self.op is not None else None

    @property
    def affinity_tried(self) -> str | None:
        return self.op.affinity_tried if self.op is not None else None

    @property
    def served(self) -> str:
        """El modelo que responde: el alternativo de la afinidad en lugar del del rol (REQ-016)."""
        if self.affinity is not None and self.model == self.requested:
            return self.affinity
        return self.model

    def log_fields(self, failed: ChatResult | None) -> dict:
        """Los campos del respaldo para el evento de la operación entera (REQ-013)."""
        fields: dict = {
            "error_class": _class_value(failed.error_class) if failed else None,
            # REQ-017: la causa de un `connect_error` también en las delegaciones troceadas.
            "connection_failure": failed.connection_failure if failed else None,
        }
        if self.hop is not None:
            fields["model_requested"] = self.requested
            fields["fallback_reason"] = self.hop["reason"]
            fields["fallback_class"] = self.hop["class"]
        elif self.affinity is not None:
            fields["model_requested"] = self.requested
        if self.op is not None:
            fields.update(self.op.log_fields())
        fields.update(_backend_params_log_fields(self.role_params))
        return fields

    def notice(self, multiple: bool) -> str:
        if self.hop is None:
            return ""
        origin = None
        if multiple:
            chunk = self.hop["chunk"]
            origin = (
                i18n.t("mcp.warning.origin.chunk", chunk=chunk)
                if chunk is not None
                else i18n.t("mcp.warning.origin.reduce")
            )
        return _fallback_notice(self.hop, origin)


#: Unidades de la línea de ahorro: código → clave del catálogo.
_FEEDBACK_UNITS = {
    "chars": "mcp.receipt.unit.chars",
    "image_bytes": "mcp.receipt.unit.image_bytes",
}


def _savings_feedback(chars_in: int, label: str, *, event: dict) -> str:
    """Línea de ahorro que se anexa al resultado cuando la entrada se leyó server-side.

    `event` es la fila en curso ya fundida (`cost.in_flight_row`): los tokens son de **Claude**
    (`claude_tokens`, REQ-035), nunca el `tokens_in` del modelo local. Una imagen dice solo los
    bytes: sin dimensiones no hay forma de saber sus tokens de Claude (REQ-038).
    """
    unit = i18n.t(_FEEDBACK_UNITS[label])
    if cost.is_image(event):
        return "\n\n" + i18n.t("mcp.receipt.read_server_side", amount=_machine(chars_in), unit=unit)
    tokens = claude_tokens(chars_in, kind="text", event=event)
    return "\n\n" + i18n.t(
        "mcp.receipt.read_server_side_tokens",
        amount=_machine(chars_in),
        unit=unit,
        tokens=_machine(tokens),
    )


def _chat(
    model: str,
    system: str,
    user: str | list[dict],
    max_tokens: int,
    temperature: float = 0.2,
    *,
    tool: str = "local_delegate",
    chars_in: int = 0,
    source: str = "inline",
    truncated_in: bool = False,
    raw_len: int | None = None,
    path: str | None = None,
    response_format: dict | None = None,
    json_schema_fallback: bool = False,
    feedback_label: str = "chars",
    feedback: bool = True,
    input_unit: str = "chars",
    strip_fences: bool = False,
    write_to: Path | None = None,
    role: str | None = None,
    explicit: bool = False,
    fallback: dict | None = None,
    postprocess: Callable[[str, bool], str] | None = None,
    num_sections: int | None = None,
    focus: bool = False,
    report: dict | None = None,
) -> str:
    """POST al endpoint. Devuelve solo texto y registra la llamada en USAGE_LOG.

    `role` habilita el respaldo de ese rol; `explicit` lo apaga para un modelo elegido por quien
    llama (REQ-005). Con `fallback`, el aviso de que respondió otro modelo se deja en ese dict en
    vez de pegarlo al texto: lo usa quien parsea el resultado (REQ-007). Con `report`, lo mismo
    para el aviso de salida truncada: va a `report["truncated_out"]` y no al texto (B2c).

    `user` acepta un `str` (texto->texto) o una lista de bloques de contenido
    OpenAI-compatible (p. ej. `[{"type":"text",...},{"type":"image_url",...}]` para
    local_describe_image).
    """
    down = _backend_down_text()
    if down is not None:
        return down
    entry_id = _inflight_start(tool=tool, model=model, source=source, chars_in=chars_in)
    # Turno por operación (REQ-003): una llamada simple (también la de imagen) es una operación.
    op = _OperationTurn(entry_id, model, tool, role_name=role, explicit=explicit)
    try:
        # Resolved once per operation (REQ-009); `None` keeps today's body (REQ-022).
        role_params = _role_params_for(role, explicit)
        result, latency_ms, json_schema_status, attempts = _run_chat(
            model,
            system,
            user,
            max_tokens,
            temperature,
            response_format=response_format,
            json_schema_fallback=json_schema_fallback,
            role=role,
            explicit=explicit,
            size=chars_in or None,
            entry_id=entry_id,
            op=op,
            role_params=role_params,
        )
    except BaseException as exc:
        _note_failure(exc)  # issue #476: logged by the middleware, never silently lost
        raise
    finally:
        op.release_slot()
        _inflight_end(entry_id)

    text = _strip_think(result.text) if result.ok else result.text
    # Quitar los fences aquí y no en quien llama es lo que permite escribir a disco el código ya
    # limpio: hacerlo fuera dejaría dentro del archivo las ``` que el modelo a veces añade.
    if strip_fences and result.ok:
        text = _strip_fences(text)
    truncated_out = result.finish_reason == "length"
    # El postproceso trabaja sobre la salida PURA del modelo: antes del aviso de truncado, del de
    # respaldo, de `chars_out` y de la coletilla de ahorro. Hacerlo después dejaría lo que inserta
    # detrás de esos avisos (resumen-por-secciones, revisión del plan B3).
    if postprocess is not None and result.ok:
        text = postprocess(text, truncated_out)
    truncation_notice = f"\n\n{WARNING_MARKER}{i18n.t('mcp.warning.output_truncated')}]"
    # Con `write_to` el aviso viaja en el RECIBO, no dentro del archivo: lo que se escribe es lo
    # que generó el modelo y nada más.
    if report is not None:
        report["truncated_out"] = truncated_out
    elif truncated_out and write_to is None:
        text += truncation_notice
    fallback_info = _fallback_info(model, result, attempts, op.affinity_tried)
    # La afinidad (T15) no es un respaldo ni lleva aviso: queda en el log (REQ-016).
    served = fallback_info["answered_by"] if fallback_info else (op.affinity or model)
    fallback_notice = ""
    if fallback_info is not None:
        if fallback is not None:
            fallback.update(fallback_info)
        else:
            fallback_notice = _fallback_notice(fallback_info)
    if write_to is None:
        text += fallback_notice
    _log_event(
        tool=tool,
        model=served,
        source=source,
        chars_in=chars_in,
        chars_out=len(text),
        chars_out_raw=len(result.text) if result.ok else None,
        latency_ms=latency_ms,
        ok=result.ok,
        error=result.error,
        finish_reason=result.finish_reason,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        truncated_in=truncated_in,
        truncated_out=truncated_out,
        raw_len=raw_len,
        path=path if source == "path" else None,
        json_schema=json_schema_status,
        input_unit=input_unit,
        output_to_file=write_to is not None and result.ok,
        chunks=len(attempts),
        model_requested=model if fallback_info or op.affinity else None,
        fallback_reason=fallback_info["reason"] if fallback_info else None,
        fallback_class=fallback_info["class"] if fallback_info else None,
        error_class=None if result.ok else _class_value(result.error_class),
        num_sections=num_sections,
        focus=focus,
        connection_failure=None if result.ok else result.connection_failure,
        attempts=attempts,
        **op.log_fields(),
        **_backend_params_log_fields(role_params),
    )
    # Un fallo del backend NO se escribe al archivo: `result.text` trae el mensaje de error, y
    # dejarlo en disco con nombre de código fuente sería peor que no escribir nada. Se devuelve
    # tal cual, igual que en cualquier otra tool.
    if write_to is not None and result.ok:
        return (
            _write_target(
                write_to,
                text,
                event=cost.in_flight_row(tool=tool, source=source, path=path),
            )
            + (truncation_notice if truncated_out else "")
            + fallback_notice
        )
    # `feedback=False` lo usa quien va a PARSEAR el resultado: anexar la línea de ahorro al texto
    # rompería un JSON válido. Ver `local_extract`, que la recoloca dentro de `_local_delegate`.
    if feedback and source == "path" and result.ok and config.FEEDBACK_ENABLED:
        event = cost.in_flight_row(tool=tool, source=source, path=path, input_unit=input_unit)
        text += _savings_feedback(chars_in, feedback_label, event=event)
    return text


# --- Chunking por límites naturales (local_translate / local_delegate) --------
# Las tools que transforman el texto ENTERO producen tanta salida como entrada, así que una
# sola llamada choca contra max_tokens y devuelve el documento cortado. Partimos la entrada
# por el límite natural más grueso que sirva (headers Markdown -> párrafos -> líneas -> corte
# duro) y traducimos/transformamos cada trozo por separado.
#
# Invariante: "".join(_chunk_text(t, n)) == t. Cada trozo conserva el separador original con
# el que terminaba, así las costuras se reensamblan sin inventar ni perder saltos de línea.
def _split_by_diff_files(text: str) -> list[str]:
    """Corta un diff unificado justo ANTES de la cabecera de cada archivo.

    Un diff no tiene headers Markdown, así que sin esto cae a párrafos y los trozos empiezan a
    mitad de un hunk: líneas `+` huérfanas cuya cabecera —la que dice de qué archivo son— quedó
    en el trozo anterior. Medido sobre un diff de 44 archivos: 1 de 11 trozos empezaba en
    frontera de archivo.

    Se **autoinhibe** si el texto no empieza por una cabecera de diff: así un Markdown que
    incluya un diff dentro de un fence se sigue partiendo por headers, y este splitter no puede
    degradar a `local_translate` ni a `local_summarize` sobre documentos normales.

    El respaldo `--- `/`+++ ` (diffs sin `--git`) solo se usa cuando NO hay ningún `diff --git`:
    en un diff `--git` cada archivo trae también su `--- a/x`, y cortar por las dos cabeceras
    partiría cada archivo en dos, dejando piezas que empiezan en `---` sin decir de qué archivo.
    """
    stripped = text.lstrip()
    if not (stripped.startswith("diff --git ") or re.match(r"--- \S", stripped)):
        return [text]
    if re.search(r"(?m)^diff --git ", text):
        pattern = r"(?m)(?=^diff --git )"
    else:
        pattern = r"(?m)(?=^--- \S.*\n\+\+\+ )"
    return [p for p in re.split(pattern, text) if p]


def _split_by_headers(text: str) -> list[str]:
    """Corta justo ANTES de cada header Markdown (`# `…`###### `)."""
    return [p for p in re.split(r"(?m)(?=^#{1,6} )", text) if p]


def _split_by_paragraphs(text: str) -> list[str]:
    """Corta DESPUÉS de cada línea en blanco (cada trozo conserva su `\\n\\n`)."""
    return [p for p in re.split(r"(?<=\n\n)", text) if p]


def _split_by_lines(text: str) -> list[str]:
    """Corta después de cada `\\n` (cada trozo conserva su salto)."""
    return [p for p in re.split(r"(?<=\n)", text) if p]


_SPLITTERS = (_split_by_diff_files, _split_by_headers, _split_by_paragraphs, _split_by_lines)


# --- Inventario de un diff (local_commit_msg) --------------------------------
# Medido: el `--stat` completo de un diff de 164 585 chars son 2 987 — cabe entero donde el diff
# no cabe. Y con solo ese inventario el modelo ya nombra el cambio real, mientras que con los
# primeros 20 000 chars del diff nombra el primer archivo por orden alfabético. Por eso el paso
# que redacta el mensaje lo recibe SIEMPRE, y por eso se calcula aquí y no se le pide al modelo:
# es un conteo, no un juicio.
@dataclass
class _DiffFile:
    """What a diff says about one file, computed without a model (#461)."""

    path: str
    status: str = "M"  # A (added), M (modified), D (deleted), R (renamed)
    added: int = 0
    removed: int = 0
    plus_symbols: list[str] = field(default_factory=list)
    minus_symbols: list[str] = field(default_factory=list)

    def symbols(self) -> tuple[list[str], list[str], list[str]]:
        """`(added, removed, changed)` top-level names; changed = on both `+` and `-` lines."""
        plus, minus = set(self.plus_symbols), set(self.minus_symbols)
        added = [n for n in dict.fromkeys(self.plus_symbols) if n not in minus]
        removed = [n for n in dict.fromkeys(self.minus_symbols) if n not in plus]
        changed = [n for n in dict.fromkeys(self.plus_symbols) if n in minus]
        return added, removed, changed


# A top-level definition on a `+`/`-` line: column 0 (no indentation), so methods, nested
# functions and locals stay out. Covers Python, JS/TS, Rust, Go and the like; what it misses is
# simply not listed, it never invents a name.
_DIFF_SYMBOL = re.compile(
    r"(?:export\s+(?:default\s+)?)?(?:pub(?:\([\w:]+\))?\s+)?(?:declare\s+)?(?:abstract\s+)?"
    r"(?:async\s+)?"
    r"(?:def|class|function\*?|interface|type|enum|const|let|var|fn|func|struct|trait|mod)"
    r"\s+([A-Za-z_$][\w$]*)"
)


def _diff_facts(diff: str) -> list[_DiffFile]:
    """Per file of the diff: path, A/M/D/R status, `+`/`-` line counts and top-level names.

    El conteo distingue las cabeceras `--- `/`+++ ` de las líneas de contenido por su posición
    —solo son cabecera antes del primer `@@` del archivo— y no por su texto. Mirando el texto,
    borrar una línea que empiece por `--` se registraría como cabecera y no se contaría.
    """
    files: list[_DiffFile] = []
    current: _DiffFile | None = None
    in_hunk = False

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            rest = line[len("diff --git ") :]
            pair = re.match(r"a/(.+) b/\1$", rest)
            current = _DiffFile(pair.group(1) if pair else rest.split(" b/", 1)[-1].lstrip("b/"))
            files.append(current)
            in_hunk = False
        elif current is None:
            continue
        elif line.startswith("@@"):
            in_hunk = True
        elif not in_hunk:
            # Zona de cabecera: `+++ b/x` manda sobre el nombre adivinado de `diff --git`, salvo
            # en un borrado (`+++ /dev/null`), donde el nombre bueno es el de `--- a/x`.
            if line.startswith("+++ "):
                if line[4:] == "/dev/null":
                    current.status = "D"
                else:
                    current.path = line[4:].removeprefix("b/")
            elif line.startswith("--- "):
                if line[4:] == "/dev/null":
                    current.status = "A"
                else:
                    current.path = line[4:].removeprefix("a/")
            elif line.startswith("new file mode"):
                current.status = "A"
            elif line.startswith("deleted file mode"):
                current.status = "D"
            elif line.startswith("rename from "):
                current.status = "R"
            elif line.startswith("rename to "):
                current.path = line[len("rename to ") :]
        elif line.startswith("+"):
            current.added += 1
            if symbol := _DIFF_SYMBOL.match(line, 1):
                current.plus_symbols.append(symbol.group(1))
        elif line.startswith("-"):
            current.removed += 1
            if symbol := _DIFF_SYMBOL.match(line, 1):
                current.minus_symbols.append(symbol.group(1))
    return files


def _diff_inventory(diff: str) -> list[tuple[str, int, int]]:
    """Devuelve `(ruta, líneas añadidas, líneas quitadas)` por archivo del diff."""
    return [(f.path, f.added, f.removed) for f in _diff_facts(diff)]


def _format_inventory(files: list[tuple[str, int, int]], max_chars: int) -> str:
    """Rinde el inventario como texto, colapsado por directorio si no cabe en `max_chars`.

    Sin el colapso, un diff de cientos de archivos desplazaría del prompt final justo el material
    que el modelo tiene que resumir.
    """
    if not files:
        return ""
    added_total = sum(m for _, m, _ in files)
    removed_total = sum(n for _, _, n in files)
    header = f"Archivos del cambio ({len(files)} en total, +{added_total} -{removed_total}):"
    detail = "\n".join(f"  {path} | +{added} -{removed}" for path, added, removed in files)
    if len(header) + 1 + len(detail) <= max_chars:
        return f"{header}\n{detail}"

    by_root: dict[str, list[int]] = {}
    for path, added, removed in files:
        root = path.split("/", 1)[0] if "/" in path else "(raíz)"
        totals = by_root.setdefault(root, [0, 0, 0])
        totals[0] += 1
        totals[1] += added
        totals[2] += removed
    detail = "\n".join(
        f"  {root}/ | {n} archivos, +{added} -{removed}"
        for root, (n, added, removed) in by_root.items()
    )
    return f"{header} agrupados por directorio porque la lista completa no cabía\n{detail}"


def _format_diff_symbols(facts: list[_DiffFile], max_chars: int) -> str:
    """The top-level names each file adds (+), removes (-) or touches (~), within `max_chars`.

    Files that do not fit are counted, not silently dropped: the model must know the list is
    partial and must not read its end as «nothing else changed».
    """
    header = (
        "Definiciones de primer nivel en las líneas +/- del diff (+ añadida, - quitada, ~ tocada):"
    )
    rows: list[str] = []
    for fact in facts:
        added, removed, changed = fact.symbols()
        parts = [
            f"{mark} {', '.join(names)}"
            for mark, names in (("+", added), ("-", removed), ("~", changed))
            if names
        ]
        if parts:
            rows.append(f"  {fact.path}: {'; '.join(parts)}")
    if not rows:
        return ""
    kept: list[str] = []
    used = len(header)
    for row in rows:
        omitted_note = 60  # room for the «N more» line below
        if used + 1 + len(row) + omitted_note > max_chars:
            break
        kept.append(row)
        used += 1 + len(row)
    if not kept:
        return ""
    if len(kept) < len(rows):
        kept.append(
            f"  (y {len(rows) - len(kept)} archivos más con definiciones, omitidos por espacio)"
        )
    return "\n".join([header, *kept])


def _format_diff_facts(facts: list[_DiffFile], max_chars: int) -> str:
    """Inventory with A/M/D/R status plus top-level names, the ground truth of the reduce (#461).

    The file list goes first and keeps the collapse of `_format_inventory`; the names use what is
    left of `max_chars`.
    """
    if not facts:
        return ""
    added_total = sum(f.added for f in facts)
    removed_total = sum(f.removed for f in facts)
    header = (
        f"Archivos del cambio ({len(facts)} en total, +{added_total} -{removed_total}; "
        "A añadido, M modificado, D borrado, R renombrado):"
    )
    detail = "\n".join(f"  {f.status} {f.path} | +{f.added} -{f.removed}" for f in facts)
    files_block = f"{header}\n{detail}"
    if len(files_block) > max_chars:
        files_block = _format_inventory([(f.path, f.added, f.removed) for f in facts], max_chars)
    symbols_block = _format_diff_symbols(facts, max_chars - len(files_block) - 2)
    return f"{files_block}\n\n{symbols_block}" if symbols_block else files_block


# --- Troceado de código por definiciones (local_explain_code, B2c) -----------------------------
# Medido (revisión del 2026-10-14): con el truncado a 20 000 chars, la explicación de `cli.py` (32 %
# leído) dio por completa una lista de subcomandos a la que faltaban `doctor`, `benchmark` y
# `llamaswap`. Se trocea por definiciones de primer nivel, para que ninguna quede partida, y el
# paso final recibe SIEMPRE el inventario de nombres, calculado aquí como el del diff.
_TOP_LEVEL_START = re.compile(r"(?:@|async\s+def\s|def\s|class\s)")
_TOP_LEVEL_NAME = re.compile(r"(?m)^(?:async\s+def|def|class)\s+(\w+)")


def _split_by_top_level_defs(text: str) -> list[str]:
    """Corta justo ANTES de cada `def`/`class` de primer nivel (columna 0).

    Los decoradores se pegan a la definición que sigue (también los de varias líneas); lo
    anterior a la primera definición es un trozo. Invariante: `"".join(...) == text`.
    """
    pieces: list[str] = []
    current = ""
    in_decorator = False
    for line in text.splitlines(keepends=True):
        if _TOP_LEVEL_START.match(line):
            # Tras un decorador no se corta: la definición (o el siguiente decorador) va con él.
            if not in_decorator and current:
                pieces.append(current)
                current = ""
            in_decorator = line.startswith("@")
        current += line
    if current:
        pieces.append(current)
    return pieces


def _code_pieces(text: str, budget: int) -> list[str] | None:
    """Trozos de <= `budget` por definiciones de primer nivel; `None` si no hay ninguna."""
    if not _TOP_LEVEL_NAME.search(text):
        return None
    chunks: list[str] = []
    for chunk in _pack(_split_by_top_level_defs(text), budget):
        chunks.extend(_chunk_text(chunk, budget) if len(chunk) > budget else [chunk])
    return chunks


# --- Números de línea (#460) ---------------------------------------------------------------------
# Sin números, «¿en qué línea está X?» no tenía respuesta: el modelo veía el código pelado y, al
# trocear, cada trozo empezaba sin saber dónde caía. Con `path` cada línea llega como `N| línea`, con
# N el número ABSOLUTO del fichero (el que usa `Read offset`), también dentro de cada trozo. Se
# numera ANTES de empaquetar, así el presupuesto en chars mide lo que de verdad viaja.
LINE_PREFIX_SEP = "| "


def _number_lines(text: str, start: int = 1) -> str:
    """`text` con `N| ` delante de cada línea, contando desde `start` y cortando solo en `\\n`.

    Solo `\\n`, como `Read` (y `read_text` ya convirtió `\\r\\n`): `splitlines` cortaría también en
    `\\f` o `\\u2028` y desfasaría la cuenta respecto al fichero.
    """
    lines = text.split("\n")
    tail = lines.pop() if lines else ""
    out = [f"{n}{LINE_PREFIX_SEP}{line}\n" for n, line in enumerate(lines, start)]
    if tail:  # última línea sin salto final
        out.append(f"{start + len(lines)}{LINE_PREFIX_SEP}{tail}")
    return "".join(out)


def _numbered_code_pieces(text: str, budget: int) -> list[str]:
    """Trozos numerados de <= `budget` chars, cada uno con su numeración absoluta del fichero.

    Las unidades se cortan sobre el texto SIN numerar (las definiciones de primer nivel, como
    `_code_pieces`, o los párrafos si no hay ninguna: con prefijo ya no quedan líneas en blanco
    que buscar), se numeran con su desplazamiento y luego se empaquetan; una unidad numerada que
    no cabe se parte por líneas, que conservan su prefijo.
    """
    if _TOP_LEVEL_NAME.search(text):
        units = _split_by_top_level_defs(text)
    else:
        units = _split_by_paragraphs(text)
    numbered: list[str] = []
    line = 1
    for unit in units:
        numbered.append(_number_lines(unit, line))
        line += unit.count("\n")
    chunks: list[str] = []
    for chunk in _pack(numbered, budget):
        chunks.extend(_chunk_text(chunk, budget) if len(chunk) > budget else [chunk])
    return chunks


def _top_level_names_with_lines(text: str) -> list[str]:
    """Las definiciones de primer nivel como `nombre:línea` (línea absoluta del fichero)."""
    return [
        f"{m.group(1)}:{text.count(chr(10), 0, m.start()) + 1}"
        for m in _TOP_LEVEL_NAME.finditer(text)
    ]


#: #460: lo que se le dice al modelo del prefijo, en todos los pasos de `local_explain_code` con
#: `path`. Va antes de la orden de idioma, que cierra el system.
_LINE_NUMBERS_CLAUSE = (
    " Cada línea del código empieza por su número de línea en el fichero seguido de «| »; ese "
    "prefijo no es parte del código. Cuando ubiques o cites algo, da ese número de línea."
)


def _format_names(names: list[str], max_chars: int, with_lines: bool = False) -> str:
    """El inventario de definiciones de primer nivel, recortado con su cuenta si no cabe."""
    if not names:
        return ""
    count = f"{len(names)} en total, como nombre:línea" if with_lines else f"{len(names)} en total"
    header = f"Definiciones de primer nivel del fichero ({count}):"
    shown: list[str] = []
    used = len(header)
    for name in names:
        if used + len(name) + 2 > max_chars:
            break
        shown.append(name)
        used += len(name) + 2
    rest = len(names) - len(shown)
    tail = f" y {rest} más" if rest else ""
    return f"{header} {', '.join(shown)}{tail}"


# B2e: lo que una función REGISTRA no es una definición de primer nivel. Medido en vivo (B2d) y con
# la sonda de `evidence/B2e/probes/`: `cli.py` da 4 trozos, `build_parser` registra 16 subcomandos
# con `add_parser("…")` (y `benchmark` con `benchmark.add_parser(sub)`, sin el literal), y la
# explicación final perdió `doctor` y `benchmark` porque dependían de que el modelo los copiara dos
# veces, en la nota del trozo y en el reduce. Se calculan aquí con `ast`, como el inventario.
#: Las llamadas que registran un nombre con su primer argumento (`sub.add_parser("doctor")`).
_REGISTERING_CALLS = ("add_parser",)


def _registered_names(text: str) -> list[tuple[str | None, list[str], list[str]]]:
    """(función, nombres literales, módulos) de cada función que registra algo, en orden.

    `nombres` son los primeros argumentos literales de `X.add_parser("…")`; `módulos`, la `X` de
    `X.add_parser(sub)` sin literal (el módulo registra lo suyo). La función es la más interna que
    contiene la llamada (`None` en el nivel del módulo). `[]` si `ast` no puede leer el fichero.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    found: dict[str | None, tuple[list[str], list[str]]] = {}

    def _visit(node: ast.AST, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = owner
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                inner = child.name
            elif (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _REGISTERING_CALLS
                and child.args
            ):
                first = child.args[0]
                names, modules = found.setdefault(owner, ([], []))
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if first.value not in names:
                        names.append(first.value)
                elif isinstance(child.func.value, ast.Name) and child.func.value.id not in modules:
                    modules.append(child.func.value.id)
            _visit(child, inner)

    _visit(tree, None)
    return [(owner, names, modules) for owner, (names, modules) in found.items()]


def _format_registered(
    registered: list[tuple[str | None, list[str], list[str]]], max_chars: int
) -> str:
    """El inventario de lo que registra cada función, recortado con su cuenta si no cabe."""
    if not registered:
        return ""
    header = "Nombres que registran las funciones del fichero (llamadas a add_parser):"
    lines = [header]
    used = len(header)
    for owner, names, modules in registered:
        label = f"- {owner}" if owner else "- nivel del módulo"
        parts = list(names) + [f"lo que registra el módulo `{m}`" for m in modules]
        shown: list[str] = []
        line_used = len(label) + 2
        for part in parts:
            # Sitio para la cola « y N más», que también cuenta.
            if used + line_used + len(part) + 2 + len(" y 9999 más") > max_chars:
                break
            shown.append(part)
            line_used += len(part) + 2
        if not shown:
            break
        rest = len(parts) - len(shown)
        tail = f" y {rest} más" if rest else ""
        lines.append(f"{label}: {', '.join(shown)}{tail}")
        used += line_used + 1
    return "\n".join(lines) if len(lines) > 1 else ""


def _pack(pieces: list[str], max_chars: int) -> list[str]:
    """Agrupa piezas consecutivas en trozos de <= max_chars (sin partir ninguna pieza)."""
    packed: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > max_chars:
            packed.append(current)
            current = piece
        else:
            current += piece
    if current:
        packed.append(current)
    return packed


def _chunk_text(text: str, max_chars: int, _level: int = 0) -> list[str]:
    """Parte `text` en trozos de <= max_chars por el límite natural más grueso posible."""
    if len(text) <= max_chars:
        return [text]
    if _level >= len(_SPLITTERS):
        # Sin ningún límite natural utilizable (p. ej. un solo párrafo gigantesco): corte duro.
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    pieces = _SPLITTERS[_level](text)
    if len(pieces) <= 1:
        return _chunk_text(text, max_chars, _level + 1)
    chunks: list[str] = []
    for chunk in _pack(pieces, max_chars):
        if len(chunk) > max_chars:
            chunks.extend(_chunk_text(chunk, max_chars, _level + 1))
        else:
            chunks.append(chunk)
    return chunks


def _reattach_separator(chunk: str, output: str) -> str:
    """Devuelve la salida del trozo con el separador original del final del trozo.

    Conserva el formato en la costura: si el trozo terminaba en línea en blanco, la salida
    también; si terminaba en un simple `\\n` (mitad de una lista o de un bloque de código),
    no se inyecta un párrafo que no estaba en el original.
    """
    trailing = chunk[len(chunk.rstrip()) :]
    return output.strip() + trailing


def _chat_chunked(
    model: str,
    system: str,
    content: str,
    build_user,
    *,
    tool: str,
    source: str,
    temperature: float = 0.2,
    truncated_in: bool = False,
    raw_len: int | None = None,
    path: str | None = None,
    chunk_chars: int | None = None,
    role: str | None = None,
    explicit: bool = False,
) -> str:
    """Procesa `content` por trozos y concatena las salidas EN ORDEN.

    Una llamada al backend por trozo (cada una con su propio `max_tokens <= CHUNK_MAX_TOKENS`),
    un único evento en el log con `chunks: N`, y una sola entrada en "En curso" que va marcando
    el trozo en proceso. Si un trozo aun así sale truncado, se vuelve a partir y se reintenta:
    el resultado final llega completo en vez de con el aviso `[salida truncada]`.
    """
    down = _backend_down_text()
    if down is not None:
        return down
    chunk_chars = chunk_chars or config.CHUNK_CHARS
    chunks = _chunk_text(content, chunk_chars)
    entry_id = _inflight_start(
        tool=tool, model=model, source=source, chars_in=len(content), chunks=len(chunks)
    )
    outputs: list[str] = []
    calls = 0
    latency_ms = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    failed: ChatResult | None = None
    truncated_out = False
    # Las llamadas reales de toda la operación, saltos incluidos (REQ-024).
    all_attempts: list[Attempt] = []
    # Turno por operación (REQ-003): todos los trozos bajo el mismo turno.
    op = _OperationTurn(entry_id, model, tool, role_name=role, explicit=explicit)
    # The role's parameters, resolved once for every chunk and step (REQ-009, REQ-012).
    current = _CurrentModel(
        model, role, explicit, entry_id, op, role_params=_role_params_for(role, explicit)
    )

    def _accumulate(result: ChatResult, ms: int, attempts: list[Attempt]) -> None:
        nonlocal calls, latency_ms, tokens_in, tokens_out
        all_attempts.extend(attempts)
        calls += len(attempts)
        latency_ms += ms
        if result.tokens_in is not None:
            tokens_in = (tokens_in or 0) + result.tokens_in
        if result.tokens_out is not None:
            tokens_out = (tokens_out or 0) + result.tokens_out

    def _process(piece: str, depth: int = 0) -> str | None:
        """Devuelve el texto del trozo, o None si el backend falló (aborta la operación)."""
        nonlocal failed, truncated_out
        max_tokens = min(len(piece) // 2 + 128, config.CHUNK_MAX_TOKENS)
        result, ms, attempts = current.call(
            system, build_user(piece.strip()), max_tokens, temperature, size=len(piece)
        )
        _accumulate(result, ms, attempts)
        if not result.ok:
            failed = result
            return None
        if result.finish_reason == "length" and depth < 2 and len(piece) > config.CHUNK_MIN_CHARS:
            # El trozo seguía siendo demasiado grande para el techo de tokens: pártelo y
            # reintenta en vez de devolver la salida cortada.
            halves = _chunk_text(piece, max(config.CHUNK_MIN_CHARS, len(piece) // 2))
            if len(halves) > 1:
                _inflight_phase(entry_id, "retry")
                parts: list[str] = []
                for half in halves:
                    out = _process(half, depth + 1)
                    if out is None:
                        return None
                    parts.append(_reattach_separator(half, out))
                return "".join(parts).strip()
        if result.finish_reason == "length":
            truncated_out = True
        return _strip_think(result.text)

    try:
        for index, piece in enumerate(chunks, start=1):
            _inflight_progress(entry_id, index)
            current.chunk = index
            output = _process(piece)
            if output is None:
                break
            outputs.append(_reattach_separator(piece, output))
    except BaseException as exc:
        _note_failure(exc)  # issue #476: logged by the middleware, never silently lost
        raise
    finally:
        op.release_slot()
        _inflight_end(entry_id)

    if failed is not None:
        text = failed.text
        ok = False
        error = failed.error
        finish_reason = failed.finish_reason
    else:
        text = "".join(outputs).strip()
        ok = True
        error = None
        finish_reason = "length" if truncated_out else "stop"
        if truncated_out:
            text += f"\n\n{WARNING_MARKER}{i18n.t('mcp.warning.output_truncated')}]"
        text += current.notice(len(chunks) > 1)

    _log_event(
        tool=tool,
        model=current.served if ok or current.affinity else model,
        source=source,
        chars_in=len(content),
        chars_out=len(text),
        latency_ms=latency_ms,
        ok=ok,
        error=error,
        finish_reason=finish_reason,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        truncated_in=truncated_in,
        truncated_out=truncated_out,
        raw_len=raw_len,
        path=path if source == "path" else None,
        chunks=calls,
        pieces=len(chunks),
        attempts=all_attempts,
        **current.log_fields(failed),
    )
    if source == "path" and ok and config.FEEDBACK_ENABLED:
        event = cost.in_flight_row(tool=tool, source=source, path=path)
        text += _savings_feedback(len(content), "chars", event=event)
    if ok and calls > 1 and config.FEEDBACK_ENABLED:
        text += "\n\n" + i18n.t("mcp.receipt.chunked", calls=calls)
    return text


# Marcas inequívocas: códigos de error y frases que solo aparecen en un desborde.
_OVERFLOW_MARKERS = (
    "exceed_context_size",  # tipo de error de llama.cpp
    "context_length_exceeded",  # código de OpenAI/vLLM
    "context window",
    "prompt is too long",
)
# Fuera de esas, se exige una palabra de «contexto» Y una de «exceso». Ninguna de las dos por
# separado dice nada —`context shift` y `maximum tokens` son opciones normales del backend—,
# juntas sí.
_OVERFLOW_CONTEXT_WORDS = ("context", "contexto")
_OVERFLOW_EXCESS_WORDS = (
    "exceed",  # cubre exceeds / exceeded / exceeding
    "too long",
    "too large",
    "too many tokens",
    "overflow",
    "maximum",
)


def _is_context_overflow(result: ChatResult | None) -> bool:
    """True si el backend rechazó la llamada por no caber en el contexto del modelo.

    Los presupuestos de troceado están en CARACTERES y el límite del modelo en TOKENS, y la
    relación entre los dos depende del contenido: la prosa de un `.md` da 3,12 chars/token y
    `uv.lock` —hashes y URLs— da 1,57, medido. Un presupuesto en chars que sirve para un
    documento revienta con otro, así que el que manda tiene que ser el límite real, no la
    estimación: ver `_chat_map_reduce`.

    La detección **no puede ser una lista de literales de un proveedor**. Esto comparaba contra
    tres marcas y el backend de referencia dice `Context size has been exceeded.`, que no casa
    con ninguna: el reintento adaptativo llevaba anulado desde entonces y `local_summarize` se
    rendía con el `CHANGELOG.md` del propio repo. El catálogo son endpoints OpenAI-compatible
    distintos (llama-swap, Ollama, LM Studio, vLLM) y cada uno lo dice a su manera.

    La asimetría manda hacia el lado generoso: un falso positivo cuesta como mucho dos
    reintentos con trozos más pequeños, un falso negativo anula el mecanismo entero.
    """
    if result is None:
        return False
    text = result.text.lower()
    if any(marker in text for marker in _OVERFLOW_MARKERS):
        return True
    mentions_context = any(c in text for c in _OVERFLOW_CONTEXT_WORDS)
    mentions_excess = any(e in text for e in _OVERFLOW_EXCESS_WORDS)
    return mentions_context and mentions_excess


def _role_for_size(probe_len: int) -> tuple[str, str]:
    """(rol, modelo) de las tools que enrutan por tamaño: largo por encima del umbral, si no mecánico.

    Devuelve el ROL además del modelo porque el tope de entrada es del rol: con dos roles sobre el
    mismo modelo, preguntar el tope por el nombre del modelo daría el de otro rol.
    """
    role = "long" if probe_len > config.LONG_INPUT_CHARS else "mechanical"
    return role, config.models_by_role()[role]


def _map_budget(max_chars: int) -> int:
    """Caracteres por trozo del map: el 80 % del tope, para dejar sitio al prompt y a la salida."""
    return max(config.CHUNK_MIN_CHARS, int(max_chars * 0.8))


def _piece_lines(content: str, piece: Any) -> tuple[int, int] | None:
    """#455: first and last line of `piece` in `content`, or None if it is not found only once."""
    text = piece if isinstance(piece, str) else getattr(piece, "text", None)
    if not isinstance(text, str) or not isinstance(content, str):
        return None
    text = text.strip()
    if not text or content.count(text) != 1:
        return None
    first = content.count("\n", 0, content.find(text)) + 1
    return first, first + text.count("\n")


def _truncated_piece_entries(content: str, truncated: list[tuple[Any, Any]]) -> list[dict]:
    """#455: `{"piece": n}` per map partial left cut, with `"lines": [a, b]` when known."""
    entries: list[dict] = []
    for number, piece in truncated:
        entry: dict = {"piece": number}
        lines = _piece_lines(content, piece)
        if lines is not None:
            entry["lines"] = list(lines)
        entries.append(entry)
    return entries


def _truncated_pieces_notice(entries: list[dict]) -> str:
    """#455: the tail of the truncation notice that names the pieces; empty without them."""
    if not entries:
        return ""
    items = ", ".join(
        i18n.t(
            "mcp.warning.truncated_piece_lines",
            piece=e["piece"],
            first=e["lines"][0],
            last=e["lines"][1],
        )
        if "lines" in e
        else str(e["piece"])
        for e in entries
    )
    return i18n.t("mcp.warning.truncated_pieces", pieces=items)


def _dump_chunk_notes(
    folder: str, tool: str, entry_id: int, steps: list[dict], texts: list[str]
) -> None:
    """B2e: the output of every step of a chunked operation, to a LOCAL file, for a measurement.

    Only with `LOCAL_DELEGATE_DUMP_CHUNK_NOTES=<dir>` (off by default). It writes to the disk of
    this machine and nothing else: the usage log keeps the steps without their text. Best effort,
    like the log: a folder that cannot be written never breaks the tool.
    """
    # Best effort, like the usage log: a folder that cannot be written never breaks the tool.
    with suppress(OSError, ValueError):
        stamp = _utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        target = Path(folder) / f"{tool}-{stamp}-{entry_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "tool": tool,
            "steps": [dict(step, text=text) for step, text in zip(steps, texts, strict=False)],
        }
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _chat_map_reduce(
    model: str,
    system: str,
    content: str,
    build_user,
    *,
    max_chars: int,
    tool: str,
    source: str,
    max_words: int,
    temperature: float = 0.2,
    raw_len: int | None = None,
    path: str | None = None,
    reduce_system: str | None = None,
    build_reduce=None,
    partial_max_words: int | None = None,
    role: str | None = None,
    explicit: bool = False,
    pieces: list | None = None,
    system_for: Callable[[Any], str] | None = None,
    user_for: Callable[[Any], str] | None = None,
    words_for: Callable[[Any], int] | None = None,
    tokens_for: Callable[[Any, int], int] | None = None,
    split_for: Callable[[Any], list] | None = None,
    reduce: str = "model",
    reduce_extra: str = "",
    postprocess: Callable[[str, bool], str] | None = None,
    num_sections: int | None = None,
    focus: bool = False,
    response_format: dict | None = None,
    json_schema_fallback: bool = False,
    reduce_shortcut: Callable[[list[str]], str | None] | None = None,
    report: dict | None = None,
    max_tokens_for: Callable[[int], int] | None = None,
    final_max_tokens_for: Callable[[int], int] | None = None,
) -> str:
    """Resume un documento que no cabe en el modelo: resume por trozos y luego los resúmenes.

    El chunking de `_chat_chunked` sirve para *transformar* (traducir, reescribir): concatenar
    las salidas es correcto porque cada trozo se corresponde con su parte del resultado. Para
    **reducir** —un único resumen de todo— concatenar no vale: haría falta un resumen por trozo
    pegado con otro, no un resumen global. De ahí el map-reduce.

    Hasta ahora estas tools simplemente *truncaban* la entrada y avisaban, que en un documento
    grande significa resumir el principio e ignorar el resto en silencio útil. Ahora se lee
    entero.

    El reduce es jerárquico: si los resúmenes parciales tampoco caben, se vuelven a resumir por
    niveles (tope de 3, suficiente para cualquier archivo realista y con final garantizado).
    Como en `_chat_chunked`: N llamadas, **un** evento de log con `chunks: N`.

    **Modo por trozo** (resumen-por-secciones): quien llama trae los trozos hechos (`pieces`) y
    cómo tratar cada uno —`system_for`, `user_for`, `words_for`, `tokens_for` y `split_for`, que
    valen también para los subtrozos del reintento por desborde—. Con `reduce="concat"` no hay
    reduce por el modelo: los parciales ya están en su formato final y se unen en orden. Sin esos
    parámetros, el comportamiento es el de siempre, byte a byte.

    **Salida que se parsea** (`local_extract` troceado, B2c): `response_format` va en cada paso;
    `reduce_shortcut` puede dar el resultado sin llamar al modelo (devuelve `None` si no puede); y
    con `report` no se pega nada al texto —ni el aviso de truncado, ni el de respaldo, ni el
    ahorro, ni el recibo—: esos datos quedan en `report` para que quien parsea los recoloque.

    `max_tokens_for(words)` replaces the shared `2·w+64` cap of every step (map, regroup and
    reduce) for a tool that needs its own (lint, B2d-2). `final_max_tokens_for(words)`, when
    given, replaces it only in the steps that combine partials (reduce and regroup): the map keeps
    `max_tokens_for` (lint, B2e).
    """
    down = _backend_down_text()
    if down is not None:
        return down
    budget = _map_budget(max_chars)
    if pieces is None:
        pieces = _chunk_text(content, budget)
    entry_id = _inflight_start(
        tool=tool, model=model, source=source, chars_in=len(content), chunks=len(pieces)
    )
    calls = 0
    latency_ms = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    failed: ChatResult | None = None
    truncated_calls = 0  # llamadas que acabaron por `length`: un parcial cortado ya perdió material
    # Las llamadas reales de toda la operación, saltos incluidos (REQ-024).
    all_attempts: list[Attempt] = []
    # Turno por operación (REQ-003): map, reagrupados y reduce bajo el mismo turno.
    op = _OperationTurn(entry_id, model, tool, role_name=role, explicit=explicit)
    # The role's parameters, resolved once for every chunk and step (REQ-009, REQ-012).
    current = _CurrentModel(
        model, role, explicit, entry_id, op, role_params=_role_params_for(role, explicit)
    )

    raw_chars = 0  # what the model generated, before `_strip_think` and the post-processing
    # B2e: one entry per step (map, regroup, reduce) for the usage log, without the text; the text
    # goes only to the local dump of `LOCAL_DELEGATE_DUMP_CHUNK_NOTES` when it is on.
    steps: list[dict] = []
    step_texts: list[str] = []
    dump_dir = config.dump_chunk_notes_dir()

    def _one(sys_prompt: str, user: str, max_tokens: int, kind: str = "map") -> str | None:
        nonlocal calls, latency_ms, tokens_in, tokens_out, failed, truncated_calls, raw_chars
        result, ms, attempts = current.call(
            sys_prompt,
            user,
            max_tokens,
            temperature,
            size=len(user),
            response_format=response_format,
            json_schema_fallback=json_schema_fallback,
        )
        all_attempts.extend(attempts)
        calls += len(attempts)
        latency_ms += ms
        if result.tokens_in is not None:
            tokens_in = (tokens_in or 0) + result.tokens_in
        if result.tokens_out is not None:
            tokens_out = (tokens_out or 0) + result.tokens_out
        steps.append(
            {
                "kind": kind,
                "chars_out": len(result.text) if result.ok else 0,
                "finish_reason": result.finish_reason,
            }
        )
        if dump_dir:
            step_texts.append(result.text if result.ok else "")
        if not result.ok:
            failed = result
            return None
        raw_chars += len(result.text)
        if result.finish_reason == "length":
            truncated_calls += 1
        return _strip_think(result.text)

    def _last_cut() -> bool:
        """#455: whether the step `_one` just ran (and returned text) ended by `length`."""
        return bool(steps) and steps[-1]["finish_reason"] == "length"

    def _discard_last() -> None:
        """#455: the last step was cut and is retried split: it stops counting as truncated."""
        nonlocal truncated_calls, raw_chars
        steps[-1]["retried"] = True
        truncated_calls -= 1
        raw_chars -= steps[-1]["chars_out"]

    # #455: (number of the top-level piece, the piece) of each map partial still cut after the
    # retries, to say in the notice which part of the input may be missing.
    truncated_pieces: list[tuple[int, Any]] = []

    def _tokens(words: int) -> int:
        if max_tokens_for is not None:
            return max_tokens_for(words)
        return int(words * 2) + 64

    def _final_tokens(words: int) -> int:
        if final_max_tokens_for is not None:
            return final_max_tokens_for(words)
        return _tokens(words)

    # Cada parcial se deja algo más largo que el resumen final: el reduce necesita material
    # con el que trabajar, y un parcial demasiado corto ya habría perdido lo que importa.
    #
    # `partial_max_words` existe porque hay reduces cuyo resultado es MUCHO más corto que su
    # material: un mensaje de commit son ~250 palabras como mucho, pero el parte de los archivos de
    # un trozo no cabe en eso y saldría cortado por `finish_reason=length`. Perder material en el map
    # es el mismo defecto que el truncado de la entrada, un nivel más adentro.
    partial_words = partial_max_words if partial_max_words is not None else max(80, max_words)
    custom_reduce = reduce_system
    if reduce_system is None:
        # `reduce_extra` (el enfoque de local_summarize) va sobre el reduce POR DEFECTO sin
        # convertirlo en uno propio: así la rama «un solo parcial» y el reagrupado no cambian.
        reduce_system = (
            _guard(
                "un ÚNICO resumen global en prosa clara, sin repetir ni enumerar los fragmentos",
                max_words,
            )
            + reduce_extra
        )
    if build_reduce is None:

        def build_reduce(joined: str) -> str:
            return (
                "Estos son resúmenes parciales y EN ORDEN de un mismo documento. "
                f"Redacta un único resumen global:\n\n{joined}"
            )

    # Cuando los parciales tampoco caben se reagrupan, y ese paso intermedio produce más
    # material para el reduce —no el resultado final—. Con un reduce propio hay que reagrupar
    # con el system del MAP: hacerlo con el del reduce emitiría mensajes de commit intermedios
    # que luego se resumirían entre sí. Sin reduce propio se mantiene el comportamiento de hoy.
    regroup_system = system if custom_reduce is not None else reduce_system

    def _map_system(piece) -> str:
        return system_for(piece) if system_for is not None else system

    def _map_user(piece) -> str:
        return user_for(piece) if user_for is not None else build_user(piece.strip())

    def _map_tokens(piece) -> int:
        words = words_for(piece) if words_for is not None else partial_words
        return tokens_for(piece, words) if tokens_for is not None else _tokens(words)

    def _split(piece) -> list:
        if split_for is not None:
            return split_for(piece)
        return _chunk_text(piece, max(config.CHUNK_MIN_CHARS, len(piece) // 2))

    def _map_piece(piece, depth: int = 0) -> list[str] | None:
        """Resume un trozo; si el backend dice que no cabe, lo parte y reintenta.

        El presupuesto en chars es una estimación de cuántos tokens ocupará el trozo, y con
        contenido denso se queda corta. En vez de calibrar la estimación a ojo —que no acota
        nada: un diff de un fichero base64 baja de 0,75 chars/token— se deja que responda el
        backend y se reintenta más pequeño. Dos niveles: un trozo que no cabe partido en cuatro
        no es un problema de presupuesto.
        """
        nonlocal failed
        out = _one(_map_system(piece), _map_user(piece), _map_tokens(piece))
        if out is not None:
            if _last_cut():
                # #455: the OUTPUT was cut (`length`): split and retry like `_chat_chunked`,
                # instead of handing the reduce a partial that already lost material.
                parts = _split(piece) if depth < 2 and _can_split(piece) else []
                if len(parts) >= 2:
                    _discard_last()
                    return _map_parts(parts, depth)
                truncated_pieces.append((current.chunk, piece))
            return [out]
        if depth >= 2 or not _is_context_overflow(failed):
            return None
        parts = _split(piece)
        if len(parts) < 2:
            return None  # indivisible: el error se queda como está
        failed = None  # el desborde deja de ser terminal en cuanto hay con qué reintentar
        return _map_parts(parts, depth)

    def _map_parts(parts: list, depth: int) -> list[str] | None:
        # Only reached when a piece is split again (cut output or context overflow): #454.
        _inflight_phase(entry_id, "retry")
        outputs: list[str] = []
        for part in parts:
            sub = _map_piece(part, depth + 1)
            if sub is None:
                return None
            outputs.extend(sub)
        return outputs

    def _can_split(piece) -> bool:
        # The guard of `_chat_chunked`: a piece this small is not cut by its size.
        text = piece if isinstance(piece, str) else getattr(piece, "text", None)
        return not isinstance(text, str) or len(text) > config.CHUNK_MIN_CHARS

    def _regroup(group: str, depth: int = 0) -> list[str] | None:
        """One regroup step; if its output is cut (`length`), the group is split and retried."""
        out = _one(
            regroup_system, build_user(group.strip()), _final_tokens(partial_words), "regroup"
        )
        if out is None:
            return None
        if _last_cut() and depth < 2 and len(group) > config.CHUNK_MIN_CHARS:
            halves = _chunk_text(group, max(config.CHUNK_MIN_CHARS, len(group) // 2))
            if len(halves) >= 2:
                _discard_last()
                outputs: list[str] = []
                for half in halves:
                    sub = _regroup(half, depth + 1)
                    if sub is None:
                        return None
                    outputs.extend(sub)
                return outputs
        return [out]

    try:
        summaries: list[str] = []
        for index, piece in enumerate(pieces, start=1):
            _inflight_progress(entry_id, index)
            current.chunk = index
            outs = _map_piece(piece)
            if outs is None:
                break
            summaries.extend(outs)

        # #473: the map partials in chunk order, before any regroup replaces them.
        map_partials = list(summaries)
        current.chunk = None
        text = ""
        if failed is None:
            # Con un solo parcial y sin reduce propio, ese parcial YA es el resultado. Con un
            # reduce propio no: el parcial está en el formato del map —para un commit, un parte
            # por archivo— y saltarse el reduce devolvería eso en vez de un mensaje. Pasa con un
            # `CHUNK_MIN_CHARS` alto, que es configurable.
            if reduce == "concat":
                # Los parciales ya están en el formato final (una sección tras otra): unirlos en
                # orden ES el resultado. Un reduce por el modelo los volvería a aplanar en prosa.
                text = "\n\n".join(s.strip() for s in summaries)
            elif len(summaries) == 1 and custom_reduce is None:
                text = summaries[0]
            elif reduce_shortcut is not None and (shortcut := reduce_shortcut(summaries)):
                # Los parciales ya dan el resultado sin juicio (un solo trozo trae datos): sin
                # llamada extra.
                text = shortcut
            else:
                _inflight_phase(entry_id, "reduce")
                for _level in range(3):
                    joined = "\n\n".join(summaries)
                    prompt = build_reduce(joined)
                    # Se mide el prompt ARMADO, no los parciales pelados: lo que se envía puede
                    # llevar delante material fijo (el inventario del diff, p. ej.), y medir sin
                    # él desbordaría el contexto justo en la llamada que produce el resultado.
                    if len(prompt) <= budget:
                        out = _one(reduce_system, prompt, _final_tokens(max_words), "reduce")
                        text = out or ""
                        break
                    # Ni los parciales caben: se reducen por grupos y se repite.
                    grouped: list[str] = []
                    for group in _chunk_text(joined, budget):
                        outs = _regroup(group)
                        if outs is None:
                            break
                        grouped.extend(outs)
                    if failed is not None:
                        break
                    summaries = grouped
                else:
                    text = "\n\n".join(summaries)
    except BaseException as exc:
        _note_failure(exc)  # issue #476: logged by the middleware, never silently lost
        raise
    finally:
        op.release_slot()
        _inflight_end(entry_id)

    ok = failed is None
    if not ok:
        text, error, finish_reason = failed.text, failed.error, failed.finish_reason
        if _is_context_overflow(failed):
            # Aquí el reintento adaptativo ya partió el trozo y siguió sin caber. El error crudo
            # del backend no dice ni que el problema es el tamaño ni qué se puede tocar, así que
            # se antepone lo accionable y se conserva detrás la respuesta original.
            detail = failed.text.removeprefix(ERROR_PREFIX)
            text = ERROR_PREFIX + i18n.t(
                "mcp.error.context_overflow",
                model=model,
                chunk=config.CHUNK_MIN_CHARS,
                detail=detail,
            )
            error = "context_overflow"
    else:
        error, finish_reason = None, "stop"
        if postprocess is not None:
            text = postprocess(text, truncated_calls > 0)
        # Antes un parcial cortado por `length` se aceptaba en silencio y el evento decía `stop`:
        # el resumen perdía parte de un trozo sin que nadie lo supiera (revisión del plan, B6).
        if truncated_calls:
            finish_reason = "length"
        if report is None:
            if truncated_calls:
                notice = i18n.t(
                    "mcp.warning.output_truncated_calls", truncated=truncated_calls, calls=calls
                )
                notice += _truncated_pieces_notice(
                    _truncated_piece_entries(content, truncated_pieces)
                )
                text += f"\n\n{WARNING_MARKER}{notice}]"
            text += current.notice(len(pieces) > 1)

    _log_event(
        tool=tool,
        model=current.served if ok or current.affinity else model,
        source=source,
        chars_in=len(content),
        chars_out=len(text),
        chars_out_raw=raw_chars if ok else None,
        latency_ms=latency_ms,
        ok=ok,
        error=error,
        finish_reason=finish_reason,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        truncated_in=False,  # el sentido de todo esto es que ya no se trunca
        truncated_out=ok and truncated_calls > 0,
        raw_len=raw_len,
        path=path if source == "path" else None,
        chunks=calls,
        pieces=len(pieces),
        num_sections=num_sections,
        focus=focus,
        json_schema=current.json_schema if response_format is not None else None,
        attempts=all_attempts,
        steps=steps,
        **current.log_fields(failed),
    )
    if dump_dir:
        _dump_chunk_notes(dump_dir, tool, entry_id, steps, step_texts)
    if report is not None:
        report.update(
            truncated_calls=truncated_calls if ok else 0,
            # #455: which map pieces stayed cut (number and, when found, lines of `content`).
            truncated_pieces=_truncated_piece_entries(content, truncated_pieces) if ok else [],
            calls=calls,
            pieces=len(pieces),
            partials=map_partials if ok else [],
            # Las claves del contrato de `fallback` (REQ-010), sin el trozo interno.
            fallback=(
                {k: v for k, v in current.hop.items() if k != "chunk"}
                if current.hop is not None
                else None
            ),
        )
        return text
    if source == "path" and ok and config.FEEDBACK_ENABLED:
        event = cost.in_flight_row(tool=tool, source=source, path=path)
        text += _savings_feedback(len(content), "chars", event=event)
    if ok and calls > 1 and config.FEEDBACK_ENABLED:
        text += "\n\n" + i18n.t("mcp.receipt.map_reduce", parts=len(pieces), calls=calls)
    return text


def _strip_fences(s: str) -> str:
    """Quita fences markdown (```json / ```python / ```) que a veces envuelven la salida."""
    s = s.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        lines = lines[1:]  # descarta la línea de apertura del fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def _json_schema_payload(fields: list[str]) -> dict:
    """response_format json_object+schema para local_extract (ver doc de llama-server).

    Cada propiedad se restringe a tipos primitivos (string/number/boolean/null): un
    sub-schema vacío ({}) permite objetos/arrays anidados y algunos modelos (p. ej.
    gemma3-4b) anidan el valor en vez de devolverlo plano — {"campo": {"valor": "x"}}
    en lugar de {"campo": "x"}.
    """
    primitive = {"type": ["string", "number", "boolean", "null"]}
    return {
        "type": "json_object",
        "schema": {
            "type": "object",
            "properties": {f: primitive for f in fields},
            "required": list(fields),
        },
    }


# Códigos de idioma que se traducen a un nombre legible en la orden de `local_commit_msg`. Un mapa
# corto a propósito: lo que no esté aquí se usa tal cual lo escribió quien configuró la variable
# (`LOCAL_DELEGATE_COMMIT_LANGUAGE=catalán` ya funciona sin tocar nada).
_LANGUAGE_NAMES: dict[str, str] = {
    "es": "español",
    "en": "inglés",
    "fr": "francés",
    "pt": "portugués",
    "de": "alemán",
    "it": "italiano",
}


#: El valor explícito de `LOCAL_DELEGATE_COMMIT_LANGUAGE` que conserva la regla de antes: el
#: idioma predominante de los textos del diff.
COMMIT_LANGUAGE_DIFF = "diff"

# Topes de `local_commit_msg` desde B2c: el cuerpo obligatorio no cabe en los de antes (256 tokens
# en la llamada única y 90 palabras en el paso final del troceado).
_COMMIT_BODY_BULLETS = "2 a 6"
COMMIT_MAX_TOKENS = 700
COMMIT_REDUCE_MAX_WORDS = 250


# --- Commit language from the repository's own history (#461) ---------------------------------
# A commit message follows the repo's convention, not the user's. The daemon's cwd is not the
# user's repo, so the only anchor is the diff's `path`: if that file lives inside a work tree, the
# subjects of its recent commits are read from the reflog (`logs/HEAD`, plain text) — no `git`
# subprocess, so nothing in the repo's config or hooks can run. A diff dumped to a temp folder has
# no repo above it and keeps the rule of before.
_REFLOG_COMMIT = re.compile(r"^commit(?: \([^)]*\))?: (.+)$")
_CONVENTIONAL_PREFIX = re.compile(r"^\w+(?:\([^)]*\))?!?:\s*")
_ES_MARKERS = frozenset(
    [
        "de",
        "la",
        "el",
        "los",
        "las",
        "que",
        "para",
        "con",
        "por",
        "del",
        "una",
        "un",
        "al",
        "sin",
        "se",
        "y",
        "o",
        "lo",
        "su",
        "ya",
        "cuando",
        "añade",
        "agrega",
        "quita",
        "arregla",
        "corrige",
        "usa",
        "evita",
        "mueve",
        "actualiza",
    ]
)
_EN_MARKERS = frozenset(
    [
        "the",
        "to",
        "for",
        "and",
        "of",
        "in",
        "with",
        "from",
        "on",
        "by",
        "when",
        "is",
        "are",
        "add",
        "adds",
        "fix",
        "fixes",
        "remove",
        "removes",
        "update",
        "updates",
        "use",
        "uses",
        "avoid",
        "move",
        "moves",
        "bump",
        "drop",
        "handle",
    ]
)
_REPO_LANGUAGE_MIN_VOTES = 5
_REPO_LANGUAGE_MIN_SHARE = 0.7
_REFLOG_TAIL_BYTES = 65_536


def _git_dir_above(start: Path) -> Path | None:
    """The git dir of the work tree that contains `start`, following a worktree's `.git` file."""
    for folder in (start, *start.parents):
        dot_git = folder / ".git"
        try:
            if dot_git.is_dir():
                return dot_git
            if dot_git.is_file():
                text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
                if text.startswith("gitdir:"):
                    target = Path(text[len("gitdir:") :].strip())
                    target = target if target.is_absolute() else folder / target
                    return target if target.is_dir() else None
                return None
        except OSError:
            return None
    return None


def _recent_commit_subjects(git_dir: Path, limit: int = 20) -> list[str]:
    """The subjects of the last `limit` commits made in this clone, newest last."""
    reflog = git_dir / "logs" / "HEAD"
    try:
        with reflog.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _REFLOG_TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    subjects = []
    for line in tail.splitlines():
        _, _, message = line.partition("\t")
        if match := _REFLOG_COMMIT.match(message):
            subjects.append(match.group(1).strip())
    return subjects[-limit:]


def _guess_language(subjects: Sequence[str]) -> str | None:
    """`"es"` or `"en"` when the subjects clearly agree; `None` when they are few or mixed.

    Each subject votes by counting marker words (the Conventional prefix aside); an accented
    letter counts as Spanish. Ties and subjects without markers do not vote.
    """
    votes = {"es": 0, "en": 0}
    for subject in subjects:
        text = _CONVENTIONAL_PREFIX.sub("", subject).lower()
        words = re.findall(r"[a-záéíóúüñ]+", text)
        es = sum(w in _ES_MARKERS for w in words) + len(re.findall(r"[áéíóúñ¿¡]", text))
        en = sum(w in _EN_MARKERS for w in words)
        if es != en:
            votes["es" if es > en else "en"] += 1
    total = votes["es"] + votes["en"]
    if total < _REPO_LANGUAGE_MIN_VOTES:
        return None
    winner = max(votes, key=lambda k: votes[k])
    return winner if votes[winner] / total >= _REPO_LANGUAGE_MIN_SHARE else None


def _repo_commit_language(path: str | None) -> str | None:
    """The language of the recent commits of the repo that holds the diff file, if clear."""
    if not path:
        return None
    try:
        start = Path(path).expanduser().resolve().parent
    except (OSError, RuntimeError, ValueError):
        return None
    git_dir = _git_dir_above(start)
    if git_dir is None:
        return None
    return _guess_language(_recent_commit_subjects(git_dir))


def _commit_language_instruction(path: str | None = None) -> str:
    """La orden de idioma del prompt de sistema de `local_commit_msg` (REQ-044, REQ-028).

    Medido en la tanda de afinidad (2026-10-07): con el prompt de antes, que no pedía idioma, el
    26B escribió 17 de 30 mensajes en inglés y Qwen3.6 6 de 30, sobre un repo documentado en
    español. Precedencia (enmienda del 2026-10-14, decisión del usuario): la variable
    `LOCAL_DELEGATE_COMMIT_LANGUAGE` si está puesta; si no, el idioma vigente del producto. La regla
    de antes, «el idioma predominante del diff», queda solo como el valor explícito `diff`: en repos
    bilingües el modelo elegía uno u otro. `LOCAL_DELEGATE_OUTPUT_LANGUAGE` no entra aquí.
    #461: between the variable and the product language goes the language of the recent commits
    of the repo that holds `path`, when the reflog says it clearly (`_repo_commit_language`).
    """
    code = config.commit_language()
    if code.lower() == COMMIT_LANGUAGE_DIFF:
        return (
            "Escribe el mensaje de commit entero (primera línea y cuerpo) en el idioma "
            "predominante de los textos del diff (comentarios, documentación y mensajes)."
        )
    name = _language_name(code or _repo_commit_language(path) or i18n.lang())
    return f"Escribe el mensaje de commit entero (primera línea y cuerpo) en {name}."


def _language_name(code: str) -> str:
    """Un código de idioma con su nombre legible para el prompt; lo que no se conoce, tal cual.

    `es-CU` y `es_ES` se reconocen por su primera parte.
    """
    first_part = code.lower().replace("_", "-").split("-")[0]
    return _LANGUAGE_NAMES.get(first_part, code)


def _response_language_clause() -> str:
    """La orden de idioma de las 4 tools de texto libre (REQ-028), que va DETRÁS de `_guard`.

    Sale de `i18n.response_language()`, la única regla (variable de salida → idioma vigente), y se
    lee en cada llamada. Los prompts no se traducen: solo se añade esta orden.
    """
    name = _language_name(i18n.response_language().value)
    return f" Responde en {name}, aunque el contenido esté en otro idioma."


def _written_language_clause() -> str:
    """The hardened language order of `local_summarize` and `local_lint_summary` (REQ-028, B2d).

    Same place and same rule as `_response_language_clause`, which explain_code and describe_image
    keep (10/10 in the live sample). Here the plain order gave 34/40 over the four tools, with
    summarize 8/10 and lint_summary 6/10, and none of the failures was in the opposite language:
    they were mixed. The model translated the frame and kept fragments of the input as they were
    ("Múltiples `if` statements", "Restoration successful."), writing noun phrases instead of
    sentences. So the order now says what is written in the requested language (every
    sentence, also the description of each error or rule, in full sentences and not copied from
    the input) and the only things that stay verbatim (requested headings, paths, code,
    identifiers and rule or error codes).

    B2d-2: the order also names the bold labels, as `_lint_language_clause` does since B2d-fix. In
    set 3 the model copied the document's subheadings as `**…**` labels in the other language (5
    in batch 1 and 4 in batch 2): the order listed "the headings asked for verbatim" as what stays
    as it is, and the model took the labels of the subsections for them. Only the `## ` lines of
    the list are asked for verbatim; the labels are text to write in the requested language.
    """
    name = _language_name(i18n.response_language().value)
    return _written_language_head(name) + (
        f" También van en {name} las etiquetas en negrita, también las que nombran una "
        "subsección: tradúcelas aunque en el contenido aparezcan en otro idioma. Solo se quedan "
        "tal cual los títulos de las líneas '## ' que se piden literales, las rutas, el código, "
        "los identificadores y los códigos de regla o de error."
    )


def _written_language_head(name: str) -> str:
    """What both hardened orders share: every sentence is written in `name`, not copied."""
    return (
        f" Escribe toda la respuesta en {name}, aunque el contenido esté en otro idioma: redacta "
        f"en {name} cada frase, también la descripción de cada error o regla, con frases "
        "completas y sin copiar frases del contenido."
    )


def _lint_language_clause() -> str:
    """The language order of `local_lint_summary`: the hardened one, plus its labels (B2d-fix).

    In the live probe X (`evidence/B2d-fix/live-probe-X.json`) the model wrote its sentences in
    English but copied 5-8 bold labels and check names of the Spanish `doctor` report as they were
    ("Cadenas de respaldo", "Coste y relleno", "Servicios"), which the plain hardened order allowed:
    it said nothing about labels, and it listed "the headings asked for verbatim", which a lint
    summary does not have and the model could take for its labels. So here the labels, section
    names and check names are named explicitly as text to write in the requested language, and
    the verbatim list is only paths, code, identifiers and rule or error codes. `local_summarize`
    keeps `_written_language_clause`: its `##` headings must stay verbatim.
    """
    name = _language_name(i18n.response_language().value)
    return _written_language_head(name) + (
        f" También van en {name} las etiquetas en negrita, los nombres de sección y los nombres "
        "de cada chequeo o prueba: tradúcelos aunque en el contenido aparezcan en otro idioma. "
        "Solo se quedan tal cual las rutas, el código, los identificadores y los códigos de regla "
        "o de error."
    )


def _guard(output_format: str, max_words: int | None = None) -> str:
    limit = f" Máximo {max_words} palabras." if max_words else ""
    return (
        "Responde directo desde el input. NO uses herramientas, NO busques en internet. "
        f"Output EXACTO: {output_format}.{limit} Nada fuera del formato."
    )


#: #455: chars of code per output token allowed in a map step of the chunked `local_explain_code`.
#: With the shared `2·350+64 = 764` tokens, 15 of 15 chunked runs (October log) cut some map note,
#: at ~3 100-3 200 characters (~4.2 per token) for chunks of ~12 000: the notes needed more than
#: 27 % of the chunk. `len // 8` gives 1 500 tokens (~6 300 characters, half the chunk, twice the
#: observed need) for 12 000 and 2 000 at the 16 000 of the `code` budget, under
#: `CHUNK_MAX_TOKENS` (2 048); that chunk (~5 300 tokens at 3 chars/token) plus 2 000 asks the
#: model about as much as the single call already does (20 000 characters plus 700 tokens). The reduce prompt is still
#: measured against `budget`, and longer notes regroup instead of overflowing.
EXPLAIN_MAP_CHARS_PER_TOKEN = 8


def _explain_map_max_tokens(piece: str, words: int) -> int:
    """The cap of each map step of the chunked `local_explain_code`; never below the shared one."""
    shared = int(words * 2) + 64
    return max(shared, min(len(piece) // EXPLAIN_MAP_CHARS_PER_TOKEN, config.CHUNK_MAX_TOKENS))


# Output caps of `local_lint_summary` (B2d-2). Before: `2·w+96` in the single call (496 tokens for
# the default 200 words) and the shared `2·w+64` of the chunking. With the hardened language order
# (71846c1) `gemma4-26b-a4b` went from 3 of 22 truncated lint answers to 3 of 4, all stopped at
# exactly 496: a lint summary carries paths, codes and counts, which cost more tokens per word
# than prose. PROVISIONAL values, to be confirmed by the live measurement of
# `evidence/B2d-2/live-plan.md` (0 truncated gemma4 lint answers on the sample).
LINT_TOKENS_PER_WORD = 3
LINT_TOKENS_BASE = 128
LINT_CHUNK_TOKENS_BASE = 96


def _lint_max_tokens(words: int) -> int:
    """The cap of the single `local_lint_summary` call for `words` words."""
    return int(words * LINT_TOKENS_PER_WORD) + LINT_TOKENS_BASE


#: B2f (rule (2) of the user, 2026-10-18): the single call of the `long` role doubles its cap.
#: With the inventory in front of the log, `gemma4-26b-a4b` names every rule code with its
#: description, and the ruff logs with the most codes ended in `length` at 728 tokens in 3 of 3
#: repetitions (`evidence/B2f/live.md`). The `mechanical` role keeps `_lint_max_tokens`.
LINT_LONG_SINGLE_TOKENS_FACTOR = 2


def _lint_single_max_tokens(words: int, role: str) -> int:
    """The cap of the single `local_lint_summary` call: twice as much with the `long` role."""
    factor = LINT_LONG_SINGLE_TOKENS_FACTOR if role == "long" else 1
    return factor * _lint_max_tokens(words)


def _lint_chunk_max_tokens(words: int) -> int:
    """The base cap of the steps of the chunked `local_lint_summary` (map and final steps)."""
    return int(words * LINT_TOKENS_PER_WORD) + LINT_CHUNK_TOKENS_BASE


#: Wave lint-large-logs (limit step, 2026-10-19): the map of the chunked lint doubles its cap
#: (1 392 tokens for 200 words). Even with the terse format (one line per listed file, only its
#: codes) the map steps of a ruff log of 180 k characters reach ~3 000 characters, ten files with
#: dozens of codes each, and 696 tokens cut them (`evidence/lint-large-logs/plan.md`, iteration 2).
LINT_MAP_TOKENS_FACTOR = 2


def _lint_map_max_tokens(words: int) -> int:
    """The cap of each map step of the chunked `local_lint_summary`."""
    return LINT_MAP_TOKENS_FACTOR * _lint_chunk_max_tokens(words)


# B2e (user decision of 2026-10-18): the cap of the FINAL steps of the chunked lint (reduce and
# regroup) is three times the map cap: 2 088 tokens for the default 200 words, against 696
# before. With 696 the final step of the logs of 6 and 8 chunks (L1-L3) ended in `length` in the
# 18 calls of the branch, at 2 023-2 850 characters (~4 per token): the lint format asks for one
# entry per file, and those logs name 40-109 files, so ~60-70 characters per entry needs
# ~1 800-2 050 tokens for the longest. The single call keeps its caps (`_lint_max_tokens`), and
# the map keeps `_lint_chunk_max_tokens`. With the reduce prompt within `_map_budget` (38 400
# characters for `long`), prompt plus output stays under the 38 400 tokens of `gemma4-26b-a4b`.
# Wave lint-large-logs (limit step, 2026-10-19): four times, 2 784 tokens. With the entries bounded
# to the 10 most named files, the final step of a ruff log with 91 codes still ended in `length`
# at ~6 000 characters (~3 per token) in 2 of 3, its section of totals naming every code.
LINT_FINAL_TOKENS_FACTOR = 4


def _lint_final_max_tokens(words: int) -> int:
    """The cap of the steps that combine partials (reduce and regroup) of the chunked lint."""
    return LINT_FINAL_TOKENS_FACTOR * _lint_chunk_max_tokens(words)


def _lint_count_clause() -> str:
    """The count rule of `local_lint_summary` (B2d-3), in the single call and in the reduce.

    The format asked for "the count per error type/rule" with no condition, and when the log had
    no figures the model made them up: in the live measurement of B2d-2 `fidelity_total` went from
    9 to 12 over the 10 logs of set 3, with per-item counts in parentheses ("Claude Code Client
    (3)") that the log does not carry. A count now comes only from the log: the one it writes (a
    total line or a written count) or the one obtained by counting lines it repeats; otherwise no
    number at all.

    Step 1b (2026-10-17): a total line of the log ("Found 10 errors.", "57 passed") is copied as
    it is. In the live measurement of step 1 the answers of `ruff` lost theirs ("Found 10
    errors.", "Found 7 errors."; `evidence/B2d-3/live.md`). The examples carry no figures, so
    that the model has none to copy from the prompt; with no total line, no total.

    B2d-4 (second round, 2026-10-17): no sentence of its own for the compacted block. The marker
    of `compact_repeated_lines` writes both figures ("y N más", "M en total"), so it is a count the
    content writes, which this rule already covers. With a sentence of its own, in the first round
    the model of A12 counted the lines it saw instead of copying N (`evidence/B2d-4/live.md`).
    """
    return (
        " La cantidad sale solo del contenido: la que el contenido escribe (una línea de total o "
        "un recuento) o la que cuentas tú con las líneas que el contenido repite. Si el contenido "
        "no la da y no se puede contar, no pongas ningún número: nada de recuentos entre "
        "paréntesis. Si el contenido trae una línea de total (la que dice cuántos errores, "
        "avisos o tests hay, como «Found … errors.» o «… passed»), cópiala tal cual, con sus "
        "cifras; si no la trae, no inventes ninguna."
    )


# B2d-4: lines with the same problem are compacted BEFORE the model sees them. With the count rule
# of B2d-3 (step 1b) the 89-line `corpus affinity --check` log (B35) was cut by `max_tokens` in
# the 3 repetitions: the model named one by one the 80-odd `commit-…` items with the same message,
# and the step 1c rule ("one line that names them together") named them all in one line and was
# cut too. A prompt rule depends on the model obeying it; here the program does it and counts N
# itself, so the model cannot list what it does not see nor make up how many there are.
#: A group of lines this large (equal but for one token) is compacted.
LINT_REPEAT_MIN = 10
#: How many lines of a compacted group reach the model, in their place in the log.
LINT_REPEAT_KEEP = 3
#: Members of a group further apart than this many lines start another group.
LINT_REPEAT_GAP = 3
#: A token with a path or a file location: a line that has one never groups (a lint log with the
#: same rule in many files, or many times in one file, keeps every diagnostic).
_LOCATION_TOKEN = re.compile(r"[/\\]|\.[A-Za-z]{1,5}(?::\d+)*:?$|:\d+")
#: A token that is only a figure: never the one that changes either (figures are what the count
#: rule and the control of the live measurement protect).
_FIGURE_TOKEN = re.compile(r"[\d.,:;%()<>=+~-]+")


def _repeat_keys(tokens: list[str]) -> list[tuple[str, ...]]:
    """The templates of a line: the line with ONE token masked, for each token that may change."""
    if any(_LOCATION_TOKEN.search(token) for token in tokens):
        return []  # a diagnostic tied to a place in a file is never compacted
    keys = []
    for i, token in enumerate(tokens):
        if _FIGURE_TOKEN.fullmatch(token):
            continue
        keys.append((str(i), *tokens[:i], "\0", *tokens[i + 1 :]))
    return keys


def compact_repeated_lines(text: str) -> tuple[str, list[int]]:
    """Compact the groups of lines that are equal but for one token (`local_lint_summary`, B2d-4).

    A dense block (members at most `LINT_REPEAT_GAP` lines apart) of `LINT_REPEAT_MIN` lines or
    more keeps its first `LINT_REPEAT_KEEP` lines where they are, and after the last of them a
    line says how many more there are and how many in all, counted here. Lines with
    fewer than three tokens never group (a list of bare hashes is not "the same problem"), nor a
    line with a path or a file location, and a bare figure is never the token that changes. Returns the text and the sizes
    of the compacted groups (for the tests and the fidelity counter).
    """
    lines = text.splitlines()
    split = [line.split() for line in lines]
    keys = [_repeat_keys(tokens) if len(tokens) >= 3 else [] for tokens in split]
    counts: dict[tuple[str, ...], int] = {}
    for line_keys in keys:
        for key in set(line_keys):
            counts[key] = counts.get(key, 0) + 1
    # Each line goes to its largest template (ties: the first token that may change).
    chosen = [max(k, key=lambda key: counts[key]) if k else None for k in keys]
    positions: dict[tuple[str, ...], list[int]] = {}
    for index, key in enumerate(chosen):
        if key is not None:
            positions.setdefault(key, []).append(index)
    # A group is a dense block (B35: two templates interleaved line by line), not lines that come
    # back far apart: the same hint repeated under each diagnostic of a Biome log stays as it is.
    blocks: list[list[int]] = []
    for members in positions.values():
        block = [members[0]]
        for index in members[1:]:
            if index - block[-1] > LINT_REPEAT_GAP:
                blocks.append(block)
                block = []
            block.append(index)
        blocks.append(block)
    blocks = [block for block in blocks if len(block) >= LINT_REPEAT_MIN]
    if not blocks:
        return text, []
    dropped = {index for block in blocks for index in block[LINT_REPEAT_KEEP:]}
    # The marker gives both figures, counted here: how many more and how many in all. With only N
    # (first round of B2d-4) the model of A12 counted the lines it saw ("6 instances") instead.
    markers = {block[LINT_REPEAT_KEEP - 1]: len(block) for block in blocks}
    out: list[str] = []
    for index, line in enumerate(lines):
        if index in dropped:
            continue
        out.append(line)
        if index in markers:
            indent = line[: len(line) - len(line.lstrip())]
            size = markers[index]
            more = size - LINT_REPEAT_KEEP
            out.append(f"{indent}… y {more} líneas más como las anteriores ({size} en total)")
    tail = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + tail, sorted(len(block) for block in blocks)


def _lint_inventory_line(header: str, items: list[str], max_chars: int) -> str:
    """Una línea del inventario del lint troceado, recortada SIN cifras («y otros»)."""
    if not items:
        return ""
    shown: list[str] = []
    used = len(header) + len(" y otros")
    for item in items:
        if used + len(item) + 2 > max_chars:
            break
        shown.append(item)
        used += len(item) + 2
    if not shown:
        return ""
    tail = " y otros" if len(shown) < len(items) else ""
    return f"{header} {', '.join(shown)}{tail}"


def _lint_inventory(log: str, max_chars: int, with_counts: bool = False) -> str:
    """B2e: los ficheros y códigos de regla del log, calculados por programa, sin recuentos.

    En el lint troceado el reduce solo veía los parciales, y en vivo (B2d-2, tanda C) devolvió dos
    párrafos de prosa sin un código ni un fichero. Las expresiones son las del contador de
    fidelidad (`lint_patterns`); los más nombrados van primero y no se dice cuántos: una cifra que
    el log no escribe es justo lo que la regla de la cantidad prohíbe.

    Wave lint-counts (2026-10-18): with `with_counts` each code carries how many times the whole
    log names it (`lint_patterns.code_counts`), counted here. Only the single call of the `long`
    role asks for it, where the model sees the whole log: in the live pass of 0.36.0 the Spanish
    summary of a ruff log of 14 k characters got 2 of 15 figures wrong (D101 6 instead of 5, D400
    4 instead of 3) by counting them itself (`evidence/lint-counts/live.md`). The chunked reduce
    keeps the inventory without figures.
    """
    half = max_chars // 2
    files = _lint_inventory_line(
        "Ficheros que nombra el log (los más nombrados primero):",
        lint_patterns.files_by_frequency(log),
        half,
    )
    if with_counts:
        header = (
            "Códigos de regla o error que nombra el log, con las veces que aparece cada uno en "
            "todo el log (contadas por el programa; los más frecuentes primero):"
        )
        items = [f"{code}: {count}" for code, count in lint_patterns.code_counts(log)]
    else:
        header = "Códigos de regla o error que nombra el log (los más frecuentes primero):"
        items = lint_patterns.codes_by_frequency(log)
    codes = _lint_inventory_line(header, items, max_chars - len(files) - 1)
    return "\n".join(line for line in (files, codes) if line)


def _lint_not_mentioned(answer: str, log: str) -> str:
    """B2e fallback: what of the inventory the summary does not name, added by the program.

    One line and no figures, so that the reader knows which files and rules of the log were left
    out. B2e put it in the chunked lint; B2f also in the single call of the `long` role.
    """
    missing = lint_patterns.not_mentioned(answer, log)
    if not missing:
        return answer
    line = i18n.t("mcp.lint.not_mentioned", items=", ".join(missing))
    return f"{answer.rstrip()}\n\n{line}"


def _lint_single_user(content: str, log: str, role: str) -> str:
    """The user prompt of the single `local_lint_summary` call.

    B2f: with the `long` role the inventory of files and rule codes of the log (computed by the
    program, without counts, as in the chunked reduce of B2e) goes in front of the log. In the live
    measurement of B2-affinity `gemma4-26b-a4b`, the model of that role, named no rule code in 9 of
    9 Spanish answers ("Línea demasiado larga" instead of `E501`), and `evidence/B2f/live.md`
    measured the same in the logs of 8-34 k characters it summarizes in one call. B2f left the
    `mechanical` role as it was (`gemma3-4b` copies the codes).

    Wave lint-counts: each code of that inventory carries its count in the whole log, and the
    prompt says to copy it (`_LINT_COUNTS_CLAUSE`).

    Affinity by language (2026-10-18): the `mechanical` role gets the same inventory. The
    affinity cell `local_lint_summary -> gemma4-26b-a4b` serves the mechanical call with the
    26B and the mechanical prompt, and without the inventory the 26B named no rule code in 9 of
    9 Spanish answers (`evidence/B2-affinity/live.md`); `evidence/affinity-by-language/live.md`.
    """
    base = f"Resume la siguiente salida de linter/tests:\n\n{content}"
    budget = int(_map_budget(config.max_chars_for_role(role)) * 0.25)
    inventory = _lint_inventory(log, budget, with_counts=True)
    if not inventory:
        return base
    return f"{inventory}\n\nLa lista de arriba sale del log de abajo.{_LINT_COUNTS_CLAUSE} {base}"


#: Wave lint-large-logs: how many files get an entry in the chunked lint (map and final step).
#: The same 10 as the "not mentioned" line (`lint_patterns.not_mentioned`). With one entry per
#: file, the final step of logs naming 50-130 files wrote 6-8 k characters and ended in `length`
#: in 7 of 9 calls even with 2 088 tokens (`evidence/B2e/live.md`); the rest is a line counted by
#: the program.
LINT_TOP_FILES = 10


def _lint_map_user(piece: str) -> str:
    """The user prompt of each map step (and regroup) of the chunked lint (wave lint-large-logs).

    No figures per file: a chunk sees only part of each file, and in B2e the model counted the
    tests per file of a pytest log chunk by chunk and got them wrong (`evidence/B2e/live.md`). The
    final step gets the counts of the whole log from the program. With more files than
    `LINT_TOP_FILES`, only the most named of the chunk get an entry, so the output stays bounded.

    Iteration 2: a terse format, one line per file with only its codes or kinds of problem. In
    iteration 1 the map wrote one sentence per rule and an entry for every file of the chunk, and
    38 of the 66 map steps ended in `length` (`evidence/lint-large-logs/plan.md`).
    """
    files = lint_patterns.files_by_frequency(piece)
    head = (
        "Esto es un trozo de un log mayor. Responde en formato escueto: una línea por fichero, "
        "«fichero: códigos o tipos de problema separados por comas», sin explicarlos y sin "
        "cifras (las cifras las pone el programa en el paso final)."
    )
    if len(files) > LINT_TOP_FILES:
        head += (
            f" El trozo nombra {len(files)} ficheros: da entrada solo a estos, los más nombrados, "
            f"y a ningún otro: {', '.join(files[:LINT_TOP_FILES])}."
        )
    return f"{head}\n\nResume la siguiente salida de linter/tests:\n\n{piece}"


def _lint_final_inventory(log: str, max_chars: int) -> tuple[str, int]:
    """The inventory of the final step of the chunked lint, and how many files are left out.

    Wave lint-large-logs: the `LINT_TOP_FILES` most named files (with their number of diagnostics
    when the format lets the program count it) and the codes of the whole log with their count.
    The prompt asks for one entry per listed file only; `_lint_other_files` adds the rest.
    """
    files = lint_patterns.files_by_frequency(log)
    top = files[:LINT_TOP_FILES]
    per_file = lint_patterns.per_file_code_counts(log)
    totals = {f.lower(): sum(c.values()) for f, c in (per_file or {}).items()}
    if per_file is not None:
        header = (
            f"Los {len(top)} ficheros más nombrados del log (de {len(files)}), con su número de "
            "diagnósticos contado por el programa:"
        )
        items = [f"{f} {totals[f.lower()]}" if f.lower() in totals else f for f in top]
    else:
        header = f"Los {len(top)} ficheros más nombrados del log (de {len(files)}):"
        items = top
    lines = [f"{header} {', '.join(items)}"] if top else []
    rule = ""
    if top:
        rule = (
            f"Escribe una entrada solo para los {len(top)} ficheros de la lista, en ese orden"
            + (
                "; el programa añade al final cuántos más hay. Ninguna entrada más tras el último."
                if len(files) > len(top)
                else "."
            )
        )
        if per_file is not None:
            rule += (
                " El total de cada fichero es el de la lista. Las cifras por código son del log "
                "entero: van en un apartado final de totales, nunca dentro de la entrada de un "
                "fichero."
            )
        else:
            rule += (
                " El log no da cifras por fichero: no pongas ninguna en las entradas. Las cifras "
                "por código, si la lista las da, son del log entero y van en un apartado final de "
                "totales."
            )
    # The rule goes first in the budget and the codes line takes what is left: the reduce prompt
    # is measured whole, and one over the budget regroups instead of reducing (B2e).
    code_items = [f"{code}: {count}" for code, count in lint_patterns.code_counts(log)]
    codes = _lint_inventory_line(
        "Códigos de regla o error del log entero, con las veces que aparece cada uno (contadas "
        "por el programa; los más frecuentes primero):",
        code_items,
        max_chars - sum(len(line) + 1 for line in lines) - len(rule) - 1,
    )
    if codes:
        lines.append(codes)
    if rule:
        lines.append(rule)
    return "\n".join(lines), len(files) - len(top)


def _lint_other_files(answer: str, left_out: int) -> str:
    """Wave lint-large-logs: the line of the program with how many files got no entry."""
    if left_out <= 0:
        return answer
    return f"{answer.rstrip()}\n\n{i18n.t('mcp.lint.other_files', count=left_out)}"


#: Wave lint-counts: what the single `long` call is told about the figures of its inventory.
_LINT_COUNTS_CLAUSE = (
    " Las cifras de los códigos están contadas por el programa en todo el log: nombra cada regla "
    "por su código, tal cual aparece en la lista, y cuando des su cantidad en total copia esa "
    "cifra en vez de contar tú."
)


def _lint_system(max_words: int) -> str:
    """El prompt de sistema de `local_lint_summary`. También entra en la huella (T15). Con la orden
    de idioma de REQ-028 depende del idioma de respuesta; B2-affinity lo midió en `es` y en `en`
    y la celda de afinidad de lint no llegó al criterio (ni con el 26B ni con Qwen3.6: dejan de
    nombrar los códigos de regla), así que salió de `matrix.CELLS`. Volvió con la afinidad por
    idioma (2026-10-19): una celda por idioma, con el inventario también en la llamada mecánica
    (`_lint_single_user`). B2d-3: la cantidad, solo cuando se puede saber
    (`_lint_count_clause`)."""
    return (
        _guard(
            "un resumen de los problemas agrupados por archivo, con la cantidad por tipo de "
            "error/regla cuando se pueda saber y los más relevantes primero",
            max_words,
        )
        + _lint_count_clause()
        + _lint_language_clause()
    )


def _translate_system(target_lang: str) -> str:
    """El prompt de sistema de `local_translate`. También entra en la huella (T15)."""
    return _guard(f"la traducción fiel al {target_lang}, conservando el formato y sin comentarios")


# --- Validación de imagen (local_describe_image, F6) -------------------------
_IMAGE_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _validate_image_path(path: str) -> str:
    """Valida la ruta de una imagen para local_describe_image. Devuelve su mime type.

    Orden: raíces permitidas -> extensión soportada (sin tocar disco) -> el archivo existe
    -> tamaño <= MAX_IMAGE_MB (con stat(), sin leer el archivo completo solo para rechazarlo).
    """
    _check_allowed_dir(path)
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in _IMAGE_MIME:
        raise ValueError(
            i18n.t("mcp.input.image_extension", suffix=suffix, valid=sorted(_IMAGE_MIME))
        )
    if not p.is_file():
        raise ValueError(i18n.t("mcp.input.missing_file", path=path))
    size = p.stat().st_size
    max_bytes = config.MAX_IMAGE_MB * 1024 * 1024
    if size > max_bytes:
        raise ValueError(
            i18n.t(
                "mcp.input.image_too_large",
                size=_machine(size / 1024 / 1024, 1),
                max=config.MAX_IMAGE_MB,
            )
        )
    return _IMAGE_MIME[suffix]


# --- Resumen estructurado (local_summarize, SDD resumen-por-secciones) ------------------------
# En el piloto de T5 la tool nombró entre el 0 % y el 27 % de los títulos aunque Claude pidió
# 450-600 palabras: el prompt pedía «prosa clara» y el modelo aplanaba el documento. Aquí el
# servidor detecta las secciones (`sections.detect`), se las da al modelo en orden y después
# completa las que falten (`sections.complete`).
#
# El presupuesto por sección va EXPLÍCITO en la lista, y en proporción al tamaño de cada sección
# (v3). La primera versión pedía «1 a 3 frases» y con el CHANGELOG (46 secciones, 500 palabras) el
# modelo escribió el doble y se cortó (etapa 1); la v2 repartía a partes iguales y las secciones
# con subsecciones se quedaban cortas: Claude las releía (etapa 2, 3/9).
_MIN_WORDS_PER_SECTION = 8
_TOKEN_SLACK_PER_SECTION = 24
_STRUCTURED_FORMAT = (
    "un resumen que sigue la estructura del documento: por cada sección de la lista, en ese "
    "orden, una línea '## ' con el título tal cual y debajo lo que dice, en las palabras que "
    "indica la lista; si la sección trae subsecciones, nombra cada una en negrita al empezar la "
    "frase que la resume"
)
_STRUCTURED_NOTE = (
    " Los títulos no cuentan en el límite de palabras; si no alcanzan para todas, deja solo el "
    "título en las últimas."
)


def _focus_clause(focus: str | None) -> str:
    """El enfoque, ya saneado, delimitado como dato dentro del prompt de sistema."""
    if not focus:
        return ""
    return (
        f" Prioriza este aspecto: «{focus}». Conserva literales los datos concretos que tengan que "
        "ver con él (cifras, nombres, decisiones)."
    )


def _structured_system(max_words: int, extra: str) -> str:
    return _guard(_STRUCTURED_FORMAT, max_words) + _STRUCTURED_NOTE + extra


def _section_list(sections_, max_words: int) -> str:
    """Una línea por sección con sus palabras, y sus subsecciones anidadas debajo."""
    allocation = sections.allocate_by_size(
        [s.content_size for s in sections_], max_words, minimum=_MIN_WORDS_PER_SECTION
    )
    lines = []
    for section, words in zip(sections_, allocation, strict=True):
        note = " (el texto antes de la primera sección)" if section.synthetic else ""
        if section.empty:
            # B2d-2: no words for a section with nothing under it, so nothing is invented.
            lines.append(f"- {section.heading} (vacía en el documento: solo el título)")
        else:
            lines.append(f"- {section.heading}{note} (unas {words} palabras)")
        lines.extend(f"  - {sub}" for sub in section.subheadings)
    return "\n".join(lines)


def _structured_user(
    sections_, max_words: int, content: str, continues_from: str | None = None
) -> str:
    parts = []
    if continues_from:
        parts.append(
            f"El fragmento empieza a mitad de la sección «{continues_from}»: resume primero ese "
            "principio en 1 o 2 frases, sin línea de título; después, las secciones de la lista."
        )
    parts.append(f"Secciones, en orden:\n{_section_list(sections_, max_words)}")
    parts.append(f"Resume el siguiente contenido:\n\n{content}")
    return "\n\n".join(parts)


def _structured_max_tokens(words: int, sections_) -> int:
    """Sitio para los títulos y subtítulos, que no cuentan en `max_words` (REQ-202), y margen.

    3 tokens por palabra pedida y no 2: con muchas secciones el modelo se pasa del presupuesto, y
    un corte por `max_tokens` a mitad de un trozo deja secciones enteras sin resumir, que es peor
    que un resumen algo más largo (etapa 1: 3 de 5 trozos del CHANGELOG cortados con 2).
    """
    headings = [s.heading for s in sections_] + [t for s in sections_ for t in s.subheadings]
    # Y un colchón por sección: con el reparto por tamaño a una sección pequeña le tocan 8
    # palabras y el modelo escribe al menos una frase entera; sin colchón, el CHANGELOG (47
    # secciones) volvía a cortarse por `max_tokens` (etapa 1 de la v3).
    slack = _TOKEN_SLACK_PER_SECTION * len(sections_)
    return int(words * 3) + 64 + sum(len(t) // 2 + 8 for t in headings) + slack


def _structured_summary(
    *,
    model: str,
    role: str,
    content: str,
    structure,
    max_words: int,
    extra: str,
    focus: bool,
    source: str,
    truncated_in: bool,
    raw_len: int | None,
    path: str | None,
) -> str:
    plan = sections.sections_for_summary(content, structure)
    headings = [s.heading for s in plan]
    empty_in_document = frozenset(i for i, s in enumerate(plan) if s.empty)

    def _complete(text: str, truncated: bool) -> str:
        return sections.complete(
            text, headings, truncated=truncated, empty_in_document=empty_in_document
        ).text

    max_chars = config.max_chars_for_role(role)
    if len(content) <= max_chars:
        return _chat(
            model,
            _structured_system(max_words, extra),
            _structured_user(plan, max_words, content),
            max_tokens=_structured_max_tokens(max_words, plan),
            tool="local_summarize",
            role=role,
            chars_in=len(content),
            source=source,
            truncated_in=truncated_in,
            raw_len=raw_len,
            path=path,
            postprocess=_complete,
            num_sections=len(plan),
            focus=focus,
        )

    # Documento largo: se trocea SOLO al principio de las secciones (nunca en un `#` de una valla
    # de código), cada trozo se resume con sus secciones y su parte de `max_words`, y los
    # parciales se concatenan en orden: ya están en el formato final.
    chunks = sections.allocate_words(
        sections.chunks_by_sections(content, plan, _map_budget(max_chars), _chunk_text),
        max_words,
    )

    def _chunk_system(chunk) -> str:
        if chunk.sections:
            return _structured_system(chunk.words, extra)
        return _guard("un resumen en prosa clara", chunk.words) + extra

    def _chunk_user(chunk) -> str:
        text = chunk.text.strip()
        if chunk.sections:
            return _structured_user(chunk.sections, chunk.words, text, chunk.continues_from)
        if chunk.continues_from:
            return (
                f"Este fragmento continúa la sección «{chunk.continues_from}». Resume solo este "
                f"fragmento en 1 a 3 frases, sin línea de título:\n\n{text}"
            )
        return f"Resume el siguiente contenido:\n\n{text}"

    return _chat_map_reduce(
        model,
        _structured_system(max_words, extra),
        content,
        lambda piece: f"Resume el siguiente contenido:\n\n{piece}",
        max_chars=max_chars,
        tool="local_summarize",
        role=role,
        source=source,
        max_words=max_words,
        raw_len=raw_len,
        path=path,
        pieces=chunks,
        system_for=_chunk_system,
        user_for=_chunk_user,
        words_for=lambda chunk: chunk.words,
        tokens_for=lambda chunk, words: _structured_max_tokens(words, chunk.sections),
        split_for=lambda chunk: sections.split_chunk(chunk, content, plan, _chunk_text),
        reduce="concat",
        postprocess=_complete,
        num_sections=len(plan),
        focus=focus,
    )


# --- Tools ------------------------------------------------------------------
@mcp.tool(annotations=_annotations(TOOL_TITLES["local_summarize"]))
def local_summarize(
    text: str | None = None,
    path: str | None = None,
    max_words: int = 150,
    focus: str | None = None,
) -> str:
    """PREFER this tool over reading the file with Read when the file is large
    (>200 lines / >10 KB) and you only need a summary, not the literal content.

    Summarizes text or the content of a file with a local model, without spending Claude's context.

    Use it to summarize large files/documents: pass 'path' and the file is read server-side, so
    the full content does NOT enter Claude's context (only the short summary comes back).
    Alternatively pass 'text'. Routes automatically to the mechanical model (short inputs) or to
    the long-context model (large documents).

    Args:
        text: Text to summarize (use this or 'path').
        path: Path to a file whose content is summarized (read server-side).
        max_words: Maximum length of the summary in words.
        focus: Optional. What you care about in the document (e.g. "configuration figures",
            "risks"): the summary prioritizes it and keeps its concrete data verbatim.
    """
    probe = path and Path(path).is_file()
    probe_len = Path(path).stat().st_size if probe else len(text or "")
    role, model = _role_for_size(probe_len)
    content, truncated_in, raw_len = _read_input(text, path, _NO_TRUNCATE)
    clean_focus = sections.sanitize_focus(focus)
    # La orden de idioma (REQ-028) va con el enfoque: así llega al map, al reduce y a cada trozo
    # del resumen estructurado, que la reciben por `extra`/`reduce_extra`.
    extra = _focus_clause(clean_focus) + _written_language_clause()
    # Solo con el modelo largo: el mecánico (4B, entradas cortas) se saltó la «Introducción» en la
    # etapa 1 de la v3 (0,86), y el criterio escrito antes de medir era limitarlo al rol `long`.
    structured = config.STRUCTURED_SUMMARY and role == "long"
    structure = sections.detect(content) if structured else None
    if structure is not None:
        return _truncation_prefix(content, truncated_in, raw_len) + _structured_summary(
            model=model,
            role=role,
            content=content,
            structure=structure,
            max_words=max_words,
            extra=extra,
            focus=clean_focus is not None,
            source="path" if path else "inline",
            truncated_in=truncated_in,
            raw_len=raw_len,
            path=path,
        )

    # Sin estructura (o con el interruptor apagado): el camino de siempre. Desde la 0.36.0 lleva
    # la orden de idioma (REQ-028); los corpus congelados lo declaran en `PROMPT_BOUNDARIES`.
    system = _guard("un resumen en prosa clara", max_words) + extra

    def _build(piece: str) -> str:
        return f"Resume el siguiente contenido:\n\n{piece}"

    if len(content) > config.max_chars_for_role(role):
        # No cabe: se resume por partes y luego se resumen los resúmenes. Antes esto se
        # truncaba, o sea que se resumía el principio y el resto se ignoraba.
        return _chat_map_reduce(
            model,
            system,
            content,
            _build,
            max_chars=config.max_chars_for_role(role),
            tool="local_summarize",
            role=role,
            source="path" if path else "inline",
            max_words=max_words,
            raw_len=raw_len,
            path=path,
            reduce_extra=extra,
            focus=clean_focus is not None,
        )

    user = _build(content)
    result = _chat(
        model,
        system,
        user,
        max_tokens=int(max_words * 2) + 64,
        tool="local_summarize",
        role=role,
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
        focus=clean_focus is not None,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_classify"]))
def local_classify(text: str, labels: list[str]) -> str:
    """Classifies a text into ONE of the given labels, with a local model.

    Returns exactly one label from the list, with no additional text.

    Args:
        text: Text to classify.
        labels: List of candidate labels.
    """
    label_list = ", ".join(labels)
    system = _guard(f"exactamente una de estas etiquetas: [{label_list}]", max_words=5)
    user = f"Clasifica este texto:\n\n{text}"
    return _chat(
        config.MODEL_MECHANICAL,
        system,
        user,
        max_tokens=16,
        temperature=0.0,
        tool="local_classify",
        role="mechanical",
        chars_in=len(text),
        source="inline",
    )


#: Palabras de cada paso de `local_extract` troceado: `_tokens(224)` son los 512 de la llamada única.
_EXTRACT_WORDS = 224


def _extract_shortcut(partials: list[str]) -> str | None:
    """El resultado de `local_extract` troceado sin llamar al modelo, si no hace falta juicio.

    Si como mucho UN parcial trae algún valor no nulo, ese parcial ya es el objeto final (o el
    primero, si ninguno trae nada). Con dos o más con datos decide el modelo (decisión 7 de B2).
    """
    objects: list[dict] = []
    for partial in partials:
        try:
            data = json.loads(_strip_fences(partial))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        objects.append(data)
    with_values = [o for o in objects if any(v is not None for v in o.values())]
    if len(with_values) > 1 or not objects:
        return None
    return json.dumps(with_values[0] if with_values else objects[0], ensure_ascii=False)


def _fill_nulls_from_partials(data: dict, fields: list[str], partials: list[str]) -> None:
    """#473: a requested field the reduce left null takes the first non-null value of the partials.

    In chunk order; a non-null value of the reduce is never overwritten. A partial that is not a
    JSON object is skipped. Deterministic: no model call.
    """
    objects: list[dict] = []
    for partial in partials:
        try:
            parsed = json.loads(_strip_fences(partial))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    for name in fields:
        if data.get(name) is not None:
            continue
        for obj in objects:
            if obj.get(name) is not None:
                data[name] = obj[name]
                break


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_extract"]))
def local_extract(
    fields: list[str],
    text: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """PREFER this tool over reading the file with Read when the file is large
    (>200 lines / >10 KB) and you only need structured fields, not the literal content.

    Extracts structured fields from a text/file as JSON, with a local model.

    Pass 'path' to read the file server-side (spends no Claude context) or 'text'. Returns an
    object with exactly the requested keys, already validated: the caller does not have to parse
    a string. What is not data travels under the reserved key `_local_delegate` (`truncated` and
    `warning`, `read_server_side`, `fallback`, or `error` and `raw`); with chunked input, `chunked`
    says how many pieces there were and which fields stayed null in all of them. Routes
    automatically to the mechanical model (short inputs) or to the long-context model (large
    documents): the size probe uses file bytes for 'path' and characters for 'text' (~5-10%
    difference in UTF-8, acceptable).
    By default it asks the backend for schema-constrained JSON (`LOCAL_DELEGATE_JSON_SCHEMA=auto`);
    if the backend does not support it, it retries in free mode.

    Args:
        fields: Names of the fields to extract (JSON keys).
        text: Source text (use this or 'path').
        path: Path to a source file (read server-side).
    """
    probe = path and Path(path).is_file()
    probe_len = Path(path).stat().st_size if probe else len(text or "")
    role, model = _role_for_size(probe_len)
    # Entera (B2c): lo que no cabe en una llamada se trocea en vez de truncarse.
    content, _truncated_in, raw_len = _read_input(text, path, _NO_TRUNCATE)
    max_chars = config.max_chars_for_role(role)
    key_list = ", ".join(f'"{f}"' for f in fields)
    system = _guard(f"un objeto JSON válido con exactamente estas claves: {{{key_list}}}")
    use_schema = config.JSON_SCHEMA_MODE != "off"
    response_format = _json_schema_payload(fields) if use_schema else None
    json_schema_fallback = config.JSON_SCHEMA_MODE == "auto"
    fallback_info: dict = {}
    report: dict = {}
    source = "path" if path else "inline"

    def _build(piece: str) -> str:
        return f"Extrae los campos del siguiente contenido:\n\n{piece}"

    if len(content) > max_chars:
        # SIN nada pegado al texto (`report`): esta tool parsea el resultado. El aviso de truncado,
        # el respaldo y el ahorro bajan a `_local_delegate`.
        raw = _chat_map_reduce(
            model,
            system + " Si un campo no aparece en este fragmento, ponlo a null.",
            content,
            _build,
            max_chars=max_chars,
            tool="local_extract",
            role=role,
            source=source,
            max_words=_EXTRACT_WORDS,
            partial_max_words=_EXTRACT_WORDS,
            temperature=0.0,
            reduce_system=system
            + " Combina los objetos parciales: para cada clave, el valor que traigan; si "
            "difieren, el más completo y específico; null si ninguno lo trae.",
            build_reduce=lambda joined: (
                "Estos son objetos JSON parciales y EN ORDEN extraídos de los fragmentos de un "
                f"mismo documento. Devuelve un único objeto con las claves pedidas:\n\n{joined}"
            ),
            reduce_shortcut=_extract_shortcut,
            raw_len=raw_len,
            path=path,
            response_format=response_format,
            json_schema_fallback=json_schema_fallback,
            report=report,
        )
        truncated_calls = report.get("truncated_calls", 0)
        calls = report.get("calls", 0)
        pieces = report.get("pieces", 0)
        if report.get("fallback"):
            fallback_info.update(report["fallback"])
    else:
        raw = _chat(
            model,
            system,
            _build(content),
            max_tokens=512,
            temperature=0.0,
            tool="local_extract",
            role=role,
            fallback=fallback_info,
            chars_in=len(content),
            source=source,
            raw_len=raw_len,
            path=path,
            response_format=response_format,
            json_schema_fallback=json_schema_fallback,
            # SIN la línea de ahorro pegada al texto: esta tool parsea el resultado, y ese sufijo
            # convertía un JSON perfecto en uno imparseable. El dato no se pierde, baja unas
            # líneas más abajo a `_local_delegate`, que es donde va lo que no son datos.
            feedback=False,
            report=report,
        )
        truncated_calls = 1 if report.get("truncated_out") else 0
        calls = 1
        pieces = 1
    result = _strip_fences(raw)

    # `truncated`/`warning` significan desde B2c «salida truncada en un trozo» (REQ-010): la
    # entrada ya no se trunca nunca.
    truncation: dict = {}
    if truncated_calls:
        truncation = {
            "truncated": True,
            "warning": i18n.t(
                "mcp.warning.output_truncated_calls", truncated=truncated_calls, calls=calls
            )
            # #455: which pieces stayed cut, from `report` (the chunked path only).
            + _truncated_pieces_notice(report.get("truncated_pieces") or []),
        }

    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        # El modelo devolvió algo que no es JSON, o el backend falló y `result` trae el aviso de
        # error. Degradar con la carga cruda es mejor que lanzar: quien llama ve qué pasó en vez
        # de recibir una excepción de protocolo.
        error = {"error": i18n.t("mcp.extract.not_json"), "raw": result}
        return {"_local_delegate": {**error, **truncation}}
    if not isinstance(data, dict):
        error = {"error": i18n.t("mcp.extract.not_object"), "raw": result}
        return {"_local_delegate": {**error, **truncation}}

    if pieces > 1:
        _fill_nulls_from_partials(data, fields, report.get("partials") or [])
    meta: dict = dict(truncation)
    # #473: a chunked document where some field stayed null in every chunk. No chunk saw the
    # whole document, so that null may mean "not seen", not "absent": say so, with the count
    # of chunks and the fields, instead of returning it silently.
    null_fields = [f for f in fields if data.get(f) is None] if pieces > 1 else []
    if null_fields:
        notice = i18n.t(
            "mcp.warning.extract_null_in_chunks", pieces=pieces, fields=", ".join(null_fields)
        )
        meta["chunked"] = {"pieces": pieces, "null_fields": null_fields, "notice": notice}
        # A truncation warning keeps its exact text (#455 contract); it already says that
        # material may be missing, and the detail stays in `chunked`.
        meta.setdefault("warning", notice)
    if path and config.FEEDBACK_ENABLED:
        # Tokens de Claude de la fila en curso (REQ-035), no del modelo local.
        event = cost.in_flight_row(tool="local_extract", source="path", path=path)
        meta["read_server_side"] = {
            "chars": len(content),
            "approx_tokens": claude_tokens(len(content), kind="text", event=event),
        }
    if fallback_info:
        # Con el resto de metadatos, nunca dentro de los campos que el agente usa tal cual.
        meta["fallback"] = fallback_info
    if meta:
        data["_local_delegate"] = meta
    return data


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_boilerplate"], writes=True))
def local_boilerplate(spec: str, language: str, target: str, overwrite: bool = False) -> str:
    """Generates boilerplate code from a specification, with a local code model.

    **Writes the code to `target`** and returns only a two-line receipt (path, size). The generated
    code never enters your context: that is where the saving is, and that is why `target` is not
    optional. To see it, open the file; to use it, it is already in place.

    Args:
        spec: Description of what the code must do.
        language: Programming language (e.g. 'python', 'typescript').
        target: ABSOLUTE path of the file to write. Missing directories are created.
        overwrite: Overwrite `target` if it already exists. By default it fails, and it fails
            BEFORE generating anything.
    """
    target_path = _validate_target(target, overwrite)
    system = _guard(f"solo código {language} válido, sin explicaciones ni ```")
    user = f"Genera {language} para: {spec}"
    return _chat(
        config.MODEL_CODE,
        system,
        user,
        max_tokens=1536,
        temperature=0.1,
        tool="local_boilerplate",
        role="code",
        chars_in=len(spec),
        source="inline",
        strip_fences=True,
        write_to=target_path,
    )


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_delegate"]))
def local_delegate(
    task: str,
    input: str,
    output_format: str,
    model: str | None = None,
    chunk: str = "auto",
) -> str:
    """Generic escape tool: delegates a text->text task to a local model.

    Use it when no specific tool fits. Builds the prompt with guardrails and returns text.

    With long inputs it splits the input at natural boundaries (Markdown headers, paragraphs),
    applies the SAME task to each chunk and concatenates the outputs in order. That is right for
    transforming the whole text (translate, rewrite, reformat) but NOT for reduction tasks over the
    whole (counting, picking the maximum, a single global summary): for those pass `chunk='off'` or
    use `local_summarize`.

    Args:
        task: Task instruction (one sentence with an explicit output format).
        input: Content to operate on.
        output_format: Exact expected output format.
        model: Model to use; one of the ids configured in the catalog. Defaults to the mechanical one.
        chunk: 'auto' (splits only if the input is long), 'on' (splits whenever possible),
            'off' (a single call; a long input may come back truncated).
    """
    chosen = model or config.MODEL_MECHANICAL
    # Un modelo pedido por quien llama —o elegido por una persona en la pregunta de abajo— no
    # usa respaldo (REQ-005): lo eligió alguien, y cambiarlo en silencio sería desobedecer.
    explicit = model is not None
    if chosen not in config.ALLOWED_MODELS:
        # La lista de válidos ya iba en el error, así que el servidor siempre supo la respuesta.
        # Se ofrece en vez de solo enunciarla. Ojo con la consecuencia, que es real: con respuesta,
        # una llamada que hoy falla al instante y sin gastar backend pasa a ejecutar inferencia.
        # Sin respuesta —mecanismo apagado, cliente sin soporte, plazo agotado, negativa— se
        # devuelve el error de hoy tal cual y no se toca el backend.
        valid = sorted(config.ALLOWED_MODELS)
        model_answer = questions.ask(
            i18n.t("mcp.question.choose_model.message", model=chosen, valid=", ".join(valid)),
            questions.ChooseModel,
        )
        if model_answer is None or model_answer.model not in config.ALLOWED_MODELS:
            return ERROR_PREFIX + i18n.t("mcp.error.invalid_model", model=chosen, valid=valid)
        chosen = model_answer.model
    if chunk not in {"auto", "on", "off"}:
        return ERROR_PREFIX + i18n.t("mcp.error.invalid_chunk", chunk=chunk)
    if not output_format.strip():
        # El parámetro es obligatorio, así que nunca falta — pero nadie comprobaba que trajera algo,
        # y con la cadena vacía el guardrail se queda sin formato y el modelo improvisa. Si no hay
        # quien responda, se sigue como hasta ahora.
        format_answer = questions.ask(
            i18n.t("mcp.question.choose_format.message"),
            questions.ChooseFormat,
        )
        if format_answer is not None and format_answer.format.strip():
            output_format = format_answer.format.strip()
    system = _guard(output_format)
    if chunk == "on" or (chunk == "auto" and len(input) > config.CHUNK_CHARS):
        return _chat_chunked(
            chosen,
            system,
            input,
            lambda piece: f"{task}\n\nInput:\n{piece}",
            tool="local_delegate",
            role="mechanical",
            explicit=explicit,
            source="inline",
        )
    return _chat(
        chosen,
        system,
        f"{task}\n\nInput:\n{input}",
        max_tokens=config.CHUNK_MAX_TOKENS,
        tool="local_delegate",
        role="mechanical",
        explicit=explicit,
        chars_in=len(input),
        source="inline",
    )


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_lint_summary"]))
def local_lint_summary(
    path: str | None = None,
    text: str | None = None,
    max_words: int = 200,
) -> str:
    """PREFER this tool over reading the file with Read when the file is large
    (>200 lines / >10 KB) and you only need a grouped summary, not the literal content. If you ran
    a command with long output, dump it to a file and pass 'path'.

    Summarizes linter/test/CI output with a local model, without spending Claude's context.

    Meant for long, noisy logs (ESLint, clippy, pytest, tsc, CI). Pass 'path' and the file is read
    server-side, so the full log does NOT enter Claude's context: only a summary grouped by file
    comes back, with the count per error type/rule and the most important first. Alternatively
    pass 'text'. Routes automatically to the mechanical model (short) or the long-context model
    (long).

    Args:
        path: Path to the lint/test output file (read server-side). Use this or 'text'.
        text: Lint/test output as text.
        max_words: Maximum length of the summary in words.
    """
    probe = path and Path(path).is_file()
    probe_len = Path(path).stat().st_size if probe else len(text or "")
    role, model = _role_for_size(probe_len)
    content, truncated_in, raw_len = _read_input(text, path, _NO_TRUNCATE)
    log = content
    # B2d-4: the program, not the model, compacts the lines with the same problem and counts them.
    content, _groups = compact_repeated_lines(content)
    system = _lint_system(max_words)

    if len(content) > config.max_chars_for_role(role):
        # Un log de CI es justo el caso donde truncar duele: los errores interesantes suelen
        # estar al final, y era exactamente lo que se descartaba.
        # B2e: el paso final lleva el formato de la tool (`system`, con la regla de la cantidad y
        # la del idioma) y no el reduce por defecto, que pedía prosa «sin enumerar»; con reduce
        # propio el reagrupado usa también el `system` de lint. Delante de los parciales, el
        # inventario de ficheros y códigos del log entero, por programa y sin recuentos.
        # Wave lint-large-logs: the final step gets an entry only for the most named files, with
        # the counts of the program, and the program adds how many files are left out.
        inventory, left_out = _lint_final_inventory(
            log, int(_map_budget(config.max_chars_for_role(role)) * 0.25)
        )

        def _build_reduce(joined: str) -> str:
            head = f"{inventory}\n\n" if inventory else ""
            return (
                f"{head}Estos son resúmenes parciales y EN ORDEN de un mismo log de linter/tests. "
                "La lista de arriba sale del log entero; los parciales pueden no cubrirla. Un "
                "fichero que aparece en varios parciales va en una sola entrada. Redacta un único "
                f"resumen de todo el log:\n\n{joined}"
            )

        def _add_not_mentioned(answer: str, _truncated: bool) -> str:
            # B2e, respaldo decidido por el usuario el 2026-10-17 (la primera medición no llegó):
            # lo del inventario que el resumen no nombra lo añade el programa, en una línea y sin
            # cifras, para que el lector sepa qué ficheros y reglas del log quedaron fuera.
            return _lint_not_mentioned(_lint_other_files(answer, left_out), log)

        return _chat_map_reduce(
            model,
            system,
            content,
            _lint_map_user,
            max_chars=config.max_chars_for_role(role),
            tool="local_lint_summary",
            role=role,
            source="path" if path else "inline",
            max_words=max_words,
            raw_len=raw_len,
            path=path,
            reduce_system=system,
            build_reduce=_build_reduce,
            max_tokens_for=_lint_map_max_tokens,
            final_max_tokens_for=_lint_final_max_tokens,
            postprocess=_add_not_mentioned,
        )

    # B2f: con el rol largo, el inventario delante del log y la línea «sin mencionar» detrás, como
    # en el troceado; el rol mecánico, como antes.
    user = _lint_single_user(content, log, role)
    result = _chat(
        model,
        system,
        user,
        max_tokens=_lint_single_max_tokens(max_words, role),
        tool="local_lint_summary",
        role=role,
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
        postprocess=(lambda answer, _t: _lint_not_mentioned(answer, log))
        if role == "long"
        else None,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_commit_msg"]))
def local_commit_msg(
    diff: str | None = None,
    path: str | None = None,
    style: str = "conventional",
) -> str:
    """PREFER this tool over reading the file with Read when the file is large
    (>200 lines / >10 KB) and you only need a commit message, not the literal content.

    Drafts a commit message from a diff, with a local code model.

    Pass 'path' to a diff file (e.g. the output of `git diff` dumped to a file) and it is read
    server-side, so the full diff does NOT enter Claude's context. Alternatively pass 'diff' as
    text. ALWAYS review the message before using it.

    Args:
        diff: The diff as text (use this or 'path').
        path: Path to a file with the diff (read server-side).
        style: 'conventional' (Conventional Commits) or 'plain'.
    """
    if style not in {"conventional", "plain"}:
        return ERROR_PREFIX + i18n.t("mcp.error.invalid_style", style=style)
    content, truncated_in, raw_len = _read_input(diff, path, _NO_TRUNCATE)
    if not content.strip():
        return ERROR_PREFIX + i18n.t("mcp.error.empty_diff")
    # El cuerpo es OBLIGATORIO (B2c). Con «cuerpo opcional» y un tope de 256 tokens el modelo
    # paraba solo tras la primera línea: medido el 2026-10-14, `chars_out` 53–66 en 8 de 10 filas,
    # todas con `finish_reason=stop`.
    if style == "conventional":
        fmt = (
            "un mensaje de commit estilo Conventional Commits: primera línea "
            "'tipo(scope): resumen' en imperativo y <=72 caracteres; una línea en blanco y un "
            f"cuerpo OBLIGATORIO de {_COMMIT_BODY_BULLETS} viñetas '- ' que digan qué cambia y "
            "para qué"
        )
    else:
        fmt = (
            "un mensaje de commit: primera línea imperativa <=72 caracteres; una línea en "
            f"blanco y un cuerpo OBLIGATORIO de {_COMMIT_BODY_BULLETS} viñetas '- ' que digan "
            "qué cambia y para qué"
        )
    # El idioma va solo donde se REDACTA el mensaje: este `system` es el de la llamada única y el
    # del reduce del map-reduce (`reduce_system=system`). El map y el reagrupado de partes usan
    # `map_system`, que produce notas intermedias que nadie lee y no lleva la orden.
    system = f"{_guard(fmt)} {_commit_language_instruction(path)}"
    user = f"Escribe el mensaje de commit para este diff:\n\n{content}"

    if len(content) > config.max_chars_for_role("code"):
        # El diff no cabe en una llamada. Antes se truncaba: medido sobre un diff de 164 585
        # chars y 44 archivos, el modelo veía 20 027 chars —7 archivos, todos de `.sdd/`— y
        # devolvía `chore: update GitHub Actions pages artifact version`, o sea el primer
        # archivo por orden alfabético de rutas. Ahora entra entero: parte por archivo, un
        # parte por trozo, y el mensaje se redacta sobre esos partes MÁS el inventario completo.
        # #461: the inventory carries the A/M/D/R status and the top-level names of each file,
        # computed here without a model. With only per-chunk notes, a vague note («date
        # utilities») let the reduce fill in neighbouring concepts («time zones») absent from
        # the diff; these facts are what the reduce is told to stay within.
        facts = _diff_facts(content)
        files = [(f.path, f.added, f.removed) for f in facts]
        budget = max(config.CHUNK_MIN_CHARS, int(config.max_chars_for_role("code") * 0.8))
        inventory = _format_diff_facts(facts, int(budget * 0.25))
        # El formato del map NO se describe con una plantilla del tipo `- ruta: qué cambió`:
        # medido, el modelo la devuelve copiada tal cual —`- ruta: qué cambió y para qué`— y ese
        # trozo se pierde entero. Se ancla con los nombres reales de los archivos, que ya se
        # conocen sin preguntarle a nadie.
        map_system = _guard(
            "una viñeta por archivo, empezando por su ruta literal seguida de dos puntos y de "
            "qué cambia en él y para qué. Sé concreto: nombra las funciones, clases, "
            "componentes o claves que aparecen en el fragmento y no generalices ni menciones "
            "nada que no esté en él. Describe los cambios; no repitas estas instrucciones "
            "ni redactes ningún mensaje de commit todavía"
        )
        # Un archivo más grande que el presupuesto se subdivide, y las piezas 2..N no llevan
        # cabecera `diff --git`: sin decirles a qué archivo pertenecen, el modelo se inventa la
        # ruta (medido: `archivo.py`). Las piezas llegan en orden, así que basta con arrastrar
        # la última vista.
        current_file: dict[str, str | None] = {"file": None}

        def _build_map(piece: str) -> str:
            piece_facts = _diff_facts(piece)
            piece_paths = [fact.path for fact in piece_facts]
            names = _format_diff_symbols(piece_facts, 800)
            names_block = f"\n{names}" if names else ""
            if piece_paths:
                current_file["file"] = piece_paths[-1]
                header = (
                    f"Archivos de este fragmento: {', '.join(piece_paths)}.\n"
                    f"Usa esas rutas literales, una viñeta por archivo."
                )
            elif current_file["file"]:
                header = (
                    f"Este fragmento CONTINÚA el archivo {current_file['file']} y no repite su "
                    f"cabecera. Escribe una sola viñeta, para {current_file['file']}."
                )
            else:
                header = "Escribe una viñeta por archivo, con su ruta literal."
            return f"{header}{names_block}\n\nDi qué cambia en este fragmento de diff:\n\n{piece}"

        def _build_reduce(joined: str) -> str:
            head = f"{inventory}\n\n" if inventory else ""
            return (
                f"{head}Estas son notas EN ORDEN sobre los archivos de un mismo cambio. La "
                "lista de arriba es el inventario COMPLETO del diff; las notas pueden no "
                "cubrirlo entero ni estar todas bien. Menciona SOLO lo que respalden esa lista, "
                "sus definiciones o las notas: no añadas funciones, conceptos ni temas que no "
                "aparezcan ahí; si una nota es general, quédate en lo general y no la completes "
                "con conceptos afines. El resumen describe el comportamiento que "
                "cambia y para qué, no el número de archivos ni los tests que lo acompañan, y "
                "el scope es un ámbito lógico, nunca un nombre de fichero. Escribe el mensaje "
                "de commit del cambio completo, con su primera línea y un cuerpo de "
                f"{_COMMIT_BODY_BULLETS} viñetas:\n\n"
                f"{joined}"
            )

        commit_message = _chat_map_reduce(
            config.MODEL_CODE,
            map_system,
            content,
            _build_map,
            max_chars=config.max_chars_for_role("code"),
            tool="local_commit_msg",
            role="code",
            source="path" if path else "inline",
            max_words=COMMIT_REDUCE_MAX_WORDS,
            # Los partes son material intermedio y hay varios archivos por trozo: con el tope
            # del mensaje final saldrían cortados por `finish_reason=length`.
            partial_max_words=350,
            reduce_system=system,
            build_reduce=_build_reduce,
            raw_len=raw_len,
            path=path,
        )
        if not commit_message.startswith(ERROR_PREFIX):
            commit_message += "\n\n" + i18n.t(
                "mcp.receipt.commit_scope", files=len(files), chars=_machine(len(content))
            )
        return commit_message

    result = _chat(
        config.MODEL_CODE,
        system,
        user,
        max_tokens=COMMIT_MAX_TOKENS,
        temperature=0.2,
        tool="local_commit_msg",
        role="code",
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_translate"]))
def local_translate(
    target_lang: str,
    text: str | None = None,
    path: str | None = None,
) -> str:
    """PREFER this tool over reading the file with Read when the file is large
    (>200 lines / >10 KB) and you only need the translation, not the literal content.

    Translates text or the content of a file with a local model, without spending Claude's context.

    Pass 'path' to read the file server-side (the original does not enter Claude's context) or
    'text'. Keeps the format of the original and returns ONLY the translation. Routes
    automatically to the mechanical model (short) or the long-context model (long).

    Long documents are split at natural boundaries (Markdown headers, paragraphs) and each chunk
    is translated in its own call; the result comes back complete and in order, without the
    truncated-output warning.

    Args:
        target_lang: Target language (e.g. 'Spanish', 'English', 'French').
        text: Text to translate (use this or 'path').
        path: Path to a file whose content is translated (read server-side).
    """
    probe = path and Path(path).is_file()
    probe_len = Path(path).stat().st_size if probe else len(text or "")
    role, model = _role_for_size(probe_len)
    content, truncated_in, raw_len = _read_input(text, path, config.max_chars_for_role(role))
    system = _translate_system(target_lang)
    result = _chat_chunked(
        model,
        system,
        content,
        lambda piece: f"Traduce al {target_lang} el siguiente texto:\n\n{piece}",
        tool="local_translate",
        role=role,
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_explain_code"]))
def local_explain_code(
    code: str | None = None,
    path: str | None = None,
    question: str | None = None,
) -> str:
    """PREFER this tool over reading the file with Read when the file is large
    (>200 lines / >10 KB) and you only need an explanation, not the literal content.

    Explains in prose what a code snippet/file does, with a local code model.

    Pass 'path' to read the file server-side (the full code does NOT enter Claude's context; only
    the explanation comes back) or 'code'. Optionally focus the explanation with 'question'.
    With 'path' the model sees the file's line numbers, so it can answer where something is
    ("name: line") and you can then Read only that range with offset/limit.
    Review the explanation: a local model writes it.

    Args:
        code: Code to explain (use this or 'path').
        path: Path to a code file (read server-side).
        question: Concrete question or focus (optional).
    """
    # Entera (B2c): antes se truncaba al tope del rol y la explicación daba por completo lo leído.
    content, _truncated_in, raw_len = _read_input(code, path, _NO_TRUNCATE)
    max_chars = config.max_chars_for_role("code")
    extra = f" Enfócate en: {question}." if question else ""
    language = _response_language_clause()
    # #460: con `path`, el modelo ve cada línea con su número absoluto del fichero, para que
    # «¿en qué línea está X?» tenga respuesta y el agente lea luego solo ese rango con `Read`.
    # Con `code=` no: quien llama ya tiene el texto delante y no hay fichero al que remitir, así
    # que el texto en línea sigue igual byte a byte y sin el ~10-15 % de chars del prefijo.
    numbered = bool(path)
    lines_clause = _LINE_NUMBERS_CLAUSE if numbered else ""
    model_content = _number_lines(content) if numbered else content
    system = (
        _guard(
            f"una explicación clara en prosa de qué hace el código y cómo.{extra}", max_words=250
        )
        + lines_clause
        + language
    )
    source = "path" if path else "inline"

    # Trocear o no se decide sobre el fichero PELADO, como antes: el prefijo no hace trocear un
    # fichero que cabía (el corpus de calidad `explicar-install-20k` sigue siendo una llamada).
    # La llamada única crece lo que pesa el prefijo (~5-6 chars por línea en un fichero de
    # 20 000, ~15 %), holgado frente al contexto del modelo: el tope del rol es de calidad, no de
    # contexto. En el troceado, en cambio, cada trozo se mide YA numerado contra el presupuesto.
    if len(content) > max_chars:
        # No cabe: notas por definición en cada trozo y la explicación sobre las notas MÁS el
        # inventario de nombres de primer nivel, con la pregunta y la orden de idioma (REQ-028).
        budget = _map_budget(max_chars)
        # B2e: lo registrado va primero dentro del mismo tope; sin registros, el inventario de
        # siempre, byte a byte.
        inventory_cap = int(budget * 0.25)
        registrations = _registered_names(content)
        registered = _format_registered(registrations, inventory_cap)
        names_cap = inventory_cap - len(registered) - 2 if registered else inventory_cap
        # #460: con `path` el inventario lleva la línea de cada definición, calculada por programa:
        # aunque una nota del map la pierda, el reduce la tiene.
        if numbered:
            names = _format_names(_top_level_names_with_lines(content), names_cap, with_lines=True)
        else:
            names = _format_names(_TOP_LEVEL_NAME.findall(content), names_cap)
        if registered:
            names = f"{names}\n{registered}" if names else registered
        if numbered:
            map_format = (
                "una viñeta por cada función, clase o método de este fragmento, empezando por su "
                "nombre literal y el número de línea donde empieza, como «nombre (línea N):», "
                "seguido de qué hace. No expliques todavía el fichero entero"
            )
        else:
            map_format = (
                "una viñeta por cada función o clase de este fragmento, empezando por su nombre "
                "literal seguido de dos puntos y de qué hace. No expliques todavía el fichero "
                "entero"
            )
        map_system = _guard(map_format) + lines_clause + language

        def _build_map(piece: str) -> str:
            return f"Toma notas de este fragmento de código:\n\n{piece}"

        def _build_reduce(joined: str) -> str:
            head = f"{names}\n\n" if names else ""
            also = (
                " y de los nombres que registran sus funciones; nómbralos todos en la explicación"
                if registered
                else ""
            )
            keep_lines = (
                " Las notas y la lista dan números de línea del fichero: consérvalos, y si se "
                "pregunta dónde está algo, responde con «nombre: línea»."
                if numbered
                else ""
            )
            return (
                f"{head}Estas son notas EN ORDEN sobre los fragmentos de un mismo fichero de "
                "código. La lista de arriba es el inventario COMPLETO de sus definiciones de "
                f"primer nivel{also}; las notas pueden no cubrirlo entero.{keep_lines} Explica el "
                f"fichero completo:\n\n{joined}"
            )

        registered_items = [
            item for _o, found, modules in registrations for item in found + modules
        ]

        def _add_not_mentioned(answer: str, _truncated: bool) -> str:
            # B2e, the fallback of decision 3 of 2026-10-17 (the explain round of 2026-10-18 did
            # not reach): what the file registers and the explanation does not name is added by
            # the program, in one line, as in the chunked lint. Without registrations, nothing.
            missing = [n for n in registered_items if not lint_patterns.mentions(n, answer)]
            if not missing:
                return answer
            line = i18n.t("mcp.explain.not_mentioned", items=", ".join(missing))
            return f"{answer.rstrip()}\n\n{line}"

        return _chat_map_reduce(
            config.MODEL_CODE,
            map_system,
            model_content,
            _build_map,
            max_chars=max_chars,
            tool="local_explain_code",
            role="code",
            source=source,
            max_words=250,
            partial_max_words=350,
            reduce_system=system,
            build_reduce=_build_reduce,
            raw_len=raw_len,
            path=path,
            pieces=(
                _numbered_code_pieces(content, budget)
                if numbered
                else _code_pieces(content, budget)
            ),
            tokens_for=_explain_map_max_tokens,
            postprocess=_add_not_mentioned,
        )

    return _chat(
        config.MODEL_CODE,
        system,
        f"Explica el siguiente código:\n\n{model_content}",
        max_tokens=700,
        tool="local_explain_code",
        role="code",
        chars_in=len(model_content),
        source=source,
        raw_len=raw_len,
        path=path,
    )


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_describe_image"]))
def local_describe_image(
    path: str,
    question: str | None = None,
    max_words: int = 200,
) -> str:
    """PREFER this tool over attaching or reading the image yourself when you only need a
    description, the visible text (simple OCR) or a specific answer about an image, not the image
    itself in your context.

    Describes an image (or answers a question about it) with a local vision model. The image is
    read server-side: it NEVER enters Claude's context, only the text answer comes back.

    Scope guardrail: ONLY image->text (describe, read visible text, answer a specific question
    about the image). This tool NEVER generates or edits images.

    Args:
        path: Path to the image (png/jpg/jpeg/webp/gif), read server-side.
        question: Concrete question or focus about the image (optional; by default it describes
            it).
        max_words: Maximum length of the answer in words.
    """
    try:
        mime = _validate_image_path(path)
    except ValueError as e:
        return f"{ERROR_PREFIX}{e}"
    raw_bytes = Path(path).read_bytes()
    raw_len = len(raw_bytes)
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    prompt = question or "Describe esta imagen con detalle."
    system = (
        _guard("una respuesta en prosa clara sobre la imagen", max_words)
        + _response_language_clause()
    )
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]
    return _chat(
        config.MODEL_VISION,
        system,
        content,
        max_tokens=int(max_words * 2) + 64,
        tool="local_describe_image",
        role="vision",
        chars_in=raw_len,
        source="path",
        raw_len=raw_len,
        path=path,
        feedback_label="image_bytes",
        input_unit="bytes",
    )


def _port_listening(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False


def _vram_info() -> str | None:
    """Libre/total de VRAM vía nvidia-smi (best-effort; None si el binario no está)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    line = out.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2:
        return line
    used, total = parts
    try:
        free_mb = float(total.replace("MiB", "").strip()) - float(used.replace("MiB", "").strip())
        warn = i18n.t("mcp.status.low_memory") if free_mb < 2048 else ""
    except ValueError:
        warn = ""
    return i18n.t("mcp.status.vram", used=used, total=total, warning=warn)


def _ram_info() -> str | None:
    """Usado/total de RAM DE SISTEMA (best-effort, F7.9; None si no se pudo leer).

    Portable sin dependencias nuevas: Windows vía ctypes (GlobalMemoryStatusEx, sin lanzar
    procesos), Linux vía /proc/meminfo. macOS no está implementado (devuelve None; nunca
    rompe local_status). Motivo: llama-server mapea el GGUF también en RAM (mmap) aunque el
    cómputo sea 100% GPU, así que un catálogo que cabe en VRAM puede igual agotar la RAM.
    """
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return None
            total_gb = stat.ullTotalPhys / 1024**3
            free_gb = stat.ullAvailPhys / 1024**3
        elif sys.platform.startswith("linux"):
            info: dict[str, str] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    key, _, rest = line.partition(":")
                    info[key] = rest.strip()
            total_gb = float(info["MemTotal"].split()[0]) / 1024**2
            avail_raw = info.get("MemAvailable", info.get("MemFree", "0"))
            free_gb = float(avail_raw.split()[0]) / 1024**2
        else:
            return None
    except Exception:
        return None
    used_gb = total_gb - free_gb
    warn = i18n.t("mcp.status.low_memory") if free_gb < 2 else ""
    return i18n.t(
        "mcp.status.ram", used=_machine(used_gb, 1), total=_machine(total_gb, 1), warning=warn
    )


def _llamaswap_groups() -> str | None:
    """Nombres de los groups activos en LLAMASWAP_CONFIG (best-effort, F7).

    Requiere el extra opcional [llamaswap] (pyyaml) y que LLAMASWAP_CONFIG apunte a un
    config.yaml con 'groups:'. Nunca rompe local_status: cualquier fallo (extra ausente,
    archivo inexistente, YAML inválido) devuelve None y la línea simplemente no aparece.
    """
    cfg_path = config.llamaswap_config_path()
    if not cfg_path:
        return None
    try:
        from . import llamaswap_config as lc

        data = lc.load_config(Path(cfg_path))
    except Exception:
        return None
    groups = data.get("groups")
    if not groups:
        return None
    return ", ".join(sorted(groups))


def _model_status_value(m: dict) -> str | None:
    """Estado de un modelo del campo `status` de /v1/models (#901 de llama-swap).

    llama-swap lo expone como objeto anidado ``{"value": "loaded"|"unloaded"}`` (verificado en
    vivo). Se tolera también un string plano; otros backends (Ollama, llama-swap < v236) no lo
    traen y devuelven None, en cuyo caso simplemente no se muestra el estado.
    """
    st = m.get("status")
    if isinstance(st, dict):
        val = st.get("value")
        return val if isinstance(val, str) else None
    return st if isinstance(st, str) else None


def _probe_timeout() -> httpx2.Timeout:
    """El plazo de TODO sondeo de estado (REQ-013): 3 s para conectar y 2 s para leer.

    Para conectar no vale menos: en Windows un puerto cerrado tarda ~2,1 s en rechazarse, y con 1 s
    llegaba como `ConnectTimeout` y se leía como una VPN (medido en el paso 0 de T3).
    """
    return httpx2.Timeout(config.PROBE_READ_TIMEOUT, connect=config.PROBE_CONNECT_TIMEOUT)


@dataclass(frozen=True)
class BackendState:
    """Lo que dice un sondeo de `/v1/models` (REQ-012).

    `cause` es un valor de `failures.ConnectionCause` como texto, y `detail` su texto; los dos `None`
    cuando el backend está disponible. Con un fallo, `models` es la última lista buena de ESTA
    `BASE_URL` (o vacía), con `status: None` en cada modelo y `models_stale=True`.
    """

    available: bool
    models: list[dict]
    models_stale: bool
    cause: str | None
    detail: str | None
    status_http: int | None


#: La última lista buena de `/v1/models`, por `BASE_URL` (REQ-021). Por URL y no en una sola ranura:
#: si cambia el backend, la lista del anterior no es de este. En memoria: no sobrevive al proceso.
_LAST_GOOD_LISTS: dict[str, list[dict]] = {}


def probe_backend() -> BackendState:
    """Sondea `GET /v1/models` y dice si el backend está disponible y, si no, por qué. Nunca lanza.

    `available` exige un 2xx cuyo cuerpo sea un objeto con una lista `data`; cualquier otra forma
    se trata como `ValueError` y sale `invalid_response` (antes, un 2xx sin `data` daba
    «disponible sin modelos»). Dentro de `data`, la tolerancia de siempre: una entrada que no es un
    objeto se ignora y un `id` ausente se pinta `"?"`.
    """
    url = config.BASE_URL
    endpoint = f"{url}/models"
    # Todo dentro del `try`, también armar la lista: un `id` que no se puede ordenar, o cualquier
    # otra sorpresa del cuerpo, sale como causa y no como excepción hacia el panel o `local_status`.
    try:
        with httpx2.Client(timeout=_probe_timeout()) as c:
            r = c.get(endpoint, headers=config.auth_headers())
        if not r.is_success:
            cause = failures.connection_cause(r.status_code, loopback=_backend_on_loopback())
            return _failed_probe(url, cause, status=r.status_code, status_http=r.status_code)
        body = r.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            # `ValueError` y no `TypeError` a propósito: es la regla 10 del clasificador
            # (`invalid_response`), la misma que un cuerpo que no es JSON (REQ-012).
            raise ValueError(  # noqa: TRY004
                "models_body_without_data_list"
            )
        models = [
            {"id": m.get("id", "?"), "status": _model_status_value(m)}
            for m in data
            if isinstance(m, dict)
        ]
        models.sort(key=lambda x: x["id"])
    except Exception as exc:  # el sondeo nunca lanza: lo que no se espera también tiene causa
        cause = failures.connection_cause(exc, loopback=_backend_on_loopback())
        return _failed_probe(url, cause, endpoint=endpoint, exception=exc)
    _LAST_GOOD_LISTS[url] = models
    # El sondeo barato que cierra el corte (issue #436): `local_status` o el panel ven el backend.
    cooldown.backend_breaker().record_success(cooldown.backend_key())
    return BackendState(True, models, False, None, None, r.status_code)


def _failed_probe(
    url: str,
    cause: failures.ConnectionCause,
    *,
    status: int | None = None,
    status_http: int | None = None,
    endpoint: str | None = None,
    exception: BaseException | None = None,
) -> BackendState:
    saved = [{**m, "status": None} for m in _LAST_GOOD_LISTS.get(url, [])]
    text = failures.detail(
        cause,
        host=config.backend_host(url),
        status=status,
        endpoint=endpoint,
        exception=exception,
    )
    return BackendState(False, saved, True, cause.value, text, status_http)


def _models_with_status() -> tuple[bool, list[dict]]:
    """(backend_up, [{"id","status"}]) desde GET /v1/models; status None si el backend no lo da.

    Envoltorio de :func:`probe_backend` para quien solo necesita esas dos cosas. Con el backend
    caído, la lista es la última buena de esta URL, sin estado (REQ-021).
    """
    state = probe_backend()
    return state.available, state.models


def _llamaswap_running() -> str | None:
    """Modelos montados vía GET {base sin /v1}/running de llama-swap (best-effort)."""
    base = config.BASE_URL.removesuffix("/v1")
    try:
        with httpx2.Client(timeout=_probe_timeout()) as c:
            r = c.get(f"{base}/running", headers=config.auth_headers())
            if not r.is_success:
                return None
            data = r.json()
    except (httpx2.HTTPError, ValueError):
        return None
    entries = data.get("running") if isinstance(data, dict) else None
    if not entries:
        return i18n.t("mcp.status.running_none")
    parts = [
        f"{e.get('model', '?')} ({e.get('state', '?')})" for e in entries if isinstance(e, dict)
    ]
    return ", ".join(parts) if parts else i18n.t("mcp.status.running_none")


def _describe_backend_breaker() -> list[str]:
    """El corte por backend inalcanzable (issue #436): su configuración y, si está abierto, cuánto
    le queda. `local_status` sondea antes, así que con el backend de vuelta ya sale cerrado."""
    if not config.BACKEND_BREAKER:
        return [i18n.t("mcp.status.breaker.off")]
    lines = [
        i18n.t(
            "mcp.status.breaker.on",
            failures=config.BACKEND_BREAKER_FAILURES,
            seconds=_machine(config.BACKEND_BREAKER_S),
            cap=_machine(config.BACKEND_BREAKER_MAX_S),
        )
    ]
    cut = cooldown.backend_breaker().lookup(cooldown.backend_key())
    if cut is not None:
        lines.append(i18n.t("mcp.status.breaker.open", remaining=_machine(cut.remaining_s)))
    return lines


def _describe_cooldown() -> list[str]:
    """REQ-013: los modelos enfriados, lo que les queda y cuántas veces seguidas han entrado."""
    if not config.COOLDOWN:
        return [i18n.t("mcp.status.cooldown.off")]
    lines = [
        i18n.t(
            "mcp.status.cooldown.on",
            failures=config.COOLDOWN_FAILURES,
            seconds=_machine(config.COOLDOWN_S),
            cap=_machine(config.COOLDOWN_MAX_S),
        )
    ]
    active = cooldown.from_config().active()
    if not active:
        lines.append(i18n.t("mcp.status.cooldown.none"))
    for model, cooldown_entry in sorted(active.items()):
        times = (
            i18n.t("mcp.status.cooldown.times_one")
            if cooldown_entry.reentries == 1
            else i18n.t("mcp.status.cooldown.times_many", n=cooldown_entry.reentries)
        )
        lines.append(
            i18n.t(
                "mcp.status.cooldown.model",
                model=model,
                remaining=_machine(cooldown_entry.remaining_s),
                times=times,
            )
        )
    return lines


def _clashes_by_groups(snapshot: topology.Snapshot) -> str:
    """La relación de choques por grupos de la config (REQ-008): cada grupo con sus banderas.

    Con las banderas se lee la regla de REQ-001: dentro de un grupo `swap` chocan entre sí; un grupo
    `exclusivo` choca con los demás que no son `persistente`. Los grupos vacíos no salen.
    """
    parts = []
    for name, group in snapshot.groups.items():
        if not group.members:
            continue
        flags = [
            i18n.t("mcp.status.group.swap" if group.swap else "mcp.status.group.no_swap"),
            i18n.t(
                "mcp.status.group.exclusive"
                if group.exclusive
                else "mcp.status.group.not_exclusive"
            ),
        ]
        if group.persistent:
            flags.append(i18n.t("mcp.status.group.persistent"))
        parts.append(f"{name} [{', '.join(flags)}]: {', '.join(group.members)}")
    return " | ".join(parts) if parts else i18n.t("mcp.status.group.none")


def _describe_turn() -> str:
    """REQ-008 y REQ-002: si hay turno, qué choca, qué está en uso y cuántos esperan; si no, por qué."""
    snapshot = _topology()
    if not isinstance(snapshot, topology.Snapshot):
        return i18n.t("mcp.status.turn.no", reason=topology.reason_text(snapshot.reason))
    state = _turn.snapshot()
    in_use = ", ".join(_turn.in_use()) or i18n.t("mcp.status.turn.nothing")
    return i18n.t(
        "mcp.status.turn.yes",
        clashes=_clashes_by_groups(snapshot),
        in_use=in_use,
        waiting=len(state.queue),
    )


#: Las causas en las que ALGUIEN contesta: no es «caído» (el ámbar del badge, REQ-014/REQ-015).
_CAUSES_WITH_RESPONSE = frozenset(
    {
        failures.ConnectionCause.HTTP_ERROR.value,
        failures.ConnectionCause.INVALID_RESPONSE.value,
        failures.ConnectionCause.NO_RESPONSE.value,
    }
)


def _backend_state_text(state: BackendState) -> str:
    """El estado de la línea `Backend:` de `local_status`, con el criterio del badge (REQ-015)."""
    if state.available:
        return i18n.t("mcp.status.backend.up")
    if state.cause == failures.ConnectionCause.CREDENTIAL.value:
        return i18n.t("mcp.status.backend.no_access", detail=state.detail)
    if state.cause in _CAUSES_WITH_RESPONSE:
        return i18n.t("mcp.status.backend.error", detail=state.detail)
    return i18n.t("mcp.status.backend.down", detail=state.detail)


@mcp.tool(annotations=_annotations(TOOL_TITLES["local_status"]))
def local_status() -> str:
    """Read-only diagnostics of the local backend and the model catalog.

    Use it to find out which local models are available and to check that the backend is alive
    before delegating in bulk, or to diagnose why a local_* tool failed.
    """
    lines: list[str] = [f"local-delegate v{_get_version()}"]
    lines.extend(_describe_language())
    lines.append("")

    state = probe_backend()
    backend_up, models = state.available, state.models
    origin = i18n.t(
        "mcp.status.origin.local"
        if config.backend_origin() == "local"
        else "mcp.status.origin.remote"
    )
    lines.append(
        i18n.t("mcp.status.backend.line", url=config.BASE_URL, state=_backend_state_text(state))
    )
    lines.append(i18n.t("mcp.status.compute", origin=origin, host=config.backend_host()))
    if backend_up:
        if models:
            shown = ", ".join(
                f"{m['id']} ({m['status']})" if m["status"] else m["id"] for m in models
            )
        else:
            shown = i18n.t("mcp.status.models_none")
        lines.append(i18n.t("mcp.status.models", models=shown))

    lines.append("")
    lines.append(i18n.t("mcp.status.roles"))
    for role, model in (
        ("mechanical", config.MODEL_MECHANICAL),
        ("long", config.MODEL_LONG),
        ("code", config.MODEL_CODE),
    ):
        lines.append(f"  {role}: {model} (max_chars={config.max_chars_for_role(role)})")
    lines.append(f"  vision: {config.MODEL_VISION} (max_image_mb={config.MAX_IMAGE_MB})")
    lines.extend(_describe_backend_params())
    lines.extend(chains.describe())
    lines.append(i18n.t("mcp.status.concurrency", n=config.MAX_CONCURRENT_REQUESTS))
    lines.append(_describe_turn())
    lines.extend(_describe_cooldown())
    lines.extend(_describe_backend_breaker())

    current_log = _current_log_path()
    n_events = 0
    n_tests = 0
    backend_calls = 0
    saved_tokens = 0
    net_tokens = 0
    if current_log.is_file():
        records: list[dict] = []
        with current_log.open(encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    records.append(json.loads(raw_line))
                except json.JSONDecodeError:
                    continue
        # Misma fusión y misma contabilidad que el dashboard (coste-api-y-cuota, REQ-006): sin
        # fundir, la fila no trae su densidad y esta tool daría 0 donde el panel da la cifra.
        # Filas viejas y nuevas al mismo formato antes de contar (REQ-006).
        records = [
            legacy_names.normalize("usage", r) if isinstance(r, dict) else r for r in records
        ]
        for rec in cost.merge(records, log_dir=config.LOG_DIR):
            # Las pruebas no cuentan, con la misma regla que el panel (test-windows-out-of-metrics,
            # REQ-018): cliente `mcp`, banco o ventana de prueba.
            if attribution.test_reason(rec):
                n_tests += 1
                continue
            n_events += 1
            acc = _accounting(rec)
            backend_calls += acc["backend_calls"]
            saved_tokens += acc["saved"]
            net_tokens += acc["net"]
    lines.append("")
    lines.append(i18n.t("mcp.status.log.path", path=current_log))
    lines.append(
        # REQ-005: el neto (lo leído server-side menos lo devuelto al contexto), como el KPI del
        # panel, y el bruto entre paréntesis. Los fallos no suman a ninguno de los dos.
        i18n.t(
            "mcp.status.log.events",
            events=n_events,
            calls=backend_calls,
            net=net_tokens,
            gross=saved_tokens,
        )
        + (i18n.t("mcp.status.log.tests_out", n=n_tests) if n_tests else "")
    )
    for window in test_windows.load(config.LOG_DIR).open_windows():
        lines.append(
            i18n.t(
                "mcp.status.test_window",
                id=window.id,
                start=test_windows.format_instant(window.start),
            )
        )
    # REQ-027: la velocidad normal de cada modelo. Observar no rompe la tool (REQ-028): si no se
    # puede describir, el informe sale sin esa línea.
    with suppress(Exception):
        lines.append(f"  {_describe_pace()}")

    lines.append("")
    if config.WEB_ENABLED:
        web_up = _port_listening(config.WEB_HOST, config.WEB_PORT)
        lines.append(
            i18n.t(
                "mcp.status.web.line",
                state=i18n.t("mcp.status.web.active" if web_up else "mcp.status.web.inactive"),
                host=config.WEB_HOST,
                port=config.WEB_PORT,
            )
        )
    else:
        lines.append(i18n.t("mcp.status.web.disabled"))

    vram = _vram_info()
    if vram:
        lines.append("")
        lines.append(i18n.t("mcp.status.vram_line", info=vram))

    ram = _ram_info()
    if ram:
        lines.append(i18n.t("mcp.status.ram_line", info=ram))

    # REQ-013: `/running` solo si `/models` respondió. Con el backend inalcanzable, un plazo de
    # conexión y no dos.
    running = _llamaswap_running() if backend_up else None
    if running:
        lines.append(i18n.t("mcp.status.running", running=running))

    groups = _llamaswap_groups()
    if groups:
        lines.append(i18n.t("mcp.status.groups", groups=groups))

    lines.extend(_describe_deprecated_names())
    return "\n".join(lines)


def _describe_language() -> list[str]:
    """REQ-019: el idioma de ESTE proceso servidor (el daemon corre sin la shell del usuario), su
    origen y el `language.json`, con sus avisos. Los mismos datos que la cabecera de `doctor`."""
    report = i18n.language_report()
    lines = [
        i18n.t("mcp.status.language.line", lang=report.lang, source=report.source, path=report.path)
    ]
    lines.extend(i18n.t("mcp.status.language.warning", detail=d) for d in report.warnings)
    if report.follow_system:
        lines.append(i18n.t("mcp.status.language.follow_system", path=report.path))
    # REQ-028 (issue #260): el idioma en que las tools de texto libre piden responder al modelo.
    value, source, warning = i18n.response_language_lines()
    lines.append(i18n.t("mcp.status.output_language.line", value=value, source=source))
    if warning:
        lines.append(i18n.t("mcp.status.language.warning", detail=warning))
    return lines


def _describe_backend_params() -> list[str]:
    """REQ-016/023 (SDD backend-extra-params, T14): the per-role parameters of THIS process.

    The daemon's file and its own `LOCAL_DELEGATE_BACKEND_PARAMS` (which may differ from the
    user's shell, the blind spot of `doctor`): one line per role with keys, values and source,
    and the warnings of `backend_params.report()`, context ones included. Only accepted values;
    a dropped entry shows its role, key and code, never its value (REQ-006). Without parameters
    or warnings, no line at all, so the report stays the one of before.
    """
    rows = [row for row in backend_params.report() if row.values or row.warnings]
    if not rows:
        return []
    lines = [i18n.t("mcp.status.backend_params.line", path=backend_params.path())]
    origin = {
        backend_params.SOURCE_ENV: i18n.t("mcp.status.backend_params.from_env"),
        backend_params.SOURCE_FILE: i18n.t("mcp.status.backend_params.from_file"),
    }
    for row in rows:
        if row.values:
            params = ", ".join(
                f"{key}={backend_params.format_param_value(value)} "
                + origin[row.source.get(key, backend_params.SOURCE_FILE)]
                for key, value in row.values.items()
            )
            lines.append(i18n.t("mcp.status.backend_params.role", role=row.role, params=params))
        lines.extend(
            i18n.t("mcp.status.backend_params.warning", detail=backend_params.warning_text(w))
            for w in row.warnings
        )
    return lines


def _describe_deprecated_names() -> list[str]:
    """Old variable names with a successor that are set in THIS process's environment.

    `doctor` looks at the shell it runs in and at the `env` of `settings.json`, but not at the
    daemon's environment nor the stdio server's: only the process itself knows, through
    `config.DEPRECATED_ENV_VALUES` (read only to warn; the old names have no effect). The value is
    never printed.
    """
    from . import deprecation_notices, deprecations

    entries = [
        entry
        for name, value in sorted(config.DEPRECATED_ENV_VALUES.items())
        if value is not None
        and (entry := deprecations.find(name)) is not None
        and entry.new is not None
    ]
    if not entries:
        return []
    return ["", i18n.t("mcp.status.deprecated")] + [
        f"  {deprecation_notices.warning_text(e)}" for e in entries
    ]


def prepare_ctrl_break() -> None:
    """Hace que Ctrl+Break se pare como Ctrl+C. Solo hace algo en Windows.

    Windows tiene **dos** eventos de consola y Python solo convierte uno en `KeyboardInterrupt`:
    `CTRL_C_EVENT` sí, `CTRL_BREAK_EVENT` (o sea `SIGBREAK`) no. Con el handler por defecto la CRT
    mata el proceso, y eso se midió en los dos caminos del paquete: `serve` salía con **3** y el
    MCP stdio con **0xC000013A** (`STATUS_CONTROL_C_EXIT`), este último sin llegar a imprimir nada.

    En `serve` el 3 no venía de nuestro código, y esa parte importa para entender por qué el arreglo
    es este y no un `except` más. uvicorn captura `SIGINT`, `SIGTERM` y `SIGBREAK`; al terminar
    **restaura el handler original y vuelve a lanzar la señal** (`Server.capture_signals`). Para
    `SIGINT` el original es `default_int_handler`, así que la re-emisión produce el
    `KeyboardInterrupt` que `serve` ya cazaba —de ahí su comentario— y para `SIGBREAK` el original
    era `SIG_DFL` y la re-emisión mataba el proceso a mitad del apagado: se midió que `serve()`
    nunca retornaba y que `atexit` nunca corría, con el gestor de sesiones del SDK ya cerrado.

    Por eso el arreglo no es capturar más excepciones sino **cambiar cuál es el handler original**:
    puesto `default_int_handler` en `SIGBREAK`, Ctrl+Break desemboca en el mismo camino que Ctrl+C,
    que ya está probado.

    Dos cuidados deliberados:

    - Solo se pisa `SIG_DFL`. Si alguien ya instaló un handler propio, el suyo manda.
    - `signal.signal` solo vale en el hilo principal; fuera de él lanza `ValueError` y aquí eso
      significa «no toca hacer nada», no un fallo.
    """
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is None:  # POSIX: Ctrl+C ya es SIGINT y no hay nada que igualar
        return
    try:
        if signal.getsignal(sigbreak) is signal.SIG_DFL:
            signal.signal(sigbreak, signal.default_int_handler)
    except (ValueError, OSError):
        # `signal.signal` solo vale en el hilo principal, y fuera de él lanza `ValueError`. Eso
        # aquí no es un fallo: significa que no toca hacer nada. Igualar Ctrl+Break a Ctrl+C es
        # una mejora del cierre, no un requisito para servir, así que no poder hacerlo jamás debe
        # impedir que el servidor arranque.
        pass
