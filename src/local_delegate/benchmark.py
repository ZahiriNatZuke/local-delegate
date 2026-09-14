"""Benchmark reproducible para backends locales densos y Mixture of Experts.

El runner no arranca, descarga ni reconfigura modelos. Ejecuta un corpus sintetico contra un
endpoint OpenAI-compatible ya aislado por el operador y escribe JSONL sin prompts ni secretos.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import functools
import hashlib
import json
import logging
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import httpx2

from . import config

# El muestreo frecuente de /metrics no debe convertir el benchmark en un log de cada GET.
logging.getLogger("httpx2").setLevel(logging.WARNING)

_METRIC_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+(?P<value>\S+)$")
_TRACKED_METRICS = {
    "llamaswap_memory_used_bytes",
    "llamaswap_gpu_memory_used_bytes",
    "llamaswap_gpu_util_percent",
    "llamaswap_gpu_power_draw_watts",
}


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    instruction: str
    facts: tuple[str, ...]
    filler: str
    target_chars: int
    max_tokens: int
    expected_terms: tuple[str, ...]
    expected_json_fields: tuple[str, ...] = ()


def load_cases(path: Path) -> list[BenchmarkCase]:
    """Carga el schema versionado del corpus y valida lo imprescindible."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("corpus invalido: se esperaba schema_version=1 y cases[]")
    result: list[BenchmarkCase] = []
    seen: set[str] = set()
    for raw in data["cases"]:
        case_id = str(raw.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"id de caso vacio o duplicado: {case_id!r}")
        seen.add(case_id)
        result.append(
            BenchmarkCase(
                id=case_id,
                instruction=str(raw["instruction"]),
                facts=tuple(str(item) for item in raw.get("facts", [])),
                filler=str(raw.get("filler", "")),
                target_chars=max(1, int(raw.get("target_chars", 1))),
                max_tokens=max(1, int(raw.get("max_tokens", 512))),
                expected_terms=tuple(str(item) for item in raw.get("expected_terms", [])),
                expected_json_fields=tuple(
                    str(item) for item in raw.get("expected_json_fields", [])
                ),
            )
        )
    return result


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


def materialize_case(case: BenchmarkCase) -> str:
    """Genera entrada determinista hasta el tamaño objetivo sin datos externos."""
    core = "\n".join(case.facts)
    filler = case.filler.strip() or "Contexto neutro para medir procesamiento de prompt."
    chunks = [core] if core else []
    index = 1
    while len("\n".join(chunks)) < case.target_chars:
        chunks.append(f"Nota contextual {index}: {filler}")
        index += 1
    return "\n".join(chunks)[: case.target_chars]


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


def score_response(case: BenchmarkCase, response: str) -> dict[str, Any]:
    """Calcula señales simples; la revisión semántica sigue siendo humana."""
    lower = response.casefold()
    matched = [term for term in case.expected_terms if term.casefold() in lower]
    score: dict[str, Any] = {
        "expected_terms": len(case.expected_terms),
        "matched_terms": len(matched),
        "term_coverage": round(len(matched) / len(case.expected_terms), 4)
        if case.expected_terms
        else None,
    }
    if case.expected_json_fields:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
        try:
            payload = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            payload = None
        score["json_valid"] = isinstance(payload, dict)
        score["json_fields_present"] = (
            sorted(field for field in case.expected_json_fields if field in payload)
            if isinstance(payload, dict)
            else []
        )
    return score


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
    from ctypes import wintypes

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
    que relanzarlo.
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
    ) -> None:
        self.process_name = process_name
        self.gpu_luid = gpu_luid
        self.stream_error: str | None = None
        self._find = find
        self._read_memory = read_memory
        self._stream_factory = stream_factory
        self._vram_max_age = vram_max_age
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


def run_benchmark(args: argparse.Namespace) -> int:
    cases = load_cases(Path(args.cases))
    selected = set(args.case or [])
    if selected:
        unknown = selected - {case.id for case in cases}
        if unknown:
            raise ValueError(f"casos desconocidos: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.id in selected]

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
    try:
        with (
            httpx2.Client(timeout=args.timeout, headers=headers) as client,
            output.open("a", encoding="utf-8") as sink,
        ):
            for case in cases:
                content = materialize_case(case)
                prompt_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                for run in range(1, args.runs + 1):
                    payload = {
                        "model": args.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Cumple el formato pedido y no inventes datos.",
                            },
                            {
                                "role": "user",
                                "content": f"{case.instruction}\n\nCONTENIDO:\n{content}",
                            },
                        ],
                        "temperature": 0.0,
                        "seed": args.seed,
                        "max_tokens": case.max_tokens,
                    }
                    if args.reasoning_effort:
                        payload["chat_template_kwargs"] = {
                            "reasoning_effort": args.reasoning_effort
                        }
                    started = time.perf_counter()
                    response_text = ""
                    error: str | None = None
                    usage: dict[str, Any] = {}
                    timings: dict[str, Any] = {}
                    finish_reason: str | None = None
                    with (
                        MetricsSampler(metrics_url, args.sample_interval, headers) as sampler,
                        ResourceSampler(probe, args.sample_interval) as resources,
                    ):
                        try:
                            response = client.post(f"{base_url}/chat/completions", json=payload)
                            response.raise_for_status()
                            data = response.json()
                            choice = data["choices"][0]
                            response_text = str(choice["message"]["content"])
                            finish_reason = choice.get("finish_reason")
                            usage = data.get("usage") or {}
                            timings = data.get("timings") or {}
                        except (
                            httpx2.HTTPError,
                            KeyError,
                            IndexError,
                            TypeError,
                            ValueError,
                        ) as exc:
                            error = f"{type(exc).__name__}: {exc}"
                            if isinstance(exc, httpx2.HTTPStatusError):
                                detail = exc.response.text.strip().replace("\n", " ")[:500]
                                if detail:
                                    error = f"{error} · backend={detail}"
                            failures += 1
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    resource_summary = resources.summary()
                    record: dict[str, Any] = {
                        "schema_version": 1,
                        "ts": datetime.now(UTC).isoformat(),
                        "label": args.label,
                        "model": args.model,
                        "variant": {
                            "quantization": args.quantization,
                            "context_size": args.context_size,
                            "n_cpu_moe": args.n_cpu_moe,
                            "llama_swap_version": args.llama_swap_version,
                            "llama_server_version": args.llama_server_version,
                            "reasoning_effort": args.reasoning_effort,
                            "probe_process": args.probe_process,
                            "gpu_luid": probe.gpu_luid if probe else None,
                        },
                        "case": case.id,
                        "run": run,
                        "thermal_state": "cold" if run == 1 else "hot",
                        "seed": args.seed,
                        "input_chars": len(content),
                        "input_sha256": prompt_hash,
                        "latency_ms": elapsed_ms,
                        "ok": error is None,
                        "error": error,
                        "finish_reason": finish_reason,
                        "usage": usage,
                        "timings": timings,
                        "metrics_peak": sampler.peaks(),
                        "resources": resource_summary,
                        "score": score_response(case, response_text) if not error else None,
                        "response_chars": len(response_text),
                        "response_sha256": hashlib.sha256(
                            response_text.encode("utf-8")
                        ).hexdigest(),
                    }
                    if args.save_responses:
                        record["response"] = response_text
                    sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                    sink.flush()
                    state = "OK" if error is None else "ERROR"
                    annul = resource_summary["annul"]
                    suffix = f" annul={annul}" if annul else ""
                    print(f"[{state}] {case.id} run={run} latency={elapsed_ms}ms{suffix}")
    finally:
        if probe is not None:
            probe.close()
    return 1 if failures else 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "benchmark",
        help="Ejecuta un corpus sintetico contra un backend canary y escribe resultados JSONL.",
    )
    parser.add_argument("--model", required=True, help="id expuesto por el backend canary")
    parser.add_argument(
        "--label", required=True, help="etiqueta de config, p. ej. gptoss-ncmoe12-c8k"
    )
    parser.add_argument("--cases", required=True, help="archivo JSON del corpus versionado")
    parser.add_argument("--case", action="append", help="id de caso a ejecutar (repetible)")
    parser.add_argument("--runs", type=int, default=3, help="corridas por caso (default 3)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--quantization", default=None)
    parser.add_argument("--context-size", type=int, default=None)
    parser.add_argument("--n-cpu-moe", type=int, default=None)
    parser.add_argument("--llama-swap-version", default=None)
    parser.add_argument("--llama-server-version", default=None)
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high"),
        default=None,
        help="chat_template_kwargs para modelos razonadores como gpt-oss",
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
        help="guarda respuestas completas; el corpus incluido es sintetico",
    )
    parser.set_defaults(func=run_benchmark)
