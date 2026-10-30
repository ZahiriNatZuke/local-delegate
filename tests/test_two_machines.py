"""Concurrency PC+Mac, lot 4: two «machines» in one, with two processes (REQ-020..026, REQ-031).

- The backend: `fake_switching_backend.FakeSwitchingBackend`, a llama-swap stand-in in a thread of
  this test, with two models that clash (`model-x`, `model-y`).
- «PC»: a child process running `daemon.serve` on a free port, with the topology of the fake
  backend (both models in one `swap` group) and `MACHINE_NAME=pc-test`.
- «Mac»: a child process that imports `local_delegate.server` with `MACHINE_NAME=mac-test`, the
  same backend, NO topology and `TURN_URL` naming the PC's daemon (the tunnel case: a loopback
  backend that counts as remote; the guard «to itself» does not fire because the port is not its
  `WEB_PORT` and the `daemon_id` differs). It runs operations of many chunks of `model-x`.
- The test asks the PC's daemon over `/mcp` for an operation of `model-y`.

Each child starts with `sys.executable` (the venv's) WITHOUT `-I`, through a launcher that puts
this checkout's `src` first on `sys.path` and checks that `local_delegate` comes from there (exit
code 3 otherwise), and with an environment built from scratch: no token, Keychain or real log of
whoever runs the suite can leak in. Every child is stopped in a `finally` (terminate → wait(10) →
kill) and checked dead by PID; every wait has a cap, and the whole test 120 s.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx2
import pytest
from conftest import REAL_HOME
from fake_switching_backend import FakeSwitchingBackend

from local_delegate import config, server

pytestmark = pytest.mark.xdist_group("two_machines")

SRC = Path(__file__).resolve().parent.parent / "src"
X = "model-x"
Y = "model-y"
API_KEY = "two-machines-test-key-0123456789"
TEST_CAP_S = 120.0
TURN_YIELD_S = 2.0
TURN_LEASE_S = 3.0  # heartbeat every 1 s
HTTP_TIMEOUT_S = 10.0
LOAD_S = 0.05
#: Markers of this test that must never reach a real file of the user.
MARKERS = (X, Y, "pc-test", "mac-test")

LAUNCHER = textwrap.dedent(
    """
    import json, sys, threading, time
    from pathlib import Path

    src = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(src))
    try:
        import local_delegate
    except ImportError as error:
        sys.stderr.write(f"local_delegate not importable: {error}\\n")
        sys.exit(3)
    if not Path(local_delegate.__file__).resolve().is_relative_to(src):
        sys.stderr.write(f"local_delegate from {local_delegate.__file__}, not under {src}\\n")
        sys.exit(3)
    role = sys.argv[2]
    if role == "pc":
        from local_delegate import daemon
        sys.exit(daemon.serve("127.0.0.1", int(sys.argv[3])))

    from local_delegate import config, server

    config.LONG_INPUT_CHARS = 1000
    config.MAX_CHARS_BY_ROLE["long"] = 1000
    out, stop, mode = Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5]
    results = []
    lock = threading.Lock()

    def one(paragraphs):
        text = "\\n\\n".join(f"p{i} " + ("palabra " * 75).strip() for i in range(paragraphs))
        try:
            server.local_summarize(text=text)
            outcome = "ok"
        except Exception as error:
            outcome = repr(error)
        with lock:
            results.append(outcome)

    if mode == "parallel":
        threads = [threading.Thread(target=one, args=(40,)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(100)
    else:  # loop: short operations, one after another, until the test says stop
        end = time.monotonic() + 90
        while not stop.exists() and time.monotonic() < end:
            one(3)
    out.write_text(json.dumps(results), encoding="utf-8")
    """
)


class Deadline:
    def __init__(self, seconds: float) -> None:
        self.end = time.monotonic() + seconds

    def left(self, cap: float) -> float:
        remaining = self.end - time.monotonic()
        assert remaining > 0, f"the test went past its {TEST_CAP_S:.0f} s cap"
        return min(cap, remaining)


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _until(condition: Callable[[], object], cap: float, deadline: Deadline, what: str) -> object:
    end = time.monotonic() + deadline.left(cap)
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"{what} (after {cap:.0f} s)")


def _environment(home: Path, log_dir: Path, machine: str, backend: str, **extra: str) -> dict:
    """From scratch: only what the system needs, a home in `tmp_path` and the test's variables."""
    env = {
        name: os.environ[name]
        for name in ("SystemRoot", "SYSTEMROOT", "PATH", "TEMP", "TMP", "TMPDIR")
        if name in os.environ
    }
    for name in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME"):
        env[name] = str(home)
    log_dir.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "LOCAL_DELEGATE_LANG": "es",
            "LOCAL_DELEGATE_LOG_DIR": str(log_dir),
            "LOCAL_DELEGATE_LOG": str(log_dir / "usage.jsonl"),
            "LOCAL_DELEGATE_MACHINE_NAME": machine,
            "LOCAL_DELEGATE_API_KEY": API_KEY,
            "LOCAL_DELEGATE_WEB_TOKEN": "",
            "LOCAL_DELEGATE_BASE_URL": backend,
            "LOCAL_DELEGATE_MODEL_LONG": X,
            "LOCAL_DELEGATE_MODEL_MECHANICAL": Y,
            "LOCAL_DELEGATE_FALLBACK": "off",
            "LOCAL_DELEGATE_TURN_YIELD_S": str(TURN_YIELD_S),
            "LOCAL_DELEGATE_TURN_LEASE_S": str(TURN_LEASE_S),
            "LOCAL_DELEGATE_TIMEOUT": str(HTTP_TIMEOUT_S),
        }
    )
    env.update(extra)
    return env


@contextmanager
def _child(args: list[str], env: dict, log: Path) -> Iterator[subprocess.Popen]:
    """A child process that is always stopped: terminate → wait(10) → kill, then checked by PID."""
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
            assert not server._pid_alive(process.pid), f"child {process.pid} is still alive"


def _topology_yaml(path: Path) -> Path:
    path.write_text(
        textwrap.dedent(
            f"""
            models:
              {X}:
                cmd: 'fake --port ${{PORT}}'
              {Y}:
                cmd: 'fake --port ${{PORT}}'
            groups:
              swap:
                swap: true
                exclusive: false
                members:
                - {X}
                - {Y}
            """
        ),
        encoding="utf-8",
    )
    return path


def _events(log_dir: Path) -> list[dict]:
    events: list[dict] = []
    for file in sorted(log_dir.glob("usage*.jsonl")):
        events += [json.loads(x) for x in file.read_text(encoding="utf-8").splitlines() if x]
    return events


def _real_files() -> dict[Path, int]:
    """The real files a run could dirty, with their size now (0 when absent)."""
    data = config._default_log_dir()
    paths = [REAL_HOME / ".claude.json", data / "inflight.json"]
    paths += sorted(data.glob("usage*.jsonl"))
    return {p: (p.stat().st_size if p.exists() else 0) for p in paths}


def _assert_real_files_clean(before: dict[Path, int]) -> None:
    """None of this test's markers in the real files (in what a log gained since `before`).

    Not a hash: the user's own daemon and Claude Code write these files while the suite runs.
    """
    for path, size in before.items():
        if not path.exists():
            continue
        data = path.read_bytes()
        if path.suffix == ".jsonl":
            data = data[size:]
        text = data.decode("utf-8", errors="replace")
        found = [m for m in MARKERS if m in text]
        assert not found, f"{path} got {found}: the test reached a real file"


def _together(rows: list[dict]) -> list[dict] | None:
    """The rows, if they hold the PC's own operation and the Mac's at the same time."""
    local = any(r.get("tool") == "local_classify" and not r.get("host") for r in rows)
    remote = any(r.get("host") == "mac-test" for r in rows)
    return rows if local and remote else None


class _Pc:
    def __init__(self, port: int) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"

    def inflight(self) -> list[dict]:
        try:
            response = httpx2.get(f"{self.base}/api/inflight", timeout=2.0)
        except httpx2.HTTPError:
            return []
        return response.json().get("inflight", []) if response.status_code == 200 else []

    def alive(self) -> bool:
        try:
            return httpx2.get(f"{self.base}/api/daemon", timeout=1.0).status_code == 200
        except httpx2.HTTPError:
            return False

    def classify(self) -> dict | None:
        """One `local_classify` (model-y) through the daemon's `/mcp`."""
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Mcp-Protocol-Version": "2025-06-18",
        }
        url = f"{self.base}/mcp"
        timeout = httpx2.Timeout(60.0, connect=5.0)
        with httpx2.Client(timeout=timeout) as client:
            init = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "two-machines-test", "version": "0"},
                },
            }
            response = client.post(url, json=init, headers=headers)
            assert response.status_code == 200, response.text
            headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
            client.post(
                url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers
            )
            call = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "local_classify",
                    "arguments": {"text": "hola", "labels": ["a", "b"]},
                },
            }
            body = client.post(url, json=call, headers=headers).text
        for line in body.splitlines():
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if data.get("id") == 2:
                    return data
        return json.loads(body) if body.strip().startswith("{") else None


@pytest.fixture
def machines(tmp_path):
    """The fake backend running, the PC's and the Mac's folders and the launcher, and cleanup."""
    backend = FakeSwitchingBackend({X: 0.2, Y: 0.1}, load_s=LOAD_S)
    port = backend.start()
    launcher = tmp_path / "launcher.py"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    before = _real_files()
    try:
        yield {
            "backend": backend,
            "base": f"http://127.0.0.1:{port}/v1",
            "launcher": launcher,
            "tmp": tmp_path,
        }
    finally:
        backend.stop()
    _assert_real_files_clean(before)


def _start_pc(machines: dict, deadline: Deadline):
    tmp = machines["tmp"]
    port = _free_port()
    env = _environment(
        tmp / "pc-home",
        tmp / "pc-data",
        "pc-test",
        machines["base"],
        LLAMASWAP_CONFIG=str(_topology_yaml(tmp / "llamaswap.yaml")),
    )
    args = [str(machines["launcher"]), str(SRC), "pc", str(port)]
    return port, args, env


def _mac_args(machines: dict, port: int, mode: str) -> tuple[list[str], dict, Path, Path]:
    tmp = machines["tmp"]
    out, stop = tmp / f"mac-{mode}.json", tmp / f"mac-{mode}.stop"
    env = _environment(
        tmp / "mac-home",
        tmp / "mac-data",
        "mac-test",
        machines["base"],
        LOCAL_DELEGATE_TURN_URL=f"http://127.0.0.1:{port}/",
    )
    args = [str(machines["launcher"]), str(SRC), "mac", str(out), str(stop), mode]
    return args, env, out, stop


def test_one_queue_for_two_machines(machines):
    deadline = Deadline(TEST_CAP_S)
    tmp = machines["tmp"]
    backend: FakeSwitchingBackend = machines["backend"]
    port, pc_args, pc_env = _start_pc(machines, deadline)
    pc = _Pc(port)
    with _child(pc_args, pc_env, tmp / "pc.log") as pc_process:
        _until(
            lambda: pc.alive() or pc_process.poll() is not None,
            30,
            deadline,
            "the PC's daemon never answered",
        )
        assert pc_process.poll() is None, (tmp / "pc.log").read_text(errors="replace")
        mac_args, mac_env, out, _stop = _mac_args(machines, port, "parallel")
        with _child(mac_args, mac_env, tmp / "mac.log") as mac_process:
            _until(
                lambda: (
                    len([e for e in pc.inflight() if e.get("host") == "mac-test"]) >= 2
                    or mac_process.poll() is not None
                ),
                30,
                deadline,
                "the Mac's operations never showed up in the PC's /api/inflight",
            )
            assert mac_process.poll() is None, f"the Mac exited with {mac_process.returncode}: " + (
                tmp / "mac.log"
            ).read_text(errors="replace")
            answer: dict = {}
            t0 = time.monotonic()

            def ask() -> None:
                answer["result"] = pc.classify()
                answer["elapsed"] = time.monotonic() - t0

            asking = threading.Thread(target=ask, daemon=True)
            asking.start()
            both = _until(
                lambda: _together(pc.inflight()),
                15,
                deadline,
                "the PC's /api/inflight never showed its own operation and the Mac's together",
            )
            assert all("state" in r for r in both), both
            mac_rows = [r for r in both if r.get("host") == "mac-test"]
            assert all(r.get("host_via") == "lease" for r in mac_rows), mac_rows
            asking.join(deadline.left(60))
            assert not asking.is_alive(), "the PC's operation never finished"
            result = answer["result"]
            assert result is not None and "result" in result, result
            assert result["result"].get("isError") is not True, result
            # REQ-031: within TURN_YIELD_S + heartbeat_s + HTTP_TIMEOUT + load.
            bound = TURN_YIELD_S + TURN_LEASE_S / 3 + HTTP_TIMEOUT_S + LOAD_S
            assert answer["elapsed"] < bound, f"{answer['elapsed']:.1f} s > {bound:.1f} s"
            mac_process.wait(deadline.left(90))
            assert mac_process.returncode == 0, (tmp / "mac.log").read_text(errors="replace")
        outcomes = json.loads(out.read_text(encoding="utf-8"))
        assert outcomes == ["ok", "ok"], outcomes

    order = backend.order()
    assert Y in order and order.count(Y) == 1, order
    assert len(order) <= 3, f"X and Y interleaved more than one yield allows: {order}"

    pc_events = _events(tmp / "pc-data")
    mac_events = _events(tmp / "mac-data")
    classify = [e for e in pc_events if e.get("tool") == "local_classify"]
    assert len(classify) == 1 and classify[0]["ok"] is True, classify
    assert "read_timeout" not in json.dumps(classify[0])
    assert "remote_turn" not in classify[0]  # a local operation does not carry it (REQ-026)
    assert not [e for e in pc_events if e.get("tool") == "local_summarize"], "counted twice"
    summaries = [e for e in mac_events if e.get("tool") == "local_summarize"]
    assert len(summaries) == 2, summaries
    for event in summaries:
        assert event.get("remote_turn") in ("granted", "forced"), event
        assert "turn" in event.get("concurrency", {}).get("phases", {}), event
    assert sum(e.get("turn_yields", 0) for e in summaries) >= 1, summaries

    def key(event: dict) -> tuple:
        concurrency = event.get("concurrency", {})
        start = concurrency.get("phases", {}).get("backend", {}).get("start")
        return event.get("tool"), concurrency.get("requested_model"), start

    duplicated = {key(e) for e in pc_events} & {key(e) for e in mac_events}
    assert not duplicated, f"the same operation in both logs: {duplicated}"


def test_the_mac_goes_on_without_turn_when_the_daemon_dies(machines):
    deadline = Deadline(TEST_CAP_S)
    tmp = machines["tmp"]
    port, pc_args, pc_env = _start_pc(machines, deadline)
    pc = _Pc(port)
    mac_args, mac_env, out, stop = _mac_args(machines, port, "loop")
    with _child(pc_args, pc_env, tmp / "pc.log") as pc_process:
        _until(pc.alive, 30, deadline, "the PC's daemon never answered")
        with _child(mac_args, mac_env, tmp / "mac.log") as mac_process:
            try:
                _until(
                    lambda: any(
                        e.get("remote_turn") == "granted" for e in _events(tmp / "mac-data")
                    ),
                    30,
                    deadline,
                    "the Mac never got a turn from the PC",
                )
                pc_process.terminate()
                pc_process.wait(deadline.left(10))
                _until(
                    lambda: any(
                        e.get("remote_turn") == "unreachable" for e in _events(tmp / "mac-data")
                    ),
                    40,
                    deadline,
                    "the Mac never said `unreachable` after the PC's daemon died",
                )
            finally:
                stop.write_text("stop", encoding="utf-8")
            mac_process.wait(deadline.left(30))
            assert mac_process.returncode == 0, (tmp / "mac.log").read_text(errors="replace")
    outcomes = json.loads(out.read_text(encoding="utf-8"))
    assert outcomes and all(o == "ok" for o in outcomes), outcomes


def test_the_launcher_refuses_a_local_delegate_from_elsewhere(tmp_path):
    """The guard of the launcher: `local_delegate` not under the given `src` → exit code 3."""
    launcher = tmp_path / "launcher.py"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    empty = tmp_path / "not-src"
    empty.mkdir()
    env = _environment(tmp_path / "home", tmp_path / "data", "x", "http://127.0.0.1:1/v1")
    with _child([str(launcher), str(empty), "pc", "1"], env, tmp_path / "out.log") as process:
        process.wait(30)
    assert process.returncode == 3, (tmp_path / "out.log").read_text(errors="replace")
