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

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

from . import autostart, config

mcp = FastMCP("local-delegate")


# --- Helpers ----------------------------------------------------------------
def _read_input(text: str | None, path: str | None, max_chars: int) -> str:
    """Devuelve el contenido a procesar. Si viene 'path', lo lee server-side."""
    if path:
        p = Path(path)
        if not p.is_file():
            raise ValueError(f"No existe el archivo: {path}")
        content = p.read_text(encoding="utf-8", errors="replace")
    elif text is not None:
        content = text
    else:
        raise ValueError("Debes proporcionar 'text' o 'path'.")
    if len(content) > max_chars:
        content = content[:max_chars] + "\n[...contenido truncado...]"
    return content


def _log_event(
    *, tool: str, model: str, source: str, chars_in: int, chars_out: int, latency_ms: int, ok: bool
) -> None:
    """Escribe una línea JSONL en USAGE_LOG. Nunca debe romper una tool."""
    try:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "model": model,
            "source": source,  # "path" = leído server-side (no entró al contexto de Claude)
            "chars_in": int(chars_in),
            "chars_out": int(chars_out),
            "latency_ms": int(latency_ms),
            "ok": bool(ok),
        }
        config.USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with config.USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # el logging es best-effort; jamás propaga


def _post_chat(model: str, payload: dict) -> str:
    """POST al endpoint /chat/completions con reintento opcional si el backend está caído."""
    headers = {"Authorization": f"Bearer {config.API_KEY}"} if config.API_KEY else {}
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=config.HTTP_TIMEOUT) as client:
                r = client.post(
                    f"{config.BASE_URL}/chat/completions", json=payload, headers=headers
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except httpx.ConnectError:
            # El backend no está escuchando. Si el auto-arranque está activo, intenta
            # levantarlo (opt-in, específico de llama-swap) y reintenta una vez.
            if attempt == 1 and config.AUTOSTART and autostart.ensure_backend(wait=30):
                continue
            return (
                f"[local-delegate error] no se pudo conectar al endpoint ({config.BASE_URL}). "
                "¿Está corriendo tu backend OpenAI-compatible?"
            )
        except httpx.HTTPStatusError as e:
            return f"[local-delegate error] {model} respondió {e.response.status_code}: {e.response.text[:300]}"
        except httpx.HTTPError as e:
            return f"[local-delegate error] fallo de conexión al endpoint ({config.BASE_URL}): {e}"
        except (KeyError, IndexError, ValueError) as e:
            return f"[local-delegate error] respuesta inesperada de {model}: {e}"
    return f"[local-delegate error] no se pudo completar la petición a {model}."


def _chat(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float = 0.2,
    *,
    tool: str = "local_delegate",
    chars_in: int = 0,
    source: str = "inline",
) -> str:
    """POST al endpoint. Devuelve solo texto y registra la llamada en USAGE_LOG."""
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
    t0 = time.monotonic()
    result = _post_chat(model, payload)
    latency_ms = int((time.monotonic() - t0) * 1000)
    ok = not result.startswith("[local-delegate error]")
    _log_event(
        tool=tool,
        model=model,
        source=source,
        chars_in=chars_in,
        chars_out=len(result),
        latency_ms=latency_ms,
        ok=ok,
    )
    return result


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


def _guard(formato: str, max_words: int | None = None) -> str:
    limite = f" Máximo {max_words} palabras." if max_words else ""
    return (
        "Responde directo desde el input. NO uses herramientas, NO busques en internet. "
        f"Output EXACTO: {formato}.{limite} Nada fuera del formato."
    )


# --- Tools ------------------------------------------------------------------
@mcp.tool()
def local_summarize(
    text: str | None = None,
    path: str | None = None,
    max_words: int = 150,
) -> str:
    """Resume texto o el contenido de un archivo con un modelo local, sin gastar contexto de Claude.

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
    raw_len = Path(path).stat().st_size if probe else len(text or "")
    model = config.MODEL_LONG if raw_len > config.LONG_INPUT_CHARS else config.MODEL_MECHANICAL
    content = _read_input(text, path, config.max_chars_for(model))
    system = _guard("un resumen en prosa clara", max_words)
    user = f"Resume el siguiente contenido:\n\n{content}"
    return _chat(
        model,
        system,
        user,
        max_tokens=int(max_words * 2) + 64,
        tool="local_summarize",
        chars_in=len(content),
        source="path" if path else "inline",
    )


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
    """Extrae campos estructurados de un texto/archivo como JSON, con un modelo local.

    Pasa 'path' para leer el archivo server-side (no gasta contexto de Claude) o 'text'.
    Devuelve un objeto JSON con exactamente las claves pedidas.

    Args:
        fields: Nombres de los campos a extraer (claves del JSON).
        text: Texto fuente (usa esto o 'path').
        path: Ruta a un archivo fuente (leído server-side).
    """
    content = _read_input(text, path, config.max_chars_for(config.MODEL_MECHANICAL))
    claves = ", ".join(f'"{f}"' for f in fields)
    system = _guard(f"un objeto JSON válido con exactamente estas claves: {{{claves}}}")
    user = f"Extrae los campos del siguiente contenido:\n\n{content}"
    return _strip_fences(
        _chat(
            config.MODEL_MECHANICAL,
            system,
            user,
            max_tokens=512,
            temperature=0.0,
            tool="local_extract",
            chars_in=len(content),
            source="path" if path else "inline",
        )
    )


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
    """Resume salida de linters/tests/CI con un modelo local, sin gastar contexto de Claude.

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
    raw_len = Path(path).stat().st_size if probe else len(text or "")
    model = config.MODEL_LONG if raw_len > config.LONG_INPUT_CHARS else config.MODEL_MECHANICAL
    content = _read_input(text, path, config.max_chars_for(model))
    system = _guard(
        "un resumen de los problemas agrupados por archivo, con el conteo por tipo de "
        "error/regla y los más relevantes primero",
        max_words,
    )
    user = f"Resume la siguiente salida de linter/tests:\n\n{content}"
    return _chat(
        model,
        system,
        user,
        max_tokens=int(max_words * 2) + 96,
        tool="local_lint_summary",
        chars_in=len(content),
        source="path" if path else "inline",
    )


@mcp.tool()
def local_commit_msg(
    diff: str | None = None,
    path: str | None = None,
    style: str = "conventional",
) -> str:
    """Redacta un mensaje de commit a partir de un diff, con un modelo local de código.

    Pasa 'path' a un archivo de diff (p. ej. la salida de `git diff` volcada a fichero) y se lee
    server-side, de modo que el diff completo NO entra al contexto de Claude. Alternativamente
    pasa 'diff' como texto. Revisa SIEMPRE el mensaje antes de usarlo.

    Args:
        diff: El diff como texto (usa esto o 'path').
        path: Ruta a un archivo con el diff (leído server-side).
        style: 'conventional' (Conventional Commits) o 'plain'.
    """
    content = _read_input(diff, path, config.max_chars_for(config.MODEL_CODE))
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
    return _chat(
        config.MODEL_CODE,
        system,
        user,
        max_tokens=256,
        temperature=0.2,
        tool="local_commit_msg",
        chars_in=len(content),
        source="path" if path else "inline",
    )


@mcp.tool()
def local_translate(
    target_lang: str,
    text: str | None = None,
    path: str | None = None,
) -> str:
    """Traduce texto o el contenido de un archivo con un modelo local, sin gastar contexto de Claude.

    Pasa 'path' para leer el archivo server-side (el original no entra al contexto de Claude) o
    'text'. Conserva el formato del original y devuelve SOLO la traducción. Enruta al modelo
    mecánico (corto) o al de contexto largo (largo) automáticamente.

    Args:
        target_lang: Idioma destino (p. ej. 'español', 'inglés', 'francés').
        text: Texto a traducir (usa esto o 'path').
        path: Ruta a un archivo cuyo contenido se traduce (leído server-side).
    """
    probe = path and Path(path).is_file()
    raw_len = Path(path).stat().st_size if probe else len(text or "")
    model = config.MODEL_LONG if raw_len > config.LONG_INPUT_CHARS else config.MODEL_MECHANICAL
    content = _read_input(text, path, config.max_chars_for(model))
    system = _guard(
        f"la traducción fiel al {target_lang}, conservando el formato y sin comentarios"
    )
    user = f"Traduce al {target_lang} el siguiente texto:\n\n{content}"
    return _chat(
        model,
        system,
        user,
        max_tokens=min(len(content) // 2 + 128, 2048),
        tool="local_translate",
        chars_in=len(content),
        source="path" if path else "inline",
    )


@mcp.tool()
def local_explain_code(
    code: str | None = None,
    path: str | None = None,
    question: str | None = None,
) -> str:
    """Explica en prosa qué hace un fragmento/archivo de código, con un modelo local de código.

    Pasa 'path' para leer el archivo server-side (el código completo NO entra al contexto de
    Claude; solo vuelve la explicación) o 'code'. Opcionalmente enfoca la explicación con
    'question'. Revisa la explicación: la genera un modelo local.

    Args:
        code: Código a explicar (usa esto o 'path').
        path: Ruta a un archivo de código (leído server-side).
        question: Pregunta o foco concreto (opcional).
    """
    content = _read_input(code, path, config.max_chars_for(config.MODEL_CODE))
    extra = f" Enfócate en: {question}." if question else ""
    system = _guard(
        f"una explicación clara en prosa de qué hace el código y cómo.{extra}", max_words=250
    )
    user = f"Explica el siguiente código:\n\n{content}"
    return _chat(
        config.MODEL_CODE,
        system,
        user,
        max_tokens=700,
        tool="local_explain_code",
        chars_in=len(content),
        source="path" if path else "inline",
    )


def main() -> None:
    """Punto de entrada del MCP stdio (usado por [project.scripts] local-delegate)."""
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
