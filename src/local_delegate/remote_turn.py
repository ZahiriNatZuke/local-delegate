"""The client of the remote turn: an operation of THIS machine joins the turn of the daemon on the
backend's machine (concurrency PC+Mac, lot 4).

A process whose backend is another machine's llama-swap (the Mac against the PC) has no local turn
(`NO_TURN_REMOTE_BACKEND`): it would take the GPU from the PC's operations without asking. Here it
asks the PC's daemon through `/api/turn/*` (lot 3, `web/turn_api.py`), and the server's contract
is kept to the letter:

- `acquire` once, then `heartbeat` on the same lease: while queued (bounded long waits, one after
  the other, never two at once) and while granted (a `daemon=True` thread every `heartbeat_s`).
  `acquire` is repeated only after `expired` or a lost answer: repeating it while queued sends the
  operation to the end of the queue.
- `429` (the daemon is full): wait `heartbeat_s` and try again, inside `QUEUE_MAX_WAIT_S`.
- The daemon unusable (REQ-025 case 1: no answer, 404/405, 401/403, unreadable answer or a higher
  `v`): the operation goes on WITHOUT a turn, as before this lot. The reason is remembered for
  60 s (404/405: 10 min), so the next operations do not pay the timeout again, and it is logged
  once per process and reason.
- Never to itself (REQ-020): a loopback URL on this process's own `WEB_PORT`, or a daemon whose
  `daemon_id` is the one in this machine's `daemon.json`, is `self` and goes without a turn.

Discovery (REQ-021) is `turn_url`: with `LOCAL_DELEGATE_TURN_URL=auto` (the default) and a backend
on loopback there is no URL at all, so a local-only setup never sends a single request (REQ-040).

The credential (REQ-016) is `LOCAL_DELEGATE_REMOTE_WEB_TOKEN` (or the Keychain) when present, else
the backend's key, always as `Authorization: Bearer`. It is never logged nor stored here.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, NoReturn
from urllib.parse import urlsplit

import httpx2

from . import config, i18n, token_source, turn

logger = logging.getLogger(__name__)

#: The protocol version this client speaks; an answer with a higher `v` is `unsupported` (REQ-041).
API_VERSION = 1
#: Plazos de REQ-025: connection 3 s, read `heartbeat_s + 5` s.
CONNECT_TIMEOUT_S = 3.0
READ_MARGIN_S = 5.0
#: The interval before the first answer says otherwise (the server's `min(5, TURN_LEASE_S / 3)`).
DEFAULT_HEARTBEAT_S = 5.0
#: How long an unusable daemon is remembered, by reason (REQ-025 case 1).
UNUSABLE_TTL_S = 60.0
UNSUPPORTED_TTL_S = 600.0
#: How long a release may take: it is best-effort, the lease expires on its own anyway.
RELEASE_READ_S = 3.0

ACQUIRE_PATH = "api/turn/acquire"
HEARTBEAT_PATH = "api/turn/heartbeat"
RELEASE_PATH = "api/turn/release"

# Values of `remote_turn` in the usage event (REQ-026).
GRANTED = "granted"
FORCED = "forced"
NO_TURN = "no_turn"
SELF = "self"
UNREACHABLE = "unreachable"
UNSUPPORTED = "unsupported"
UNAUTHORIZED = "unauthorized"
NEEDS_SECRET = "needs_secret"
BAD_RESPONSE = "bad_response"
#: What `local_status` says for a `LOCAL_DELEGATE_TURN_URL` that is not a usable URL.
BAD_URL = "bad_url"

_STATUSES = frozenset({"queued", "granted", "yield", "expired", "no_turn"})


class Unusable(Exception):
    """The daemon cannot give a turn: the operation goes on without one, with this reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Busy(Exception):
    """`429`: the daemon is alive but full. Wait and try again (REQ-025 case 2)."""


class _Lost(Exception):
    """No answer to a request that may have arrived: a lease in hand may or may not be alive."""


@dataclass(frozen=True)
class Answer:
    status: str
    lease: str | None
    daemon_id: str
    position: int | None
    in_use: tuple[str, ...]
    model: str | None
    forced: bool
    heartbeat_s: float
    stalled_s: float


# --- discovery -------------------------------------------------------------------------------


def _mode() -> str:
    raw = config.TURN_URL.strip()
    return raw.lower() if raw.lower() in ("", "auto", "off") else raw


def explicit_url() -> bool:
    """`LOCAL_DELEGATE_TURN_URL` names a daemon (not `auto` nor `off`)."""
    return _mode() not in ("", "auto", "off")


def _valid(url: str) -> bool:
    parts = urlsplit(url)
    try:
        parts.port  # noqa: B018 - a bad port raises here
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and not parts.username
        and not parts.password
    )


def _normalized(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def turn_url(*, remote_backend: bool) -> str | None:
    """The daemon to ask for the turn, or `None` (no remote turn for this process).

    REQ-020/021: `off` → never; a URL → that one; `auto` → the backend machine's daemon, only when
    the backend is not on loopback (`remote_backend`). A local backend with `auto` gives `None`
    before anything else is looked at: that is the whole of REQ-040.
    """
    mode = _mode()
    if mode == "off":
        return None
    if mode in ("", "auto"):
        if not remote_backend:
            return None
        url = config.remote_panel_url()
        return url or None
    return _normalized(mode) if _valid(mode) else None


def display_url(url: str) -> str:
    """`scheme://host:port/` without anything else: fit for `local_status` and the logs."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}/"


def _host_of(url: str) -> str:
    return urlsplit(url).hostname or ""


def points_to_itself(url: str) -> bool:
    """The guard by address (REQ-020): a loopback URL on this process's own web port."""
    parts = urlsplit(url)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    return config._is_loopback_host(parts.hostname or "") and port == config.WEB_PORT


def local_daemon_id() -> str | None:
    """The `daemon_id` of this machine's daemon, from its `daemon.json`; `None` if unknown."""
    try:
        data = json.loads((config.LOG_DIR / "daemon.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("daemon_id") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def credential() -> str:
    """The secret sent as `Bearer`: the remote port token if there is one, else the backend key."""
    return token_source.remote_web_token() or token_source.api_key()


# --- the remembered "unusable" ---------------------------------------------------------------


class _Memory:
    """Per daemon URL: the last reason it was unusable and until when. Plus what was logged."""

    lock = threading.Lock()
    unusable: ClassVar[dict[str, tuple[str, float]]] = {}
    logged: ClassVar[set[str]] = set()
    last: ClassVar[dict[str, str]] = {}


def remembered(url: str) -> str | None:
    """The reason `url` is unusable, while it is remembered; `None` otherwise."""
    with _Memory.lock:
        found = _Memory.unusable.get(url)
        if found is None:
            return None
        reason, until = found
        if time.monotonic() >= until:
            _Memory.unusable.pop(url, None)
            return None
        return reason


def remember(url: str, reason: str) -> None:
    """Remember `url` as unusable and say it once per process and reason (REQ-025 case 1)."""
    ttl = UNSUPPORTED_TTL_S if reason in (UNSUPPORTED, SELF) else UNUSABLE_TTL_S
    with _Memory.lock:
        _Memory.unusable[url] = (reason, time.monotonic() + ttl)
        _Memory.last[url] = reason
        first = reason not in _Memory.logged
        _Memory.logged.add(reason)
    if first and reason != SELF:
        logger.warning(i18n.t("mcp.remote_turn.unusable", url=display_url(url), reason=reason))


def note_result(url: str, result: str) -> None:
    """The last result against `url`, for `local_status`."""
    with _Memory.lock:
        _Memory.last[url] = result


def last_result(url: str) -> str | None:
    with _Memory.lock:
        return _Memory.last.get(url)


def reset() -> None:
    """Forget everything (tests): reasons, what was logged and the shared client."""
    with _Memory.lock:
        _Memory.unusable.clear()
        _Memory.logged.clear()
        _Memory.last.clear()
    _Transport.close()


# --- transport -------------------------------------------------------------------------------


def _new_client() -> httpx2.Client:
    # Its own client and not the backend's: other timeouts (REQ-025), never redirects (a 3xx is a
    # bad answer) and no cookies kept between requests.
    return httpx2.Client(
        timeout=httpx2.Timeout(DEFAULT_HEARTBEAT_S + READ_MARGIN_S, connect=CONNECT_TIMEOUT_S),
        follow_redirects=False,
    )


class _Transport:
    """One client per process, created on the first remote request (never in local-only use)."""

    lock = threading.Lock()
    client: httpx2.Client | None = None
    #: The factory; the tests put an in-process `TestClient` here.
    factory: Callable[[], httpx2.Client] = staticmethod(_new_client)

    @classmethod
    def get(cls) -> httpx2.Client:
        with cls.lock:
            if cls.client is None:
                cls.client = cls.factory()
            return cls.client

    @classmethod
    def close(cls) -> None:
        with cls.lock:
            client, cls.client = cls.client, None
        if client is not None:
            try:
                client.close()
            except Exception:  # closing is tidying up; nothing depends on it
                pass


def set_client_factory(factory: Callable[[], httpx2.Client]) -> None:
    """Use `factory` for the shared client from now on (tests); the current client is closed."""
    _Transport.close()
    _Transport.factory = staticmethod(factory)  # type: ignore[assignment]


def _parse(response: httpx2.Response) -> Answer:
    code = response.status_code
    if code in (404, 405):
        raise Unusable(UNSUPPORTED)
    if code == 401:
        raise Unusable(UNAUTHORIZED)
    if code == 403:
        try:
            error = response.json().get("error")
        except (ValueError, AttributeError):
            error = None
        raise Unusable(NEEDS_SECRET if error == "turn_needs_secret" else UNAUTHORIZED)
    if code == 429:
        raise _Busy
    if code != 200:
        raise Unusable(BAD_RESPONSE)
    try:
        data = response.json()
    except ValueError:
        raise Unusable(BAD_RESPONSE) from None
    if not isinstance(data, dict):
        raise Unusable(BAD_RESPONSE)
    version = data.get("v")
    if not isinstance(version, int) or isinstance(version, bool):
        raise Unusable(BAD_RESPONSE)
    if version > API_VERSION:
        raise Unusable(UNSUPPORTED)  # REQ-041: a newer protocol degrades as unsupported
    status = data.get("status")
    if status not in _STATUSES:
        raise Unusable(BAD_RESPONSE)
    try:
        heartbeat_s = float(data.get("heartbeat_s") or DEFAULT_HEARTBEAT_S)
        stalled_s = float(data.get("stalled_s") or 0.0)
        position = data.get("position")
        position = int(position) if position is not None else None
        in_use = tuple(str(m) for m in (data.get("in_use") or ()))
    except (TypeError, ValueError):
        raise Unusable(BAD_RESPONSE) from None
    lease = data.get("lease")
    model = data.get("model")
    return Answer(
        status=status,
        lease=lease if isinstance(lease, str) and lease else None,
        daemon_id=str(data.get("daemon_id") or ""),
        position=position,
        in_use=in_use,
        model=model if isinstance(model, str) and model else None,
        forced=data.get("forced") is True,
        # Never 0 nor absurd: the loop and the thread wait this long between requests.
        heartbeat_s=min(max(heartbeat_s, 0.05), 60.0),
        stalled_s=max(0.0, stalled_s),
    )


def _post(url: str, path: str, body: dict[str, Any], *, read_s: float) -> Answer:
    """One request to the daemon. `Unusable`, `_Busy` or `_Lost` when there is no usable answer."""
    try:
        response = _Transport.get().post(
            url + path,
            json=body,
            headers={"Authorization": f"Bearer {credential()}"},
            timeout=httpx2.Timeout(read_s, connect=CONNECT_TIMEOUT_S),
        )
    except httpx2.TimeoutException:
        raise _Lost from None
    except Exception:
        # `HTTPError` and anything else the transport may raise (a bad proxy setting, a TLS
        # library error): the turn is a nicety, and a failure here never fails the delegation.
        raise Unusable(UNREACHABLE) from None
    return _parse(response)


# --- one operation's lease -------------------------------------------------------------------


Beat = Callable[[], dict[str, Any]]


class RemoteLease:
    """The remote turn of ONE operation for ONE model: asked, kept alive and given back.

    `acquire` blocks like a local turn wait and returns a `turn.Grant`; it raises
    `turn.AbandonedWait` when `should_stop` says so (cancellation or a saturated queue), and
    `Unusable` when the operation must go on without a turn (with the reason). After the grant a
    thread beats every `heartbeat_s` and raises the flags the operation reads before each send:
    `yield_requested` (REQ-030) and `lost` (`expired`, REQ-025 case 3). `release` is idempotent.
    """

    def __init__(
        self,
        url: str,
        *,
        op: str,
        host: str,
        tool: str,
        model: str,
        role: str = "",
        chain: tuple[str, ...] = (),
        chars_in: int = 0,
        chunks: int | None = None,
        beat: Beat | None = None,
    ) -> None:
        self.url = url
        self.daemon_host = _host_of(url)
        self._request = {
            "op": op,
            "host": host,
            "tool": tool,
            "model": model,
            "role": role,
            "chain": list(chain)[:16],
            "chars_in": max(0, int(chars_in)),
        }
        if chunks:
            self._request["chunks"] = int(chunks)
        self.model = model
        self._beat: Beat = beat or dict
        self.lease_id: str | None = None
        self.heartbeat_s = DEFAULT_HEARTBEAT_S
        self.granted = False
        self.forced = False
        self.busy = False
        self.yield_requested = threading.Event()
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._released = False
        #: The server's `stalled_s` at the last queued answer, and when it came (REQ-024).
        self._stalled: tuple[float, float] | None = None

    # --- waiting -----------------------------------------------------------------------------

    def wake(self) -> None:
        """Interrupt a pause of `acquire` (the call was cancelled)."""
        self._wake.set()

    def stalled_s(self, since: float) -> float:
        """Seconds without the queue moving: the daemon's clock while queued (REQ-024), else ours.

        `since` is when the wait started: before the first queued answer (or while the daemon is
        full, 429) the only clock is the wait's own.
        """
        now = time.monotonic()
        if self._stalled is None or self.busy:
            return now - since
        stalled, at = self._stalled
        return stalled + (now - at)

    def _read_s(self) -> float:
        return self.heartbeat_s + READ_MARGIN_S

    def _pause(self, seconds: float) -> None:
        self._wake.wait(seconds)
        self._wake.clear()

    def acquire(
        self, on_wait: turn.OnWait, should_stop: Callable[[], bool] | None = None
    ) -> turn.Grant:
        stop = should_stop or (lambda: False)
        reason = remembered(self.url)
        if reason is not None:
            raise Unusable(reason)
        if points_to_itself(self.url):
            remember(self.url, SELF)
            raise Unusable(SELF)
        retried_lost = False
        while True:
            if stop():
                self._give_back()
                raise turn.AbandonedWait
            started = time.monotonic()
            try:
                if self.lease_id is None:
                    answer = _post(self.url, ACQUIRE_PATH, self._request, read_s=self._read_s())
                else:
                    answer = _post(
                        self.url, HEARTBEAT_PATH, self._beat_body(), read_s=self._read_s()
                    )
            except _Busy:
                self.busy = True
                on_wait(0, ())
                self._pause(self.heartbeat_s)
                continue
            except _Lost:
                # No answer: a lease in hand may be gone. Ask again ONCE (the contract allows it
                # after a lost answer); a second loss in a row is an unreachable daemon.
                if retried_lost:
                    self._fail(UNREACHABLE)
                retried_lost = True
                self.lease_id = None
                continue
            except Unusable as error:
                self._fail(error.reason)
            retried_lost = False
            self.busy = False
            self.heartbeat_s = answer.heartbeat_s
            if answer.daemon_id and answer.daemon_id == local_daemon_id():
                # The guard by identity (REQ-020): that daemon is this machine's own.
                if answer.lease:
                    self.lease_id = answer.lease
                self._give_back()
                remember(self.url, SELF)
                raise Unusable(SELF)
            if answer.status == "no_turn":
                self._give_back()
                note_result(self.url, NO_TURN)
                raise Unusable(NO_TURN)
            if answer.status == "expired" or answer.lease is None:
                # Lost with the daemon alive (REQ-025 case 3): ask again, at the end of the queue.
                self.lease_id = None
                self._stalled = None
                self._pause(min(1.0, self.heartbeat_s / 2))
                continue
            self.lease_id = answer.lease
            if answer.status == "queued":
                self._stalled = (answer.stalled_s, time.monotonic())
                on_wait(answer.position or 1, answer.in_use)
                # The server waits up to `heartbeat_s` for a change; an answer that came back at
                # once (another long wait open, or the position moved) must not turn into a loop.
                pause = min(1.0, self.heartbeat_s / 2)
                if time.monotonic() - started < pause:
                    self._pause(pause)
                continue
            # granted or yield: the turn is ours (a yield right away still means "granted").
            self.granted = True
            self.forced = answer.forced
            if answer.status == "yield":
                self.yield_requested.set()
            note_result(self.url, FORCED if answer.forced else GRANTED)
            self._start_beating()
            return turn.Grant(str(self._request["op"]), frozenset({self.model}), answer.forced)

    def _fail(self, reason: str) -> NoReturn:
        self._give_back()
        remember(self.url, reason)
        raise Unusable(reason)

    # --- keeping it ----------------------------------------------------------------------------

    def _beat_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"lease": self.lease_id}
        try:
            state = self._beat() if self.granted else {}
        except Exception:  # the state is a nicety; the beat itself is what keeps the lease
            state = {}
        if state.get("in_backend") is True:
            body["in_backend"] = True
        waiting = state.get("waiting_backend")
        if isinstance(waiting, dict) and waiting:
            body["waiting_backend"] = {str(k): str(v) for k, v in list(waiting.items())[:16]}
        elif waiting is True:
            body["waiting_backend"] = True
        chunk = state.get("chunk")
        if isinstance(chunk, int) and not isinstance(chunk, bool) and chunk >= 0:
            body["chunk"] = chunk
        phase = state.get("phase")
        if phase in ("map", "reduce", "retry"):
            body["phase"] = phase
        return body

    def _start_beating(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._beat_loop, name="remote-turn-heartbeat", daemon=True
        )
        self._thread.start()

    def _beat_loop(self) -> None:
        # The only sender while granted: the heartbeats of a lease go one after the other.
        while not self._stop.wait(self.heartbeat_s):
            if self.lease_id is None:
                return
            try:
                answer = _post(self.url, HEARTBEAT_PATH, self._beat_body(), read_s=self._read_s())
            except (Unusable, _Busy, _Lost):
                # Nothing to do now: the next beat tries again, and a daemon that comes back with
                # the lease gone answers `expired`.
                continue
            if self._stop.is_set():
                return
            self.heartbeat_s = answer.heartbeat_s
            if answer.status == "yield":
                self.yield_requested.set()
            elif answer.status in ("expired", "no_turn"):
                self.lost.set()
                return

    # --- giving it back -------------------------------------------------------------------------

    def _give_back(self) -> None:
        lease, self.lease_id = self.lease_id, None
        if lease is None:
            return
        try:
            _post(self.url, RELEASE_PATH, {"lease": lease}, read_s=RELEASE_READ_S)
        except (Unusable, _Busy, _Lost):
            pass  # best-effort: the lease expires on its own after `TURN_LEASE_S`

    def release(self) -> None:
        """Stop beating and give the lease back. Idempotent; never raises."""
        if self._released:
            return
        self._released = True
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            # A beat may be on its way; it does not hold the release up for long.
            thread.join(timeout=0.5)
        try:
            self._give_back()
        except Exception:  # a release never breaks the operation's `finally`
            pass


# --- `local_status` ---------------------------------------------------------------------------


def status_line(*, remote_backend: bool) -> str | None:
    """REQ-027: the «Remote turn» line of `local_status`, or `None` when it does not apply."""
    mode = _mode()
    if mode == "off":
        return i18n.t("mcp.status.remote_turn.off") if remote_backend else None
    url = turn_url(remote_backend=remote_backend)
    if url is None:
        if explicit_url():
            return i18n.t("mcp.status.remote_turn.unavailable", reason=BAD_URL)
        return None
    reason = remembered(url)
    if reason is None and points_to_itself(url):
        reason = SELF
    if reason is not None:
        return i18n.t("mcp.status.remote_turn.unavailable", reason=reason)
    return i18n.t("mcp.status.remote_turn.active", url=display_url(url))
