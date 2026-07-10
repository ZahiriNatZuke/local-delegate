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
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import httpx
from filelock import FileLock, Timeout
from mcp.server.fastmcp import FastMCP

from . import autostart, config

mcp = FastMCP("local-delegate")


# --- Versión del paquete (cacheada) ------------------------------------------
_PACKAGE_VERSION: str | None = None


def _get_version() -> str:
    global _PACKAGE_VERSION
    if _PACKAGE_VERSION is None:
        try:
            _PACKAGE_VERSION = _pkg_version("local-delegate-mcp")
        except PackageNotFoundError:
            _PACKAGE_VERSION = "0.0.0"
    return _PACKAGE_VERSION


# --- Cliente httpx module-level (keep-alive entre delegaciones) -------------
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(timeout=config.HTTP_TIMEOUT)
    return _client


# --- Delegaciones en curso (visibilidad; solo dentro de este proceso) -------
_inflight_lock = threading.Lock()
_inflight: dict[int, dict] = {}
_inflight_next_id = 0


def _inflight_start(*, tool: str, model: str, source: str, chars_in: int) -> int:
    global _inflight_next_id
    with _inflight_lock:
        _inflight_next_id += 1
        entry_id = _inflight_next_id
        _inflight[entry_id] = {
            "tool": tool,
            "model": model,
            "source": source,
            "chars_in": chars_in,
            "started_at": time.time(),
        }
    return entry_id


def _inflight_end(entry_id: int) -> None:
    with _inflight_lock:
        _inflight.pop(entry_id, None)


def inflight_snapshot() -> list[dict]:
    """Copia de las delegaciones en curso, con `elapsed_s`. Usada por la web de métricas."""
    now = time.time()
    with _inflight_lock:
        return [
            {
                "id": entry_id,
                "tool": v["tool"],
                "model": v["model"],
                "source": v["source"],
                "chars_in": v["chars_in"],
                "elapsed_s": round(now - v["started_at"], 1),
            }
            for entry_id, v in _inflight.items()
        ]


# --- Helpers ----------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
        with lock:
            with log_path.open("a", encoding="utf-8") as f:
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
            "v": _get_version(),
        }
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
    headers = {"Authorization": f"Bearer {config.API_KEY}"} if config.API_KEY else {}
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
        except httpx.ConnectError:
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
        except httpx.HTTPStatusError as e:
            return ChatResult(
                text=(
                    f"[local-delegate error] {model} respondió {e.response.status_code}: "
                    f"{e.response.text[:300]}"
                ),
                ok=False,
                error=f"http_{e.response.status_code}",
            )
        except httpx.HTTPError as e:
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
) -> str:
    """POST al endpoint. Devuelve solo texto y registra la llamada en USAGE_LOG.

    `user` acepta un `str` (texto->texto) o una lista de bloques de contenido
    OpenAI-compatible (p. ej. `[{"type":"text",...},{"type":"image_url",...}]` para
    local_describe_image).
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

    entry_id = _inflight_start(tool=tool, model=model, source=source, chars_in=chars_in)
    try:
        t0 = time.monotonic()
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
        latency_ms = int((time.monotonic() - t0) * 1000)
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
    )
    if source == "path" and result.ok and config.FEEDBACK_ENABLED:
        tokens = result.tokens_in
        if tokens is None and feedback_char_estimate:
            tokens = chars_in // config.CHARS_PER_TOKEN
        if tokens is not None:
            text += (
                f"\n\n(leído server-side: {chars_in:,} {feedback_label} ≈ {tokens:,} tokens "
                "que no entraron a tu contexto)"
            )
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
@mcp.tool()
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
    content, truncated_in, raw_len = _read_input(text, path, config.max_chars_for(model))
    system = _guard("un resumen en prosa clara", max_words)
    user = f"Resume el siguiente contenido:\n\n{content}"
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


@mcp.tool()
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


@mcp.tool()
def local_extract(
    fields: list[str],
    text: str | None = None,
    path: str | None = None,
) -> str:
    """PREFIERE esta tool en vez de leer el archivo con Read cuando el archivo es grande
    (>200 líneas / >10 KB) y solo necesitas campos estructurados, no el contenido literal.

    Extrae campos estructurados de un texto/archivo como JSON, con un modelo local.

    Pasa 'path' para leer el archivo server-side (no gasta contexto de Claude) o 'text'.
    Devuelve un objeto JSON con exactamente las claves pedidas. Enruta al modelo mecánico
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
        )
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool()
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


@mcp.tool()
def local_delegate(
    task: str,
    input: str,
    output_format: str,
    model: str | None = None,
) -> str:
    """Tool genérica de escape: delega una tarea texto->texto a un modelo local.

    Úsala cuando ninguna tool específica encaje. Arma el prompt con guardrails y devuelve texto.

    Args:
        task: Instrucción de la tarea (una frase con formato de salida explícito).
        input: Contenido sobre el que operar.
        output_format: Formato exacto de salida esperado.
        model: Modelo a usar; uno de los ids configurados en el catálogo. Por defecto el mecánico.
    """
    chosen = model or config.MODEL_MECHANICAL
    if chosen not in config.ALLOWED_MODELS:
        return f"[local-delegate error] modelo inválido '{chosen}'. Válidos: {sorted(config.ALLOWED_MODELS)}"
    system = _guard(output_format)
    user = f"{task}\n\nInput:\n{input}"
    return _chat(
        chosen,
        system,
        user,
        max_tokens=1024,
        tool="local_delegate",
        chars_in=len(input),
        source="inline",
    )


@mcp.tool()
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
    content, truncated_in, raw_len = _read_input(text, path, config.max_chars_for(model))
    system = _guard(
        "un resumen de los problemas agrupados por archivo, con el conteo por tipo de "
        "error/regla y los más relevantes primero",
        max_words,
    )
    user = f"Resume la siguiente salida de linter/tests:\n\n{content}"
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


@mcp.tool()
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


@mcp.tool()
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
    user = f"Traduce al {target_lang} el siguiente texto:\n\n{content}"
    result = _chat(
        model,
        system,
        user,
        max_tokens=min(len(content) // 2 + 128, 2048),
        tool="local_translate",
        chars_in=len(content),
        source="path" if path else "inline",
        truncated_in=truncated_in,
        raw_len=raw_len,
        path=path,
    )
    return _truncation_prefix(content, truncated_in, raw_len) + result


@mcp.tool()
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


@mcp.tool()
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


def _llamaswap_running() -> str | None:
    """Modelos montados vía GET {base sin /v1}/running de llama-swap (best-effort)."""
    base = config.BASE_URL[: -len("/v1")] if config.BASE_URL.endswith("/v1") else config.BASE_URL
    try:
        with httpx.Client(timeout=1.0) as c:
            r = c.get(f"{base}/running")
            if not r.is_success:
                return None
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    entries = data.get("running") if isinstance(data, dict) else None
    if not entries:
        return "ningún modelo montado"
    parts = [
        f"{e.get('model', '?')} ({e.get('state', '?')})" for e in entries if isinstance(e, dict)
    ]
    return ", ".join(parts) if parts else "ningún modelo montado"


@mcp.tool()
def local_status() -> str:
    """Diagnóstico de solo lectura del backend local y el catálogo de modelos.

    Úsala para saber qué modelos locales hay disponibles y verificar que el backend está vivo
    antes de delegar en masa, o para diagnosticar por qué una tool local_* falló.
    """
    lines: list[str] = [f"local-delegate v{_get_version()}", ""]

    backend_up = False
    model_ids: list[str] = []
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{config.BASE_URL}/models")
            r.raise_for_status()
            model_ids = sorted(m.get("id", "?") for m in r.json().get("data", []))
            backend_up = True
    except (httpx.HTTPError, ValueError):
        backend_up = False
    lines.append(f"Backend: {config.BASE_URL} — {'arriba' if backend_up else 'CAÍDO'}")
    if backend_up:
        lines.append(f"  modelos expuestos: {', '.join(model_ids) if model_ids else '(ninguno)'}")

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

    current_log = _current_log_path()
    n_events = 0
    saved_chars = 0
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
                if rec.get("source") == "path":
                    saved_chars += int(rec.get("chars_in", 0) or 0)
    lines.append("")
    lines.append(f"Log (mes actual): {current_log}")
    lines.append(
        f"  eventos: {n_events} — contexto ahorrado acumulado: "
        f"~{saved_chars // config.CHARS_PER_TOKEN} tokens"
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

    running = _llamaswap_running()
    if running:
        lines.append(f"llama-swap /running: {running}")

    groups = _llamaswap_groups()
    if groups:
        lines.append(f"llama-swap groups activos (LLAMASWAP_CONFIG): {groups}")

    return "\n".join(lines)


_CLI_COMMANDS = {"check-llamaswap", "init-llamaswap"}  # subcomandos opt-in, ver cli.py


def main() -> None:
    """Punto de entrada del MCP stdio (usado por [project.scripts] local-delegate).

    Sin argumentos: arranca el servidor MCP stdio (comportamiento de siempre, usado por
    cualquier host MCP). Con un subcomando conocido (p. ej. ``local-delegate
    check-llamaswap ...``) delega a los CLIs opt-in de ``cli.py`` (requieren el extra
    ``[llamaswap]``) y termina — nunca llega a arrancar el servidor MCP en ese caso.
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
