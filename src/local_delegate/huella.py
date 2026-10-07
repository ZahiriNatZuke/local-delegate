"""La huella de un modelo cargado y el unico lector de `cmd` del paquete (REQ-010).

Una celda de la matriz de afinidad solo vale para el modelo EXACTO que se midio: otro `-ncmoe`
bajo el mismo id, otro GGUF en el rol por variable de entorno o un prompt de sistema cambiado dan
otro modelo en la practica aunque el nombre sea el mismo. La huella junta lo que lo distingue:

- la ruta del GGUF (`-m` / `--model`) y su tamano en disco;
- los flags que cambian el modelo cargado: `-ncmoe` / `--n-cpu-moe`, `-c` / `--ctx-size`, los tipos
  de cache (`-ctk` / `-ctv` y sus formas largas), todo `--reasoning*` y `--mmproj`;
- el `sha256` del prompt de sistema de la tool.

`flags_del_cmd` es el unico parser de `cmd` del paquete: lo usan la tanda de la evaluacion, la
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
_FORMAS: dict[str, tuple[str, ...]] = {
    "modelo": ("-m", "--model"),
    "n_cpu_moe": ("-ncmoe", "--n-cpu-moe"),
    "ctx_size": ("-c", "--ctx-size"),
    "cache_type_k": ("-ctk", "--cache-type-k"),
    "cache_type_v": ("-ctv", "--cache-type-v"),
    "mmproj": ("-mm", "--mmproj"),
}
_ENTEROS = frozenset({"n_cpu_moe", "ctx_size"})
# Un valor que empieza por «-» es otro flag solo si sigue una letra o otro guion: «-1» es un valor.
_ES_FLAG = re.compile(r"^-(?:-|[A-Za-z])")


def _tokens(cmd: str | Sequence[str]) -> list[str]:
    """Parte el `cmd` por espacios, respetando comillas simples y dobles.

    Sin escapes a proposito: `shlex` en modo POSIX se come las barras invertidas de una ruta de
    Windows (`D:\\modelos\\x.gguf` saldria `D:modelosx.gguf`). Los saltos de linea del YAML plegado
    cuentan como espacio.
    """
    if not isinstance(cmd, str):
        return [str(parte) for parte in cmd]
    tokens: list[str] = []
    actual: list[str] = []
    comilla: str | None = None
    hay_token = False
    for caracter in cmd:
        if comilla is not None:
            if caracter == comilla:
                comilla = None
            else:
                actual.append(caracter)
        elif caracter in "\"'":
            comilla = caracter
            hay_token = True
        elif caracter.isspace():
            if actual or hay_token:
                tokens.append("".join(actual))
            actual, hay_token = [], False
        else:
            actual.append(caracter)
            hay_token = True
    if actual or hay_token:
        tokens.append("".join(actual))
    return tokens


def _valores_por_flag(tokens: Sequence[str]) -> dict[str, str | None]:
    """`flag -> valor` (el ultimo gana, como en llama-server). Sin valor, `None`."""
    valores: dict[str, str | None] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not _ES_FLAG.match(token):
            i += 1
            continue
        nombre, igual, valor = token.partition("=")
        if igual:
            valores[nombre] = valor
            i += 1
            continue
        if i + 1 < len(tokens) and not _ES_FLAG.match(tokens[i + 1]):
            valores[nombre] = tokens[i + 1]
            i += 2
        else:
            valores[nombre] = None
            i += 1
    return valores


def _entero_o_texto(valor: str) -> int | str:
    try:
        return int(valor)
    except ValueError:
        return valor


def flags_del_cmd(cmd: str | Sequence[str]) -> dict[str, Any]:
    """Los flags de REQ-010 y la ruta del modelo. Todas las claves salen siempre (`None` si falta).

    Claves fijas: `modelo`, `n_cpu_moe`, `ctx_size`, `cache_type_k`, `cache_type_v`, `mmproj`.
    Ademas, `reasoning` y cualquier otro `--reasoning-*` presente, con el nombre del flag sin los
    guiones iniciales y con `_` (`--reasoning-budget` -> `reasoning_budget`).
    """
    valores = _valores_por_flag(_tokens(cmd))
    salida: dict[str, Any] = {}
    for clave, formas in _FORMAS.items():
        valor = next((valores[f] for f in formas if valores.get(f) is not None), None)
        salida[clave] = _entero_o_texto(valor) if valor is not None and clave in _ENTEROS else valor
    salida["reasoning"] = None
    for flag, valor in valores.items():
        if flag.startswith("--reasoning"):
            salida[flag[2:].replace("-", "_")] = valor
    return salida


def _tamano(ruta: str | None) -> int | None:
    if not ruta:
        return None
    try:
        return Path(ruta).stat().st_size
    except OSError:
        return None


def huella(modelo_cfg: Mapping[str, Any], prompt_sistema: str) -> dict[str, Any]:
    """La huella de un modelo de la config de llama-swap (su entrada, con `cmd`) y de una tool."""
    flags = flags_del_cmd(modelo_cfg.get("cmd") or "")
    ruta = flags.pop("modelo")
    return {
        "ruta": ruta,
        "tamano_bytes": _tamano(ruta),
        "flags": flags,
        "prompt_sha256": hashlib.sha256(prompt_sistema.encode("utf-8")).hexdigest(),
    }
