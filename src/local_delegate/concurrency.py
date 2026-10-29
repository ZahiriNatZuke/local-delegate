"""Concurrency trace of one operation, for the usage log (concurrency PC+Mac, step 0).

The PC daemon and the Mac's MCP each keep their own turn and slots, and both send to the same
llama-swap. To see who waited for whom, each usage-log entry carries, under `concurrency`:

* `phases`: for `turn`, `slot` and `backend`, the UTC start of the first and the UTC end of the
  last time the operation went through that phase, the summed milliseconds and how many times.
  `turn` and `slot` are the waits for the daemon's turn and for a slot of
  `MAX_CONCURRENT_REQUESTS`; `backend` is the POST to the backend, so it includes llama-swap's own
  queue and the model load. A phase that never happened is left out (no turn on a remote backend).
* `requested_model`: the model the tool asked for (the role's model, or the explicit one).
* `backend_models`: the models of llama-swap's `/running` right before the first POST, as
  `{model: state}`. Cached for a short while and queried with a short cap: it is observation, so it
  never blocks a call for long and never breaks one. Left out when `/running` did not answer.
* `model_swap`: whether the first POST went to a model that was not `ready` then (so the call
  made llama-swap load it, or waited for a load). Left out when `backend_models` is.
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

    def backend_starting(self, model: str, real: Callable[[str], str] | None = None) -> None:
        """Before the FIRST POST of the operation: what llama-swap had loaded, and whether this
        call needs a model that was not ready. Later POSTs of the operation do not sample again."""
        with self._lock:
            if self._backend_sampled:
                return
            self._backend_sampled = True
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


def backend_starting(model: str, real: Callable[[str], str] | None = None) -> None:
    trace = _CURRENT.get()
    if trace is None:
        return
    try:
        trace.backend_starting(model, real)
    except Exception:  # observation: the POST goes on without the sample
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
