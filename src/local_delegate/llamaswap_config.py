"""llamaswap_config.py — generación y validación OPCIONAL de groups de llama-swap.

Capacidad opt-in del paquete (extra ``[llamaswap]``, dependencia ``pyyaml``). El paquete
NUNCA toca el config.yaml de llama-swap por sí solo: estas funciones solo se ejecutan si el
usuario invoca los CLIs ``local-delegate check-llamaswap`` / ``local-delegate init-llamaswap``
(ver ``cli.py``). El resto del MCP funciona exactamente igual sin este módulo ni el extra.

El estimador de VRAM es un GUARDRAIL conservador, no un simulador: cuando hay metadatos de
arquitectura en el propio GGUF (capas, cabezas KV, dimensión de cabeza) y un ``--ctx-size``
explícito en el ``cmd``, calcula el tamaño real del KV cache; si falta cualquiera de esas dos
cosas, cae a una estimación gruesa (``tamaño_archivo * 1.2``) y lo marca como tal en el reporte.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import huella

try:
    import yaml
except ImportError:  # pragma: no cover - depende del entorno de instalación
    yaml = None  # type: ignore[assignment]

_EXTRA_INSTALL_MSG = 'pip install "local-delegate-mcp[llamaswap]"'

# ¿Vale el estimador de VRAM (con `-ncmoe` y `--mmproj`) para decidir si cabe un residente
# (`llamaswap residencia --fijar`, REQ-031)? Solo si sus cuatro estimaciones quedan entre -3 % y
# +10 % de lo medido en F2 (insumos/llamaswap-grupos.md §2), con los `-ncmoe` MEDIDOS. Control del
# 2026-10-07 con los GGUF reales (solo cabecera), en MiB, estimado frente a medido:
#   gemma3-4b 3 581 / 3 270 (+9,5 %, pasa); gemma4-12b + mmproj 19 587 / 9 060 (+116,2 %);
#   gemma4-26b-a4b -ncmoe 12 45 280 / 10 534 (+329,8 %); qwen36-35b-a3b -ncmoe 20 11 559 / 10 120
#   (+14,2 %).
# Falla en tres. La resta de expertos da 4,03 y 6,95 GiB a la CPU; lo que se dispara es el KV cache
# (12 GiB en el 12B, 35 GiB en el 26B), que se calcula como si todas las capas tuvieran atención
# completa sobre todo el contexto. Hipótesis, sin medir: los Gemma usan ventana deslizante en la
# mayoría de capas. Por eso `--fijar` exige `--vram-modelo` para todos los modelos implicados.
ESTIMADOR_NCMOE_VALIDADO = False


def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError(_EXTRA_INSTALL_MSG)


# --- Parser de metadatos GGUF (solo header, nunca los tensores de pesos) ----------------

_GGUF_MAGIC = b"GGUF"

# tipo GGUF -> (formato struct, tamaño en bytes)
_SCALAR_FMT: dict[int, tuple[str, int]] = {
    0: ("B", 1),  # UINT8
    1: ("b", 1),  # INT8
    2: ("H", 2),  # UINT16
    3: ("h", 2),  # INT16
    4: ("I", 4),  # UINT32
    5: ("i", 4),  # INT32
    6: ("f", 4),  # FLOAT32
    7: ("?", 1),  # BOOL
    10: ("Q", 8),  # UINT64
    11: ("q", 8),  # INT64
    12: ("d", 8),  # FLOAT64
}
_STRING_TYPE = 8
_ARRAY_TYPE = 9

_ARCH_SUFFIXES = (
    "block_count",
    "attention.head_count",
    "attention.head_count_kv",
    "attention.key_length",
    "embedding_length",
)


def _read_gguf_string(f) -> str:
    (length,) = struct.unpack("<Q", f.read(8))
    return f.read(length).decode("utf-8", errors="replace")


def _read_gguf_value(f, vtype: int):
    if vtype == _STRING_TYPE:
        return _read_gguf_string(f)
    if vtype == _ARRAY_TYPE:
        (elem_type,) = struct.unpack("<I", f.read(4))
        (count,) = struct.unpack("<Q", f.read(8))
        if elem_type == _STRING_TYPE:
            for _ in range(count):
                _read_gguf_string(f)
        else:
            fmt, size = _SCALAR_FMT[elem_type]  # KeyError -> tipo no soportado, propaga
            f.read(size * count)
        return None  # los arrays no nos interesan para las claves de arquitectura
    fmt, size = _SCALAR_FMT[vtype]  # KeyError si es un tipo desconocido
    (value,) = struct.unpack("<" + fmt, f.read(size))
    return value


def read_gguf_arch_info(gguf_path: Path) -> dict[str, int] | None:
    """Lee el header de metadatos de un GGUF y devuelve n_layer/n_head_kv/head_dim.

    Nunca lee los tensores de pesos (el header de metadatos es del orden de KB, incluso en
    un GGUF de varios GB). Devuelve None si el archivo no es un GGUF válido, tiene un tipo de
    valor no soportado, o faltan campos imprescindibles (block_count / head_count / una forma
    de derivar head_dim) — en cualquiera de esos casos el llamador debe usar el fallback grueso.
    """
    try:
        with gguf_path.open("rb") as f:
            if f.read(4) != _GGUF_MAGIC:
                return None
            (version,) = struct.unpack("<I", f.read(4))
            if version < 2:
                return None
            f.read(8)  # tensor_count, no lo necesitamos
            (kv_count,) = struct.unpack("<Q", f.read(8))
            found: dict[str, object] = {}
            arch: str | None = None
            for _ in range(kv_count):
                key = _read_gguf_string(f)
                (vtype,) = struct.unpack("<I", f.read(4))
                value = _read_gguf_value(f, vtype)
                if key == "general.architecture":
                    arch = value if isinstance(value, str) else arch
                elif key.endswith(_ARCH_SUFFIXES):
                    found[key] = value
    except (OSError, struct.error, KeyError, UnicodeDecodeError):
        return None

    if not arch:
        return None
    block_count = found.get(f"{arch}.block_count")
    head_count = found.get(f"{arch}.attention.head_count")
    if block_count is None or not head_count:
        return None
    head_count_kv = found.get(f"{arch}.attention.head_count_kv") or head_count
    key_length = found.get(f"{arch}.attention.key_length")
    embedding_length = found.get(f"{arch}.embedding_length")
    if key_length:
        head_dim = key_length
    elif embedding_length:
        head_dim = int(embedding_length) // int(head_count)
    else:
        return None
    return {
        "n_layer": int(block_count),
        "n_head_kv": int(head_count_kv),
        "head_dim": int(head_dim),
    }


# --- Tabla de tensores del GGUF (para restar los expertos de `-ncmoe`) ---------------------
#
# Despues de los metadatos, el GGUF lista cada tensor: nombre, dimensiones, tipo y offset dentro de
# la seccion de datos. El tamano de cada tensor se saca como la diferencia entre offsets
# consecutivos (el ultimo, hasta el final del fichero), sin tabla de tipos: asi no hay que saber
# cuantos bytes ocupa cada cuantizacion, y el relleno de alineacion cae dentro del tensor anterior.
# Se lee solo la cabecera (unos MB en un GGUF con vocabulario grande), nunca los pesos.

_ALINEACION_POR_DEFECTO = 32
# `blk.<i>.ffn_*_exps.*`: los tensores de expertos que `-ncmoe N` deja en la CPU para `i < N`.
_TENSOR_DE_EXPERTOS = re.compile(r"^blk\.(\d+)\.ffn_[A-Za-z0-9_]*_exps\.")


def read_gguf_tensor_sizes(gguf_path: Path) -> dict[str, int] | None:
    """Bytes de cada tensor del GGUF, por nombre. `None` si la cabecera no se puede leer."""
    try:
        tamano_fichero = gguf_path.stat().st_size
        with gguf_path.open("rb") as f:
            if f.read(4) != _GGUF_MAGIC:
                return None
            (version,) = struct.unpack("<I", f.read(4))
            if version < 2:
                return None
            (tensor_count,) = struct.unpack("<Q", f.read(8))
            (kv_count,) = struct.unpack("<Q", f.read(8))
            alineacion = _ALINEACION_POR_DEFECTO
            for _ in range(kv_count):
                key = _read_gguf_string(f)
                (vtype,) = struct.unpack("<I", f.read(4))
                value = _read_gguf_value(f, vtype)
                if key == "general.alignment" and isinstance(value, int) and value > 0:
                    alineacion = value
            offsets: list[tuple[int, str]] = []
            for _ in range(tensor_count):
                nombre = _read_gguf_string(f)
                (n_dims,) = struct.unpack("<I", f.read(4))
                f.read(8 * n_dims)
                f.read(4)  # tipo: no hace falta, el tamano sale de los offsets
                (offset,) = struct.unpack("<Q", f.read(8))
                offsets.append((offset, nombre))
            fin_cabecera = f.tell()
    except (OSError, struct.error, KeyError, UnicodeDecodeError):
        return None
    inicio_datos = -(-fin_cabecera // alineacion) * alineacion
    offsets.sort()
    tamanos: dict[str, int] = {}
    for i, (offset, nombre) in enumerate(offsets):
        siguiente = offsets[i + 1][0] if i + 1 < len(offsets) else tamano_fichero - inicio_datos
        if siguiente < offset:
            return None
        tamanos[nombre] = siguiente - offset
    return tamanos


def bytes_de_expertos_en_cpu(tamanos: dict[str, int], n_cpu_moe: int) -> int:
    """Bytes de los tensores de expertos de las capas `i < n_cpu_moe` (los que no van a la GPU)."""
    total = 0
    for nombre, tamano in tamanos.items():
        capa = _TENSOR_DE_EXPERTOS.match(nombre)
        if capa and int(capa.group(1)) < n_cpu_moe:
            total += tamano
    return total


# --- Parser ligero de flags relevantes en el 'cmd' de una entrada models.<id> -----------

# bytes por elemento del KV cache según --cache-type-k/-v de llama-server (aproximado).
_CACHE_TYPE_BYTES: dict[str, float] = {
    "f32": 4.0,
    "f16": 2.0,
    "q8_0": 1.0625,
    "q4_0": 0.5625,
    "q4_1": 0.625,
    "q5_0": 0.6875,
    "q5_1": 0.75,
}
_DEFAULT_CACHE_BYTES = _CACHE_TYPE_BYTES["f16"]  # default real de llama-server sin el flag


def _parse_cmd_flags(cmd: str) -> dict[str, str]:
    """Tokeniza 'cmd' (ya plegado a una línea por PyYAML) y extrae los flags que importan."""
    tokens = cmd.split()
    wanted = {
        "--model": "model",
        "-m": "model",
        "--ctx-size": "ctx_size",
        "-c": "ctx_size",
        "--cache-type-k": "cache_type_k",
        "--cache-type-v": "cache_type_v",
    }
    flags: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        key = wanted.get(tokens[i])
        if key and i + 1 < len(tokens):
            flags[key] = tokens[i + 1]
            i += 2
        else:
            i += 1
    return flags


def parse_model_gguf_path(cmd: str) -> Path | None:
    """Ubica el .gguf del modelo (--model/-m) dentro del 'cmd' de una entrada models.<id>."""
    model = _parse_cmd_flags(cmd).get("model")
    return Path(model) if model else None


# --- Estimadores de VRAM y RAM -----------------------------------------------------------


@dataclass
class ResourceEstimate:
    model_id: str
    gb: float
    method: str  # "gguf-metadata" | "flat-fallback" | "weights-only" | "override" | "error"
    detail: str
    gguf_path: Path | None = None
    error: str | None = None
    # Bytes de expertos que `-ncmoe` deja en la CPU y que se restaron de los pesos (0 sin el flag).
    expertos_cpu_bytes: int = 0
    # Bytes del fichero de `--mmproj` que se sumaron (0 sin el flag).
    mmproj_bytes: int = 0


VramEstimate = ResourceEstimate  # alias retrocompatible (nombre histórico de F7.1-F7.7)


def estimate_model_vram(
    model_id: str, model_entry: dict, override_gb: float | None = None
) -> VramEstimate:
    """Estima la VRAM (GiB) que ocupa un modelo cargado.

    Guardrail conservador, no simulador: con metadatos de arquitectura del propio GGUF y un
    --ctx-size explícito calcula pesos + KV cache real; si falta cualquiera de las dos cosas,
    cae a 'tamaño_archivo * 1.2' y lo marca como estimación gruesa en el campo 'method'.
    """
    if override_gb is not None:
        return VramEstimate(
            model_id, override_gb, "override", f"{override_gb:.2f} GiB (forzado por el usuario)"
        )

    cmd = model_entry.get("cmd", "") if isinstance(model_entry, dict) else ""
    gguf_path = parse_model_gguf_path(cmd)
    if gguf_path is None:
        return VramEstimate(model_id, 0.0, "error", "", error="no se encontró --model/-m en 'cmd'")
    if not gguf_path.is_file():
        return VramEstimate(
            model_id,
            0.0,
            "error",
            "",
            gguf_path=gguf_path,
            error=f"archivo no encontrado: {gguf_path}",
        )

    flags = _parse_cmd_flags(cmd)
    # `-ncmoe` y `--mmproj` salen del parser unico de `cmd` (`huella.flags_del_cmd`), que conoce la
    # forma corta y la larga de cada flag.
    flags_huella = huella.flags_del_cmd(cmd)
    n_cpu_moe = flags_huella.get("n_cpu_moe")
    n_cpu_moe = n_cpu_moe if isinstance(n_cpu_moe, int) and n_cpu_moe > 0 else 0
    expertos = 0
    nota_moe = ""
    if n_cpu_moe:
        tamanos = read_gguf_tensor_sizes(gguf_path)
        if tamanos is None:
            nota_moe = f"; -ncmoe {n_cpu_moe} sin restar (tabla de tensores ilegible)"
        else:
            expertos = bytes_de_expertos_en_cpu(tamanos, n_cpu_moe)
            nota_moe = f"; -ncmoe {n_cpu_moe}: {expertos / 1024**3:.2f} GiB de expertos en CPU"
    mmproj_bytes = 0
    if flags_huella.get("mmproj"):
        mmproj = Path(flags_huella["mmproj"])
        if not mmproj.is_file():
            return VramEstimate(
                model_id,
                0.0,
                "error",
                "",
                gguf_path=gguf_path,
                error=f"mmproj no encontrado: {mmproj}",
            )
        mmproj_bytes = mmproj.stat().st_size
    mmproj_gb = mmproj_bytes / 1024**3
    nota_mm = f" + mmproj {mmproj_gb:.2f} GiB" if mmproj_bytes else ""
    size_gb = (gguf_path.stat().st_size - expertos) / 1024**3
    ctx = int(flags["ctx_size"]) if flags.get("ctx_size", "").isdigit() else None
    arch_info = read_gguf_arch_info(gguf_path) if ctx else None
    extra = {"expertos_cpu_bytes": expertos, "mmproj_bytes": mmproj_bytes}

    if arch_info and ctx:
        bytes_k = _CACHE_TYPE_BYTES.get(flags.get("cache_type_k", ""), _DEFAULT_CACHE_BYTES)
        bytes_v = _CACHE_TYPE_BYTES.get(flags.get("cache_type_v", ""), _DEFAULT_CACHE_BYTES)
        kv_gb = (
            arch_info["n_layer"]
            * arch_info["n_head_kv"]
            * arch_info["head_dim"]
            * ctx
            * (bytes_k + bytes_v)
        ) / 1024**3
        total = size_gb * 1.05 + kv_gb + mmproj_gb
        detail = (
            f"pesos {size_gb:.2f} GiB + KV {kv_gb:.2f} GiB{nota_mm} "
            f"(ctx={ctx}, capas={arch_info['n_layer']}, kv_heads={arch_info['n_head_kv']}, "
            f"cache_k={flags.get('cache_type_k', 'f16')}, cache_v={flags.get('cache_type_v', 'f16')}"
            f"{nota_moe})"
        )
        return VramEstimate(model_id, total, "gguf-metadata", detail, gguf_path=gguf_path, **extra)

    total = size_gb * 1.2 + mmproj_gb
    detail = (
        f"pesos {size_gb:.2f} GiB x1.2{nota_mm} "
        f"(estimación gruesa: sin metadatos GGUF o sin --ctx-size{nota_moe})"
    )
    return VramEstimate(model_id, total, "flat-fallback", detail, gguf_path=gguf_path, **extra)


def estimate_model_ram(
    model_id: str, model_entry: dict, override_gb: float | None = None
) -> ResourceEstimate:
    """Estima la RAM DE SISTEMA (no VRAM) que ocupa un modelo cargado.

    llama-server mapea el GGUF también en RAM (mmap) aunque el cómputo sea 100% GPU
    (-ngl alto): en la práctica, la RAM residente observada ronda el tamaño del archivo de
    pesos, incluso con offload completo. Esta estimación asume justamente eso (offload
    completo) y usa solo el tamaño de pesos — es un límite INFERIOR razonable para ese caso
    común, no una simulación: con -ngl bajo (offload parcial) la RAM real será MAYOR (más
    capas y el KV cache se quedan en CPU), y esta función no lo detecta ni lo compensa.
    """
    if override_gb is not None:
        return ResourceEstimate(
            model_id, override_gb, "override", f"{override_gb:.2f} GiB (forzado por el usuario)"
        )

    cmd = model_entry.get("cmd", "") if isinstance(model_entry, dict) else ""
    gguf_path = parse_model_gguf_path(cmd)
    if gguf_path is None:
        return ResourceEstimate(
            model_id, 0.0, "error", "", error="no se encontró --model/-m en 'cmd'"
        )
    if not gguf_path.is_file():
        return ResourceEstimate(
            model_id,
            0.0,
            "error",
            "",
            gguf_path=gguf_path,
            error=f"archivo no encontrado: {gguf_path}",
        )

    size_gb = gguf_path.stat().st_size / 1024**3
    detail = f"pesos {size_gb:.2f} GiB (mmap; asume offload completo a GPU, -ngl alto)"
    return ResourceEstimate(model_id, size_gb, "weights-only", detail, gguf_path=gguf_path)


@dataclass
class GroupContribution:
    group: str
    swap: bool
    members: list[str] = field(default_factory=list)
    member_gb: dict[str, float] = field(default_factory=dict)
    contribution_gb: float = 0.0


def worst_case_gb(
    groups: dict, estimates: dict[str, ResourceEstimate]
) -> tuple[float, list[GroupContribution]]:
    """Peor caso de un recurso (VRAM o RAM, según qué 'estimates' se pasen) para 'groups'.

    Por grupo: si swap=true (default) solo un miembro corre a la vez -> max(miembros). Si
    swap=false, todos corren juntos -> sum(miembros). Se ignora 'exclusive' A PROPÓSITO: cuando
    exclusive=true un grupo descarga a los demás al cargar, lo que solo puede REDUCIR el pico
    real, nunca aumentarlo — sumar todos los grupos da un límite superior seguro (ahí está el
    guardrail anti-OOM). Miembros sin estimación (id no encontrado) no aportan al total.

    Sirve igual para VRAM y para RAM de sistema: cuando llama-swap descarga un modelo mata el
    proceso completo, liberando ambos recursos a la vez — la aritmética de grupos (swap/sum,
    exclusive ignorado) es idéntica, solo cambia qué diccionario de estimaciones se le pasa.
    """
    total = 0.0
    breakdown: list[GroupContribution] = []
    for gname, g in groups.items():
        members = list(g.get("members", [])) if isinstance(g, dict) else []
        swap = bool(g.get("swap", True)) if isinstance(g, dict) else True
        member_gb = {m: estimates[m].gb for m in members if m in estimates}
        contribution = (
            (max(member_gb.values()) if swap else sum(member_gb.values())) if member_gb else 0.0
        )
        total += contribution
        breakdown.append(
            GroupContribution(
                group=gname,
                swap=swap,
                members=members,
                member_gb=member_gb,
                contribution_gb=contribution,
            )
        )
    return total, breakdown


worst_case_vram_gb = worst_case_gb  # alias retrocompatible (nombre histórico de F7.1-F7.7)


# --- I/O de config.yaml (requiere el extra [llamaswap]) ------------------------------------


def load_config(path: Path) -> dict:
    """Carga un config.yaml de llama-swap; {'models': {}} si el archivo no existe todavía."""
    _require_yaml()
    if not path.is_file():
        return {"models": {}}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("models", {})
    return data


def dump_config_str(data: dict) -> str:
    """Serializa un config de llama-swap a YAML (string), sin tocar disco."""
    _require_yaml()
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


def dump_config(data: dict, path: Path) -> None:
    """Escribe un config.yaml de llama-swap.

    LIMITACIÓN: PyYAML no preserva comentarios ni el formato original (bloques '>' multilinea,
    orden de comentarios) al reescribir. Por eso los CLIs que usan esta función SIEMPRE dejan
    un '.bak' del archivo original antes de sobreescribir — es la red de seguridad, no una
    promesa de preservar formato.
    """
    path.write_text(dump_config_str(data), encoding="utf-8")
