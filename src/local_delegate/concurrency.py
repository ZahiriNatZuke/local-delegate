"""Concurrency trace of one operation, for the usage log (concurrency PC+Mac, step 0).

The PC daemon and the Mac's MCP each keep their own turn and slots, and both send to the same
llama-swap. To see who waited for whom, each usage-log entry carries, under `concurrency`:

* `phases`: for `turn`, `slot` and `backend`, the UTC start of the first and the UTC end of the
  last time the operation went through that phase, the summed milliseconds and how many times.
  `turn` and `slot` are the waits for the daemon's turn and for a slot of
  `MAX_CONCURRENT_REQUESTS`; `backend` is the POST to the backend, so it includes llama-swap's own
  queue and the model load. A phase that never happened is left out (no turn on a remote backend).
* `requested_model`: the model the tool asked for (the role's model, or the explicit one).
* `backend_models`: llama-swap's `/running` as `{model: state}`, sampled ONLY when a POST is still
  waiting `BACKEND_SAMPLE_DELAY_S` (3 s) after it was sent, once per operation;
  `backend_models_at_ms` says when. A quick call queries nothing: the daemon's rule is that it
  does not ask llama-swap without a need (the affinity tests pin it), and a call that answers in
  under 3 s neither loaded a model (6-14 s measured) nor waited behind one. Cached for a short
  while and queried with a short cap, from a timer thread: it never delays the call.
* `model_swap`: whether, at that moment, the model of the POST was not `ready` (llama-swap was
  loading it, or waiting to unload another one to load it). Left out when `backend_models` is.
* `inflight_seen`: the requests that the PC daemon saw in llama-swap's `inflight` photo when it
  already looked at it (affinity), as `{model, host}`; `host` comes from `X-Local-Delegate-Host`.

The top-level `host` (the machine of origin, `origin_fields`) is written by `server._log_event` on
every entry and by `server._inflight_start` on every `inflight` entry.

Everything here is best-effort: a failure leaves the field out and never reaches the tool.
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx2

from . import clients, config

PHASES = ("turn", "slot", "backend")

#: How long one `/running` answer is reused, and the cap of each query (connection included).
RUNNING_CACHE_S = 2.0
RUNNING_QUERY_CAP_S = 0.5
#: How long a POST must be pending before `/running` is sampled (see the module docstring).
BACKEND_SAMPLE_DELAY_S = 3.0
#: At most this many `inflight_seen` entries per event: the log keeps no long lists.
INFLIGHT_SEEN_MAX = 20


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="milliseconds")


class Trace:
    """The phases and backend observations of ONE operation. Thread-safe: a send can run in its
    own thread (`cancellation.run_abandonable`) with a copy of the context, and the same object."""

    def __init__(self, requested_model: str) -> None:
        self.requested_model = requested_model
        self._lock = threading.Lock()
        self._phases: dict[str, dict[str, Any]] = {}
        self._backend_sampled = False
        self.backend_models: dict[str, str] | None = None
        self.backend_models_at_ms: int | None = None
        self.model_swap: bool | None = None
        self.inflight_seen: list[dict[str, str | None]] | None = None

    def record(self, phase: str, start: float, end: float, ms: int) -> None:
        with self._lock:
            entry = self._phases.get(phase)
            if entry is None:
                self._phases[phase] = {"start": start, "end": end, "ms": ms, "n": 1}
                return
            entry["start"] = min(entry["start"], start)
            entry["end"] = max(entry["end"], end)
            entry["ms"] += ms
            entry["n"] += 1

    def claim_backend_sample(self) -> bool:
        """True only for the first caller: one `/running` sample per operation."""
        with self._lock:
            if self._backend_sampled:
                return False
            self._backend_sampled = True
            return True

    def sample_backend(
        self, model: str, real: Callable[[str], str] | None = None, at_ms: int = 0
    ) -> None:
        """What llama-swap had loaded while this POST waited, and whether its model was ready."""
        models = loaded_models()
        if models is None:
            return
        name = model
        if real is not None:
            try:
                name = real(model) or model
            except Exception:  # resolving an alias is observation too
                name = model
        with self._lock:
            self.backend_models = models
            self.backend_models_at_ms = int(at_ms)
            self.model_swap = models.get(name) != "ready" and models.get(model) != "ready"

    def note_inflight(self, requests: Sequence[dict[str, str | None]]) -> None:
        with self._lock:
            self.inflight_seen = [
                {"model": r.get("model"), "host": r.get("host")}
                for r in list(requests)[:INFLIGHT_SEEN_MAX]
            ]

    def log_fields(self) -> dict[str, Any]:
        """The `concurrency` object of the usage-log entry. Only what was observed."""
        with self._lock:
            fields: dict[str, Any] = {"requested_model": self.requested_model}
            phases = {
                name: {
                    "start": _iso(p["start"]),
                    "end": _iso(p["end"]),
                    "ms": int(p["ms"]),
                    "n": int(p["n"]),
                }
                for name in PHASES
                if (p := self._phases.get(name)) is not None
            }
            if phases:
                fields["phases"] = phases
            if self.backend_models is not None:
                fields["backend_models"] = dict(self.backend_models)
                fields["backend_models_at_ms"] = self.backend_models_at_ms
                fields["model_swap"] = bool(self.model_swap)
            if self.inflight_seen is not None:
                fields["inflight_seen"] = list(self.inflight_seen)
            return fields


_CURRENT: contextvars.ContextVar[Trace | None] = contextvars.ContextVar(
    "local_delegate_concurrency_trace", default=None
)


def start(requested_model: str) -> Trace:
    """A new trace for the operation that starts now, current in this context.

    It is not reset at the end on purpose: the next operation of the same context replaces it, and
    a stale trace is only written to by code that runs inside an operation (`phase`), never logged.
    """
    trace = Trace(requested_model)
    _CURRENT.set(trace)
    return trace


def current() -> Trace | None:
    return _CURRENT.get()


@contextmanager
def phase(name: str) -> Generator[None, None, None]:
    """Times `name` for the current operation (system clock for the UTC stamps, monotonic for `ms`).

    Without a current trace it does nothing. The end is recorded also when the body raises (a
    cancelled wait, an abandoned send).
    """
    trace = _CURRENT.get()
    if trace is None:
        yield
        return
    ts0 = time.time()
    t0 = time.monotonic()
    try:
        yield
    finally:
        try:
            trace.record(name, ts0, time.time(), int((time.monotonic() - t0) * 1000))
        except Exception:  # observing never breaks the call it observes
            pass


@contextmanager
def backend_phase(
    model: str, real: Callable[[str], str] | None = None
) -> Generator[None, None, None]:
    """The `backend` phase of one POST, plus the delayed `/running` sample (module docstring).

    The sample runs in a timer thread that fires only if the POST is still pending after
    `BACKEND_SAMPLE_DELAY_S`; on exit the timer is cancelled, or, if it already fired, waited for
    at most the query cap so the event gets it. With a delay of 0 or less it samples at once (tests).
    """
    trace = _CURRENT.get()
    if trace is None:
        yield
        return
    timer: threading.Timer | None = None
    try:
        if trace.claim_backend_sample():
            delay = BACKEND_SAMPLE_DELAY_S
            if delay <= 0:
                trace.sample_backend(model, real, 0)
            else:
                timer = threading.Timer(
                    delay, _sample_in_background, args=(trace, model, real, int(delay * 1000))
                )
                timer.daemon = True
                timer.start()
    except Exception:  # observation: the POST goes on without the sample
        timer = None
    with phase("backend"):
        try:
            yield
        finally:
            if timer is not None:
                timer.cancel()
                if timer.is_alive():
                    timer.join(RUNNING_QUERY_CAP_S + 0.5)


def _sample_in_background(
    trace: Trace, model: str, real: Callable[[str], str] | None, at_ms: int
) -> None:
    try:
        trace.sample_backend(model, real, at_ms)
    except Exception:  # a timer thread must never raise
        pass


# --- `waiting_backend`: one watch per send (concurrency PC+Mac, lot 1, REQ-001/002) ----------

#: How often a send that waits for llama-swap to switch models samples `/running` again.
BACKEND_WAIT_RESAMPLE_S = 10.0
#: At most this many models per send in `backend_wait`: the inflight file keeps no long lists.
BACKEND_WAIT_MAX_MODELS = 8


def waiting_for(
    models: dict[str, str] | None, model: str, resolved: str | None
) -> dict[str, str] | None:
    """The OTHER models of `/running` when the POST of `model` waits behind them, else `None`.

    `resolved` is the id llama-swap shows for `model` (an alias resolved by the topology), or
    `None` when it cannot be known (no topology: the Mac). The requested model counts as ready
    under either name. When neither name is in `/running` and the alias cannot be resolved, it is
    undecidable and nothing is marked: a false «waiting for the backend» is worse than none
    (REQ-001). The answer leaves the requested model out, under both names, and keeps at most
    `BACKEND_WAIT_MAX_MODELS`; it may be empty (nothing else loaded, the requested one starting).
    """
    if models is None:
        return None
    names = {model} | ({resolved} if resolved else set())
    states = {models.get(name) for name in names} - {None}
    if "ready" in states:
        return None
    if not states and resolved is None:
        return None
    others = sorted((m, s) for m, s in models.items() if m not in names)
    return dict(others[:BACKEND_WAIT_MAX_MODELS])


class SendWatch:
    """The `waiting_backend` watch of ONE send. `stop()` is idempotent and safe from any thread.

    The stop flag works as the send's generation, guarded by a lock of THIS watch only (a slow
    `inflight.json` write of one send never holds up the others' `stop()`). `on_wait` runs outside
    the lock: the thread checks the flag and notes `marked` under the lock, writes, then checks
    the flag again and undoes its own mark if `stop()` came in between. `stop()` raises the flag
    under the lock BEFORE it clears. Whatever order the writes land in, the last one of a stopped
    watch is a clear, so nothing is left after the cleanup, even when a `/running` query outlives
    the send (REQ-002, race (h) of the plan).
    """

    def __init__(self, on_wait: Callable[[dict[str, str] | None], None]) -> None:
        self._on_wait = on_wait
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.marked = False

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _write(self, others: dict[str, str] | None) -> bool:
        """Mark (`others`) or unmark (`None`) unless stopped. False once stopped."""
        with self._lock:
            if self._stop.is_set():
                return False
            if others is None:
                was_marked, self.marked = self.marked, False
            else:
                self.marked = True
        if others is None:
            if was_marked:
                self._on_wait(None)
            return True
        self._on_wait(others)
        with self._lock:
            stopped = self._stop.is_set()
        if stopped:
            self._on_wait(None)  # `stop()` came in while writing: undo, so a clear is last
            return False
        return True

    def stop(self) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            self._stop.set()
            marked, self.marked = self.marked, False
        if marked:
            try:
                self._on_wait(None)
            except Exception:  # cleaning is observation too: it never breaks the send
                pass

    def run(
        self,
        model: str,
        resolve: Callable[[str], str | None] | None,
        delay: float,
    ) -> None:
        """The watch thread: first sample after `delay`, then every `BACKEND_WAIT_RESAMPLE_S`
        until the requested model is ready or the send ends. Never raises."""
        try:
            if self._stop.wait(max(0.0, delay)):
                return
            resolved: str | None = None
            if resolve is not None:
                try:
                    resolved = resolve(model)
                except Exception:
                    resolved = None
            while not self._stop.is_set():
                models = loaded_models()
                others = waiting_for(models, model, resolved)
                if others is not None:
                    if not self._write(others):
                        return
                elif models is not None and _is_ready(models, model, resolved):
                    self._write(None)
                    return
                if self._stop.wait(BACKEND_WAIT_RESAMPLE_S):
                    return
        except Exception:  # a watch thread must never raise
            pass


def _is_ready(models: dict[str, str], model: str, resolved: str | None) -> bool:
    return "ready" in (models.get(model), models.get(resolved) if resolved else None)


@contextmanager
def send_watch(
    model: str,
    resolve: Callable[[str], str | None] | None,
    on_wait: Callable[[dict[str, str] | None], None],
    *,
    register: Callable[[SendWatch], None] | None = None,
) -> Generator[SendWatch, None, None]:
    """Watches ONE send for `waiting_backend` (REQ-001/002), apart from the log's single sample.

    After `BACKEND_SAMPLE_DELAY_S` with the POST still pending, a thread (with a copy of the
    caller's context) samples `/running`; if the requested model is not ready it calls
    `on_wait(others)` and samples again every `BACKEND_WAIT_RESAMPLE_S`, until the model is ready
    (`on_wait(None)`) or the send ends. A send that answers sooner queries nothing (the affinity
    rule). On exit the watch stops and clears what it marked. `register` hands the watch to
    whoever must also be able to stop it (the slot, when it lets the place go).
    """
    watch = SendWatch(on_wait)
    try:
        if register is not None:
            register(watch)
        ctx = contextvars.copy_context()
        thread = threading.Thread(
            target=ctx.run,
            args=(watch.run, model, resolve, BACKEND_SAMPLE_DELAY_S),
            name="local-delegate-send-watch",
            daemon=True,
        )
        thread.start()
    except Exception:  # observation: the POST goes on without the watch
        pass
    try:
        yield watch
    finally:
        watch.stop()


def note_inflight(requests: Sequence[dict[str, str | None]]) -> None:
    trace = _CURRENT.get()
    if trace is not None:
        try:
            trace.note_inflight(requests)
        except Exception:
            # The trace is diagnostics only: a failure here must never break the delegation.
            pass


def origin_fields() -> dict[str, str]:
    """`host` (and `host_via` when it is another machine) for a log entry or an `inflight` entry.

    A request over the daemon's `/mcp` from another machine (the Mac through the tailnet) carries
    its origin: the `X-Local-Delegate-Host` header it sent, else the address (`host_via`: `header`,
    `forwarded`, `ip`). Everything else (stdio, a loopback client) is this machine, without
    `host_via`.
    """
    try:
        found = clients.current_origin()
    except Exception:
        found = None
    if found is not None:
        return {"host": found[0], "host_via": found[1]}
    return {"host": config.machine_name()}


# --- `/running`, cached --------------------------------------------------------------------


class _RunningCache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.base: str | None = None
        self.at = 0.0
        self.value: dict[str, str] | None = None


_cache = _RunningCache()


def _query_running(base: str) -> dict[str, str] | None:
    """`{model: state}` of `GET {base}/running`, or `None` if it does not answer in time."""
    try:
        with httpx2.Client(timeout=RUNNING_QUERY_CAP_S) as c:
            r = c.get(f"{base}/running", headers=config.backend_headers())
        if not r.is_success:
            return None
        data = r.json()
    except (httpx2.HTTPError, ValueError):
        return None
    entries = data.get("running") if isinstance(data, dict) else None
    if entries is None and isinstance(data, dict):
        return {}  # llama-swap sends `null` when nothing is loaded
    if not isinstance(entries, list):
        return None
    models: dict[str, str] = {}
    for e in entries:
        if isinstance(e, dict) and isinstance(e.get("model"), str):
            state = e.get("state")
            models[e["model"]] = state if isinstance(state, str) else "unknown"
    return models


def loaded_models() -> dict[str, str] | None:
    """`/running` of the backend as `{model: state}`, reused for `RUNNING_CACHE_S`.

    A failed query is cached as well, so a backend that does not answer costs one cap every few
    seconds and not one per call.
    """
    base = config.BASE_URL.removesuffix("/v1")
    now = time.monotonic()
    with _cache.lock:
        if _cache.base == base and now - _cache.at < RUNNING_CACHE_S:
            return None if _cache.value is None else dict(_cache.value)
    value = _query_running(base)
    with _cache.lock:
        _cache.base, _cache.at, _cache.value = base, time.monotonic(), value
    return None if value is None else dict(value)


def reset_cache() -> None:
    """Forget the cached `/running` (tests)."""
    with _cache.lock:
        _cache.base, _cache.at, _cache.value = None, 0.0, None
