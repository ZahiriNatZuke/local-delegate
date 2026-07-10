"""sysinfo.py — métricas de sistema estructuradas para la web (RAM, VRAM, procesos).

Todo es best-effort y de solo lectura: cualquier fallo (binario ausente, plataforma no
soportada, salida inesperada) devuelve None/lista vacía y nunca propaga. Pensado para el
endpoint /api/system del dashboard; complementa las líneas de texto de local_status.

La VRAM por proceso es cara de medir en Windows (WDDM no la expone vía nvidia-smi, hay que
leer los perf counters "GPU Process Memory", ~1-2 s por muestra), así que se refresca en un
hilo de fondo con TTL: el endpoint siempre responde al instante con el último valor conocido.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time

# Procesos "interesantes" para el dashboard: los backends locales típicos que corren por
# debajo del MCP. El propio proceso (el MCP que sirve esta web) se añade siempre por pid.
_PROC_KEYWORDS = ("llama", "ollama", "vllm", "lmstudio", "lm-studio", "koboldcpp")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def ram_stats() -> dict | None:
    """RAM de sistema: {used_gb, total_gb, free_gb, pct}. None si no se pudo leer."""
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
            total = stat.ullTotalPhys / 1024**3
            free = stat.ullAvailPhys / 1024**3
        elif sys.platform.startswith("linux"):
            info: dict[str, str] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    key, _, rest = line.partition(":")
                    info[key] = rest.strip()
            total = float(info["MemTotal"].split()[0]) / 1024**2
            avail_raw = info.get("MemAvailable", info.get("MemFree", "0"))
            free = float(avail_raw.split()[0]) / 1024**2
        else:
            return None
    except Exception:
        return None
    used = total - free
    return {
        "used_gb": round(used, 1),
        "total_gb": round(total, 1),
        "free_gb": round(free, 1),
        "pct": round(100 * used / total, 1) if total else 0.0,
    }


def vram_stats() -> dict | None:
    """VRAM de la primera GPU vía nvidia-smi: {used_mb, total_mb, pct, gpu_util_pct}."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    parts = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
    if len(parts) != 3:
        return None
    try:
        used_mb, total_mb, util = float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None
    return {
        "used_mb": round(used_mb),
        "total_mb": round(total_mb),
        "pct": round(100 * used_mb / total_mb, 1) if total_mb else 0.0,
        "gpu_util_pct": round(util),
    }


# --- Procesos (RAM por proceso vía tasklist / /proc) --------------------------
_TASKLIST_ROW_RE = re.compile(r'^"(?P<name>[^"]+)","(?P<pid>\d+)",".*?",".*?","(?P<mem>[^"]*)"')


def _windows_processes() -> list[dict]:
    out = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=_CREATE_NO_WINDOW,
    )
    if out.returncode != 0:
        return []
    procs: list[dict] = []
    for line in out.stdout.splitlines():
        m = _TASKLIST_ROW_RE.match(line.strip())
        if not m:
            continue
        mem_digits = re.sub(r"\D", "", m.group("mem"))  # "1.234.567 K" -> 1234567 (KiB)
        procs.append(
            {
                "pid": int(m.group("pid")),
                "name": m.group("name"),
                "ram_mb": round(int(mem_digits or 0) / 1024),
            }
        )
    return procs


def _linux_processes() -> list[dict]:
    procs: list[dict] = []
    proc_root = "/proc"
    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        try:
            with open(f"{proc_root}/{entry}/comm", encoding="utf-8") as f:
                name = f.read().strip()
            rss_kb = 0
            with open(f"{proc_root}/{entry}/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        break
            procs.append({"pid": int(entry), "name": name, "ram_mb": round(rss_kb / 1024)})
        except (OSError, ValueError, IndexError):
            continue
    return procs


def interesting_processes() -> list[dict]:
    """Procesos del backend local (llama-*, ollama…) + el propio MCP, con RAM y VRAM.

    Cada entrada: {pid, name, ram_mb, vram_mb (o None), self (bool)}. Lista vacía si la
    plataforma no está soportada o la enumeración falló.
    """
    try:
        if sys.platform == "win32":
            all_procs = _windows_processes()
        elif sys.platform.startswith("linux"):
            all_procs = _linux_processes()
        else:
            return []
    except Exception:
        return []
    self_pid = os.getpid()
    vram_map = proc_vram_map()
    picked: list[dict] = []
    for p in all_procs:
        lname = p["name"].lower()
        is_self = p["pid"] == self_pid
        if not is_self and not any(k in lname for k in _PROC_KEYWORDS):
            continue
        picked.append(
            {
                **p,
                "vram_mb": vram_map.get(p["pid"]),
                "self": is_self,
            }
        )
    # el MCP primero, luego por RAM descendente (los llama-server grandes arriba)
    picked.sort(key=lambda p: (not p["self"], -p["ram_mb"]))
    return picked


# --- VRAM por proceso (cache TTL + refresco en hilo de fondo) -----------------
_VRAM_TTL_S = 15.0
_vram_lock = threading.Lock()
_vram_cache: dict = {"ts": 0.0, "data": {}}
_vram_refreshing = False


def _nvidia_smi_proc_vram() -> dict[int, int] | None:
    """pid -> MiB vía nvidia-smi compute-apps. None si no da números (WDDM en Windows)."""
    out = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=3,
        creationflags=_CREATE_NO_WINDOW,
    )
    if out.returncode != 0:
        return None
    result: dict[int, int] = {}
    any_numeric = False
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            result[int(parts[0])] = int(float(parts[1]))
            any_numeric = True
        except ValueError:
            continue  # "[N/A]" en WDDM
    return result if any_numeric else None


_PERF_INSTANCE_RE = re.compile(r"pid_(\d+)_")


def _windows_perfcounter_proc_vram() -> dict[int, int]:
    """pid -> MiB vía perf counters de Windows (WDDM). Lento (~2 s), solo desde el hilo TTL."""
    cmd = (
        "(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' -ErrorAction Stop)"
        ".CounterSamples | Where-Object CookedValue -gt 0 | ForEach-Object "
        "{ '{0} {1}' -f $_.InstanceName, $_.CookedValue }"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=_CREATE_NO_WINDOW,
    )
    if out.returncode != 0:
        return {}
    result: dict[int, int] = {}
    for line in out.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        m = _PERF_INSTANCE_RE.search(parts[0])
        if not m:
            continue
        try:
            pid, byts = int(m.group(1)), float(parts[1])
        except ValueError:
            continue
        result[pid] = result.get(pid, 0) + round(byts / 1024**2)
    return result


def _refresh_vram_map() -> None:
    global _vram_refreshing
    data: dict[int, int] = {}
    try:
        smi = _nvidia_smi_proc_vram()
        if smi is not None:
            data = smi
        elif sys.platform == "win32":
            data = _windows_perfcounter_proc_vram()
    except Exception:
        data = {}
    with _vram_lock:
        _vram_cache["ts"] = time.monotonic()
        _vram_cache["data"] = data
        _vram_refreshing = False


def proc_vram_map() -> dict[int, int]:
    """pid -> VRAM en MiB, del último muestreo. Dispara un refresco en fondo si caducó."""
    global _vram_refreshing
    with _vram_lock:
        stale = time.monotonic() - _vram_cache["ts"] > _VRAM_TTL_S
        if stale and not _vram_refreshing:
            _vram_refreshing = True
            threading.Thread(target=_refresh_vram_map, daemon=True, name="vram-sample").start()
        return dict(_vram_cache["data"])
