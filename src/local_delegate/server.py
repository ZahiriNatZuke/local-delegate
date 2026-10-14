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

import base64
import json
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
from mcp.types import ToolAnnotations

from . import (
    attribution,
    autostart,
    chains,
    clients,
    config,
    cooldown,
    cost,
    failures,
    json_state,
    legacy_names,
    llamaswap_api,
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


# `version=` declara la versión **del paquete**. Sin ella el SDK reporta la suya propia en el
# handshake `initialize`, de modo que un cliente no tenía forma de saber qué local-delegate corre.
mcp = MCPServer(
    "local-delegate",
    title="Local Delegate",
    description=(
        "Delega tareas mecánicas de texto e imagen a un modelo local por un endpoint "
        "compatible con OpenAI, para conservar cuota de la suscripción."
    ),
    website_url="https://github.com/ZahiriNatZuke/local-delegate",
    version=_get_version(),
    # El SDK los aplica outermost-first, y el orden es deliberado: «observar primero, habilitar
    # después». Hoy son independientes —el observador solo lee, el otro solo deja el contexto al
    # alcance de las capas de abajo—, pero se fija para que nadie lo cambie creyendo que da igual.
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


def _get_client() -> httpx2.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                # REQ-019: solo el plazo de CONEXIÓN baja a 10 s (o al total, si es menor). La
                # espera de carga de un modelo es de lectura y sigue en HTTP_TIMEOUT. Sin esto el
                # kernel decidía: ~21 s en Windows y ~75 s en macOS por cada fallo de la VPN.
                _client = httpx2.Client(
                    timeout=httpx2.Timeout(
                        config.HTTP_TIMEOUT,
                        connect=min(config.DELEGATION_CONNECT_TIMEOUT, config.HTTP_TIMEOUT),
                    )
                )
    return _client


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

    def _add(data: dict) -> None:
        data[key] = entry

    _inflight_mutate(_add)
    return entry_id


def _inflight_progress(entry_id: int, chunk: int) -> None:
    """Marca en qué trozo va una delegación por chunks (visible en el panel 'En curso')."""
    key = f"{os.getpid()}:{entry_id}"

    def _update(data: dict) -> None:
        entry = data.get(key)
        if isinstance(entry, dict):
            entry["chunk"] = int(chunk)

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
            # REQ-022: la espera DENTRO de local-delegate, solo cuando la hay. Sin copiarla aquí
            # el panel no la vería nunca, aunque esté escrita en el fichero.
            if v.get("local_wait"):
                entry["local_wait"] = v.get("local_wait")
            # REQ-008: con qué modelos y en qué puesto espera turno. Datos aparte, solo cuando están.
            if "turn_in_use" in v:
                entry["turn_in_use"] = v.get("turn_in_use")
            if "turn_position" in v:
                entry["turn_position"] = v.get("turn_position")
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
        raise ValueError(f"Ruta fuera de las raíces permitidas ({roots}): {path}")


def _validate_target(target: str, overwrite: bool) -> Path:
    """Valida la ruta de salida ANTES de gastar backend. Devuelve el Path ya resuelto.

    El orden importa: si el destino es inválido se falla sin llamar al modelo. Al revés se
    pagaría la inferencia para tirar el resultado, que es el peor de los dos errores posibles.

    Exige ruta **absoluta** porque el servidor corre con su propio directorio de trabajo —el del
    daemon, no el de quien llama—, así que una ruta relativa aterrizaría en un sitio que nadie
    eligió. Y se niega a pisar lo que ya está salvo permiso explícito.
    """
    if not target or not target.strip():
        raise ValueError("'target' es obligatorio: la ruta absoluta del archivo a escribir.")
    p = Path(target)
    if not p.is_absolute():
        raise ValueError(
            "'target' debe ser una ruta absoluta: el servidor no comparte tu directorio de "
            f"trabajo. Recibido: {target}"
        )
    _check_allowed_dir(target)
    if p.is_dir():
        raise ValueError(f"'target' es un directorio, no un archivo: {target}")
    if p.exists() and not overwrite:
        raise ValueError(
            f"Ya existe un archivo ahí; pasa overwrite=True si quieres pisarlo: {target}"
        )
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
    receipt = f"[escrito] {p}\n{content.count(chr(10)):,} líneas, {len(content):,} chars"
    if config.FEEDBACK_ENABLED:
        tokens = claude_tokens(len(content), kind="output", event=event)
        receipt += f" (≈{tokens:,} tokens de Claude que no entraron a tu contexto)"
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
            raise ValueError(f"No existe el archivo: {path}")
        content = p.read_text(encoding="utf-8", errors="replace")
    elif text is not None:
        content = text
    else:
        raise ValueError("Debes proporcionar 'text' o 'path'.")
    raw_len = len(content)
    truncated = raw_len > max_chars
    if truncated:
        content = content[:max_chars] + "\n[...contenido truncado...]"
    return content, truncated, raw_len


def _truncation_prefix(content: str, truncated: bool, raw_len: int) -> str:
    """Aviso visible cuando _read_input truncó la entrada (antes era un truncado silencioso)."""
    if not truncated:
        return ""
    return f"[local-delegate: entrada truncada — procesados {len(content)} de {raw_len} chars]\n"


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
        return "Ritmo de referencia: sin muestras todavía"
    parts = []
    for row in rows:
        median = row["median"]
        speed = (
            f"{median:.1f}".replace(".", ",") + " tok/s" if median is not None else "sin referencia"
        )
        parts.append(f"{row['model']} {speed} ({row['samples']} muestras)")
    return "Ritmo de referencia: " + "; ".join(parts)


def _log_event(
    *,
    tool: str,
    model: str,
    source: str,
    chars_in: int,
    chars_out: int,
    latency_ms: int,
    ok: bool,
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
) -> None:
    """Escribe una línea JSONL en el log activo (rotado por mes o fijo). Nunca rompe una tool.

    Los campos del respaldo (F3, REQ-013) son aditivos: `model` sigue siendo el modelo que
    RESPONDIÓ, así que un evento sin salto se escribe igual que antes y el histórico se lee igual.

    `attempts` son las llamadas reales de la operación: de sus `timings` salen la espera, la
    inferencia y el ritmo (REQ-024 a REQ-026).
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
        raise ValueError(
            f"tipo de conversión desconocido: {kind!r} (válidos: {_CLAUDE_TOKEN_KINDS})"
        )
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
    backend_calls = int(row.get("chunks") or 1)

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


#: Las clases que permiten saltar (tabla de F3). Capacidad solo al residente (REQ-018).
_HOPPABLE_CLASSES = frozenset({failures.FailureClass.MODEL, failures.FailureClass.CAPACITY})


def _cooldown_error(model: str, cooling: cooldown.ActiveCooldown) -> ChatResult:
    """REQ-009: el modelo está enfriándose y no queda candidato. Falla al momento, sin timeout."""
    until = datetime.fromtimestamp(cooling.until, UTC).strftime("%H:%M:%S UTC")
    return ChatResult(
        text=(
            f"[local-delegate error] {model} está en enfriamiento hasta las {until} (quedan "
            f"{cooling.remaining_s:.0f} s) tras fallar varias veces seguidas, y no hay respaldo "
            "disponible."
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
        reason, error_class = "en enfriamiento", "cooldown"
    return {
        "respondio": attempts[-1].model,
        "en_lugar_de": model,
        "motivo": reason,
        "clase": error_class,
    }


def _class_value(error_class: str | None) -> str | None:
    """La clase como texto plano para el log (`model`, `configuration`…), o None."""
    return failures.FailureClass(error_class).value if error_class else None


def _fallback_notice(info: dict, origin: str | None = None) -> str:
    """La línea de aviso, siempre DETRÁS del contenido y separada de él."""
    extra = f", {origin}" if origin else ""
    return (
        f"\n\n[local-delegate aviso: respondió {info['respondio']} en lugar de "
        f"{info['en_lugar_de']} ({info['motivo']}){extra}]"
    )


def _body_failure(
    model: str, error_class: failures.FailureClass, timings: dict | None = None
) -> ChatResult:
    """El error legible de una respuesta que llegó con 200 y aun así no sirve.

    Antes de esto, un `content` nulo reventaba con `AttributeError` a medio `_post_chat` —el tipo
    no estaba en el `except` de abajo— y se llevaba la tool por delante.
    """
    if error_class is failures.FailureClass.CONFIGURATION:
        return ChatResult(
            text=(
                f"[local-delegate error] {model} agotó `max_tokens` razonando y no llegó a "
                "responder. Súbelo, o desactiva el razonamiento de ese modelo."
            ),
            ok=False,
            error="config_max_tokens",
            error_class=error_class,
            timings=timings,
        )
    return ChatResult(
        text=f"[local-delegate error] respuesta sin contenido utilizable de {model}.",
        ok=False,
        error="bad_response",
        error_class=error_class,
        timings=timings,
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


def _post_chat(model: str, payload: dict) -> ChatResult:
    """POST al endpoint /chat/completions con reintento opcional si el backend está caído."""
    headers = config.auth_headers()
    client = _get_client()
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
            if error_class is not None:
                # Un 200 inservible también ocupó la GPU: su inferencia cuenta en el evento.
                return _body_failure(model, error_class, _timings_of(data))
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            return ChatResult(
                text=choice["message"]["content"].strip(),
                ok=True,
                finish_reason=choice.get("finish_reason"),
                tokens_in=usage.get("prompt_tokens"),
                tokens_out=usage.get("completion_tokens"),
                timings=_timings_of(data),
            )
        except httpx2.HTTPError as e:
            # Un solo `except` para toda la familia, y la diferencia la marca el clasificador.
            # Antes había tres, y `ConnectTimeout` se colaba por el genérico: no es subclase de
            # `ConnectError` —son ramas hermanas—, así que un plazo de conexión agotado se
            # clasificaba como `http_error` y nadie ofrecía arrancar el backend.
            if isinstance(e, httpx2.ReadTimeout):
                # La señal de REQ-018 es la muestra tomada al vencer, no una consulta ahora.
                error_class = failures.classify(e, model_loaded=probe.model_loaded())
            else:
                error_class = failures.classify(e)
            if failures.is_backend_missing(e):
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
                        f"El backend local no responde en {config.backend_host()}. ¿Lo arranco?",
                        questions.StartBackend,
                    )
                    if answer is not None and answer.start and autostart.ensure_backend(wait=30):
                        continue
                # REQ-017: la causa, con el texto único de `failures`, en vez de suponer que el
                # backend no está corriendo (con una VPN caída, lo está).
                cause = failures.connection_cause(e, loopback=_backend_on_loopback())
                return ChatResult(
                    text=(
                        "[local-delegate error] no se pudo conectar con el backend: "
                        + failures.detail(cause, host=config.backend_host(), exception=e)
                    ),
                    ok=False,
                    error="connect_error",
                    error_class=error_class,
                    connection_failure=cause.value,
                )
            if isinstance(e, httpx2.HTTPStatusError):
                return ChatResult(
                    text=(
                        f"[local-delegate error] {model} respondió {e.response.status_code}: "
                        f"{e.response.text[:300]}"
                    ),
                    ok=False,
                    error=f"http_{e.response.status_code}",
                    error_class=error_class,
                )
            if isinstance(e, httpx2.ReadTimeout):
                # El backend SÍ aceptó la conexión: lo más probable es que llama-swap esté
                # montando el modelo. Arrancar otro backend no arregla nada aquí.
                return ChatResult(
                    text=(
                        f"[local-delegate error] {model} no respondió en "
                        f"{config.HTTP_TIMEOUT:.0f} s. Puede que el backend aún lo esté cargando."
                    ),
                    ok=False,
                    error="read_timeout",
                    error_class=error_class,
                )
            return ChatResult(
                text=f"[local-delegate error] fallo de conexión al endpoint ({config.BASE_URL}): {e}",
                ok=False,
                error="http_error",
                error_class=error_class,
            )
        except (KeyError, IndexError, ValueError) as e:
            return ChatResult(
                text=f"[local-delegate error] respuesta inesperada de {model}: {e}",
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
    raise AssertionError("_post_chat: los dos intentos terminan siempre en un return")


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


# --- Turno por conjunto de modelos compatibles (daemon-reparte-el-backend, REQ-002 a REQ-009) ---
# Una operación (una llamada a una tool, con todos sus trozos y saltos) pide turno ANTES que la
# plaza y lo conserva de principio a fin; las que usan modelos que chocan en llama-swap esperan a
# que les toque en vez de quitarse el modelo una a otra. El núcleo vive en `turn.py` y la
# relación de choques en `topology.py`; aquí solo se conectan.

#: Motivo de REQ-002 cuando el backend no es de loopback (la Mac contra la PC): sin turno.
NO_TURN_REMOTE_BACKEND = "backend remoto"


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
    found: list[str] = []
    for cell in matrix.CELLS:
        if cell.tool != tool or cell.alternative in found or cell.compared_role != role_model:
            continue
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

    def _waiting_for(self, wait: Callable[[turn.OnWait], turn.Grant]) -> turn.Grant:
        """Una espera de turno con su contabilidad: `turn_wait_ms` y las claves del panel."""
        on_wait, waiting = self._on_wait_factory()
        t0 = time.monotonic()
        try:
            grant = wait(on_wait)
        finally:
            if waiting[0]:
                # Al conceder (o al salir por error), las tres claves fuera (REQ-008).
                self.wait_ms += int((time.monotonic() - t0) * 1000)
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
        grant = self._waiting_for(lambda on_wait: turn_state.request(request, on_wait))
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
        self._waiting_for(lambda on_wait: turn_state.wait_for_grant(self.op_id, on_wait))

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
    slots = _chat_slots
    if not slots.acquire(blocking=False):
        if entry_id is not None:
            _inflight_local_wait(entry_id, "slot")
        slots.acquire()
        if entry_id is not None:
            _inflight_local_wait(entry_id, None)
    try:
        with turn.slot_taken():
            yield
    finally:
        slots.release()


def _call_model(
    model: str, payload: dict, json_schema_fallback: bool
) -> tuple[ChatResult, str | None, int]:
    """Una llamada a UN modelo, con el reintento sin schema de siempre si el backend dio 400.

    Cada envío va dentro de `in_flight()`, también sin turno: el reloj de la red de seguridad no
    corre mientras el daemon tiene alguna llamada al backend en vuelo (REQ-007).
    """
    t0 = time.monotonic()
    request_body = {"model": model, **payload}
    with _turn.in_flight(), _own_call(model):
        result = _post_chat(model, request_body)
    json_schema_status = "used" if "response_format" in request_body else None
    if json_schema_status and not result.ok and result.error == "http_400":
        if json_schema_fallback:
            # El backend no soporta response_format con schema: reintenta en modo libre.
            request_body.pop("response_format", None)
            with _turn.in_flight(), _own_call(model):
                result = _post_chat(model, request_body)
            json_schema_status = "fallback"
        else:
            json_schema_status = "error"
    return result, json_schema_status, int((time.monotonic() - t0) * 1000)


def _attempt(
    model: str,
    payload: dict,
    json_schema_fallback: bool,
    state: cooldown.CooldownState,
    attempts: list[Attempt],
) -> tuple[ChatResult, str | None]:
    """UNA llamada y su reintento sin schema, DENTRO de la plaza; anota el intento y el estado."""
    result, schema, ms = _call_model(model, payload, json_schema_fallback)
    attempts.append(Attempt(model, result.ok, result.error, result.error_class, ms, result.timings))
    if result.ok:
        state.record_success(model)
    elif result.error_class is not None:
        state.record_failure(model, result.error_class)
    return result, schema


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
            text="[local-delegate error] la operación se quedó sin modelo al elegir.",
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
                        target, payload, json_schema_fallback, state, attempts
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
            text=f"{base.text}\n[local-delegate respaldo: también fallaron {tried_list}]",
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
    )
    return result, int((time.monotonic() - t0) * 1000), json_schema_status, attempts


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
    ) -> None:
        #: La entrada en vuelo de la operación, para publicar su espera local (REQ-022).
        self.entry_id = entry_id
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

    def call(
        self, system: str, user: str, max_tokens: int, temperature: float, *, size: int
    ) -> tuple[ChatResult, int, list[Attempt]]:
        result, ms, _schema, attempts = _run_chat(
            self.model,
            system,
            user,
            max_tokens,
            temperature,
            role=self.role,
            explicit=self.explicit,
            size=size,
            entry_id=self.entry_id,
            op=self.op,
        )
        info = _fallback_info(self.model, result, attempts, self.affinity_tried)
        if info is not None:
            if self.hop is None:
                self.hop = {**info, "en_lugar_de": self.requested, "chunk": self.chunk}
            self.model = info["respondio"]
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
            fields["fallback_reason"] = self.hop["motivo"]
            fields["fallback_class"] = self.hop["clase"]
        elif self.affinity is not None:
            fields["model_requested"] = self.requested
        if self.op is not None:
            fields.update(self.op.log_fields())
        return fields

    def notice(self, multiple: bool) -> str:
        if self.hop is None:
            return ""
        origin = None
        if multiple:
            chunk = self.hop["chunk"]
            origin = f"desde el trozo {chunk}" if chunk is not None else "en la reducción"
        return _fallback_notice(self.hop, origin)


def _savings_feedback(chars_in: int, label: str, *, event: dict) -> str:
    """Línea de ahorro que se anexa al resultado cuando la entrada se leyó server-side.

    `event` es la fila en curso ya fundida (`cost.in_flight_row`): los tokens son de **Claude**
    (`claude_tokens`, REQ-035), nunca el `tokens_in` del modelo local. Una imagen dice solo los
    bytes: sin dimensiones no hay forma de saber sus tokens de Claude (REQ-038).
    """
    if cost.is_image(event):
        return f"\n\n(leído server-side: {chars_in:,} {label} que no entraron a tu contexto)"
    tokens = claude_tokens(chars_in, kind="text", event=event)
    return (
        f"\n\n(leído server-side: {chars_in:,} {label} ≈ {tokens:,} tokens de Claude "
        "que no entraron a tu contexto)"
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
) -> str:
    """POST al endpoint. Devuelve solo texto y registra la llamada en USAGE_LOG.

    `role` habilita el respaldo de ese rol; `explicit` lo apaga para un modelo elegido por quien
    llama (REQ-005). Con `fallback`, el aviso de que respondió otro modelo se deja en ese dict en
    vez de pegarlo al texto: lo usa quien parsea el resultado (REQ-007).

    `user` acepta un `str` (texto->texto) o una lista de bloques de contenido
    OpenAI-compatible (p. ej. `[{"type":"text",...},{"type":"image_url",...}]` para
    local_describe_image).
    """
    entry_id = _inflight_start(tool=tool, model=model, source=source, chars_in=chars_in)
    # Turno por operación (REQ-003): una llamada simple (también la de imagen) es una operación.
    op = _OperationTurn(entry_id, model, tool, role_name=role, explicit=explicit)
    try:
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
        )
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
    truncation_notice = "\n\n[local-delegate aviso: salida truncada por max_tokens]"
    # Con `write_to` el aviso viaja en el RECIBO, no dentro del archivo: lo que se escribe es lo
    # que generó el modelo y nada más.
    if truncated_out and write_to is None:
        text += truncation_notice
    fallback_info = _fallback_info(model, result, attempts, op.affinity_tried)
    # La afinidad (T15) no es un respaldo ni lleva aviso: queda en el log (REQ-016).
    served = fallback_info["respondio"] if fallback_info else (op.affinity or model)
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
        fallback_reason=fallback_info["motivo"] if fallback_info else None,
        fallback_class=fallback_info["clase"] if fallback_info else None,
        error_class=None if result.ok else _class_value(result.error_class),
        num_sections=num_sections,
        focus=focus,
        connection_failure=None if result.ok else result.connection_failure,
        attempts=attempts,
        **op.log_fields(),
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
def _diff_inventory(diff: str) -> list[tuple[str, int, int]]:
    """Devuelve `(ruta, líneas añadidas, líneas quitadas)` por archivo del diff.

    El conteo distingue las cabeceras `--- `/`+++ ` de las líneas de contenido por su posición
    —solo son cabecera antes del primer `@@` del archivo— y no por su texto. Mirando el texto,
    borrar una línea que empiece por `--` se registraría como cabecera y no se contaría.
    """
    files: list[tuple[str, int, int]] = []
    path: str | None = None
    added = removed = 0
    in_hunk = False

    def _close() -> None:
        if path is not None:
            files.append((path, added, removed))

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            _close()
            rest = line[len("diff --git ") :]
            pair = re.match(r"a/(.+) b/\1$", rest)
            path = pair.group(1) if pair else rest.split(" b/", 1)[-1].lstrip("b/")
            added = removed = 0
            in_hunk = False
        elif path is None:
            continue
        elif line.startswith("@@"):
            in_hunk = True
        elif not in_hunk:
            # Zona de cabecera: `+++ b/x` manda sobre el nombre adivinado de `diff --git`, salvo
            # en un borrado (`+++ /dev/null`), donde el nombre bueno es el de `--- a/x`.
            if line.startswith("+++ ") and line[4:] != "/dev/null":
                path = line[4:].removeprefix("b/")
            elif line.startswith("--- ") and line[4:] != "/dev/null":
                path = line[4:].removeprefix("a/")
            elif line.startswith("rename to "):
                path = line[len("rename to ") :]
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    _close()
    return files


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
    current = _CurrentModel(model, role, explicit, entry_id, op)

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
            text += "\n\n[local-delegate aviso: salida truncada por max_tokens]"
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
        attempts=all_attempts,
        **current.log_fields(failed),
    )
    if source == "path" and ok and config.FEEDBACK_ENABLED:
        event = cost.in_flight_row(tool=tool, source=source, path=path)
        text += _savings_feedback(len(content), "chars", event=event)
    if ok and calls > 1 and config.FEEDBACK_ENABLED:
        text += f"\n\n(procesado en {calls} trozos por local-delegate)"
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
    """
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
    current = _CurrentModel(model, role, explicit, entry_id, op)

    def _one(sys_prompt: str, user: str, max_tokens: int) -> str | None:
        nonlocal calls, latency_ms, tokens_in, tokens_out, failed, truncated_calls
        result, ms, attempts = current.call(
            sys_prompt, user, max_tokens, temperature, size=len(user)
        )
        all_attempts.extend(attempts)
        calls += len(attempts)
        latency_ms += ms
        if result.tokens_in is not None:
            tokens_in = (tokens_in or 0) + result.tokens_in
        if result.tokens_out is not None:
            tokens_out = (tokens_out or 0) + result.tokens_out
        if not result.ok:
            failed = result
            return None
        if result.finish_reason == "length":
            truncated_calls += 1
        return _strip_think(result.text)

    def _tokens(words: int) -> int:
        return int(words * 2) + 64

    # Cada parcial se deja algo más largo que el resumen final: el reduce necesita material
    # con el que trabajar, y un parcial demasiado corto ya habría perdido lo que importa.
    #
    # `partial_max_words` existe porque hay reduces cuyo resultado es MUCHO más corto que su
    # material: un mensaje de commit son ~90 palabras, pero el parte de los cinco archivos de un
    # trozo no cabe en 90 y saldría cortado por `finish_reason=length`. Perder material en el map
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
            return [out]
        if depth >= 2 or not _is_context_overflow(failed):
            return None
        parts = _split(piece)
        if len(parts) < 2:
            return None  # indivisible: el error se queda como está
        failed = None  # el desborde deja de ser terminal en cuanto hay con qué reintentar
        outputs: list[str] = []
        for part in parts:
            sub = _map_piece(part, depth + 1)
            if sub is None:
                return None
            outputs.extend(sub)
        return outputs

    try:
        summaries: list[str] = []
        for index, piece in enumerate(pieces, start=1):
            _inflight_progress(entry_id, index)
            current.chunk = index
            outs = _map_piece(piece)
            if outs is None:
                break
            summaries.extend(outs)

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
            else:
                for _level in range(3):
                    joined = "\n\n".join(summaries)
                    prompt = build_reduce(joined)
                    # Se mide el prompt ARMADO, no los parciales pelados: lo que se envía puede
                    # llevar delante material fijo (el inventario del diff, p. ej.), y medir sin
                    # él desbordaría el contexto justo en la llamada que produce el resultado.
                    if len(prompt) <= budget:
                        out = _one(reduce_system, prompt, _tokens(max_words))
                        text = out or ""
                        break
                    # Ni los parciales caben: se reducen por grupos y se repite.
                    grouped: list[str] = []
                    for group in _chunk_text(joined, budget):
                        out = _one(
                            regroup_system, build_user(group.strip()), _tokens(partial_words)
                        )
                        if out is None:
                            break
                        grouped.append(out)
                    if failed is not None:
                        break
                    summaries = grouped
                else:
                    text = "\n\n".join(summaries)
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
            detail = failed.text.removeprefix("[local-delegate error] ")
            text = (
                f"[local-delegate error] el contenido no cabe en el contexto de {model}, ni "
                f"partido en trozos de {config.CHUNK_MIN_CHARS} caracteres. Sube el contexto "
                f"del backend para ese modelo, usa uno con contexto mayor, o pasa menos "
                f"contenido de una vez. Respuesta del backend: {detail}"
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
            text += (
                f"\n\n[local-delegate aviso: salida truncada por max_tokens en {truncated_calls} de "
                f"{calls} llamadas; puede faltar parte del contenido]"
            )
        text += current.notice(len(pieces) > 1)

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
        truncated_in=False,  # el sentido de todo esto es que ya no se trunca
        truncated_out=ok and truncated_calls > 0,
        raw_len=raw_len,
        path=path if source == "path" else None,
        chunks=calls,
        num_sections=num_sections,
        focus=focus,
        attempts=all_attempts,
        **current.log_fields(failed),
    )
    if source == "path" and ok and config.FEEDBACK_ENABLED:
        event = cost.in_flight_row(tool=tool, source=source, path=path)
        text += _savings_feedback(len(content), "chars", event=event)
    if ok and calls > 1 and config.FEEDBACK_ENABLED:
        text += f"\n\n(resumido de {len(pieces)} partes en {calls} pasadas por local-delegate)"
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


def _commit_language_instruction() -> str:
    """La orden de idioma del prompt de sistema de `local_commit_msg` (REQ-044).

    Medido en la tanda de afinidad (2026-10-07): con el prompt de antes, que no pedía idioma, el
    26B escribió 17 de 30 mensajes en inglés y Qwen3.6 6 de 30, sobre un repo documentado en
    español. Con `LOCAL_DELEGATE_COMMIT_LANGUAGE` puesta, el idioma es el que dice la variable;
    sin ella, el predominante de los textos del diff, en vez de lo que el modelo prefiera.
    """
    code = config.commit_language()
    if not code:
        return (
            "Escribe el mensaje de commit entero (primera línea y cuerpo) en el idioma "
            "predominante de los textos del diff (comentarios, documentación y mensajes)."
        )
    # `es-CU` y `es_ES` se reconocen por su primera parte; si no se conoce, se usa tal cual.
    first_part = code.lower().replace("_", "-").split("-")[0]
    name = _LANGUAGE_NAMES.get(first_part, code)
    return f"Escribe el mensaje de commit entero (primera línea y cuerpo) en {name}."


def _guard(output_format: str, max_words: int | None = None) -> str:
    limit = f" Máximo {max_words} palabras." if max_words else ""
    return (
        "Responde directo desde el input. NO uses herramientas, NO busques en internet. "
        f"Output EXACTO: {output_format}.{limit} Nada fuera del formato."
    )


def _lint_system(max_words: int) -> str:
    """El prompt de sistema de `local_lint_summary`. También entra en la huella (T15)."""
    return _guard(
        "un resumen de los problemas agrupados por archivo, con el conteo por tipo de "
        "error/regla y los más relevantes primero",
        max_words,
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
            f"Extensión de imagen no soportada: '{suffix}'. Válidas: {sorted(_IMAGE_MIME)}"
        )
    if not p.is_file():
        raise ValueError(f"No existe el archivo: {path}")
    size = p.stat().st_size
    max_bytes = config.MAX_IMAGE_MB * 1024 * 1024
    if size > max_bytes:
        raise ValueError(
            f"Imagen demasiado grande: {size / 1024 / 1024:.1f} MB "
            f"(máximo {config.MAX_IMAGE_MB} MB)"
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
        [s.size for s in sections_], max_words, minimum=_MIN_WORDS_PER_SECTION
    )
    lines = []
    for section, words in zip(sections_, allocation, strict=True):
        note = " (el texto antes de la primera sección)" if section.synthetic else ""
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

    def _complete(text: str, truncated: bool) -> str:
        return sections.complete(text, headings, truncated=truncated).text

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
@mcp.tool(annotations=_annotations("Resumir texto o archivo"))
def local_summarize(
    text: str | None = None,
    path: str | None = None,
    max_words: int = 150,
    focus: str | None = None,
) -> str:
    """PREFIERE esta tool en vez de leer el archivo con Read cuando el archivo es grande
    (>200 líneas / >10 KB) y solo necesitas un resumen, no el contenido literal.

    Resume texto o el contenido de un archivo con un modelo local, sin gastar contexto de Claude.

    Usa esto para resumir archivos/documentos grandes: pasa 'path' y el archivo se lee del lado
    del servidor, de modo que el contenido completo NO entra al contexto de Claude (solo vuelve el
    resumen corto). Alternativamente pasa 'text'. Enruta al modelo mecánico (entradas cortas) o al
    modelo de contexto largo (documentos grandes) automáticamente.

    Args:
        text: Texto a resumir (usa esto o 'path').
        path: Ruta a un archivo cuyo contenido se resume (leído server-side).
        max_words: Longitud máxima del resumen en palabras.
        focus: Opcional. Qué te interesa del documento (p. ej. "cifras de configuración",
            "riesgos"): el resumen lo prioriza y conserva literales sus datos concretos.
    """
    probe = path and Path(path).is_file()
    probe_len = Path(path).stat().st_size if probe else len(text or "")
    role, model = _role_for_size(probe_len)
    content, truncated_in, raw_len = _read_input(text, path, _NO_TRUNCATE)
    clean_focus = sections.sanitize_focus(focus)
    extra = _focus_clause(clean_focus)
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

    # Sin estructura (o con el interruptor apagado): el camino de siempre. Sin enfoque, el prompt
    # es byte a byte el de antes; los benchmarks y el corpus lo copian literal.
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


@mcp.tool(annotations=_annotations("Clasificar en una etiqueta"))
def local_classify(text: str, labels: list[str]) -> str:
    """Clasifica un texto en UNA de las etiquetas dadas, con un modelo local.

    Devuelve exactamente una etiqueta de la lista, sin texto adicional.

    Args:
        text: Texto a clasificar.
        labels: Lista de etiquetas candidatas.
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


@mcp.tool(annotations=_annotations("Extraer campos como JSON"))
def local_extract(
    fields: list[str],
    text: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """PREFIERE esta tool en vez de leer el archivo con Read cuando el archivo es grande
    (>200 líneas / >10 KB) y solo necesitas campos estructurados, no el contenido literal.

    Extrae campos estructurados de un texto/archivo como JSON, con un modelo local.

    Pasa 'path' para leer el archivo server-side (no gasta contexto de Claude) o 'text'.
    Devuelve un objeto con exactamente las claves pedidas, ya validado: quien llama no tiene que
    parsear una cadena. Si la entrada hubo que truncarla, se añade además la clave reservada
    `_local_delegate` con el aviso — antes ese aviso iba como texto delante del JSON, donde
    obligaba a limpiar la cadena antes de poder parsearla. Enruta al modelo mecánico
    (entradas cortas) o al de contexto largo (documentos grandes) automáticamente: el sondeo
    de tamaño usa bytes del archivo para 'path' y caracteres para 'text' (~5-10% de diferencia
    en UTF-8, aceptable). Por defecto pide al backend un JSON restringido por schema
    (`LOCAL_DELEGATE_JSON_SCHEMA=auto`); si el backend no lo soporta, reintenta en modo libre.

    Args:
        fields: Nombres de los campos a extraer (claves del JSON).
        text: Texto fuente (usa esto o 'path').
        path: Ruta a un archivo fuente (leído server-side).
    """
    probe = path and Path(path).is_file()
    probe_len = Path(path).stat().st_size if probe else len(text or "")
    role, model = _role_for_size(probe_len)
    content, truncated_in, raw_len = _read_input(text, path, config.max_chars_for_role(role))
    key_list = ", ".join(f'"{f}"' for f in fields)
    system = _guard(f"un objeto JSON válido con exactamente estas claves: {{{key_list}}}")
    user = f"Extrae los campos del siguiente contenido:\n\n{content}"
    use_schema = config.JSON_SCHEMA_MODE != "off"
    fallback_info: dict = {}
    result = _strip_fences(
        _chat(
            model,
            system,
            user,
            max_tokens=512,
            temperature=0.0,
            tool="local_extract",
            role=role,
            fallback=fallback_info,
            chars_in=len(content),
            source="path" if path else "inline",
            truncated_in=truncated_in,
            raw_len=raw_len,
            path=path,
            response_format=_json_schema_payload(fields) if use_schema else None,
            json_schema_fallback=config.JSON_SCHEMA_MODE == "auto",
            # SIN la línea de ahorro pegada al texto: esta tool parsea el resultado, y ese sufijo
            # convertía un JSON perfecto en uno imparseable. El dato no se pierde, baja unas
            # líneas más abajo a `_local_delegate`, que es donde va lo que no son datos.
            feedback=False,
        )
    )

    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        # El modelo devolvió algo que no es JSON, o el backend falló y `result` trae el aviso de
        # error. Degradar con la carga cruda es mejor que lanzar: quien llama ve qué pasó en vez
        # de recibir una excepción de protocolo.
        return {"_local_delegate": {"error": "respuesta no parseable como JSON", "crudo": result}}
    if not isinstance(data, dict):
        return {"_local_delegate": {"error": "la respuesta no es un objeto JSON", "crudo": result}}

    meta: dict = {}
    if truncated_in:
        meta["truncado"] = True
        meta["aviso"] = f"entrada truncada — procesados {len(content)} de {raw_len} chars"
    if path and config.FEEDBACK_ENABLED:
        # Tokens de Claude de la fila en curso (REQ-035), no del modelo local.
        event = cost.in_flight_row(tool="local_extract", source="path", path=path)
        meta["leido_server_side"] = {
            "chars": len(content),
            "tokens_aprox": claude_tokens(len(content), kind="text", event=event),
        }
    if fallback_info:
        # Con el resto de metadatos, nunca dentro de los campos que el agente usa tal cual.
        meta["respaldo"] = fallback_info
    if meta:
        data["_local_delegate"] = meta
    return data


@mcp.tool(annotations=_annotations("Generar código boilerplate", writes=True))
def local_boilerplate(spec: str, language: str, target: str, overwrite: bool = False) -> str:
    """Genera código boilerplate a partir de una especificación, con un modelo local de código.

    **Escribe el código en `target`** y devuelve solo un recibo de dos líneas (ruta, tamaño). El
    código generado nunca entra a tu contexto: ahí está el ahorro, y por eso `target` no es
    opcional. Para verlo, abre el archivo; para usarlo, ya está en su sitio.

    Args:
        spec: Descripción de lo que debe generar el código.
        language: Lenguaje de programación (p. ej. 'python', 'typescript').
        target: Ruta ABSOLUTA del archivo a escribir. Los directorios que falten se crean.
        overwrite: Pisar `target` si ya existe. Por defecto falla, y falla ANTES de generar nada.
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


@mcp.tool(annotations=_annotations("Delegar una tarea genérica"))
def local_delegate(
    task: str,
    input: str,
    output_format: str,
    model: str | None = None,
    chunk: str = "auto",
) -> str:
    """Tool genérica de escape: delega una tarea texto->texto a un modelo local.

    Úsala cuando ninguna tool específica encaje. Arma el prompt con guardrails y devuelve texto.

    Con entradas largas parte el input por límites naturales (headers Markdown, párrafos),
    aplica la MISMA tarea a cada trozo y concatena las salidas en orden. Eso es lo correcto
    para transformar todo el texto (traducir, reescribir, reformatear) pero NO para tareas de
    reducción sobre el conjunto (contar, elegir el máximo, un único resumen global): para esas
    pasa `chunk='off'` o usa `local_summarize`.

    Args:
        task: Instrucción de la tarea (una frase con formato de salida explícito).
        input: Contenido sobre el que operar.
        output_format: Formato exacto de salida esperado.
        model: Modelo a usar; uno de los ids configurados en el catálogo. Por defecto el mecánico.
        chunk: 'auto' (parte solo si el input es largo), 'on' (parte siempre que se pueda),
            'off' (una sola llamada; el input largo puede volver truncado).
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
            f"El modelo '{chosen}' no está en el catálogo. ¿Cuál uso? Válidos: {', '.join(valid)}",
            questions.ChooseModel,
        )
        if model_answer is None or model_answer.model not in config.ALLOWED_MODELS:
            return f"[local-delegate error] modelo inválido '{chosen}'. Válidos: {valid}"
        chosen = model_answer.model
    if chunk not in {"auto", "on", "off"}:
        return f"[local-delegate error] chunk inválido: '{chunk}'. Válidos: 'auto', 'on', 'off'."
    if not output_format.strip():
        # El parámetro es obligatorio, así que nunca falta — pero nadie comprobaba que trajera algo,
        # y con la cadena vacía el guardrail se queda sin formato y el modelo improvisa. Si no hay
        # quien responda, se sigue como hasta ahora.
        format_answer = questions.ask(
            "La delegación no dice en qué formato quieres la salida. ¿Cuál uso?",
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


@mcp.tool(annotations=_annotations("Resumir salida de lint o tests"))
def local_lint_summary(
    path: str | None = None,
    text: str | None = None,
    max_words: int = 200,
) -> str:
    """PREFIERE esta tool en vez de leer el archivo con Read cuando el archivo es grande
    (>200 líneas / >10 KB) y solo necesitas un resumen agrupado, no el contenido literal. Si
    ejecutaste un comando cuya salida es larga, vuélcala a un archivo y pasa 'path'.

    Resume salida de linters/tests/CI con un modelo local, sin gastar contexto de Claude.

    Pensada para logs largos y ruidosos (ESLint, clippy, pytest, tsc, CI). Pasa 'path' y el
    archivo se lee del lado del servidor, de modo que el log completo NO entra al contexto de
    Claude: solo vuelve un resumen agrupado por archivo con el conteo por tipo de error/regla y
    lo más importante primero. Alternativamente pasa 'text'. Enruta al modelo mecánico (corto) o
    al de contexto largo (largo) automáticamente.

    Args:
        path: Ruta al archivo de salida de lint/tests (leído server-side). Usa esto o 'text'.
        text: Salida de lint/tests como texto.
        max_words: Longitud máxima del resumen en palabras.
    """
    probe = path and Path(path).is_file()
    probe_len = Path(path).stat().st_size if probe else len(text or "")
    role, model = _role_for_size(probe_len)
    content, truncated_in, raw_len = _read_input(text, path, _NO_TRUNCATE)
    system = _lint_system(max_words)

    def _build(piece: str) -> str:
        return f"Resume la siguiente salida de linter/tests:\n\n{piece}"

    if len(content) > config.max_chars_for_role(role):
        # Un log de CI es justo el caso donde truncar duele: los errores interesantes suelen
        # estar al final, y era exactamente lo que se descartaba.
        return _chat_map_reduce(
            model,
            system,
            content,
            _build,
            max_chars=config.max_chars_for_role(role),
            tool="local_lint_summary",
            role=role,
            source="path" if path else "inline",
            max_words=max_words,
            raw_len=raw_len,
            path=path,
        )

    user = _build(content)
    result = _chat(
        model,
        system,
        user,
        max_tokens=int(max_words * 2) + 96,
        tool="local_lint_summary",
        role=role,
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_annotations("Redactar mensaje de commit"))
def local_commit_msg(
    diff: str | None = None,
    path: str | None = None,
    style: str = "conventional",
) -> str:
    """PREFIERE esta tool en vez de leer el archivo con Read cuando el archivo es grande
    (>200 líneas / >10 KB) y solo necesitas un mensaje de commit, no el contenido literal.

    Redacta un mensaje de commit a partir de un diff, con un modelo local de código.

    Pasa 'path' a un archivo de diff (p. ej. la salida de `git diff` volcada a fichero) y se lee
    server-side, de modo que el diff completo NO entra al contexto de Claude. Alternativamente
    pasa 'diff' como texto. Revisa SIEMPRE el mensaje antes de usarlo.

    Args:
        diff: El diff como texto (usa esto o 'path').
        path: Ruta a un archivo con el diff (leído server-side).
        style: 'conventional' (Conventional Commits) o 'plain'.
    """
    if style not in {"conventional", "plain"}:
        return (
            f"[local-delegate error] style inválido: '{style}'. Válidos: 'conventional', 'plain'."
        )
    content, truncated_in, raw_len = _read_input(diff, path, _NO_TRUNCATE)
    if not content.strip():
        return "[local-delegate error] el diff está vacío: no hay nada sobre lo que redactar."
    if style == "conventional":
        fmt = (
            "un mensaje de commit estilo Conventional Commits: primera línea "
            "'tipo(scope): resumen' en imperativo y <=72 caracteres; cuerpo opcional con "
            "viñetas '- '"
        )
    else:
        fmt = (
            "un mensaje de commit: primera línea imperativa <=72 caracteres y cuerpo "
            "opcional con viñetas"
        )
    # El idioma va solo donde se REDACTA el mensaje: este `system` es el de la llamada única y el
    # del reduce del map-reduce (`reduce_system=system`). El map y el reagrupado de partes usan
    # `map_system`, que produce notas intermedias que nadie lee y no lleva la orden.
    system = f"{_guard(fmt)} {_commit_language_instruction()}"
    user = f"Escribe el mensaje de commit para este diff:\n\n{content}"

    if len(content) > config.max_chars_for_role("code"):
        # El diff no cabe en una llamada. Antes se truncaba: medido sobre un diff de 164 585
        # chars y 44 archivos, el modelo veía 20 027 chars —7 archivos, todos de `.sdd/`— y
        # devolvía `chore: update GitHub Actions pages artifact version`, o sea el primer
        # archivo por orden alfabético de rutas. Ahora entra entero: parte por archivo, un
        # parte por trozo, y el mensaje se redacta sobre esos partes MÁS el inventario completo.
        files = _diff_inventory(content)
        budget = max(config.CHUNK_MIN_CHARS, int(config.max_chars_for_role("code") * 0.8))
        inventory = _format_inventory(files, int(budget * 0.25))
        # El formato del map NO se describe con una plantilla del tipo `- ruta: qué cambió`:
        # medido, el modelo la devuelve copiada tal cual —`- ruta: qué cambió y para qué`— y ese
        # trozo se pierde entero. Se ancla con los nombres reales de los archivos, que ya se
        # conocen sin preguntarle a nadie.
        map_system = _guard(
            "una viñeta por archivo, empezando por su ruta literal seguida de dos puntos y de "
            "qué cambia en él y para qué. Describe los cambios; no repitas estas instrucciones "
            "ni redactes ningún mensaje de commit todavía"
        )
        # Un archivo más grande que el presupuesto se subdivide, y las piezas 2..N no llevan
        # cabecera `diff --git`: sin decirles a qué archivo pertenecen, el modelo se inventa la
        # ruta (medido: `archivo.py`). Las piezas llegan en orden, así que basta con arrastrar
        # la última vista.
        current_file: dict[str, str | None] = {"file": None}

        def _build_map(piece: str) -> str:
            piece_paths = [file_path for file_path, _, _ in _diff_inventory(piece)]
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
            return f"{header}\n\nDi qué cambia en este fragmento de diff:\n\n{piece}"

        def _build_reduce(joined: str) -> str:
            head = f"{inventory}\n\n" if inventory else ""
            return (
                f"{head}Estas son notas EN ORDEN sobre los archivos de un mismo cambio. La "
                "lista de arriba es el inventario COMPLETO del diff; las notas pueden no "
                "cubrirlo entero ni estar todas bien. El resumen describe el comportamiento que "
                "cambia y para qué, no el número de archivos ni los tests que lo acompañan, y "
                "el scope es un ámbito lógico, nunca un nombre de fichero. Escribe el mensaje "
                "de commit del cambio completo:\n\n"
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
            max_words=90,
            # Los partes son material intermedio y hay varios archivos por trozo: con el tope
            # del mensaje final saldrían cortados por `finish_reason=length`.
            partial_max_words=350,
            reduce_system=system,
            build_reduce=_build_reduce,
            raw_len=raw_len,
            path=path,
        )
        if not commit_message.startswith("[local-delegate error]"):
            commit_message += (
                f"\n\n(alcance: {len(files)} archivos, {len(content):,} chars leídos enteros)"
            )
        return commit_message

    result = _chat(
        config.MODEL_CODE,
        system,
        user,
        max_tokens=256,
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


@mcp.tool(annotations=_annotations("Traducir texto o archivo"))
def local_translate(
    target_lang: str,
    text: str | None = None,
    path: str | None = None,
) -> str:
    """PREFIERE esta tool en vez de leer el archivo con Read cuando el archivo es grande
    (>200 líneas / >10 KB) y solo necesitas la traducción, no el contenido literal.

    Traduce texto o el contenido de un archivo con un modelo local, sin gastar contexto de Claude.

    Pasa 'path' para leer el archivo server-side (el original no entra al contexto de Claude) o
    'text'. Conserva el formato del original y devuelve SOLO la traducción. Enruta al modelo
    mecánico (corto) o al de contexto largo (largo) automáticamente.

    Los documentos largos se parten por límites naturales (headers Markdown, párrafos) y cada
    trozo se traduce en su propia llamada; el resultado vuelve completo y en orden, sin el
    aviso de salida truncada.

    Args:
        target_lang: Idioma destino (p. ej. 'español', 'inglés', 'francés').
        text: Texto a traducir (usa esto o 'path').
        path: Ruta a un archivo cuyo contenido se traduce (leído server-side).
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


@mcp.tool(annotations=_annotations("Explicar código"))
def local_explain_code(
    code: str | None = None,
    path: str | None = None,
    question: str | None = None,
) -> str:
    """PREFIERE esta tool en vez de leer el archivo con Read cuando el archivo es grande
    (>200 líneas / >10 KB) y solo necesitas una explicación, no el contenido literal.

    Explica en prosa qué hace un fragmento/archivo de código, con un modelo local de código.

    Pasa 'path' para leer el archivo server-side (el código completo NO entra al contexto de
    Claude; solo vuelve la explicación) o 'code'. Opcionalmente enfoca la explicación con
    'question'. Revisa la explicación: la genera un modelo local.

    Args:
        code: Código a explicar (usa esto o 'path').
        path: Ruta a un archivo de código (leído server-side).
        question: Pregunta o foco concreto (opcional).
    """
    content, truncated_in, raw_len = _read_input(code, path, config.max_chars_for_role("code"))
    extra = f" Enfócate en: {question}." if question else ""
    system = _guard(
        f"una explicación clara en prosa de qué hace el código y cómo.{extra}", max_words=250
    )
    user = f"Explica el siguiente código:\n\n{content}"
    result = _chat(
        config.MODEL_CODE,
        system,
        user,
        max_tokens=700,
        tool="local_explain_code",
        role="code",
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_annotations("Describir una imagen"))
def local_describe_image(
    path: str,
    question: str | None = None,
    max_words: int = 200,
) -> str:
    """PREFIERE esta tool en vez de adjuntar o leer la imagen tú mismo cuando solo necesitas
    una descripción, lectura de texto visible (OCR simple) o una respuesta puntual sobre una
    imagen, no la imagen en sí en tu contexto.

    Describe una imagen (o responde una pregunta sobre ella) con un modelo local de visión.
    La imagen se lee del lado del servidor: NUNCA entra al contexto de Claude, solo vuelve la
    respuesta en texto.

    Guardrail de alcance: SOLO imagen->texto (describir, leer texto visible, responder una
    pregunta puntual sobre la imagen). Esta tool NUNCA genera ni edita imágenes.

    Args:
        path: Ruta a la imagen (png/jpg/jpeg/webp/gif), leída server-side.
        question: Pregunta o foco concreto sobre la imagen (opcional; por defecto la describe).
        max_words: Longitud máxima de la respuesta en palabras.
    """
    try:
        mime = _validate_image_path(path)
    except ValueError as e:
        return f"[local-delegate error] {e}"
    raw_bytes = Path(path).read_bytes()
    raw_len = len(raw_bytes)
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    prompt = question or "Describe esta imagen con detalle."
    system = _guard("una respuesta en prosa clara sobre la imagen", max_words)
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
        feedback_label="bytes imagen",
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
        warn = "  ADVERTENCIA: <2 GB libres" if free_mb < 2048 else ""
    except ValueError:
        warn = ""
    return f"{used} / {total} usados{warn}"


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
    warn = "  ADVERTENCIA: <2 GB libres" if free_gb < 2 else ""
    return f"{used_gb:.1f} / {total_gb:.1f} GiB usados{warn}"


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
                "el cuerpo de /models no es un objeto con una lista `data`"
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
        return "ningún modelo montado"
    parts = [
        f"{e.get('model', '?')} ({e.get('state', '?')})" for e in entries if isinstance(e, dict)
    ]
    return ", ".join(parts) if parts else "ningún modelo montado"


def _describe_cooldown() -> list[str]:
    """REQ-013: los modelos enfriados, lo que les queda y cuántas veces seguidas han entrado."""
    if not config.COOLDOWN:
        return ["Enfriamiento: apagado (LOCAL_DELEGATE_COOLDOWN=0)"]
    lines = [
        (
            f"Enfriamiento: encendido ({config.COOLDOWN_FAILURES} fallos seguidos, "
            f"{config.COOLDOWN_S:.0f} s, tope {config.COOLDOWN_MAX_S:.0f} s)"
        )
    ]
    active = cooldown.from_config().active()
    if not active:
        lines.append("  ningún modelo enfriado")
    for model, cooldown_entry in sorted(active.items()):
        times = (
            "1 vez seguida"
            if cooldown_entry.reentries == 1
            else f"{cooldown_entry.reentries} veces seguidas"
        )
        lines.append(f"  {model}: quedan {cooldown_entry.remaining_s:.0f} s, ha entrado {times}")
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
            "swap" if group.swap else "sin swap",
            "exclusivo" if group.exclusive else "no exclusivo",
        ]
        if group.persistent:
            flags.append("persistente")
        parts.append(f"{name} [{', '.join(flags)}]: {', '.join(group.members)}")
    return " | ".join(parts) if parts else "ningún grupo"


def _describe_turn() -> str:
    """REQ-008 y REQ-002: si hay turno, qué choca, qué está en uso y cuántos esperan; si no, por qué."""
    snapshot = _topology()
    if not isinstance(snapshot, topology.Snapshot):
        return f"Turno: no ({snapshot.reason})"
    state = _turn.snapshot()
    in_use = ", ".join(_turn.in_use()) or "nada"
    return (
        f"Turno: sí (choques: {_clashes_by_groups(snapshot)}; en uso: {in_use}; "
        f"esperan: {len(state.queue)})"
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
        return "arriba"
    if state.cause == failures.ConnectionCause.CREDENTIAL.value:
        return f"SIN ACCESO: {state.detail}"
    if state.cause in _CAUSES_WITH_RESPONSE:
        return f"RESPONDE CON ERROR: {state.detail}"
    return f"CAÍDO: {state.detail}"


@mcp.tool(annotations=_annotations("Diagnóstico del backend local"))
def local_status() -> str:
    """Diagnóstico de solo lectura del backend local y el catálogo de modelos.

    Úsala para saber qué modelos locales hay disponibles y verificar que el backend está vivo
    antes de delegar en masa, o para diagnosticar por qué una tool local_* falló.
    """
    lines: list[str] = [f"local-delegate v{_get_version()}", ""]

    state = probe_backend()
    backend_up, models = state.available, state.models
    origin = "local (esta máquina)" if config.backend_origin() == "local" else "REMOTO"
    lines.append(f"Backend: {config.BASE_URL} — {_backend_state_text(state)}")
    lines.append(f"  cómputo: {origin} — {config.backend_host()}")
    if backend_up:
        if models:
            shown = ", ".join(
                f"{m['id']} ({m['status']})" if m["status"] else m["id"] for m in models
            )
        else:
            shown = "(ninguno)"
        lines.append(f"  modelos expuestos: {shown}")

    lines.append("")
    lines.append("Catálogo de roles:")
    for role, model in (
        ("mechanical", config.MODEL_MECHANICAL),
        ("long", config.MODEL_LONG),
        ("code", config.MODEL_CODE),
    ):
        lines.append(f"  {role}: {model} (max_chars={config.max_chars_for_role(role)})")
    lines.append(f"  vision: {config.MODEL_VISION} (max_image_mb={config.MAX_IMAGE_MB})")
    lines.extend(chains.describe())
    lines.append(f"  concurrencia máxima del proceso: {config.MAX_CONCURRENT_REQUESTS}")
    lines.append(_describe_turn())
    lines.extend(_describe_cooldown())

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
    lines.append(f"Log (mes actual): {current_log}")
    lines.append(
        f"  eventos: {n_events} ({backend_calls} llamadas al backend) — "
        # REQ-005: el neto (lo leído server-side menos lo devuelto al contexto), como el KPI del
        # panel, y el bruto entre paréntesis. Los fallos no suman a ninguno de los dos.
        f"contexto conservado: ~{net_tokens} tokens netos (bruto ~{saved_tokens})"
        + (f" ({n_tests} de pruebas fuera)" if n_tests else "")
    )
    for window in test_windows.load(config.LOG_DIR).open_windows():
        lines.append(
            f"  Ventana de prueba abierta: {window.id} desde "
            f"{test_windows.format_instant(window.start)}"
        )
    # REQ-027: la velocidad normal de cada modelo. Observar no rompe la tool (REQ-028): si no se
    # puede describir, el informe sale sin esa línea.
    with suppress(Exception):
        lines.append(f"  {_describe_pace()}")

    lines.append("")
    if config.WEB_ENABLED:
        web_up = _port_listening(config.WEB_HOST, config.WEB_PORT)
        lines.append(
            f"Web de métricas: {'activa' if web_up else 'inactiva'} "
            f"(http://{config.WEB_HOST}:{config.WEB_PORT})"
        )
    else:
        lines.append("Web de métricas: deshabilitada (LOCAL_DELEGATE_WEB=0)")

    vram = _vram_info()
    if vram:
        lines.append("")
        lines.append(f"VRAM (nvidia-smi): {vram}")

    ram = _ram_info()
    if ram:
        lines.append(f"RAM de sistema: {ram}")

    # REQ-013: `/running` solo si `/models` respondió. Con el backend inalcanzable, un plazo de
    # conexión y no dos.
    running = _llamaswap_running() if backend_up else None
    if running:
        lines.append(f"llama-swap /running: {running}")

    groups = _llamaswap_groups()
    if groups:
        lines.append(f"llama-swap groups activos (LLAMASWAP_CONFIG): {groups}")

    lines.extend(_describe_deprecated_names())
    return "\n".join(lines)


def _describe_deprecated_names() -> list[str]:
    """Nombres viejos de variables que ESTE proceso leyó (REQ-003).

    `doctor` mira la shell donde corre y el `env` de `settings.json`, pero no el entorno del daemon
    ni el del servidor por stdio: eso solo lo sabe el propio proceso, por `config.DEPRECATED_SEEN`.
    """
    from . import deprecation_notices, deprecations

    entries = [e for e in map(deprecations.find, sorted(config.DEPRECATED_SEEN)) if e is not None]
    if not entries:
        return []
    return ["", "Nombres obsoletos leídos por este proceso:"] + [
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
