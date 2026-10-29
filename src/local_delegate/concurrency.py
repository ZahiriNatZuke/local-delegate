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


def note_inflight(requests: Sequence[dict[str, str | None]]) -> None:
    trace = _CURRENT.get()
    if trace is not None:
        try:
            trace.note_inflight(requests)
        except Exception:
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
