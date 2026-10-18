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
from urllib.parse import urlsplit

from .. import config

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


# --- El llama-swap del backend frente a los de las pruebas ----------------------------------------
# Decisión del usuario del 2026-10-18 (B4): «Procesos del backend» no cuenta los `llama-swap.exe`
# que lanzan los tests. `tests/fake_llamaswap.py` lanza el MISMO ejecutable que el backend real, con
# `-listen 127.0.0.1:<puerto libre>`: ni el nombre ni la ruta los distinguen, el puerto sí. El del
# backend es el de `LOCAL_DELEGATE_BASE_URL`; un llama-swap que escucha en otro no es el backend de
# este panel. Sus modelos de prueba son `python.exe` y ya no entraban en la lista.
_LLAMASWAP = "llama-swap"
_LISTEN_RE = re.compile(r"(?:^|\s)--?listen(?:=|\s+)(\S+)")
#: Lo que escucha llama-swap sin `-listen` (`:8080`).
_LLAMASWAP_DEFAULT_PORT = 8080
#: Una línea de órdenes que todavía no se ha leído (la primera muestra está en camino).
PENDING = object()


def listen_port(command_line: str) -> int | None:
    """El puerto de `-listen`/`--listen` (`host:puerto` o `:puerto`) de una línea de órdenes de
    llama-swap; sin la opción, el de por defecto. `None` si el valor no trae un puerto."""
    m = _LISTEN_RE.search(command_line)
    if not m:
        return _LLAMASWAP_DEFAULT_PORT
    _, sep, port = m.group(1).strip("'\"").rpartition(":")
    return int(port) if sep and port.isdigit() else None


def backend_port() -> int | None:
    """El puerto de `LOCAL_DELEGATE_BASE_URL` (el del esquema si no lo lleva)."""
    try:
        parts = urlsplit(config.BASE_URL)
        return parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        return None


# Líneas de órdenes de los llama-swap en Windows: `tasklist` no las da y PowerShell tarda ~1 s, así que
# se leen en un hilo de fondo, como la VRAM. `ok` es `None` hasta la primera muestra y `False` si la
# última falló; `lines` son las de la última muestra (pid -> línea, vacía si no se pudo leer).
_cmd_lock = threading.Lock()
_cmd_cache: dict = {"ok": None, "lines": {}}
_cmd_refreshing = False


def _windows_llamaswap_command_lines() -> dict[int, str] | None:
    order = (
        "Get-CimInstance Win32_Process -Filter \"Name like 'llama-swap%'\" | "
        'ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }'
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", order],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=_CREATE_NO_WINDOW,
    )
    if out.returncode != 0:
        return None
    lines: dict[int, str] = {}
    for line in out.stdout.splitlines():
        pid, _, command_line = line.partition("\t")
        if pid.strip().isdigit():
            lines[int(pid)] = command_line.strip()
    return lines


def _refresh_command_lines() -> None:
    global _cmd_refreshing
    try:
        lines = _windows_llamaswap_command_lines()
    except Exception:  # best-effort, como todo el módulo: sin muestra, se cuentan todos
        lines = None
    with _cmd_lock:
        _cmd_cache["ok"] = lines is not None
        _cmd_cache["lines"] = lines or {}
        _cmd_refreshing = False


def _command_line(pid: int) -> str | object | None:
    """La línea de órdenes de `pid`, `None` si no se puede saber, o `PENDING` mientras se lee."""
    global _cmd_refreshing
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                return f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip() or None
        except OSError:
            return None
    if sys.platform != "win32":
        return None
    with _cmd_lock:
        lines, ok = _cmd_cache["lines"], _cmd_cache["ok"]
        if pid in lines:
            return lines[pid] or None
        # Un llama-swap que la última muestra no vio (recién lanzado): se pide otra en fondo.
        if not _cmd_refreshing:
            _cmd_refreshing = True
            threading.Thread(target=_refresh_command_lines, daemon=True, name="cmdline").start()
    return None if ok is False else PENDING


def is_backend_llamaswap(pid: int, port: int | None) -> bool:
    """¿Es este llama-swap el del backend? Sí si escucha en `port`; si su línea de órdenes no se
    puede leer, se cuenta (como antes de esta regla); mientras se lee, todavía no."""
    line = _command_line(pid)
    if line is PENDING:
        return False
    if line is None or port is None:
        return True
    return listen_port(str(line)) == port


def _all_processes() -> list[dict] | None:
    """Todos los procesos de la máquina, o `None` si esta plataforma no los lista."""
    if sys.platform == "win32":
        return _windows_processes()
    if sys.platform.startswith("linux"):
        return _linux_processes()
    return None


def interesting_processes() -> list[dict]:
    """Procesos del backend local (llama-*, ollama…) + el propio MCP, con RAM y VRAM.

    Cada entrada: {pid, name, ram_mb, vram_mb (o None), self (bool)}. Lista vacía si la
    plataforma no está soportada o la enumeración falló. Un llama-swap que no escucha en el puerto
    del backend (los que lanzan los tests) no entra (`is_backend_llamaswap`).
    """
    try:
        all_procs = _all_processes()
    except Exception:
        return []
    if all_procs is None:
        return []
    self_pid = os.getpid()
    vram_map = proc_vram_map()
    port = backend_port()
    picked: list[dict] = []
    for p in all_procs:
        lname = p["name"].lower()
        is_self = p["pid"] == self_pid
        if not is_self and not any(k in lname for k in _PROC_KEYWORDS):
            continue
        if not is_self and _LLAMASWAP in lname and not is_backend_llamaswap(p["pid"], port):
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
