"""Issue #576: a daemon whose listening socket died must not stay alive holding the singleton.

Two halves. The end-to-end tests run a REAL daemon (`daemon.serve`) in a child process, with its
own port and `LOCAL_DELEGATE_LOG_DIR` in `tmp_path`: they never touch the user's daemon, its port or
its state folder. The unit tests pin the decision of relieving a registered daemon, which must
never fire on a daemon that is only slow.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from filelock import FileLock

import local_delegate
from local_delegate import checks, config, daemon, server

_SRC = str(Path(local_delegate.__file__).resolve().parents[1])
#: Bound on how long a child may take to do what the test expects. Without the fix, the daemon of
#: the first tests never exits: the bound is what turns that hang into a failure.
_CAP_S = 40.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _environment(home: Path, log_dir: Path) -> dict:
    """From scratch, as in `test_two_machines`: a home and a state folder in `tmp_path`."""
    env = {
        name: os.environ[name]
        for name in ("SystemRoot", "SYSTEMROOT", "PATH", "TEMP", "TMP", "TMPDIR")
        if name in os.environ
    }
    for name in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME"):
        env[name] = str(home)
    home.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "PYTHONPATH": _SRC,
            "PYTHONIOENCODING": "utf-8",
            "LOCAL_DELEGATE_LANG": "es",
            "LOCAL_DELEGATE_LOG_DIR": str(log_dir),
            "LOCAL_DELEGATE_LOG": str(log_dir / "usage.jsonl"),
            "LOCAL_DELEGATE_WEB_TOKEN": "",
            # A backend nobody answers: the daemon starts without one, and nothing goes out.
            "LOCAL_DELEGATE_BASE_URL": "http://127.0.0.1:9/v1",
        }
    )
    return env


@contextmanager
def _child(args: list[str], env: dict, log: Path):
    """A child process that is always stopped at the end (terminate → wait → kill)."""
    with log.open("wb") as sink:
        process = subprocess.Popen(
            [sys.executable, *args], env=env, stdout=sink, stderr=subprocess.STDOUT
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(10)


def _wait_listening(port: int, process: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + _CAP_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"the daemon exited early: {log.read_text('utf-8', 'replace')}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("the daemon never listened")


# The child: the real `daemon.serve`, with uvicorn's `startup` wrapped to break the listener once
# it is up. Nothing of the daemon is replaced; only the way the socket dies is staged.
_BREAKER = textwrap.dedent(
    """
    import asyncio, socket, struct, sys, threading, time
    from local_delegate import daemon

    mode, port = sys.argv[1], int(sys.argv[2])
    original = daemon.uvicorn.Server.startup

    def reset_burst():
        # Connections that reset while they wait in the backlog: on Windows their `accept` fails
        # with WinError 64 and asyncio closes the listening socket for good (issue #576).
        sockets = []
        for _ in range(200):
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            try:
                s.connect(("127.0.0.1", port))
            except OSError:
                break
            sockets.append(s)
        for s in sockets:
            s.close()

    def block_the_loop():
        worker = threading.Thread(target=reset_burst)
        worker.start()
        time.sleep(0.3)
        worker.join()

    async def startup(self, sockets=None):
        await original(self, sockets)
        loop = asyncio.get_running_loop()
        if mode == "close":
            listener = self.servers[0]._sockets[0]
            # Selector loops reject a second stop of a closed socket (uvicorn's own close):
            # only the first one, the staged failure, reaches the loop.
            stop = loop._stop_serving
            loop._stop_serving = lambda sock: stop(sock) if sock.fileno() != -1 else None
            loop.call_later(0.5, stop, listener)
        else:
            for delay in (0.5, 1.5, 2.5, 3.5, 4.5):
                loop.call_later(delay, block_the_loop)

    daemon.uvicorn.Server.startup = startup
    sys.exit(daemon.serve("127.0.0.1", port))
    """
)


def _run_breaker(tmp_path: Path, mode: str) -> tuple[int, Path]:
    script = tmp_path / "breaker.py"
    script.write_text(_BREAKER, encoding="utf-8")
    log_dir = tmp_path / "state"
    port = _free_port()
    log = tmp_path / "child.log"
    with _child(
        [str(script), mode, str(port)], _environment(tmp_path / "home", log_dir), log
    ) as process:
        try:
            code = process.wait(_CAP_S)
        except subprocess.TimeoutExpired:
            raise AssertionError(
                "the daemon stayed alive after losing its listener (issue #576)"
            ) from None
    return code, log_dir


def _assert_left_cleanly(log_dir: Path) -> None:
    assert not (log_dir / "daemon.json").exists(), "daemon.json must not point at a dead daemon"
    lock = FileLock(str(log_dir / "daemon.lock"))
    lock.acquire(timeout=0)  # raises if the singleton were still held
    lock.release()


def test_a_daemon_whose_listener_closes_exits_with_an_error_and_says_why(tmp_path):
    code, log_dir = _run_breaker(tmp_path, "close")

    assert code == daemon.EXIT_LISTENER_DIED
    _assert_left_cleanly(log_dir)
    trace = (log_dir / daemon.ERROR_LOG_NAME).read_text(encoding="utf-8")
    assert "listening socket closed" in trace


@pytest.mark.skipif(sys.platform != "win32", reason="the ProactorEventLoop failure is Windows-only")
def test_resets_in_the_backlog_do_not_take_the_listener_down_on_windows(tmp_path):
    """The failure of #576 as it happens, not staged: clients that reset before being accepted.

    Without the tolerant accept the first burst closes the listener (WinError 64) and the daemon
    stops serving everybody; with it, the daemon keeps listening through five bursts.
    """
    script = tmp_path / "breaker.py"
    script.write_text(_BREAKER, encoding="utf-8")
    log_dir = tmp_path / "state"
    port = _free_port()
    log = tmp_path / "child.log"
    env = _environment(tmp_path / "home", log_dir)
    errors = log_dir / daemon.ERROR_LOG_NAME

    def read_trace() -> str:
        return errors.read_text(encoding="utf-8", errors="replace") if errors.exists() else ""

    with _child([str(script), "resets", str(port)], env, log) as process:
        _wait_listening(port, process, log)
        time.sleep(6.0)  # the five bursts go off between 0.5 s and 4.5 s after startup
        assert process.poll() is None, (
            f"the daemon stopped (exit {process.returncode}): {read_trace()}"
        )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                pass
        except OSError as exc:
            raise AssertionError(f"the listener is gone ({exc}): {read_trace()[-4000:]}") from None
        assert daemon.query_daemon("127.0.0.1", port, timeout=5.0) is not None, read_trace()[-4000:]
    trace = read_trace()
    assert "Accept failed on a socket" not in trace, trace
    assert "never retrieved" not in trace, "tolerated resets must not flood the error log"


class _WinError(OSError):
    """An `OSError` with a `winerror`, on any platform (only Windows gives it one natively)."""

    def __init__(self, winerror: int) -> None:
        super().__init__(f"winerror {winerror}")
        self.winerror = winerror


class _FakeListener:
    def fileno(self) -> int:
        return 7


def _tolerant_accept(script: list, delays: list | None = None):
    """A proactor whose `accept` plays ``script``: an exception raised now, one in the future, or a
    result. Returns the tolerant `accept` installed on it, the loop and the attempts made. The waits
    asked of `call_later` go to ``delays`` and are not waited for real."""
    import asyncio
    import types

    loop = asyncio.new_event_loop()
    attempts = []

    def accept(_listener):
        step = script[min(len(attempts), len(script) - 1)]
        attempts.append(step)
        kind, value = step
        if kind == "raise":
            raise value
        future = loop.create_future()
        if kind == "fail":
            future.set_exception(value)
        else:
            future.set_result(value)
        return future

    def call_later(delay, callback):
        if delays is not None:
            delays.append(delay)
        return loop.call_soon(callback)

    proactor = types.SimpleNamespace(accept=accept)
    fake_loop = types.SimpleNamespace(
        _proactor=proactor,
        create_future=loop.create_future,
        call_soon=loop.call_soon,
        call_later=call_later,
    )
    assert daemon._tolerate_accept_resets(fake_loop) is True
    assert daemon._tolerate_accept_resets(fake_loop) is False  # idempotent
    return proactor.accept, loop, attempts


def _settle(loop, future):
    try:
        return loop.run_until_complete(future)
    finally:
        loop.close()


def test_an_accept_that_fails_synchronously_is_retried():
    """Unhandled, a synchronous failure left the accept pending forever: nobody accepted again."""
    accept, loop, attempts = _tolerant_accept(
        [("raise", _WinError(64)), ("fail", _WinError(64)), ("ok", ("conn", "addr"))]
    )
    assert _settle(loop, accept(_FakeListener())) == ("conn", "addr")
    assert len(attempts) == 3


def test_client_resets_are_retried_without_a_cap():
    """A burst of 300 resets is 300 failures in a row of one accept: none of them is the listener's."""
    accept, loop, attempts = _tolerant_accept([("fail", _WinError(64))] * 300 + [("ok", "conn")])
    assert _settle(loop, accept(_FakeListener())) == "conn"
    assert len(attempts) == 301


def test_other_errors_give_the_listener_up_after_the_cap():
    """A listener that fails for its own reasons must not spin forever: asyncio gets the error."""
    delays = []
    accept, loop, attempts = _tolerant_accept([("fail", _WinError(10022))], delays)
    with pytest.raises(OSError):
        _settle(loop, accept(_FakeListener()))
    assert len(attempts) == daemon._ACCEPT_RETRIES + 1


def test_other_errors_are_retried_with_a_growing_wait():
    """Fifty retries in microseconds are not retries: the wait doubles up to one second."""
    delays = []
    accept, loop, _attempts = _tolerant_accept([("fail", _WinError(10022))], delays)
    with pytest.raises(OSError):
        _settle(loop, accept(_FakeListener()))
    first, top = daemon._ACCEPT_BACKOFF_S
    assert delays[:3] == [first, first * 2, first * 4]
    assert max(delays) == top and delays == sorted(delays)
    assert sum(delays) > 30, "the cap must stand for tens of seconds, not microseconds"


def test_client_resets_are_retried_at_once():
    """A reset needs a real client to happen again: no reason to make the next client wait."""
    delays = []
    accept, loop, _attempts = _tolerant_accept(
        [("fail", _WinError(64))] * 5 + [("ok", "c")], delays
    )
    assert _settle(loop, accept(_FakeListener())) == "c"
    assert delays == []


# A process that holds the singleton and is registered on a port nobody listens on: what the
# daemon of #576 looked like from outside.
_ZOMBIE = textwrap.dedent(
    """
    import json, os, sys, time
    from pathlib import Path
    from filelock import FileLock

    state, port = Path(sys.argv[1]), int(sys.argv[2])
    lock = FileLock(str(state / "daemon.lock"))
    lock.acquire(timeout=0)
    (state / "daemon.json").write_text(json.dumps({
        "service": "local-delegate", "mode": "daemon", "pid": os.getpid(),
        "host": "127.0.0.1", "port": port, "started_at": int(time.time()),
    }), encoding="utf-8")
    print(f"ready {os.getpid()}", flush=True)
    time.sleep(600)
    """
)


_SERVE_NOW = textwrap.dedent(
    """
    import sys
    from local_delegate import cli, daemon

    daemon._RELIEF_GRACE_SECONDS = 0
    sys.exit(cli.run(["serve", "--host", "127.0.0.1", "--port", sys.argv[1]]))
    """
)


@pytest.mark.skipif(
    not (sys.platform == "win32" or sys.platform.startswith("linux")),
    reason="the age of a process is only read on Windows and Linux; elsewhere no relief",
)
def test_serve_relieves_a_registered_daemon_that_no_longer_listens(tmp_path):
    log_dir = tmp_path / "state"
    env = _environment(tmp_path / "home", log_dir)
    port = _free_port()
    zombie_script = tmp_path / "zombie.py"
    zombie_script.write_text(_ZOMBIE, encoding="utf-8")
    zombie_log = tmp_path / "zombie.log"
    serve_log = tmp_path / "serve.log"

    with _child([str(zombie_script), str(log_dir), str(port)], env, zombie_log) as zombie:
        deadline = time.monotonic() + _CAP_S
        while not zombie_log.read_bytes().endswith(b"\n"):
            assert zombie.poll() is None and time.monotonic() < deadline, "the zombie never started"
            time.sleep(0.05)
        # The pid the zombie registered: on Windows `zombie.pid` is the venv launcher's.
        zombie_pid = int(zombie_log.read_text(encoding="utf-8").split()[1])

        # The real `serve`, with the one-minute grace taken away: the zombie is seconds old.
        serve_script = tmp_path / "serve.py"
        serve_script.write_text(_SERVE_NOW, encoding="utf-8")
        args = [str(serve_script), str(port)]
        with _child(args, env, serve_log) as fresh:
            _wait_listening(port, fresh, serve_log)
            assert zombie.wait(_CAP_S) is not None, "the zombie must have been stopped"
            state = json.loads((log_dir / "daemon.json").read_text(encoding="utf-8"))
            # The pid of the venv's `python.exe` is a launcher's on Windows: the daemon says its own.
            answering = daemon.query_daemon("127.0.0.1", port, timeout=5.0)
            assert answering is not None and answering["pid"] == state["pid"] != zombie_pid
    trace = (log_dir / daemon.ERROR_LOG_NAME).read_text(encoding="utf-8")
    assert f"relieving daemon pid={zombie_pid}" in trace


# --- The decision of relieving: never a daemon that might be working --------------------------


def _register(tmp_path, monkeypatch, *, pid=4242, started_ago=3600, port=19876):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    started_at = int(time.time()) - started_ago
    monkeypatch.setattr(daemon, "_process_started_at", lambda _pid: started_at - 2)
    (tmp_path / "daemon.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "host": "127.0.0.1",
                "port": port,
                "started_at": started_at,
            }
        ),
        encoding="utf-8",
    )


def test_an_alive_old_daemon_whose_port_refuses_is_stale(tmp_path, monkeypatch):
    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "_refuses_connections", lambda host, port: True)

    assert daemon.stale_registration()["pid"] == 4242


def test_a_daemon_that_accepts_connections_is_never_stale(tmp_path, monkeypatch):
    """Slow is not dead: the kernel accepts the connection even if the process never answers."""
    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "_refuses_connections", lambda host, port: False)

    assert daemon.stale_registration() is None


def test_a_daemon_that_just_started_is_never_stale(tmp_path, monkeypatch):
    """It holds the lock and may not have bound its port yet."""
    _register(tmp_path, monkeypatch, started_ago=5)
    monkeypatch.setattr(server, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "_refuses_connections", lambda host, port: True)

    assert daemon.stale_registration() is None


def test_a_dead_process_is_not_relieved(tmp_path, monkeypatch):
    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(daemon, "_refuses_connections", lambda host, port: True)

    assert daemon.stale_registration() is None


def test_a_registration_rewritten_meanwhile_is_not_relieved(tmp_path, monkeypatch):
    """Another daemon started while the port was probed: the old reading no longer holds."""
    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_pid_alive", lambda pid: True)

    def refuses_while_another_starts(host, port):
        _register(tmp_path, monkeypatch, pid=5151)
        return True

    monkeypatch.setattr(daemon, "_refuses_connections", refuses_while_another_starts)

    assert daemon.stale_registration() is None


def test_a_pid_reused_by_another_process_is_never_relieved(tmp_path, monkeypatch):
    """The daemon died, its pid went to someone else: that someone was created after it registered."""
    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(daemon, "_process_started_at", lambda _pid: time.time())
    monkeypatch.setattr(server, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "_refuses_connections", lambda host, port: True)

    assert daemon.stale_registration() is None


def test_a_process_whose_age_cannot_be_told_is_never_relieved(tmp_path, monkeypatch):
    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(daemon, "_process_started_at", lambda _pid: None)
    monkeypatch.setattr(server, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "_refuses_connections", lambda host, port: True)

    assert daemon.stale_registration() is None


def test_the_creation_time_of_this_very_process_is_read(tmp_path):
    """The guard above is only worth something if the real reading works where #576 happens."""
    created = daemon._process_started_at(os.getpid())
    if sys.platform == "win32" or sys.platform.startswith("linux"):
        assert created is not None and 0 < time.time() - created < 24 * 3600
    else:
        assert created is None


def test_only_a_refusal_counts_as_nobody_listening(monkeypatch):
    def timing_out(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(daemon.socket, "create_connection", timing_out)
    assert daemon._refuses_connections("127.0.0.1", 1, pause=0) is False

    def refusing(*_args, **_kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(daemon.socket, "create_connection", refusing)
    assert daemon._refuses_connections("127.0.0.1", 1, pause=0) is True


def test_the_shutdown_is_bounded_and_the_listener_is_watched(tmp_path, monkeypatch):
    """Without a bound, uvicorn closes the listener and waits forever for open MCP streams."""
    seen = {}

    class FakeUvicornServer:
        started = True

        def __init__(self, uvicorn_config):
            seen["config"] = uvicorn_config

        def run(self):
            pass

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTOSTART", False)
    monkeypatch.setattr(daemon, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(daemon.uvicorn, "Server", FakeUvicornServer)

    assert daemon.serve("127.0.0.1", 19393) == 0
    cfg = seen["config"]
    assert cfg.timeout_graceful_shutdown is not None and cfg.timeout_graceful_shutdown > 0
    assert isinstance(cfg.callback_notify, daemon._ListenerWatch)


# --- doctor -------------------------------------------------------------------------------------


def _probe(tmp_path, monkeypatch, registration):
    monkeypatch.setattr(config, "WEB_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "WEB_PORT", 19877)
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: False)
    ctx = checks.Context(
        home=tmp_path,
        daemon_status=lambda host, port: None,
        daemon_registration=lambda: registration,
    )
    return checks._probe_daemon(ctx)


def test_doctor_does_not_blame_a_process_that_reused_the_pid(tmp_path, monkeypatch):
    """A daemon killed without its cleanup leaves `daemon.json`; Windows gives its pid to another."""
    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon, "_process_started_at", lambda _pid: time.time())
    assert daemon.registered_process() is None
    monkeypatch.setattr(daemon, "_process_started_at", lambda _pid: None)  # cannot tell (macOS)
    assert daemon.registered_process() is None


def test_doctor_sees_the_registered_daemon_when_it_is_still_that_process(tmp_path, monkeypatch):
    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_pid_alive", lambda pid: True)
    assert daemon.registered_process()["pid"] == 4242


def test_doctor_tells_an_alive_daemon_without_listener_from_no_daemon(tmp_path, monkeypatch):
    result = _probe(tmp_path, monkeypatch, {"pid": 4242, "host": "127.0.0.1", "port": 19877})

    assert result.status == checks.WARN
    assert "4242" in result.detail and "sigue vivo" in result.detail


def test_doctor_without_a_live_registration_still_says_nobody(tmp_path, monkeypatch):
    assert _probe(tmp_path, monkeypatch, None).status == checks.MISSING
    other_port = {"pid": 4242, "host": "127.0.0.1", "port": 9393}
    assert _probe(tmp_path, monkeypatch, other_port).status == checks.MISSING
