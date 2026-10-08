"""La huella de un modelo cargado y el unico lector de `cmd` del paquete (REQ-010).

Una celda de la matriz de afinidad solo vale para el modelo EXACTO que se midio: otro `-ncmoe`
bajo el mismo id, otro GGUF en el rol por variable de entorno o un prompt de sistema cambiado dan
otro modelo en la practica aunque el nombre sea el mismo. La huella junta lo que lo distingue:

- la ruta del GGUF (`-m` / `--model`) y su tamano en disco;
- los flags que cambian el modelo cargado: `-ncmoe` / `--n-cpu-moe`, `-c` / `--ctx-size`, los tipos
  de cache (`-ctk` / `-ctv` y sus formas largas), todo `--reasoning*` y `--mmproj`;
- el `sha256` del prompt de sistema de la tool.

`cmd_flags` es el unico parser de `cmd` del paquete: lo usan la tanda de la evaluacion, la
topologia (para `--mmproj`), el estimador de VRAM y la matriz. Lee el `cmd` tal como queda en la
config de llama-swap, plegado en varias lineas, con las rutas de Windows (sin interpretar la barra
invertida) y con las dos formas de cada flag, la corta y la larga: la config real de hoy usa
`-ncmoe`, y un lector que solo conociera `--n-cpu-moe` veria `None` donde hay un 12.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Cada clave de la salida, con todas las formas con que llega al `cmd`.
_SHAPES: dict[str, tuple[str, ...]] = {
    "modelo": ("-m", "--model"),
    "n_cpu_moe": ("-ncmoe", "--n-cpu-moe"),
    "ctx_size": ("-c", "--ctx-size"),
    "cache_type_k": ("-ctk", "--cache-type-k"),
    "cache_type_v": ("-ctv", "--cache-type-v"),
    "mmproj": ("-mm", "--mmproj"),
}
_INTEGERS = frozenset({"n_cpu_moe", "ctx_size"})
# Un valor que empieza por «-» es otro flag solo si sigue una letra o otro guion: «-1» es un valor.
_IS_FLAG = re.compile(r"^-(?:-|[A-Za-z])")


def _tokens(cmd: str | Sequence[str]) -> list[str]:
    """Parte el `cmd` por espacios, respetando comillas simples y dobles.

    Sin escapes a proposito: `shlex` en modo POSIX se come las barras invertidas de una ruta de
    Windows (`D:\\modelos\\x.gguf` saldria `D:modelosx.gguf`). Los saltos de linea del YAML plegado
    cuentan como espacio.
    """
    if not isinstance(cmd, str):
        return [str(part) for part in cmd]
    tokens: list[str] = []
    actual: list[str] = []
    quote: str | None = None
    has_token = False
    for char in cmd:
        if quote is not None:
            if char == quote:
                quote = None
            else:
                actual.append(char)
        elif char in "\"'":
            quote = char
            has_token = True
        elif char.isspace():
            if actual or has_token:
                tokens.append("".join(actual))
            actual, has_token = [], False
        else:
            actual.append(char)
            has_token = True
    if actual or has_token:
        tokens.append("".join(actual))
    return tokens


def _values_by_flag(tokens: Sequence[str]) -> dict[str, str | None]:
    """`flag -> valor` (el ultimo gana, como en llama-server). Sin valor, `None`."""
    values: dict[str, str | None] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not _IS_FLAG.match(token):
            i += 1
            continue
        name, same, value = token.partition("=")
        if same:
            values[name] = value
            i += 1
            continue
        if i + 1 < len(tokens) and not _IS_FLAG.match(tokens[i + 1]):
            values[name] = tokens[i + 1]
            i += 2
        else:
            values[name] = None
            i += 1
    return values


def _int_or_text(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def cmd_flags(cmd: str | Sequence[str]) -> dict[str, Any]:
    """Los flags de REQ-010 y la ruta del modelo. Todas las claves salen siempre (`None` si falta).

    Claves fijas: `modelo`, `n_cpu_moe`, `ctx_size`, `cache_type_k`, `cache_type_v`, `mmproj`.
    Ademas, `reasoning` y cualquier otro `--reasoning-*` presente, con el nombre del flag sin los
    guiones iniciales y con `_` (`--reasoning-budget` -> `reasoning_budget`).
    """
    values = _values_by_flag(_tokens(cmd))
    output: dict[str, Any] = {}
    for key, shapes in _SHAPES.items():
        value = next((values[f] for f in shapes if values.get(f) is not None), None)
        output[key] = _int_or_text(value) if value is not None and key in _INTEGERS else value
    output["reasoning"] = None
    for flag, value in values.items():
        if flag.startswith("--reasoning"):
            output[flag[2:].replace("-", "_")] = value
    return output


def _size(path: str | None) -> int | None:
    if not path:
        return None
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def footprint(model_cfg: Mapping[str, Any], system_prompt: str) -> dict[str, Any]:
    """La huella de un modelo de la config de llama-swap (su entrada, con `cmd`) y de una tool."""
    flags = cmd_flags(model_cfg.get("cmd") or "")
    path = flags.pop("modelo")
    return {
        "ruta": path,
        "tamano_bytes": _size(path),
        "flags": flags,
        "prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
    }
