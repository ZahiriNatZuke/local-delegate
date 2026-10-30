"""Turn leases: how an operation of ANOTHER machine joins this daemon's turn (PC+Mac, lot 3).

A process whose backend is this machine's llama-swap (the Mac against the PC) has no thread here.
It asks for the turn through `/api/turn/*` (`web/turn_api.py`) and keeps it with heartbeats; this
module holds the leases behind those routes, with no FastAPI in it:

- `acquire` puts the operation at the end of the SAME `turn.Turn` the local operations use
  (REQ-011), as `PendingRequest(id="<host>/<op>", A={m}, role=m, direct={m})`, `m` being the
  model resolved by this daemon's topology. No topology, a backend that is not on loopback or a
  model the config does not know: `no_turn`, as for a local operation (REQ-002 of the turn).
- A lease expires after `TURN_LEASE_S` without `acquire` or `heartbeat` (REQ-012): it leaves the
  queue or `actives`, `inflight.json` and the in-flight count. Expiry is checked on every request,
  on every tick of a local turn wait (`server.TURN_TICK_HOOKS`) and by a reaper thread that lives
  while there are leases.
- Each lease has its `inflight.json` entry under `remote:<host>/<op>` (REQ-014), live in
  `server._inflight_live` while the lease lives.
- Every grant, release, expiry and change of `in_backend` calls `server._note_queue_progress()`
  (#476): a local wait behind the Mac is not taken for a saturated queue while the queue moves.
- A granted lease whose operation must yield (`Turn.must_yield`, REQ-030) answers `yield`; if it
  is still there `heartbeat_s * 2 + HTTP_TIMEOUT` after the first `yield`, it is expired.
- The daemon writes NO usage event for a remote operation (REQ-015): the machine that runs it does.

`acquire` and `heartbeat` answer as soon as the status changes or after `heartbeat_s` at most
(bounded long wait with `Turn.wait_change`); only while the lease is `queued`.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import config, topology, turn

#: This daemon's run: new on every start, written to `daemon.json`, `/api/daemon` and every answer
#: of `/api/turn/*`, so a client tells a restarted daemon (its leases are gone) from the same one.
DAEMON_ID = secrets.token_urlsafe(16)
#: Version of the answers' shape (`v`). A client that reads a higher one degrades (REQ-025).
API_VERSION = 1
#: At most this many live leases per host (REQ-017), on top of `TURN_MAX_LEASES` in total.
MAX_LEASES_PER_HOST = 8
#: The heartbeat interval the server asks for: `TURN_LEASE_S / 3`, at most 5 s (REQ-022).
MAX_HEARTBEAT_S = 5.0
#: Prefix of a remote operation's key in `inflight.json` (REQ-014).
ENTRY_PREFIX = "remote:"
#: Phases a heartbeat may publish (the same as `server._INFLIGHT_PHASES`).
PHASES = frozenset({"map", "reduce", "retry"})
#: Long waits open at once in the whole table (each holds a threadpool worker for `heartbeat_s`).
MAX_LONG_WAITS = 16

QUEUED = "queued"
GRANTED = "granted"
YIELD = "yield"
EXPIRED = "expired"
NO_TURN = "no_turn"
RELEASED = "released"


class TooManyLeases(Exception):
    """Over `TURN_MAX_LEASES` in total or `MAX_LEASES_PER_HOST` for one host (REQ-017): 429."""


@dataclass(frozen=True)
class AcquireRequest:
    """What `acquire` receives, already validated and cleaned by the route."""

    op: str
    host: str
    tool: str
    model: str
    role: str = ""
    chain: tuple[str, ...] = ()
    chars_in: int = 0
    chunks: int | None = None


@dataclass(frozen=True)
class Beat:
    """What a heartbeat publishes: the operation's state at the client."""

    in_backend: bool = False
    #: Models llama-swap is switching away from (`{model: state}`), or `True` without detail.
    waiting_backend: dict[str, str] | bool | None = None
    chunk: int | None = None
    phase: str | None = None


@dataclass
class Lease:
    id: str
    host: str
    op: str
    tool: str
    model: str
    turn: turn.Turn
    expires_at: float
    #: `time.monotonic()` at the acquire: where `stalled_s` starts counting (`_queue_stalled_s`).
    started: float
    in_backend: bool = False
    yield_since: float | None = None
    granted: bool = False
    forced: bool = False
    position: int | None = None
    in_use: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def op_id(self) -> str:
        return f"{self.host}/{self.op}"

    @property
    def entry_key(self) -> str:
        return f"{ENTRY_PREFIX}{self.op_id}"


def heartbeat_seconds() -> float:
    return min(MAX_HEARTBEAT_S, config.TURN_LEASE_S / 3)


def yield_cap_seconds() -> float:
    """How long a lease may stay active after its first `yield` (REQ-030, server side)."""
    return heartbeat_seconds() * 2 + config.HTTP_TIMEOUT


def _server():
    # Deferred: `server` is the MCP server and pulls the SDK; this module stays light to import.
    from . import server

    return server


class LeaseTable:
    """The live leases of this daemon. Thread-safe; `clock` is injectable for the tests.

    Lock order: this table's lock, then the turn's. The turn never calls back into here.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._leases: dict[str, Lease] = {}
        self._by_op: dict[str, str] = {}
        self._reaper: threading.Thread | None = None
        self._stop = threading.Event()
        #: Leases with a long wait open: at most one each (security review of #500).
        self._waiting: set[str] = set()
        #: Long waits open at once, all leases together: the threadpool is shared with the
        #: panel, the hooks and the MCP tools, so past this a queued answer comes back at once.
        self._long_waits = threading.BoundedSemaphore(MAX_LONG_WAITS)

    # --- reading ---------------------------------------------------------------------------

    def live(self) -> int:
        with self._lock:
            return len(self._leases)

    def get(self, lease_id: str) -> Lease | None:
        with self._lock:
            return self._leases.get(lease_id)

    # --- the three operations --------------------------------------------------------------

    def acquire(self, request: AcquireRequest) -> dict[str, Any]:
        """Join the turn at the end of the queue; `no_turn` if this daemon has no turn for it."""
        self.reap()
        server = _server()
        snapshot = server._topology()
        if not isinstance(snapshot, topology.Snapshot):
            return self._answer(None, NO_TURN, model=request.model)
        real = snapshot.resolve(request.model)
        if real is None:
            return self._answer(None, NO_TURN, model=request.model)
        chain = tuple(dict.fromkeys(r for r in (snapshot.resolve(m) for m in request.chain) if r))
        op_id = f"{request.host}/{request.op}"
        with self._lock:
            previous = self._by_op.get(op_id)
            if previous is not None:
                # The same operation asks again (after a `yield`, a lost answer or an expiry it has
                # not seen): its old place goes, and the new one is at the end of the queue.
                self._expire_locked(self._leases[previous])
            if len(self._leases) >= config.TURN_MAX_LEASES:
                raise TooManyLeases
            if sum(1 for x in self._leases.values() if x.host == request.host) >= (
                MAX_LEASES_PER_HOST
            ):
                raise TooManyLeases
            turn_state = server._turn
            lease = Lease(
                id=secrets.token_urlsafe(32),
                host=request.host,
                op=request.op,
                tool=request.tool,
                model=real,
                turn=turn_state,
                expires_at=self._clock() + config.TURN_LEASE_S,
                started=time.monotonic(),
            )
            entry: dict[str, Any] = {
                "tool": request.tool,
                "model": real,
                "source": "remote",
                "chars_in": int(request.chars_in),
                "started_at": time.time(),
                "pid": os.getpid(),
                "backend": config.backend_origin(),
                "host": request.host,
                "host_via": "lease",
                # Queued until the turn says otherwise (`_inflight_state`: no `in_backend`).
                "local_wait": "turn",
            }
            if request.chunks:
                entry["chunks"] = int(request.chunks)
                entry["chunk"] = 1
            # Written before the turn sees the operation: a grant patches an entry that exists.
            server._inflight_put(lease.entry_key, entry)
            self._leases[lease.id] = lease
            self._by_op[op_id] = lease.id
            result = turn_state.enqueue(
                turn.PendingRequest(
                    op_id, frozenset({real}), real, chain_order=chain, direct=frozenset({real})
                )
            )
            self._take(lease, result)
            self._ensure_reaper()
            status = self._status_locked(lease)
        return self._finish(lease, status)

    def heartbeat(self, lease_id: str, beat: Beat) -> dict[str, Any]:
        """Keep the lease alive and publish the client's state; the answer says where it stands."""
        self.reap()
        server = _server()
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                return self._answer(None, EXPIRED)
            lease.expires_at = self._clock() + config.TURN_LEASE_S
            changes: dict[str, Any] = {}
            if beat.chunk is not None:
                changes["chunk"] = int(beat.chunk)
            if beat.phase is not None:
                changes["phase"] = None if beat.phase == "map" else beat.phase
            if lease.granted:
                if beat.waiting_backend:
                    detail = beat.waiting_backend if isinstance(beat.waiting_backend, dict) else {}
                    changes["backend_wait"] = {"remote": dict(detail)}
                else:
                    changes["backend_wait"] = None
                if beat.in_backend != lease.in_backend:
                    lease.in_backend = beat.in_backend
                    lease.turn.remote_flight(lease.op_id, beat.in_backend)
                    changes["in_backend"] = bool(beat.in_backend)
                    server._note_queue_progress()
            if changes:
                server._inflight_patch(lease.entry_key, changes)
            status = self._status_locked(lease)
        return self._finish(lease, status)

    def release(self, lease_id: str) -> dict[str, Any]:
        """The operation ends: out of the turn and of `inflight.json`. Idempotent."""
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is not None:
                self._expire_locked(lease)
        return {"v": API_VERSION, "daemon_id": DAEMON_ID, "status": RELEASED}

    # --- expiry ----------------------------------------------------------------------------

    def reap(self, now: float | None = None) -> int:
        """Expire the leases past their time. Returns how many.

        The `yield` cap is checked where the `yield` is answered (`_status_locked`): a client that
        keeps beating meets it there, and one that stops beating expires here anyway.
        """
        with self._lock:
            now = self._clock() if now is None else now
            gone = [x for x in self._leases.values() if x.expires_at <= now]
            for lease in gone:
                self._expire_locked(lease)
            return len(gone)

    def clear(self) -> None:
        """Every lease out and the reaper stopped (daemon shutdown, tests)."""
        with self._lock:
            for lease in list(self._leases.values()):
                self._expire_locked(lease)
        self._stop.set()
        reaper = self._reaper
        if reaper is not None and reaper is not threading.current_thread():
            reaper.join(timeout=5)

    def _expire_locked(self, lease: Lease) -> None:
        server = _server()
        self._leases.pop(lease.id, None)
        if self._by_op.get(lease.op_id) == lease.id:
            self._by_op.pop(lease.op_id, None)
        try:
            lease.turn.expire(lease.op_id)
        finally:
            server._inflight_drop(lease.entry_key)
            server._note_queue_progress()

    # --- status ----------------------------------------------------------------------------

    def _take(self, lease: Lease, result: turn.Grant | tuple[int, tuple[str, ...]] | None) -> bool:
        """Record what the turn said about a queued lease. `False` if it is no longer there."""
        server = _server()
        if isinstance(result, turn.Grant):
            lease.granted = True
            lease.forced = result.forced
            lease.position = None
            lease.yield_since = None
            server._inflight_patch(
                lease.entry_key,
                {
                    "local_wait": None,
                    "turn_position": None,
                    "turn_in_use": None,
                    "in_backend": False,
                },
            )
            server._note_queue_progress()  # the turn changed hands (#476)
            return True
        if result is None:
            return False
        position, in_use = result
        if (position, tuple(in_use)) != (lease.position, lease.in_use):
            lease.position, lease.in_use = position, tuple(in_use)
            server._inflight_patch(
                lease.entry_key, {"turn_position": int(position), "turn_in_use": list(in_use)}
            )
        return True

    def _status_locked(self, lease: Lease) -> str:
        if self._leases.get(lease.id) is not lease:
            return EXPIRED
        if not lease.granted:
            if not self._take(lease, lease.turn.poll(lease.op_id)):
                self._expire_locked(lease)  # gone from the turn without passing by here
                return EXPIRED
            if not lease.granted:
                return QUEUED
        if not lease.turn.must_yield(lease.op_id):
            lease.yield_since = None
            return GRANTED
        now = self._clock()
        if lease.yield_since is None:
            lease.yield_since = now
        elif now - lease.yield_since >= yield_cap_seconds():
            self._expire_locked(lease)  # it ignored the `yield`: it does not hold the queue
            return EXPIRED
        return YIELD

    def _finish(self, lease: Lease, status: str) -> dict[str, Any]:
        """The bounded long wait of a queued lease, then the answer."""
        if status == QUEUED:
            status = self._long_wait(lease)
        with self._lock:
            if status != EXPIRED and self._leases.get(lease.id) is lease:
                # Answering is a sign of life too: the long wait does not eat into the lease.
                lease.expires_at = self._clock() + config.TURN_LEASE_S
            elif status != EXPIRED:
                status = EXPIRED  # released or expired by another request during the wait
        return self._answer(lease if status != EXPIRED else None, status)

    def _long_wait(self, lease: Lease) -> str:
        """Wait for the status of a queued lease to change, `heartbeat_s` at most.

        Only one long wait per lease and `MAX_LONG_WAITS` in all: a request past either answers
        `queued` at once. Without this, 60 heartbeats on one lease held the 40 workers of the
        threadpool and `/api/inflight` took 4 s (security review of #500).
        """
        with self._lock:
            if lease.id in self._waiting or not self._long_waits.acquire(blocking=False):
                return QUEUED
            self._waiting.add(lease.id)
        try:
            status = QUEUED
            deadline = time.monotonic() + heartbeat_seconds()
            while status == QUEUED:
                since = lease.turn.version()
                with self._lock:
                    status = self._status_locked(lease)
                remaining = deadline - time.monotonic()
                if status != QUEUED or remaining <= 0:
                    break
                lease.turn.wait_change(min(remaining, heartbeat_seconds()), since=since)
            return status
        finally:
            with self._lock:
                self._waiting.discard(lease.id)
            self._long_waits.release()

    def try_reap(self) -> int | None:
        """`reap` only if the table is free; `None` if it is busy (a local tick never waits here)."""
        if not self._lock.acquire(blocking=False):
            return None
        try:
            return self.reap()
        finally:
            self._lock.release()

    def _answer(
        self, lease: Lease | None, status: str, *, model: str | None = None
    ) -> dict[str, Any]:
        server = _server()
        queued = lease is not None and status == QUEUED
        in_use: tuple[str, ...] = ()
        if lease is not None:
            in_use = lease.in_use if queued else lease.turn.in_use()
        return {
            "v": API_VERSION,
            "daemon_id": DAEMON_ID,
            "lease": lease.id if lease is not None else None,
            "status": status,
            "position": lease.position if queued and lease is not None else None,
            "in_use": list(in_use),
            "model": lease.model if lease is not None else model,
            "forced": bool(lease.forced) if lease is not None else False,
            "lease_s": config.TURN_LEASE_S,
            "heartbeat_s": heartbeat_seconds(),
            "stalled_s": round(server._queue_stalled_s(lease.started), 1)
            if lease is not None
            else 0.0,
        }

    # --- reaper ----------------------------------------------------------------------------

    def _ensure_reaper(self) -> None:
        """A thread that reaps every `TURN_LEASE_S / 3` while there are leases (REQ-012)."""
        _register_tick_hook()
        if self._reaper is not None and self._reaper.is_alive():
            return
        self._stop = threading.Event()
        stop = self._stop
        self._reaper = threading.Thread(
            target=self._reap_loop, args=(stop,), name="turn-lease-reaper", daemon=True
        )
        self._reaper.start()

    def _reap_loop(self, stop: threading.Event) -> None:
        while not stop.wait(config.TURN_LEASE_S / 3):
            try:
                self.reap()
            except Exception:  # the reaper never dies of one bad pass; the next one tries again
                pass
            with self._lock:
                if not self._leases:
                    if self._reaper is threading.current_thread():
                        self._reaper = None
                    return


_table = LeaseTable()
_hook_lock = threading.Lock()
_hook_registered = False


def table() -> LeaseTable:
    return _table


def reset(*, clock: Callable[[], float] = time.monotonic) -> LeaseTable:
    """A new, empty table (tests): the old one's leases are expired and its reaper stopped."""
    global _table
    _table.clear()
    _table = LeaseTable(clock=clock)
    return _table


def _tick() -> None:
    # A local wait's tick skips the reap when the table is busy: the next tick or the reaper
    # thread does it, and the local wait is never held up by a remote request.
    _table.try_reap()


def _register_tick_hook() -> None:
    """Each tick of a local turn wait reaps too (REQ-012). Once per process."""
    global _hook_registered
    with _hook_lock:
        if _hook_registered:
            return
        _server().TURN_TICK_HOOKS.append(_tick)
        _hook_registered = True
