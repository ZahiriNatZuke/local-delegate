"""Un fallo de lectura pasajero no se queda en caché hasta que cambia el fichero.

Un antivirus o el indexador abre `test-windows.json` o `backend-params.json` sin compartir justo
cuando el daemon lo lee: `PermissionError`. El fichero no cambia, así que una caché por
`mtime`/tamaño guardaba «sin ventanas» o «sin parámetros» durante días. Como `topology._read`
(REQ-033), solo se cachea lo que dice algo del contenido: un JSON roto sí, un `OSError` no.

Cada caso mira el uso por la función pública (`test_windows.load`, `backend_params.effective`): la
lectura que falla, la siguiente con el fichero ya libre y sin tocar, y el control de que un fallo
permanente sigue en caché (no se relee). En Windows, además, con un cerrojo real de verdad
(`CreateFileW` sin compartir), que es el caso del informe.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from local_delegate import backend_params as bp
from local_delegate import llamaswap_config
from local_delegate import test_windows as tw

START = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("LOCAL_DELEGATE_BACKEND_PARAMS", raising=False)
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (32768, False))
    bp._forget()
    tw._CACHE.clear()
    yield
    bp._forget()
    tw._CACHE.clear()


def _fail_once(monkeypatch, method: str, target: Path, error: type[OSError]) -> list[int]:
    """`Path.<method>` falla una vez con `error` para `target`; devuelve cuántas lecturas hubo."""
    real = getattr(Path, method)
    reads: list[int] = []

    def failing_once(self, *args, **kwargs):
        if Path(self) == target:
            reads.append(1)
            if len(reads) == 1:
                raise error(13, "simulated sharing violation")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, method, failing_once)
    return reads


# --- test_windows ---------------------------------------------------------------------------------


def _one_window(log_dir: Path) -> str:
    return tw.start(log_dir, "probe", now=START).id


def test_windows_transient_failure_is_retried(monkeypatch, tmp_path):
    wid = _one_window(tmp_path)
    reads = _fail_once(monkeypatch, "read_text", tw.path_for(tmp_path), PermissionError)
    first = tw.load(tmp_path)
    assert first.windows == [] and first.error  # the failure is reported, not hidden
    second = tw.load(tmp_path)
    assert [w.id for w in second.windows] == [wid], "el fallo pasajero quedó en caché"
    assert second.error is None
    # Once read well, it is cached as before: no third read.
    tw.load(tmp_path)
    assert len(reads) == 2


def test_windows_broken_file_stays_cached(monkeypatch, tmp_path):
    """Control: un JSON roto dice algo del contenido; se cachea y no se relee."""
    tw.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    tw.path_for(tmp_path).write_text("{ not json", encoding="utf-8")
    real = Path.read_text
    counted: list[int] = []

    def counting(self, *args, **kwargs):
        if Path(self) == tw.path_for(tmp_path):
            counted.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    assert tw.load(tmp_path).error
    assert tw.load(tmp_path).error
    assert len(counted) == 1


# --- backend_params -------------------------------------------------------------------------------


def _write_params(top_k: int) -> Path:
    file = bp.path()
    file.write_text(json.dumps({"version": 1, "roles": {"code": {"top_k": top_k}}}), "utf-8")
    return file


def test_backend_params_transient_failure_is_retried(monkeypatch):
    file = _write_params(20)
    reads = _fail_once(monkeypatch, "read_bytes", file, PermissionError)
    first = bp.effective("code")
    assert first.values == {}
    assert "file_unreadable" in [w.code for w in first.warnings]
    second = bp.effective("code")
    assert second.values == {"top_k": 20}, "el fallo pasajero quedó en caché"
    assert second.warnings == []
    bp.effective("code")
    assert len(reads) == 2


def test_backend_params_broken_file_stays_cached(monkeypatch):
    """Control: un fichero que no es JSON sigue en caché con su `file_unreadable`."""
    file = bp.path()
    file.write_text("{ not json", encoding="utf-8")
    real = Path.read_bytes
    counted: list[int] = []

    def counting(self, *args, **kwargs):
        if Path(self) == file:
            counted.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", counting)
    for _ in range(3):
        assert "file_unreadable" in [w.code for w in bp.effective("code").warnings]
    assert len(counted) == 1


# --- With a real Windows lock (the report's repro) ------------------------------------------------


def _exclusive_lock(path: Path):
    """Abre `path` sin compartir (`share=0`), como un antivirus; devuelve el handle."""
    import ctypes
    import ctypes.wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.HANDLE,
    ]
    generic_read, open_existing = 0x80000000, 3
    handle = kernel32.CreateFileW(str(path), generic_read, 0, None, open_existing, 0, None)
    assert handle not in (None, ctypes.wintypes.HANDLE(-1).value), ctypes.get_last_error()
    return kernel32, handle


@pytest.mark.skipif(sys.platform != "win32", reason="cerrojo de compartición de Windows")
def test_real_lock_on_windows(tmp_path):
    wid = _one_window(tmp_path)
    windows_file = tw.path_for(tmp_path)
    kernel32, handle = _exclusive_lock(windows_file)
    try:
        assert tw.load(tmp_path).windows == []
    finally:
        kernel32.CloseHandle(handle)
    assert [w.id for w in tw.load(tmp_path).windows] == [wid]

    params_file = _write_params(30)
    kernel32, handle = _exclusive_lock(params_file)
    try:
        assert bp.effective("code").values == {}
    finally:
        kernel32.CloseHandle(handle)
    assert bp.effective("code").values == {"top_k": 30}
