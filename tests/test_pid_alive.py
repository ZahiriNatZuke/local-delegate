"""Issue #483: on Windows `_pid_alive` called a finished process alive.

`OpenProcess` keeps working on a dead PID while anyone holds a handle to its process object, so
the `inflight.json` entries of a dead daemon or stdio process waited the whole 1800 s TTL. Now
only an exit code of `STILL_ACTIVE` counts as alive, and access denied (the PID exists, it is just
not ours) counts as alive too.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time

import pytest

from local_delegate import config, server

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows process handles")


def _finished_process() -> subprocess.Popen:
    """A child that has exited, while the `Popen` still holds the handle to its process object."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    deadline = time.monotonic() + 30
    while proc.poll() is None:
        assert time.monotonic() < deadline, "the child never exited"
        time.sleep(0.05)
    return proc


def _running_process() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


@windows_only
def test_a_finished_process_with_a_held_handle_is_dead():
    proc = _finished_process()
    try:
        # The guard: the handle is still open, which is exactly what fooled `OpenProcess`.
        assert proc._handle  # type: ignore[attr-defined]
        assert server._pid_alive(proc.pid) is False
    finally:
        del proc


def test_a_running_process_is_alive():
    proc = _running_process()
    try:
        assert server._pid_alive(proc.pid) is True
    finally:
        proc.kill()
        proc.wait(timeout=30)


def test_the_own_process_is_alive():
    import os

    assert server._pid_alive(os.getpid()) is True


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    return tmp_path


def test_the_snapshot_prunes_the_entry_of_a_dead_pid(log_dir):
    dead = _finished_process()
    live = _running_process()
    try:
        now = time.time()
        entries = {
            f"{dead.pid}:1": {"pid": dead.pid, "started_at": now, "tool": "local_summarize"},
            f"{live.pid}:1": {"pid": live.pid, "started_at": now, "tool": "local_extract"},
        }
        (log_dir / "inflight.json").write_text(json.dumps(entries), encoding="utf-8")

        snapshot = server.inflight_snapshot()

        # Well inside the TTL: only the dead PID can have removed the first entry.
        assert [e["tool"] for e in snapshot] == ["local_extract"]
        kept = json.loads((log_dir / "inflight.json").read_text(encoding="utf-8"))
        assert set(kept) == {f"{live.pid}:1"}
    finally:
        live.kill()
        live.wait(timeout=30)
        del dead


class _FakeKernel32:
    """Stands in for kernel32 to reach the branches a real process cannot choose."""

    def __init__(self, *, open_error: int = 0, exit_code: int | None = None):
        self.open_error = open_error
        self.exit_code = exit_code
        self.closed: list[int] = []

    def OpenProcess(self, access, inherit, pid):
        if self.open_error:
            ctypes.set_last_error(self.open_error)
            return 0
        return 1234

    def GetExitCodeProcess(self, handle, code_ref):
        if self.exit_code is None:
            return 0
        code_ref._obj.value = self.exit_code
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


@windows_only
@pytest.mark.parametrize(
    ("fake", "alive", "closed"),
    [
        (_FakeKernel32(open_error=5), True, []),  # access denied: it exists, it is not ours
        (_FakeKernel32(open_error=87), False, []),  # invalid parameter: no such PID
        (_FakeKernel32(exit_code=259), True, [1234]),  # STILL_ACTIVE
        (_FakeKernel32(exit_code=0), False, [1234]),  # exited
        (_FakeKernel32(exit_code=None), True, [1234]),  # unreadable: the TTL decides
    ],
)
def test_the_windows_branches(monkeypatch, fake, alive, closed):
    monkeypatch.setattr(server, "_kernel32", lambda: fake)
    assert server._pid_alive_windows(4242) is alive
    assert fake.closed == closed
