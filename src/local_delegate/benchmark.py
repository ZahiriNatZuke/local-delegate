"""Benchmark reproducible para backends locales densos y Mixture of Experts.

El runner no arranca, descarga ni reconfigura modelos. Ejecuta el corpus v2 de tareas reales
(fuentes congeladas y verificadas por hash) contra un endpoint OpenAI-compatible ya aislado por
el operador, y escribe JSONL sin prompts ni secretos.
"""

from __future__ import annotations

import argparse
import base64
import csv
import ctypes
import functools
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import httpx2

from . import config, fallos

# El muestreo frecuente de /metrics no debe convertir el benchmark en un log de cada GET.
logging.getLogger("httpx2").setLevel(logging.WARNING)

_METRIC_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+(?P<value>\S+)$")
_TRACKED_METRICS = {
    "llamaswap_memory_used_bytes",
    "llamaswap_gpu_memory_used_bytes",
    "llamaswap_gpu_util_percent",
    "llamaswap_gpu_power_draw_watts",
}


# --- Corpus v2: tareas reales con fuentes congeladas (protocolo-f2.md §4.6) ----------------------

_CORPUS_KINDS = {"calidad", "techo"}
_CORPUS_ROLES = {"fast", "mechanical", "long", "code", "vision"}
_CORPUS_PROCEDENCIAS = {"congelado", "generado", "reconstruido", "inventado"}
_CORPUS_MEDIA = {"texto", "imagen"}


@dataclass(frozen=True)
class CorpusCase:
    id: str
    tool: str
    role: str
    kind: str
    procedencia: str
    media_type: str
    source_file: str
    source: bytes
    raw: dict[str, Any]


@dataclass(frozen=True)
class Corpus:
    cases: list[CorpusCase]
    controls: list[dict[str, Any]]
    production_config: dict[str, Any]


def _frozen_source(corpus_dir: Path, entry: dict[str, Any]) -> bytes:
    name = str(entry.get("source_file", ""))
    # Nunca una ruta viva: dos casos apuntaban a ficheros que el propio plan edita, y un hash
    # contra una ruta que cambia se invalida solo.
    if not name or Path(name).name != name:
        raise ValueError(f"{entry.get('id')}: source_file tiene que ser un nombre en fuentes/")
    path = corpus_dir / "fuentes" / name
    if not path.is_file():
        raise ValueError(f"{entry.get('id')}: falta fuentes/{name}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry.get("source_sha256"):
        # Correr otro contenido con el mismo id daria numeros de un caso que no es el del JSONL.
        raise ValueError(f"{entry.get('id')}: source_sha256 no cuadra con fuentes/{name}")
    return data


def load_corpus(path: Path) -> Corpus:
    """Carga el corpus v2 y verifica el hash de cada fuente y de cada control antes de nada."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2 or not isinstance(data.get("cases"), list):
        raise ValueError("corpus invalido: se esperaba schema_version=2 y cases[]")
    cases: list[CorpusCase] = []
    seen: set[str] = set()
    for raw in data["cases"]:
        case_id = str(raw.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"id de caso vacio o duplicado: {case_id!r}")
        seen.add(case_id)
        for field_name, allowed in (
            ("kind", _CORPUS_KINDS),
            ("role", _CORPUS_ROLES),
            ("procedencia", _CORPUS_PROCEDENCIAS),
            ("media_type", _CORPUS_MEDIA),
        ):
            if raw.get(field_name) not in allowed:
                raise ValueError(f"{case_id}: {field_name}={raw.get(field_name)!r} no es valido")
        cases.append(
            CorpusCase(
                id=case_id,
                tool=str(raw["tool"]),
                role=raw["role"],
                kind=raw["kind"],
                procedencia=raw["procedencia"],
                media_type=raw["media_type"],
                source_file=raw["source_file"],
                source=_frozen_source(path.parent, raw),
                raw=raw,
            )
        )
    controls = list(data.get("controls") or [])
    for control in controls:
        _frozen_source(path.parent, control)
    return Corpus(cases, controls, dict(data.get("production_config") or {}))


def parse_prometheus_metrics(text: str) -> dict[str, float]:
    """Extrae solo gauges operativos agregando series repetidas por suma."""
    values: dict[str, float] = {}
    for line in text.splitlines():
        match = _METRIC_RE.match(line.strip())
        if not match or match.group("name") not in _TRACKED_METRICS:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        name = match.group("name")
        values[name] = values.get(name, 0.0) + value
    return values


# --- Puntuacion (protocolo-f2.md §4.7) -----------------------------------------------------------


def normalize_for_match(text: str) -> str:
    """NFKD, sin marcas combinantes y casefold.

    NFKD solo no basta: descompone la «ó» en «o» mas un acento suelto, y el acento sigue ahi. Es
    el defecto de julio: un resumen en espanol correcto perdia cobertura por escribir bien.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


# --- Ejecucion del codigo generado (protocolo-f2.md §4.7 punto 6) ---------------------------------

EXEC_TIMEOUT_S = 10.0
# Una comprobacion es {"expr", "expected"} o {"expr", "raises"}. `expected` exige tambien el TIPO:
# la especificacion pide un int, y 45.0 no lo es. Lo escribe el arnes y no el codigo del modelo, asi
# que un `print` del codigo generado no puede fingir un resultado: se lee solo la ULTIMA linea.
_ARNES = r"""
import json
comprobaciones = json.load(open("comprobaciones.json", encoding="utf-8"))
espacio = {"__name__": "generado"}
try:
    exec(compile(open("generado.py", encoding="utf-8").read(), "generado.py", "exec"), espacio)
    cargado = True
except BaseException:
    cargado = False
resultados = []
for c in comprobaciones:
    ok = False
    if cargado:
        try:
            valor = eval(c["expr"], espacio)
            ok = "raises" not in c and type(valor) is type(c["expected"]) and valor == c["expected"]
        except BaseException as exc:
            ok = type(exc).__name__ == c.get("raises")
    resultados.append(ok)
print("\n" + json.dumps(resultados))
"""


def run_execution_checks(code: str, checks: Sequence[dict[str, Any]]) -> list[bool]:
    """Ejecuta el codigo que produccion escribiria a disco y devuelve que comprobaciones pasan.

    Es codigo escrito por un modelo, asi que corre aparte y acotado: otro proceso con `-I` (sin
    variables PYTHON* ni site de usuario), una carpeta temporal como directorio, entorno vacio (ni
    una credencial del operador), sin stdin y con tiempo maximo. No es un sandbox del sistema: el
    operador lo acepta al correr el caso (decision del usuario, tarea 19).
    """
    from .server import _strip_fences  # lo mismo que `local_boilerplate` deja en el fichero

    fallidas = [False] * len(checks)
    env = {"SYSTEMROOT": os.environ["SYSTEMROOT"]} if "SYSTEMROOT" in os.environ else {}
    with tempfile.TemporaryDirectory(prefix="ld-exec-") as carpeta:
        Path(carpeta, "generado.py").write_text(_strip_fences(code), encoding="utf-8")
        Path(carpeta, "comprobaciones.json").write_text(json.dumps(list(checks)), encoding="utf-8")
        try:
            proceso = subprocess.run(
                [sys.executable, "-I", "-c", _ARNES],
                cwd=carpeta,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=EXEC_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return fallidas
    lineas = proceso.stdout.strip().splitlines()
    try:
        resultados = json.loads(lineas[-1]) if lineas else None
    except json.JSONDecodeError:
        return fallidas
    if not isinstance(resultados, list) or len(resultados) != len(checks):
        return fallidas
    return [r is True for r in resultados]


# --- Conteos contra la fuente (protocolo-f2.md §4.7 punto 7) --------------------------------------

_RULE_CODE = re.compile(r"(?<![A-Za-z0-9])[A-Z]+[0-9]+(?![A-Za-z0-9])")
# Un entero suelto: ni pegado a letras o `_` (`v0`), ni parte de un decimal (`3.12`). Un punto de
# final de frase («D102: 7.») no lo anula.
_LOOSE_INT = re.compile(r"(?<![\w.])\d+(?!\w|\.\d)")


def check_counts(text: str, counts: Mapping[str, Sequence[int]]) -> list[str]:
    """Las reglas cuyo conteo NO cuadra con la fuente.

    Cada entero pertenece a la regla que tiene DELANTE en su linea, hasta la siguiente regla: asi
    «T201 (2), COM812 (1)» da 2 a T201 y 1 a COM812. Cuadra si la regla tiene al menos uno y todos
    estan entre los validos: el total, cuantos archivos la tienen o lo que suma en alguno. Una regla
    nombrada sin conteo no cuadra: la tarea lo pide. CP-3 vio al 2B escribir «T201: 10 archivos (3
    por archivo)» con 5 archivos y 101 avisos, y la cobertura de terminos le daba 1,0.
    """
    numbers: dict[str, list[int]] = {rule: [] for rule in counts}
    for line in text.splitlines():
        codes = list(_RULE_CODE.finditer(line))
        for index, code in enumerate(codes):
            if code.group() not in numbers:
                continue
            end = codes[index + 1].start() if index + 1 < len(codes) else len(line)
            numbers[code.group()] += [int(n) for n in _LOOSE_INT.findall(line[code.end() : end])]
    return [
        rule
        for rule, allowed in counts.items()
        if not numbers[rule] or not set(numbers[rule]) <= set(allowed)
    ]


def score_output(
    case: dict[str, Any], text: str, finish_reason: str | None, *, repeated: bool = False
) -> dict[str, Any]:
    """Puntua una respuesta de calidad y dice QUE componente la hundio (`zero_by`).

    Sin `zero_by`, CP-4 no podria saber si el puntuador acerto por la senal correcta: si la mala
    cae por `json_valid` cuando el defecto plantado era un hecho falso, acierta por la razon
    equivocada y no vale.
    """
    expected = list(case.get("expected_terms") or [])
    forbidden = list(case.get("forbidden_terms") or [])
    fields = list(case.get("expected_json_fields") or [])
    plain = normalize_for_match(text)
    matched = [term for term in expected if normalize_for_match(term) in plain]
    hits = [term for term in forbidden if normalize_for_match(term) in plain]
    components: dict[str, Any] = {
        "coverage": round(len(matched) / len(expected), 4) if expected else None,
        "matched_terms": matched,
        "forbidden_hits": hits,
        "json_valid": None,
        "json_fields_ratio": None,
        "execution_ratio": None,
        "execution_passed": None,
        "counts_ratio": None,
        "counts_wrong": None,
    }
    counts = dict(case.get("expected_counts") or {})
    if counts:
        wrong = check_counts(text, counts)
        components["counts_wrong"] = wrong
        components["counts_ratio"] = round((len(counts) - len(wrong)) / len(counts), 4)
    if fields:
        obj = _json_object(text)
        components["json_valid"] = obj is not None
        if obj is not None:
            present = sum(1 for name in fields if name in obj)
            components["json_fields_ratio"] = round(present / len(fields), 4)
    if finish_reason == "length":
        if repeated:
            # Ya se repitio con el doble de max_tokens y sigue sin terminar: no es un limite
            # nuestro, es el modelo. CP-3 (tarea 19) vio un bucle de «D102 (Docstrings)» salir
            # «sin puntuacion» y caer del agregado, que premia justo al que peor lo hizo.
            return {**components, "quality": 0.0, "zero_by": "truncado_repetido", "truncated": True}
        # La primera vez no es mala calidad: la respuesta no termino. El runner la repite con mas
        # max_tokens (§4.7 punto 3), y puntuarla aqui hundiria a un modelo por un limite nuestro.
        return {**components, "quality": None, "zero_by": None, "truncated": True}
    checks = list(case.get("execution_checks") or [])
    if checks:
        passed = run_execution_checks(text, checks)
        components["execution_passed"] = passed
        components["execution_ratio"] = round(sum(passed) / len(passed), 4)
    quality: float | None
    zero_by: str | None = None
    if hits:
        # El unico detector barato de alucinacion: acertar lo demas no lo compensa.
        quality, zero_by = 0.0, "forbidden_terms"
    elif fields and not components["json_valid"]:
        quality, zero_by = 0.0, "json_valid"
    else:
        parts = {
            "coverage": components["coverage"],
            "json_fields": components["json_fields_ratio"],
            "execution": components["execution_ratio"],
            "counts": components["counts_ratio"],
        }
        present_parts = {name: value for name, value in parts.items() if value is not None}
        quality = min(present_parts.values()) if present_parts else None
        if quality == 0:
            zero_by = next(name for name, value in present_parts.items() if value == 0)
    return {**components, "quality": quality, "zero_by": zero_by, "truncated": False}


class MetricsSampler:
    """Muestrea /metrics durante la request para no confundir before/after con el pico."""

    def __init__(
        self, url: str, interval: float = 0.25, headers: dict[str, str] | None = None
    ) -> None:
        self.url = url
        self.interval = interval
        self.headers = headers or {}
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Self:
        def sample() -> None:
            while not self._stop.is_set():
                try:
                    response = httpx2.get(self.url, timeout=1.0, headers=self.headers)
                    if response.is_success:
                        self.samples.append(parse_prometheus_metrics(response.text))
                except httpx2.HTTPError:
                    # Muestreo best-effort: si una lectura falla —el backend está ocupado
                    # cargando un modelo, o cierra la conexión— se descarta ESA muestra y se
                    # sigue muestreando. Propagar mataría el hilo, y con él el benchmark entero
                    # que es lo que se está midiendo.
                    pass
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def peaks(self) -> dict[str, float]:
        names = {name for sample in self.samples for name in sample}
        return {name: max(sample.get(name, 0.0) for sample in self.samples) for name in names}


# --- Sonda de recursos por proceso (Windows) ---------------------------------------------------
#
# REQ-F2-3 pide memoria del PROCESO y no del sistema: medir la RAM del sistema fue el error 1 del
# canary de julio, y `llamaswap_memory_used_bytes` es candidato a repetirlo. Cada supuesto de este
# bloque se verifico por ejecucion antes de escribirlo (SDD delegacion-precisa-y-fiable,
# protocolo-f2.md §3.4, tarea 12). Sin dependencias nuevas: ctypes y typeperf son stdlib y sistema.

_MIB = 1024 * 1024
_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_INVALID_HANDLE = ctypes.c_void_p(-1).value

# La instancia es pid_<pid>_luid_<luid>_phys_<n>, y un PID tiene UNA POR ADAPTADOR (hasta tres en
# la maquina de medida). Sin filtrar por LUID se sumaria la VRAM de la iGPU a la de la NVIDIA.
_GPU_PROCESS_COLUMN_RE = re.compile(
    r"GPU Process Memory\(pid_(?P<pid>\d+)_luid_(?P<luid>0x[0-9a-f]+_0x[0-9a-f]+)_phys_\d+\)"
    r"\\(?P<counter>Dedicated Usage|Shared Usage)$",
    re.IGNORECASE,
)
_GPU_ADAPTER_COLUMN_RE = re.compile(
    r"GPU Adapter Memory\(luid_(?P<luid>0x[0-9a-f]+_0x[0-9a-f]+)_phys_\d+\)\\Dedicated Usage$",
    re.IGNORECASE,
)
_COUNTER_KEYS = {"dedicated usage": "dedicated", "shared usage": "shared"}


def probe_supported() -> bool:
    """La sonda solo existe en Windows: Toolhelp32, psapi y typeperf no tienen equivalente aqui."""
    return sys.platform == "win32"


@dataclass(frozen=True)
class ResourceSample:
    """Una lectura de la sonda. `None` significa «sin muestra», nunca cero."""

    pid: int | None
    private_bytes: int | None = None
    working_set_bytes: int | None = None
    vram_dedicated_bytes: int | None = None
    vram_shared_bytes: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class VramReading:
    dedicated_bytes: int | None
    shared_bytes: int | None
    process_gone: bool = False


def _csv_row(line: str) -> list[str] | None:
    # typeperf mezcla el CSV con mensajes en la pagina de codigos de la consola («Se est�
    # saliendo»): solo son datos las lineas que empiezan por comillas.
    stripped = line.strip()
    if not stripped.startswith('"'):
        return None
    return next(csv.reader([stripped]))


def parse_typeperf_header(line: str, pid: int, luid: str) -> dict[int, str] | None:
    """Columnas de la instancia pedida, `{indice: "dedicated" | "shared"}`.

    Devuelve `None` si la linea no es la cabecera, y `{}` si lo es pero no trae esa instancia: un
    LUID equivocado tiene que acabar en cero muestras visibles, no en la VRAM de otro adaptador.
    """
    row = _csv_row(line)
    if not row or "PDH-CSV" not in row[0]:
        return None
    columns: dict[int, str] = {}
    for index, name in enumerate(row[1:], start=1):
        match = _GPU_PROCESS_COLUMN_RE.search(name)
        if match and int(match["pid"]) == pid and match["luid"].casefold() == luid.casefold():
            columns[index] = _COUNTER_KEYS[match["counter"].casefold()]
    return columns


def parse_typeperf_sample(line: str, columns: dict[int, str]) -> VramReading | None:
    """Una fila de muestras. `None` si la linea no es una fila de datos."""
    row = _csv_row(line)
    if not row or "PDH-CSV" in row[0] or not columns:
        return None
    totals: dict[str, int] = {}
    for index, key in columns.items():
        raw = row[index].strip() if index < len(row) else ""
        try:
            value = float(raw)
        except ValueError:
            continue
        if value < 0:
            # Cuando el PID muere, typeperf NO se cierra ni deja el campo vacio: emite -1 cada
            # segundo hasta agotar -sc (medido en la tarea 12). Es la senal de reresolver.
            return VramReading(None, None, process_gone=True)
        totals[key] = totals.get(key, 0) + int(value)
    if not totals:
        return None
    return VramReading(totals.get("dedicated"), totals.get("shared"))


def parse_adapter_dedicated(output: str) -> dict[str, int]:
    """`typeperf "\\GPU Adapter Memory(*)\\Dedicated Usage" -sc 1` -> `{luid: bytes}`."""
    header: list[str] | None = None
    for line in output.splitlines():
        row = _csv_row(line)
        if not row:
            continue
        if header is None:
            if "PDH-CSV" in row[0]:
                header = row
            continue
        values: dict[str, int] = {}
        for name, raw in zip(header[1:], row[1:], strict=False):
            match = _GPU_ADAPTER_COLUMN_RE.search(name)
            try:
                value = float(raw)
            except ValueError:
                continue
            if match and value >= 0:
                values[match["luid"]] = values.get(match["luid"], 0) + int(value)
        return values
    return {}


def choose_gpu_luid(
    adapter_dedicated: dict[str, int], nvidia_used_mib: float, tolerance_mib: float = 128.0
) -> str | None:
    """El LUID cuyo `Dedicated Usage` cuadra con la memoria usada que reporta `nvidia-smi`.

    Ni `nvidia-smi` expone el LUID ni los contadores de Windows dicen que adaptador es cual; la
    tarea 12 los empareja asi a mano (951,7 MiB contra 942). Si no hay exactamente un candidato
    dentro de la tolerancia no se adivina: se pide `--gpu-luid`.
    """
    matches = [
        luid
        for luid, used in adapter_dedicated.items()
        if abs(used / _MIB - nvidia_used_mib) <= tolerance_mib
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_gpu_luid(run: Callable[..., Any] = subprocess.run) -> str | None:
    """Resuelve el LUID de la NVIDIA con `typeperf` y `nvidia-smi`; `None` si no es inequivoco."""
    try:
        adapters = run(
            ["typeperf", r"\GPU Adapter Memory(*)\Dedicated Usage", "-sc", "1"],
            capture_output=True,
            text=True,
            encoding="mbcs" if sys.platform == "win32" else "utf-8",
            errors="replace",
            timeout=30,
        )
        smi = run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [line for line in smi.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            return None
        return choose_gpu_luid(parse_adapter_dedicated(adapters.stdout), float(lines[0]))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


@functools.cache
def _win32_api() -> SimpleNamespace:
    # Solo `import`: CodeQL marca mezclar `import ctypes` con `from ctypes import`, y ruff (PLR0402)
    # marca el alias. El submodulo se importa aqui porque solo existe para Windows.
    import ctypes.wintypes

    wintypes = ctypes.wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class ProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    for function in (kernel32.Process32FirstW, kernel32.Process32NextW):
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
        function.restype = wintypes.BOOL
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCountersEx),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    return SimpleNamespace(
        kernel32=kernel32,
        psapi=psapi,
        ProcessEntry32W=ProcessEntry32W,
        ProcessMemoryCountersEx=ProcessMemoryCountersEx,
    )


def list_processes() -> dict[int, str]:
    """PID -> nombre de imagen, por Toolhelp32. Vacio fuera de Windows."""
    if sys.platform != "win32":
        return {}
    api = _win32_api()
    snapshot = api.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == _INVALID_HANDLE:
        return {}
    try:
        entry = api.ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        result: dict[int, str] = {}
        ok = api.kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            result[int(entry.th32ProcessID)] = str(entry.szExeFile)
            ok = api.kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return result
    finally:
        api.kernel32.CloseHandle(snapshot)


def find_pids(name: str, lister: Callable[[], dict[int, str]] = list_processes) -> list[int]:
    return sorted(pid for pid, image in lister().items() if image.casefold() == name.casefold())


def read_process_memory(pid: int) -> tuple[int, int] | None:
    """`(PrivateUsage, WorkingSetSize)` del proceso, o `None` si no se puede abrir.

    Los dos salen de la misma llamada y se guardan siempre (P-11): con los pesos mapeados desde el
    GGUF, lo mapeado no es memoria privada y `PrivateUsage` no ve los expertos de un MoE. Que modo
    de carga lo evita se decide en CP-2b, sin tocar este codigo. Sin elevar, abrir un proceso de
    otro usuario da acceso denegado (`dwm`, `System`): eso es «sin muestra», no una excepcion.
    """
    if sys.platform != "win32":
        return None
    api = _win32_api()
    handle = api.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        counters = api.ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        if not api.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.PrivateUsage), int(counters.WorkingSetSize)
    finally:
        api.kernel32.CloseHandle(handle)


class TypeperfStream:
    """Flujo continuo de VRAM de UN PID, a 1 Hz.

    Vive mientras el PID no cambie: arrancar `typeperf` cuesta 1,4-2,8 s hasta la cabecera, asi
    que la lectura «sincrona» de VRAM es la ultima muestra del flujo, no un typeperf nuevo. Y un
    typeperf ya arrancado no ve instancias creadas despues (cabecera fija): al cambiar el PID hay
    que relanzarlo. Y tambien con el MISMO PID si la cabecera llego sin su instancia
    (`missing_instance`): pasa si typeperf arranca antes de que el proceso cree su contexto CUDA.
    """

    def __init__(
        self,
        pid: int,
        luid: str,
        *,
        interval: int = 1,
        popen: Callable[..., Any] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pid = pid
        self.luid = luid
        self.process_gone = False
        self.missing_instance = False
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: VramReading | None = None
        self._latest_at: float | None = None
        options: dict[str, Any] = {}
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        # La ruta con comodin pid_<pid>_* es la que se verifico; el LUID se filtra al parsear.
        self.command = [
            "typeperf",
            rf"\GPU Process Memory(pid_{pid}_*)\Dedicated Usage",
            rf"\GPU Process Memory(pid_{pid}_*)\Shared Usage",
            "-si",
            str(max(1, interval)),
        ]
        self._process = popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="mbcs" if sys.platform == "win32" else "utf-8",
            errors="replace",
            **options,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        stdout = self._process.stdout
        if stdout is None:
            return
        columns: dict[int, str] | None = None
        for line in stdout:
            if columns is None:
                columns = parse_typeperf_header(line, self.pid, self.luid)
                if columns == {}:
                    # Cabecera sin la instancia del PID: este flujo ya no dara ninguna muestra.
                    self.missing_instance = True
                continue
            reading = parse_typeperf_sample(line, columns)
            if reading is None:
                continue
            with self._lock:
                if reading.process_gone:
                    self.process_gone = True
                    self._latest = None
                else:
                    self._latest = reading
                    self._latest_at = self._clock()

    def latest(self, max_age: float) -> VramReading | None:
        with self._lock:
            if self._latest is None or self._latest_at is None:
                return None
            if self._clock() - self._latest_at > max_age:
                return None
            return self._latest

    def close(self) -> None:
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
        except OSError:
            # typeperf ya habia salido por su cuenta: no queda proceso que parar.
            pass
        self._thread.join(timeout=2.0)


class ProcessProbe:
    """Sonda de toda la tanda: resuelve el PID POR NOMBRE en cada lectura.

    Por nombre, y no por el `Popen` de quien lo lanzo: llama-swap relanza `llama-server.exe` al
    cambiar de modelo, y un lanzador intermedio —el `python.exe` de un venv, el `pythonw` del
    daemon— tiene otro PID que el proceso que de verdad carga la memoria (medido en la tarea 12).
    """

    def __init__(
        self,
        process_name: str,
        gpu_luid: str | None,
        *,
        find: Callable[[str], list[int]] = find_pids,
        read_memory: Callable[[int], tuple[int, int] | None] = read_process_memory,
        stream_factory: Callable[[int, str], Any] = TypeperfStream,
        vram_max_age: float = 2.5,
        clock: Callable[[], float] = time.monotonic,
        relaunch_after: float = 3.0,
    ) -> None:
        self.process_name = process_name
        self.gpu_luid = gpu_luid
        self.stream_error: str | None = None
        self._find = find
        self._read_memory = read_memory
        self._stream_factory = stream_factory
        self._vram_max_age = vram_max_age
        self._clock = clock
        # typeperf tarda 1,4-2,8 s en dar la cabecera: relanzarlo en cada muestra no la veria nunca.
        self._relaunch_after = relaunch_after
        self._stream_started_at = 0.0
        self._pid: int | None = None
        self._stream: Any = None

    def _switch(self, pid: int | None) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._pid = pid
        if pid is not None and self.gpu_luid:
            try:
                self._stream = self._stream_factory(pid, self.gpu_luid)
                self._stream_started_at = self._clock()
            except OSError as exc:
                # Sin typeperf no hay VRAM, y la corrida acaba con cero muestras de VRAM y anulada:
                # visible en el JSONL, en vez de un traceback a mitad de tanda.
                self.stream_error = f"{type(exc).__name__}: {exc}"

    def sample(self) -> ResourceSample:
        pids = self._find(self.process_name)
        if len(pids) > 1:
            # Protocolo §1.4: con dos llama-server vivos no hay forma fiable de saber cual mide.
            return ResourceSample(None, reason="multiple_processes")
        if not pids:
            if self._pid is not None:
                self._switch(None)
            return ResourceSample(None, reason="no_process")
        pid = pids[0]
        if pid != self._pid:
            self._switch(pid)
        elif (
            self._stream is not None
            and getattr(self._stream, "missing_instance", False)
            and self._clock() - self._stream_started_at >= self._relaunch_after
        ):
            # Tercer piloto de CP-3: el flujo del 2B arranco antes de que llama-server creara su
            # contexto CUDA, y como el PID no cambio en todo el bloque, 120 intentos se anularon
            # con cero muestras de VRAM. Con el mismo PID, se relanza.
            self._switch(pid)
        memory = self._read_memory(pid)
        vram = self._stream.latest(self._vram_max_age) if self._stream is not None else None
        return ResourceSample(
            pid,
            private_bytes=memory[0] if memory else None,
            working_set_bytes=memory[1] if memory else None,
            vram_dedicated_bytes=vram.dedicated_bytes if vram else None,
            vram_shared_bytes=vram.shared_bytes if vram else None,
            reason=None if memory else "no_access",
        )

    def close(self) -> None:
        self._switch(None)


def summarize_resources(
    samples: Sequence[ResourceSample], *, enabled: bool, vram_expected: bool
) -> dict[str, Any]:
    """Resumen por corrida, con el motivo de anulacion si lo hay.

    Una corrida con cero muestras se anula y se repite; no se publica vacia (protocolo §3.3). Y si
    el PID cambia a mitad, los picos mezclan dos procesos: tambien se anula (§3.2).
    """
    ram = [s for s in samples if s.private_bytes is not None]
    vram = [s for s in samples if s.vram_dedicated_bytes is not None]
    shared = [s.vram_shared_bytes for s in samples if s.vram_shared_bytes is not None]
    pids = sorted({s.pid for s in samples if s.pid is not None})
    annul: str | None = None
    if enabled:
        if any(s.reason == "multiple_processes" for s in samples):
            annul = "multiple_processes"
        elif len(pids) > 1:
            annul = "process_changed"
        elif not ram:
            annul = "zero_ram_samples"
        elif vram_expected and not vram:
            annul = "zero_vram_samples"
    return {
        "enabled": enabled,
        "pids": pids,
        # El primero y el ultimo, en orden: `pids` va ordenado y pierde cual vino antes, que es
        # justo lo que necesita el estado termico (§5.3).
        "pid_first": samples[0].pid if samples else None,
        "pid_last": next((s.pid for s in reversed(samples) if s.pid is not None), None),
        "samples": len(samples),
        "ram_samples": len(ram),
        "vram_samples": len(vram),
        "private_bytes_before": samples[0].private_bytes if samples else None,
        "private_bytes_after": samples[-1].private_bytes if samples else None,
        "private_bytes_peak": max((s.private_bytes or 0) for s in ram) if ram else None,
        "working_set_bytes_peak": max(
            (s.working_set_bytes for s in samples if s.working_set_bytes is not None),
            default=None,
        ),
        "vram_dedicated_bytes_peak": max((s.vram_dedicated_bytes or 0) for s in vram)
        if vram
        else None,
        # Primera y pico por separado: `Shared Usage` que CRECE invalida CP-1 y todo el tramo
        # desde el ultimo CP-1 en verde, no solo esta corrida (§3.2). Lo decide el analisis.
        "vram_shared_bytes_first": shared[0] if shared else None,
        "vram_shared_bytes_peak": max(shared) if shared else None,
        "annul": annul,
    }


class ResourceSampler:
    """Lectura sincrona al entrar y al salir, y en continuo entre medias.

    Asi una corrida de menos de un segundo nunca se queda sin ninguna muestra (protocolo §3.3).
    """

    def __init__(self, probe: ProcessProbe | None, interval: float = 0.25) -> None:
        self.probe = probe
        self.interval = interval
        self.samples: list[ResourceSample] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _take(self) -> None:
        if self.probe is None:
            return
        try:
            self.samples.append(self.probe.sample())
        except OSError as exc:
            self.samples.append(ResourceSample(None, reason=f"error:{type(exc).__name__}"))

    def __enter__(self) -> Self:
        if self.probe is None:
            return self
        self._take()

        def loop() -> None:
            while not self._stop.wait(self.interval):
                self._take()

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._take()

    def summary(self) -> dict[str, Any]:
        return summarize_resources(
            self.samples,
            enabled=self.probe is not None,
            vram_expected=bool(self.probe and self.probe.gpu_luid),
        )


def _root_url(base_url: str) -> str:
    clean = base_url.rstrip("/")
    return clean.removesuffix("/v1")


def _build_probe(args: argparse.Namespace) -> ProcessProbe | None | int:
    """La sonda pedida, `None` si no se pidio, o un exit code si no se puede montar."""
    if not args.probe_process:
        return None
    if not probe_supported():
        print("error: --probe-process solo funciona en Windows (Toolhelp32, psapi y typeperf)")
        return 2
    luid = args.gpu_luid or resolve_gpu_luid()
    if not luid:
        print(
            "error: no se pudo resolver el LUID de la GPU de forma inequivoca; "
            'pasalo con --gpu-luid (typeperf -qx "GPU Adapter Memory")'
        )
        return 2
    return ProcessProbe(args.probe_process, luid)


CONTENT_MARKER = "{CONTENIDO}"
REASONING_EFFORTS = ("off", "low", "medium", "high")
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_ROLES = ("fast", "mechanical", "long", "code", "vision")


def reasoning_kwargs(effort: str | None) -> dict[str, Any] | None:
    """`chat_template_kwargs` para el nivel de razonamiento pedido.

    `off` es `enable_thinking: false`, la variable que leen las plantillas de Qwen3 y afines: la
    cadena esta en `llama-server-impl.dll` de b9925. El resto va como `reasoning_effort`, que es una
    variable de la plantilla de gpt-oss y el servidor la pasa sin interpretarla. El fallo 4 de julio
    fue medir con `low` creyendo que era neutro: `off` es lo que faltaba.
    """
    if effort is None:
        return None
    if effort == "off":
        return {"enable_thinking": False}
    return {"reasoning_effort": effort}


def effective_reasoning(
    case: CorpusCase, model_effort: str | None
) -> tuple[str | None, str | None]:
    """Precedencia caso > modelo (§4.7): el mismo modelo corre casos de resumir, donde hay que
    apagarle el razonamiento, y de codigo, donde no. Con un solo valor se mediria mal uno de los dos."""
    if case.raw.get("reasoning_effort"):
        return case.raw["reasoning_effort"], "case"
    if model_effort:
        return model_effort, "model"
    return None, None


def build_payload(
    case: CorpusCase,
    model: str,
    seed: int,
    reasoning_effort: str | None,
    *,
    max_tokens: int | None = None,
    source: bytes | None = None,
) -> dict[str, Any]:
    """La peticion de produccion para ese caso, con SU temperatura y la semilla de la corrida.

    La temperatura es la que capturo el constructor de la tool real (P-12, 2026-09-14): con
    temperatura 0 y `-np 1` las tres corridas salian identicas byte a byte y la banda de ruido no
    medía nada. La semilla la varia el llamador por corrida, asi que sigue siendo reproducible.

    `system` y `user_template` son los que capturo el constructor de la tool real. En imagen, el
    payload lleva `image_url` igual que `local_describe_image`: sin eso el rol `vision` no se podia
    medir en absoluto. `source` sustituye la entrada (la imagen de control de CP-3).
    """
    raw = case.raw
    data = case.source if source is None else source
    user: Any
    if case.media_type == "imagen":
        mime = _IMAGE_MIME[Path(case.source_file).suffix.lower()]
        encoded = base64.b64encode(data).decode("ascii")
        user = [
            {"type": "text", "text": raw["user_template"]},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]
    else:
        # Lo que ve el modelo en produccion: `_read_input` lee con read_text, que normaliza \r\n.
        content = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        user = raw["user_template"].replace(CONTENT_MARKER, content, 1)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": raw["system"]},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens or raw["max_tokens"],
        "temperature": float(raw["temperature"]),
        "seed": seed,
        "stream": False,
    }
    if raw.get("response_format"):
        payload["response_format"] = raw["response_format"]
    kwargs = reasoning_kwargs(reasoning_effort)
    if kwargs:
        payload["chat_template_kwargs"] = kwargs
    return payload


def is_context_rejection(status: int, body: str) -> bool:
    """El prompt no cabe en el contexto del modelo: una clase propia, ni mala calidad ni descartada.

    En julio estos se contaron como fallos del modelo y descartaron uno bueno (§3.5). El tipo
    `exceed_context_size_error` esta en `llama-server-impl.dll` de b9925; que la respuesta real lo
    traiga se confirma con los sondeos de techo, y el cuerpo del error se guarda por si hay que
    reclasificar.
    """
    return status == 400 and "exceed_context_size_error" in body


@dataclass
class Attempt:
    outcome: str
    text: str = ""
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)
    reasoning_chars: int = 0
    error: str | None = None
    error_body: str | None = None


def post_attempt(client: httpx2.Client, url: str, payload: dict[str, Any]) -> Attempt:
    try:
        response = client.post(url, json=payload)
    except httpx2.HTTPError as exc:
        return Attempt("error", error=f"{type(exc).__name__}: {exc}")
    body = response.text
    if response.status_code >= 400:
        outcome = (
            "rechazo_por_contexto" if is_context_rejection(response.status_code, body) else "error"
        )
        return Attempt(outcome, error=f"http_{response.status_code}", error_body=body.strip()[:500])
    try:
        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise TypeError("message no es un objeto")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return Attempt(
            "error", error=f"respuesta inesperada: {type(exc).__name__}", error_body=body[:500]
        )
    content = message.get("content")
    reasoning = str(message.get("reasoning_content") or "")
    finish = choice.get("finish_reason")
    text = content if isinstance(content, str) else ""
    error = None
    if finish == "length" and not text.strip() and reasoning.strip():
        # Se gasto max_tokens pensando y no contesto: es configuracion, no calidad (§4.7 punto 4),
        # la misma clase que ya da `fallos.py`. Repetirlo con mas tokens taparia el problema.
        outcome = fallos.Clase.CONFIGURACION.value
    elif finish == "length":
        outcome = "truncado"
    elif not isinstance(content, str):
        outcome, error = "error", "content nulo"
    else:
        outcome = "ok"
    return Attempt(
        outcome,
        text=text,
        finish_reason=finish,
        usage=data.get("usage") or {},
        timings=data.get("timings") or {},
        reasoning_chars=len(reasoning),
        error=error,
    )


class ThermalTracker:
    """Fria solo la primera peticion tras cargar el modelo (protocolo §5.3).

    La senal de carga es el cambio de PID de `llama-server.exe` que ya sigue la sonda. Sin sonda
    no hay senal y el estado queda en `None`, en vez de inventarse: el runner de julio marcaba fria
    la primera corrida DE CADA CASO, e inflaba la banda de ruido con valores mal etiquetados.
    """

    def __init__(self) -> None:
        self._last_pid: int | None = None
        self._started = False

    def classify(self, resources: dict[str, Any]) -> str | None:
        pids = resources.get("pids") or []
        if not resources.get("enabled") or not pids:
            return None
        if not self._started:
            # Primera peticion de la invocacion: fria si el proceso aparecio durante ella.
            cold = resources.get("pid_first") is None
        else:
            cold = any(pid != self._last_pid for pid in pids)
        self._started = True
        self._last_pid = resources.get("pid_last") or self._last_pid
        return "cold" if cold else "hot"


MAX_ANNUL_RETRIES = 2


def _select_cases(corpus: Corpus, args: argparse.Namespace) -> list[CorpusCase]:
    cases = corpus.cases
    if args.case:
        unknown = set(args.case) - {case.id for case in cases}
        if unknown:
            raise ValueError(f"casos desconocidos: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.id in set(args.case)]
    if args.role:
        cases = [case for case in cases if case.role in set(args.role)]
    return cases


def run_benchmark(args: argparse.Namespace) -> int:
    corpus_path = Path(args.cases)
    corpus = load_corpus(corpus_path)
    cases = _select_cases(corpus, args)
    control_source: bytes | None = None
    if args.input_control:
        control = next((c for c in corpus.controls if c["id"] == args.input_control), None)
        if control is None:
            print(f"error: no hay control {args.input_control!r} en el corpus")
            return 2
        # Ya verificado por hash en load_corpus. Solo aplica a los casos que el control declara.
        control_source = (corpus_path.parent / "fuentes" / control["source_file"]).read_bytes()
        cases = [case for case in cases if case.id in control["para"]]
    if not cases:
        print("error: ningun caso seleccionado")
        return 2
    without_prompt = [
        c.id for c in cases if not c.raw.get("system") or not c.raw.get("user_template")
    ]
    if without_prompt:
        print(
            f"error: casos sin prompt de una llamada ({', '.join(without_prompt)}): regenera el corpus"
        )
        return 2

    output = Path(args.output)
    if output.exists() and not args.append:
        print(f"error: {output} ya existe; usa --append o elige otra ruta")
        return 2

    probe = _build_probe(args)
    if isinstance(probe, int):
        return probe
    output.parent.mkdir(parents=True, exist_ok=True)

    base_url = (args.endpoint or config.BASE_URL).rstrip("/")
    metrics_url = f"{_root_url(base_url)}/metrics"
    headers = {"Content-Type": "application/json"}
    api_key = args.api_key or config.API_KEY
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    failures = 0
    thermal = ThermalTracker()
    try:
        with (
            httpx2.Client(timeout=args.timeout, headers=headers) as client,
            output.open("a", encoding="utf-8") as sink,
        ):
            for case in cases:
                source = control_source if control_source is not None else case.source
                effort, effort_source = effective_reasoning(case, args.reasoning_effort)
                for run in range(1, args.runs + 1):
                    # Semilla distinta por corrida y la misma en sus reintentos (P-12): con la
                    # temperatura de produccion, las corridas miden la variacion real del modelo.
                    run_seed = args.seed + run - 1
                    max_tokens = int(case.raw["max_tokens"])
                    attempt = 1
                    doubled = False
                    annul_retries = 0
                    retry_reason: str | None = None
                    while True:
                        payload = build_payload(
                            case,
                            args.model,
                            run_seed,
                            effort,
                            max_tokens=max_tokens,
                            source=source,
                        )
                        started = time.perf_counter()
                        with (
                            MetricsSampler(metrics_url, args.sample_interval, headers) as sampler,
                            ResourceSampler(probe, args.sample_interval) as resources,
                        ):
                            result = post_attempt(client, f"{base_url}/chat/completions", payload)
                        elapsed_ms = round((time.perf_counter() - started) * 1000)
                        resource_summary = resources.summary()
                        scored = case.kind == "calidad" and result.outcome in ("ok", "truncado")
                        record: dict[str, Any] = {
                            "schema_version": 2,
                            "ts": datetime.now(UTC).isoformat(),
                            "label": args.label,
                            "model": args.model,
                            "variant": {
                                "quantization": args.quantization,
                                "context_size": args.context_size,
                                "n_cpu_moe": args.n_cpu_moe,
                                # Parte de la identidad de la medida (§5.2): con mmap el contador
                                # privado no ve los pesos, y §6 invalida un rol si difiere.
                                "load_mode": args.load_mode,
                                "llama_swap_version": args.llama_swap_version,
                                "llama_server_version": args.llama_server_version,
                                "reasoning_effort": effort,
                                "reasoning_effort_source": effort_source,
                                "probe_process": args.probe_process,
                                "gpu_luid": probe.gpu_luid if probe else None,
                            },
                            "case": case.id,
                            "role": case.role,
                            "kind": case.kind,
                            "procedencia": case.procedencia,
                            "input_variant": args.input_control,
                            "run": run,
                            "attempt": attempt,
                            # Por que existe este intento: None el primero, y si no «anulada»
                            # o «truncado». El analisis juzga la corrida por su ultimo intento.
                            "retry_reason": retry_reason,
                            "max_tokens": max_tokens,
                            "thermal_state": thermal.classify(resource_summary),
                            "seed": run_seed,
                            "temperature": payload["temperature"],
                            "input_bytes": len(source),
                            "input_sha256": hashlib.sha256(source).hexdigest(),
                            "latency_ms": elapsed_ms,
                            "outcome": result.outcome,
                            "ok": result.outcome == "ok",
                            "error": result.error,
                            "error_body": result.error_body,
                            "finish_reason": result.finish_reason,
                            "usage": result.usage,
                            "timings": result.timings,
                            "reasoning_chars": result.reasoning_chars,
                            "metrics_peak": sampler.peaks(),
                            "resources": resource_summary,
                            # Anulada por la sonda: se repite hasta MAX_ANNUL_RETRIES veces.
                            # Distinto de rechazo y de mala calidad.
                            "descartada": resource_summary["annul"] is not None,
                            "descartada_motivo": resource_summary["annul"],
                            "score": score_output(
                                case.raw, result.text, result.finish_reason, repeated=doubled
                            )
                            if scored
                            else None,
                            "response_chars": len(result.text),
                            "response_sha256": hashlib.sha256(
                                result.text.encode("utf-8")
                            ).hexdigest(),
                        }
                        if args.save_responses:
                            record["response"] = result.text
                        sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                        sink.flush()
                        if result.outcome == "error":
                            failures += 1
                        quality = (record["score"] or {}).get("quality")
                        annul = resource_summary["annul"]
                        print(
                            f"[{result.outcome}] {case.id} run={run} attempt={attempt} "
                            f"latency={elapsed_ms}ms quality={quality}"
                            + (f" annul={annul}" if annul else "")
                        )
                        # Todos los intentos quedan en el JSONL: un descarte silencioso seria
                        # indistinguible de un caso que no se corrio.
                        # Anulada: la medida no vale, asi que se repite con los mismos tokens. El
                        # comentario de antes decia que se repetia y no lo hacia: CP-3 dejo la
                        # primera corrida de cada modelo con 2 validas en vez de 3.
                        if annul is not None and annul_retries < MAX_ANNUL_RETRIES:
                            annul_retries += 1
                            attempt += 1
                            retry_reason = "anulada"
                            continue
                        # Truncado se repite UNA vez con el doble de max_tokens (§4.7 punto 3); si
                        # vuelve a truncar, ya puntuo 0 arriba.
                        if result.outcome == "truncado" and case.kind == "calidad" and not doubled:
                            doubled = True
                            attempt += 1
                            max_tokens *= 2
                            retry_reason = "truncado"
                            continue
                        break
    finally:
        if probe is not None:
            probe.close()
    return 1 if failures else 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "benchmark",
        help="Ejecuta el corpus v2 de tareas reales contra un backend canary y escribe JSONL.",
    )
    parser.add_argument("--model", required=True, help="id expuesto por el backend canary")
    parser.add_argument(
        "--label", required=True, help="etiqueta de config, p. ej. gptoss-ncmoe12-c8k"
    )
    parser.add_argument(
        "--cases",
        required=True,
        help="cases.json del corpus v2, p. ej. benchmarks/catalogo-2026-09/cases.json",
    )
    parser.add_argument("--case", action="append", help="id de caso a ejecutar (repetible)")
    parser.add_argument(
        "--role", action="append", choices=_ROLES, help="solo los casos de este rol (repetible)"
    )
    parser.add_argument(
        "--input-control",
        default=None,
        help="sustituye la entrada por este control del corpus (CP-3), solo en sus casos",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        # 5 y no 3 desde el tercer piloto de CP-3: con temperatura de produccion, una corrida mala
        # movia la mediana de 3 y ponia la dispersion en su maximo.
        help="corridas por caso (default 5)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="semilla base: la corrida n usa seed + n - 1 (y la misma en sus reintentos)",
    )
    parser.add_argument("--quantization", default=None)
    parser.add_argument("--context-size", type=int, default=None)
    parser.add_argument("--n-cpu-moe", type=int, default=None)
    parser.add_argument(
        "--load-mode",
        default=None,
        help="--load-mode de llama-server (p. ej. none); el analisis exige el mismo en vigente y candidato",
    )
    parser.add_argument("--llama-swap-version", default=None)
    parser.add_argument("--llama-server-version", default=None)
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        default=None,
        help="razonamiento del modelo; off apaga el pensamiento. El valor del caso manda",
    )
    parser.add_argument(
        "--endpoint", default=None, help="BASE_URL /v1; default LOCAL_DELEGATE_BASE_URL"
    )
    parser.add_argument("--api-key", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--sample-interval", type=float, default=0.25)
    parser.add_argument(
        "--probe-process",
        default=None,
        help="mide RAM y VRAM de este proceso por nombre, p. ej. llama-server.exe (solo Windows)",
    )
    parser.add_argument(
        "--gpu-luid",
        default=None,
        help="LUID del adaptador para la VRAM (p. ej. 0x00000000_0x0000F722); "
        "sin el, se resuelve contra nvidia-smi",
    )
    parser.add_argument("--output", required=True, help="JSONL de salida")
    parser.add_argument("--append", action="store_true")
    parser.add_argument(
        "--save-responses",
        action="store_true",
        help="guarda las respuestas completas; hacen falta para la revision a ciegas",
    )
    parser.set_defaults(func=run_benchmark)
