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
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

import httpx2
from filelock import FileLock, Timeout
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import autostart, config

# --- Versión del paquete (cacheada) ------------------------------------------
# Se define antes de instanciar el server porque este la declara en su constructor.
_PACKAGE_VERSION: str | None = None


def _get_version() -> str:
    global _PACKAGE_VERSION
    if _PACKAGE_VERSION is None:
        try:
            _PACKAGE_VERSION = _pkg_version("local-delegate-mcp")
        except PackageNotFoundError:
            _PACKAGE_VERSION = "0.0.0"
    return _PACKAGE_VERSION


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
)


def _anotaciones(titulo: str) -> ToolAnnotations:
    """Anotaciones comunes a las 11 tools, que son todas de la misma naturaleza.

    `read_only_hint`: ninguna tool modifica nada del entorno de quien llama. Escriben en el log de
    uso, pero eso es contabilidad interna del propio servidor —lo que alimenta el dashboard—, no un
    efecto sobre los datos del usuario. `destructive_hint` e `idempotent_hint` se omiten a
    propósito: el protocolo solo les da sentido cuando `read_only_hint` es falso, y ponerlos aquí
    sería ruido que además se contradice con lo anterior.

    `open_world_hint` en falso: el dominio es cerrado y conocido —el endpoint configurado en
    `LOCAL_DELEGATE_BASE_URL` y los archivos bajo las raíces permitidas—. Ninguna tool sale a
    buscar a un mundo abierto, y para un cliente eso es la diferencia entre delegar a tu GPU o a
    algo que puede tocar internet.
    """
    return ToolAnnotations(title=titulo, read_only_hint=True, open_world_hint=False)


# --- Cliente httpx2 module-level (keep-alive entre delegaciones) -------------
_client: httpx2.Client | None = None
_client_lock = threading.Lock()
_chat_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_REQUESTS)


def _get_client() -> httpx2.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx2.Client(timeout=config.HTTP_TIMEOUT)
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


def _read_inflight_data(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_write_json(path: Path, data: dict) -> None:
    # El temporal lleva el pid en el nombre: varios procesos MCP (cada sesión de Claude en
    # stdio, más el daemon) escriben este mismo archivo, y un ".tmp" compartido hacía que
    # dos escrituras simultáneas se pisaran el temporal y publicaran contenido mezclado o
    # perdido — entradas fantasma / delegaciones que nunca aparecían en "En curso".
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)  # si replace() funcionó ya no existe
        except OSError:
            pass


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
) -> None:
    """Escribe una línea JSONL en el log activo (rotado por mes o fijo). Nunca rompe una tool."""
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
        if json_schema is not None:
            rec["json_schema"] = json_schema
        log_path = _current_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _append_log_line(log_path, json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # el logging es best-effort; jamás propaga


def _accounting(row: dict) -> dict:
    """Contabilidad normalizada de UN evento. Única fuente de las cuentas del panel.

    Separa dos magnitudes que el dashboard confundía en una sola estimación por caracteres:

    - **ahorro** (`saved`): lo que NO entró al contexto de Claude. Es el contenido leído
      server-side contado **una vez**, aunque se troceara: el trabajo extra de trocear lo pagó
      la GPU local, no el contexto.
    - **coste** (`tokens_in`/`tokens_out`, `backend_calls`): lo que gastó de verdad el backend,
      con el prompt de sistema repetido en cada trozo.

    Se prefiere SIEMPRE el token real que reportó el backend (`usage`); la estimación
    `chars ÷ 4` es solo el respaldo cuando falta, y entonces el evento se marca `estimated`.
    """
    chars_in = int(row.get("chars_in", 0) or 0)
    chars_out = int(row.get("chars_out", 0) or 0)
    # `chunks` es el número REAL de llamadas al backend y se omite cuando vale 1 (ver
    # `_log_event`). Lo ha sido desde el commit que introdujo el chunking, así que esto
    # contabiliza bien también el histórico ya grabado.
    backend_calls = int(row.get("chunks") or 1)

    raw_in = row.get("tokens_in")
    raw_out = row.get("tokens_out")
    estimated = raw_in is None or raw_out is None

    # `chars_in` no siempre son caracteres: en local_describe_image son BYTES de la imagen.
    # Los eventos anteriores al campo `input_unit` se reconocen por el nombre de la tool.
    unit = row.get("input_unit") or (
        "bytes" if row.get("tool") == "local_describe_image" else "chars"
    )
    estimable = unit == "chars"

    tokens_in = (
        int(raw_in)
        if raw_in is not None
        else (chars_in // config.CHARS_PER_TOKEN if estimable else 0)
    )
    tokens_out = int(raw_out) if raw_out is not None else chars_out // config.CHARS_PER_TOKEN

    if row.get("source") != "path":
        saved = 0  # el input ya viajó por el contexto de Claude: no hay ahorro que apuntar
    elif estimable:
        saved = chars_in // config.CHARS_PER_TOKEN
    elif raw_in is not None:
        saved = int(raw_in)  # imagen: el token real es el único orden de magnitud honesto
    else:
        saved = 0  # ni token real ni unidad estimable: 0 antes que un número inventado

    return {
        "backend_calls": backend_calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "saved": saved,
        "estimated": estimated,
    }


@dataclass
class ChatResult:
    text: str
    ok: bool
    error: str | None = None  # mensaje corto cuando ok=False
    finish_reason: str | None = None  # choices[0].finish_reason
    tokens_in: int | None = None  # usage.prompt_tokens si el backend lo da
    tokens_out: int | None = None  # usage.completion_tokens


def _post_chat(model: str, payload: dict) -> ChatResult:
    """POST al endpoint /chat/completions con reintento opcional si el backend está caído."""
    headers = config.auth_headers()
    client = _get_client()
    for attempt in (1, 2):
        try:
            r = client.post(f"{config.BASE_URL}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            choice = data["choices"][0]
            usage = data.get("usage") or {}
            return ChatResult(
                text=choice["message"]["content"].strip(),
                ok=True,
                finish_reason=choice.get("finish_reason"),
                tokens_in=usage.get("prompt_tokens"),
                tokens_out=usage.get("completion_tokens"),
            )
        except httpx2.ConnectError:
            # El backend no está escuchando. Si el auto-arranque está activo, intenta
            # levantarlo (opt-in, específico de llama-swap) y reintenta una vez.
            if attempt == 1 and config.AUTOSTART and autostart.ensure_backend(wait=30):
                continue
            return ChatResult(
                text=(
                    f"[local-delegate error] no se pudo conectar al endpoint ({config.BASE_URL}). "
                    "¿Está corriendo tu backend OpenAI-compatible?"
                ),
                ok=False,
                error="connect_error",
            )
        except httpx2.HTTPStatusError as e:
            return ChatResult(
                text=(
                    f"[local-delegate error] {model} respondió {e.response.status_code}: "
                    f"{e.response.text[:300]}"
                ),
                ok=False,
                error=f"http_{e.response.status_code}",
            )
        except httpx2.HTTPError as e:
            return ChatResult(
                text=f"[local-delegate error] fallo de conexión al endpoint ({config.BASE_URL}): {e}",
                ok=False,
                error="http_error",
            )
        except (KeyError, IndexError, ValueError) as e:
            return ChatResult(
                text=f"[local-delegate error] respuesta inesperada de {model}: {e}",
                ok=False,
                error="bad_response",
            )
    return ChatResult(
        text=f"[local-delegate error] no se pudo completar la petición a {model}.",
        ok=False,
        error="retry_exhausted",
    )


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


def _run_chat(
    model: str,
    system: str,
    user: str | list[dict],
    max_tokens: int,
    temperature: float,
    *,
    response_format: dict | None = None,
    json_schema_fallback: bool = False,
) -> tuple[ChatResult, int, str | None]:
    """UNA llamada al endpoint bajo el semáforo de concurrencia.

    Devuelve (resultado, latencia_ms, estado_json_schema). No registra nada en el log ni
    toca el inflight: de eso se encargan _chat (una llamada = un evento) y _chat_chunked
    (N llamadas = un evento con `chunks`).
    """
    payload = {
        "model": model,
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

    t0 = time.monotonic()
    with _chat_slots:
        result = _post_chat(model, payload)
        json_schema_status = "used" if response_format is not None else None
        if response_format is not None and not result.ok and result.error == "http_400":
            if json_schema_fallback:
                # El backend no soporta response_format con schema: reintenta en modo libre.
                payload.pop("response_format", None)
                result = _post_chat(model, payload)
                json_schema_status = "fallback"
            else:
                json_schema_status = "error"
    return result, int((time.monotonic() - t0) * 1000), json_schema_status


def _savings_feedback(chars_in: int, tokens_in: int | None, label: str, char_estimate: bool) -> str:
    """Línea de ahorro que se anexa al resultado cuando la entrada se leyó server-side."""
    tokens = tokens_in
    if tokens is None and char_estimate:
        tokens = chars_in // config.CHARS_PER_TOKEN
    if tokens is None:
        return ""
    return (
        f"\n\n(leído server-side: {chars_in:,} {label} ≈ {tokens:,} tokens "
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
    feedback_char_estimate: bool = True,
    feedback: bool = True,
    input_unit: str = "chars",
) -> str:
    """POST al endpoint. Devuelve solo texto y registra la llamada en USAGE_LOG.

    `user` acepta un `str` (texto->texto) o una lista de bloques de contenido
    OpenAI-compatible (p. ej. `[{"type":"text",...},{"type":"image_url",...}]` para
    local_describe_image).
    """
    entry_id = _inflight_start(tool=tool, model=model, source=source, chars_in=chars_in)
    try:
        result, latency_ms, json_schema_status = _run_chat(
            model,
            system,
            user,
            max_tokens,
            temperature,
            response_format=response_format,
            json_schema_fallback=json_schema_fallback,
        )
    finally:
        _inflight_end(entry_id)

    text = _strip_think(result.text) if result.ok else result.text
    truncated_out = result.finish_reason == "length"
    if truncated_out:
        text += "\n\n[local-delegate aviso: salida truncada por max_tokens]"
    _log_event(
        tool=tool,
        model=model,
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
    )
    # `feedback=False` lo usa quien va a PARSEAR el resultado: anexar la línea de ahorro al texto
    # rompería un JSON válido. Ver `local_extract`, que la recoloca dentro de `_local_delegate`.
    if feedback and source == "path" and result.ok and config.FEEDBACK_ENABLED:
        text += _savings_feedback(
            chars_in, result.tokens_in, feedback_label, feedback_char_estimate
        )
    return text


# --- Chunking por límites naturales (local_translate / local_delegate) --------
# Las tools que transforman el texto ENTERO producen tanta salida como entrada, así que una
# sola llamada choca contra max_tokens y devuelve el documento cortado. Partimos la entrada
# por el límite natural más grueso que sirva (headers Markdown -> párrafos -> líneas -> corte
# duro) y traducimos/transformamos cada trozo por separado.
#
# Invariante: "".join(_chunk_text(t, n)) == t. Cada trozo conserva el separador original con
# el que terminaba, así las costuras se reensamblan sin inventar ni perder saltos de línea.
def _split_by_headers(text: str) -> list[str]:
    """Corta justo ANTES de cada header Markdown (`# `…`###### `)."""
    return [p for p in re.split(r"(?m)(?=^#{1,6} )", text) if p]


def _split_by_paragraphs(text: str) -> list[str]:
    """Corta DESPUÉS de cada línea en blanco (cada trozo conserva su `\\n\\n`)."""
    return [p for p in re.split(r"(?<=\n\n)", text) if p]


def _split_by_lines(text: str) -> list[str]:
    """Corta después de cada `\\n` (cada trozo conserva su salto)."""
    return [p for p in re.split(r"(?<=\n)", text) if p]


_SPLITTERS = (_split_by_headers, _split_by_paragraphs, _split_by_lines)


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

    def _accumulate(result: ChatResult, ms: int) -> None:
        nonlocal calls, latency_ms, tokens_in, tokens_out
        calls += 1
        latency_ms += ms
        if result.tokens_in is not None:
            tokens_in = (tokens_in or 0) + result.tokens_in
        if result.tokens_out is not None:
            tokens_out = (tokens_out or 0) + result.tokens_out

    def _process(piece: str, depth: int = 0) -> str | None:
        """Devuelve el texto del trozo, o None si el backend falló (aborta la operación)."""
        nonlocal failed, truncated_out
        max_tokens = min(len(piece) // 2 + 128, config.CHUNK_MAX_TOKENS)
        result, ms, _schema = _run_chat(
            model, system, build_user(piece.strip()), max_tokens, temperature
        )
        _accumulate(result, ms)
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
            output = _process(piece)
            if output is None:
                break
            outputs.append(_reattach_separator(piece, output))
    finally:
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

    _log_event(
        tool=tool,
        model=model,
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
    )
    if source == "path" and ok and config.FEEDBACK_ENABLED:
        text += _savings_feedback(len(content), tokens_in, "chars", True)
    if ok and calls > 1 and config.FEEDBACK_ENABLED:
        text += f"\n\n(procesado en {calls} trozos por local-delegate)"
    return text


def _chat_map_reduce(
    model: str,
    system: str,
    content: str,
    build_user,
    *,
    tool: str,
    source: str,
    max_words: int,
    temperature: float = 0.2,
    raw_len: int | None = None,
    path: str | None = None,
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
    """
    budget = max(config.CHUNK_MIN_CHARS, int(config.max_chars_for(model) * 0.8))
    pieces = _chunk_text(content, budget)
    entry_id = _inflight_start(
        tool=tool, model=model, source=source, chars_in=len(content), chunks=len(pieces)
    )
    calls = 0
    latency_ms = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    failed: ChatResult | None = None

    def _one(sys_prompt: str, user: str, words: int) -> str | None:
        nonlocal calls, latency_ms, tokens_in, tokens_out, failed
        result, ms, _schema = _run_chat(model, sys_prompt, user, int(words * 2) + 64, temperature)
        calls += 1
        latency_ms += ms
        if result.tokens_in is not None:
            tokens_in = (tokens_in or 0) + result.tokens_in
        if result.tokens_out is not None:
            tokens_out = (tokens_out or 0) + result.tokens_out
        if not result.ok:
            failed = result
            return None
        return _strip_think(result.text)

    # Cada parcial se deja algo más largo que el resumen final: el reduce necesita material
    # con el que trabajar, y un parcial demasiado corto ya habría perdido lo que importa.
    partial_words = max(80, max_words)
    reduce_system = _guard(
        "un ÚNICO resumen global en prosa clara, sin repetir ni enumerar los fragmentos",
        max_words,
    )

    try:
        summaries: list[str] = []
        for index, piece in enumerate(pieces, start=1):
            _inflight_progress(entry_id, index)
            out = _one(system, build_user(piece.strip()), partial_words)
            if out is None:
                break
            summaries.append(out)

        text = ""
        if failed is None:
            if len(summaries) == 1:
                text = summaries[0]
            else:
                for _level in range(3):
                    joined = "\n\n".join(summaries)
                    if len(joined) <= budget:
                        out = _one(
                            reduce_system,
                            "Estos son resúmenes parciales y EN ORDEN de un mismo documento. "
                            f"Redacta un único resumen global:\n\n{joined}",
                            max_words,
                        )
                        text = out or ""
                        break
                    # Ni los parciales caben: se reducen por grupos y se repite.
                    grouped: list[str] = []
                    for group in _chunk_text(joined, budget):
                        out = _one(reduce_system, build_user(group.strip()), partial_words)
                        if out is None:
                            break
                        grouped.append(out)
                    if failed is not None:
                        break
                    summaries = grouped
                else:
                    text = "\n\n".join(summaries)
    finally:
        _inflight_end(entry_id)

    ok = failed is None
    if not ok:
        text, error, finish_reason = failed.text, failed.error, failed.finish_reason
    else:
        error, finish_reason = None, "stop"

    _log_event(
        tool=tool,
        model=model,
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
        truncated_out=False,
        raw_len=raw_len,
        path=path if source == "path" else None,
        chunks=calls,
    )
    if source == "path" and ok and config.FEEDBACK_ENABLED:
        text += _savings_feedback(len(content), tokens_in, "chars", True)
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


def _guard(formato: str, max_words: int | None = None) -> str:
    limite = f" Máximo {max_words} palabras." if max_words else ""
    return (
        "Responde directo desde el input. NO uses herramientas, NO busques en internet. "
        f"Output EXACTO: {formato}.{limite} Nada fuera del formato."
    )


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


# --- Tools ------------------------------------------------------------------
@mcp.tool(annotations=_anotaciones("Resumir texto o archivo"))
def local_summarize(
    text: str | None = None,
    path: str | None = None,
    max_words: int = 150,
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
    """
    probe = path and Path(path).is_file()
    probe_len = Path(path).stat().st_size if probe else len(text or "")
    model = config.MODEL_LONG if probe_len > config.LONG_INPUT_CHARS else config.MODEL_MECHANICAL
    content, truncated_in, raw_len = _read_input(text, path, _NO_TRUNCATE)
    system = _guard("un resumen en prosa clara", max_words)

    def _build(piece: str) -> str:
        return f"Resume el siguiente contenido:\n\n{piece}"

    if len(content) > config.max_chars_for(model):
        # No cabe: se resume por partes y luego se resumen los resúmenes. Antes esto se
        # truncaba, o sea que se resumía el principio y el resto se ignoraba.
        return _chat_map_reduce(
            model,
            system,
            content,
            _build,
            tool="local_summarize",
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
        max_tokens=int(max_words * 2) + 64,
        tool="local_summarize",
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_anotaciones("Clasificar en una etiqueta"))
def local_classify(text: str, labels: list[str]) -> str:
    """Clasifica un texto en UNA de las etiquetas dadas, con un modelo local.

    Devuelve exactamente una etiqueta de la lista, sin texto adicional.

    Args:
        text: Texto a clasificar.
        labels: Lista de etiquetas candidatas.
    """
    etiquetas = ", ".join(labels)
    system = _guard(f"exactamente una de estas etiquetas: [{etiquetas}]", max_words=5)
    user = f"Clasifica este texto:\n\n{text}"
    return _chat(
        config.MODEL_MECHANICAL,
        system,
        user,
        max_tokens=16,
        temperature=0.0,
        tool="local_classify",
        chars_in=len(text),
        source="inline",
    )


@mcp.tool(annotations=_anotaciones("Extraer campos como JSON"))
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
    model = config.MODEL_LONG if probe_len > config.LONG_INPUT_CHARS else config.MODEL_MECHANICAL
    content, truncated_in, raw_len = _read_input(text, path, config.max_chars_for(model))
    claves = ", ".join(f'"{f}"' for f in fields)
    system = _guard(f"un objeto JSON válido con exactamente estas claves: {{{claves}}}")
    user = f"Extrae los campos del siguiente contenido:\n\n{content}"
    use_schema = config.JSON_SCHEMA_MODE != "off"
    result = _strip_fences(
        _chat(
            model,
            system,
            user,
            max_tokens=512,
            temperature=0.0,
            tool="local_extract",
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
        datos = json.loads(result)
    except json.JSONDecodeError:
        # El modelo devolvió algo que no es JSON, o el backend falló y `result` trae el aviso de
        # error. Degradar con la carga cruda es mejor que lanzar: quien llama ve qué pasó en vez
        # de recibir una excepción de protocolo.
        return {"_local_delegate": {"error": "respuesta no parseable como JSON", "crudo": result}}
    if not isinstance(datos, dict):
        return {"_local_delegate": {"error": "la respuesta no es un objeto JSON", "crudo": result}}

    meta: dict = {}
    if truncated_in:
        meta["truncado"] = True
        meta["aviso"] = f"entrada truncada — procesados {len(content)} de {raw_len} chars"
    if path and config.FEEDBACK_ENABLED:
        meta["leido_server_side"] = {
            "chars": len(content),
            "tokens_aprox": len(content) // config.CHARS_PER_TOKEN,
        }
    if meta:
        datos["_local_delegate"] = meta
    return datos


@mcp.tool(annotations=_anotaciones("Generar código boilerplate"))
def local_boilerplate(spec: str, language: str) -> str:
    """Genera código boilerplate a partir de una especificación, con un modelo local de código.

    Devuelve solo el código, sin explicaciones ni fences markdown.

    Args:
        spec: Descripción de lo que debe generar el código.
        language: Lenguaje de programación (p. ej. 'python', 'typescript').
    """
    system = _guard(f"solo código {language} válido, sin explicaciones ni ```")
    user = f"Genera {language} para: {spec}"
    return _strip_fences(
        _chat(
            config.MODEL_CODE,
            system,
            user,
            max_tokens=1536,
            temperature=0.1,
            tool="local_boilerplate",
            chars_in=len(spec),
            source="inline",
        )
    )


@mcp.tool(annotations=_anotaciones("Delegar una tarea genérica"))
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
    if chosen not in config.ALLOWED_MODELS:
        return f"[local-delegate error] modelo inválido '{chosen}'. Válidos: {sorted(config.ALLOWED_MODELS)}"
    if chunk not in {"auto", "on", "off"}:
        return f"[local-delegate error] chunk inválido: '{chunk}'. Válidos: 'auto', 'on', 'off'."
    system = _guard(output_format)
    if chunk == "on" or (chunk == "auto" and len(input) > config.CHUNK_CHARS):
        return _chat_chunked(
            chosen,
            system,
            input,
            lambda piece: f"{task}\n\nInput:\n{piece}",
            tool="local_delegate",
            source="inline",
        )
    return _chat(
        chosen,
        system,
        f"{task}\n\nInput:\n{input}",
        max_tokens=config.CHUNK_MAX_TOKENS,
        tool="local_delegate",
        chars_in=len(input),
        source="inline",
    )


@mcp.tool(annotations=_anotaciones("Resumir salida de lint o tests"))
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
    model = config.MODEL_LONG if probe_len > config.LONG_INPUT_CHARS else config.MODEL_MECHANICAL
    content, truncated_in, raw_len = _read_input(text, path, _NO_TRUNCATE)
    system = _guard(
        "un resumen de los problemas agrupados por archivo, con el conteo por tipo de "
        "error/regla y los más relevantes primero",
        max_words,
    )

    def _build(piece: str) -> str:
        return f"Resume la siguiente salida de linter/tests:\n\n{piece}"

    if len(content) > config.max_chars_for(model):
        # Un log de CI es justo el caso donde truncar duele: los errores interesantes suelen
        # estar al final, y era exactamente lo que se descartaba.
        return _chat_map_reduce(
            model,
            system,
            content,
            _build,
            tool="local_lint_summary",
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
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_anotaciones("Redactar mensaje de commit"))
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
    content, truncated_in, raw_len = _read_input(
        diff, path, config.max_chars_for(config.MODEL_CODE)
    )
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
    system = _guard(fmt)
    user = f"Escribe el mensaje de commit para este diff:\n\n{content}"
    result = _chat(
        config.MODEL_CODE,
        system,
        user,
        max_tokens=256,
        temperature=0.2,
        tool="local_commit_msg",
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_anotaciones("Traducir texto o archivo"))
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
    model = config.MODEL_LONG if probe_len > config.LONG_INPUT_CHARS else config.MODEL_MECHANICAL
    content, truncated_in, raw_len = _read_input(text, path, config.max_chars_for(model))
    system = _guard(
        f"la traducción fiel al {target_lang}, conservando el formato y sin comentarios"
    )
    result = _chat_chunked(
        model,
        system,
        content,
        lambda piece: f"Traduce al {target_lang} el siguiente texto:\n\n{piece}",
        tool="local_translate",
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_anotaciones("Explicar código"))
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
    content, truncated_in, raw_len = _read_input(
        code, path, config.max_chars_for(config.MODEL_CODE)
    )
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
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool(annotations=_anotaciones("Describir una imagen"))
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
        chars_in=raw_len,
        source="path",
        raw_len=raw_len,
        path=path,
        feedback_label="bytes imagen",
        feedback_char_estimate=False,
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
    cfg_path = os.environ.get("LLAMASWAP_CONFIG")
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


def _models_with_status() -> tuple[bool, list[dict]]:
    """(backend_up, [{"id","status"}]) desde GET /v1/models; status None si el backend no lo da."""
    try:
        with httpx2.Client(timeout=2.0) as c:
            r = c.get(f"{config.BASE_URL}/models", headers=config.auth_headers())
            r.raise_for_status()
            data = r.json().get("data", [])
    except (httpx2.HTTPError, ValueError):
        return False, []
    models = [
        {"id": m.get("id", "?"), "status": _model_status_value(m)}
        for m in data
        if isinstance(m, dict)
    ]
    models.sort(key=lambda x: x["id"])
    return True, models


def _llamaswap_running() -> str | None:
    """Modelos montados vía GET {base sin /v1}/running de llama-swap (best-effort)."""
    base = config.BASE_URL.removesuffix("/v1")
    try:
        with httpx2.Client(timeout=1.0) as c:
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


@mcp.tool(annotations=_anotaciones("Diagnóstico del backend local"))
def local_status() -> str:
    """Diagnóstico de solo lectura del backend local y el catálogo de modelos.

    Úsala para saber qué modelos locales hay disponibles y verificar que el backend está vivo
    antes de delegar en masa, o para diagnosticar por qué una tool local_* falló.
    """
    lines: list[str] = [f"local-delegate v{_get_version()}", ""]

    backend_up, models = _models_with_status()
    origin = "local (esta máquina)" if config.backend_origin() == "local" else "REMOTO"
    lines.append(f"Backend: {config.BASE_URL} — {'arriba' if backend_up else 'CAÍDO'}")
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
        ("fast", config.MODEL_FAST),
    ):
        lines.append(f"  {role}: {model} (max_chars={config.max_chars_for(model)})")
    lines.append(f"  vision: {config.MODEL_VISION} (max_image_mb={config.MAX_IMAGE_MB})")
    lines.append(f"  concurrencia máxima del proceso: {config.MAX_CONCURRENT_REQUESTS}")

    current_log = _current_log_path()
    n_events = 0
    backend_calls = 0
    saved_tokens = 0
    if current_log.is_file():
        with current_log.open(encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    rec = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                n_events += 1
                # Misma contabilidad que el dashboard: si aquí se sumara `chars_in // 4` a mano,
                # esta tool y el panel darían números distintos del MISMO log.
                acc = _accounting(rec)
                backend_calls += acc["backend_calls"]
                saved_tokens += acc["saved"]
    lines.append("")
    lines.append(f"Log (mes actual): {current_log}")
    lines.append(
        f"  eventos: {n_events} ({backend_calls} llamadas al backend) — "
        f"contexto ahorrado acumulado: ~{saved_tokens} tokens"
    )

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

    running = _llamaswap_running()
    if running:
        lines.append(f"llama-swap /running: {running}")

    groups = _llamaswap_groups()
    if groups:
        lines.append(f"llama-swap groups activos (LLAMASWAP_CONFIG): {groups}")

    return "\n".join(lines)


_CLI_COMMANDS = {
    "benchmark",
    "check-llamaswap",
    "init-llamaswap",
    "doctor",
    "serve",
    "install",
    "uninstall",
}  # subcomandos explícitos, ver cli.py


def main() -> None:
    """Punto de entrada del MCP stdio (usado por [project.scripts] local-delegate).

    Sin argumentos: arranca el servidor MCP stdio (comportamiento de siempre, usado por
    cualquier host MCP). Con un subcomando conocido (p. ej. ``local-delegate
    check-llamaswap ...``) delega a los subcomandos de ``cli.py`` y termina — nunca llega a
    arrancar el servidor MCP stdio en ese caso. Solo los comandos específicos de configuración
    de llama-swap requieren el extra ``[llamaswap]``.
    """
    if len(sys.argv) > 1 and sys.argv[1] in _CLI_COMMANDS:
        from . import cli

        sys.exit(cli.run(sys.argv[1:]))

    # Auto-arranque del backend solo si el usuario lo pidió explícitamente (opt-in).
    if config.AUTOSTART:
        autostart.ensure_backend(wait=0)
    # Web de métricas embebida en un hilo daemon: vive y muere con este proceso MCP.
    # Si el puerto ya está ocupado (otra instancia de Claude), run_in_thread devuelve None.
    if config.WEB_ENABLED:
        try:
            from .web import metrics

            metrics.run_in_thread(host=config.WEB_HOST, port=config.WEB_PORT)
        except Exception:
            pass  # la web nunca debe impedir que arranque el MCP
    mcp.run()


if __name__ == "__main__":
    main()
