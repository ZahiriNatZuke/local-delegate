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
  60 s (404/405, and an unreachable daemon that never granted a turn in this process: 10 min), so
  the next operations do not pay the timeout again, and it is logged once per process and reason.
- Never to itself (REQ-020): a loopback URL on this process's own `WEB_PORT`, or a daemon whose
  `daemon_id` is the one in this machine's `daemon.json`, is `self` and goes without a turn.

Discovery (REQ-021) is `turn_url`: with `LOCAL_DELEGATE_TURN_URL=auto` (the default) it asks only
when the backend is another machine's AND its host is private (a tailnet, a LAN; decided from the
name or the address, never with DNS). A local backend or a public one gives no URL at all, so such a
setup never sends a single request (REQ-040; review of #502).

The credential (REQ-016) is `LOCAL_DELEGATE_REMOTE_WEB_TOKEN` (or the Keychain) when present, else
the backend's key, always as `Authorization: Bearer`. It is never logged nor stored here. Every
answer is read with a total deadline and a size cap: a daemon that drips or floods cannot hold an
operation.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import math
import re
import socket
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
#: Plazos de REQ-025: connection 3 s, read `heartbeat_s + 5` s; the whole answer within both.
CONNECT_TIMEOUT_S = 3.0
READ_MARGIN_S = 5.0
#: The interval before the first answer says otherwise (the server's `min(5, TURN_LEASE_S / 3)`).
DEFAULT_HEARTBEAT_S = 5.0
#: How long an unusable daemon is remembered, by reason (REQ-025 case 1).
UNUSABLE_TTL_S = 60.0
UNSUPPORTED_TTL_S = 600.0
#: An unreachable daemon that never granted a turn in this process (a filtered port, a daemon that
#: is not there): remembered as long as a 404, so each operation does not pay the timeout again.
NEVER_REACHED_TTL_S = 600.0
#: The whole of a release, connection included: it is best-effort, the lease expires anyway.
RELEASE_READ_S = 3.0
#: The largest answer read; the server's are a few hundred bytes.
MAX_ANSWER_BYTES = 64 * 1024
#: At most this many models in `in_use`, of at most this many characters each.
MAX_IN_USE = 16
MAX_NAME_CHARS = 128

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
#: What `local_status` says when `auto` does not ask because the backend's host is not private.
PUBLIC_HOST = "public_host"

_STATUSES = frozenset({"queued", "granted", "yield", "expired", "no_turn"})
_LEASE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_MODEL_NAME = re.compile(r"[A-Za-z0-9._:/@-]{1,128}")
#: Private suffixes (review of #502): the tailnet's MagicDNS and the usual home and LAN names.
_PRIVATE_SUFFIXES = (".ts.net", ".local", ".lan", ".home.arpa", ".internal")
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",  # CGNAT, the tailnet's 100.x
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",  # ULA, the tailnet's fd7a:115c:a1e0::/48 among them
        "fe80::/10",
    )
)


class Unusable(Exception):
    """The daemon cannot give a turn: the operation goes on without one, with this reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Busy(Exception):
    """`429`: the daemon is alive but full. Wait and try again (REQ-025 case 2)."""


class _Lost(Exception):
    """No answer to a request that may have arrived: a lease in hand may or may not be alive."""


class _Stopped(Exception):
    """The operation stopped (cancelled or saturated) while an answer was being read.

    `lease` is the lease the part already read names, if any: the caller gives it back, so a
    stop in the middle of the first `acquire` does not leave a lease at the daemon.
    """

    def __init__(self, lease: str | None = None) -> None:
        super().__init__(lease)
        self.lease = lease


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


def _now() -> float:
    """The clock of the remembered reasons (the tests replace it)."""
    return time.monotonic()


# --- addresses -------------------------------------------------------------------------------


def _address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """`host` as an IP address, also IPv4 shorthand (`127.1`); `None` for a name. Never DNS."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host and all(c.isdigit() or c == "." for c in host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _bare(host: str) -> str:
    return host.strip().lower().rstrip(".")


def is_private_host(host: str) -> bool:
    """A host of a private network, decided from its text alone (review of #502, no DNS).

    Loopback, RFC 1918, the tailnet's CGNAT (100.64/10), ULA (fc00::/7) and link-local addresses;
    names under `.ts.net`, `.local`, `.lan`, `.home.arpa` or `.internal`; and one-label names
    (MagicDNS short names such as `pc`).
    """
    bare = _bare(host)
    if not bare:
        return False
    address = _address(bare)
    if address is not None:
        return any(address in network for network in _PRIVATE_NETWORKS)
    if "." not in bare:
        return True
    return bare.endswith(_PRIVATE_SUFFIXES)


def _is_this_machine(host: str) -> bool:
    """Loopback (any 127/8, `127.1` included), unspecified (`0.0.0.0`, `::`) or `*.localhost`."""
    bare = _bare(host)
    if bare == "localhost" or bare.endswith(".localhost"):
        return True
    address = _address(bare)
    return address is not None and (address.is_loopback or address.is_unspecified)


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
        and not parts.query
        and not parts.fragment
        and parts.path in ("", "/")
    )


def _normalized(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def turn_url(*, remote_backend: bool) -> str | None:
    """The daemon to ask for the turn, or `None` (no remote turn for this process).

    REQ-020/021: `off` → never; a URL → that one; `auto` → the backend machine's daemon, only when
    the backend is not on loopback (`remote_backend`) and its host is private. A local or public
    backend with `auto` gives `None` before anything else is looked at: no client, no request.
    """
    mode = _mode()
    if mode == "off":
        return None
    if mode in ("", "auto"):
        if not remote_backend:
            return None
        url = config.remote_panel_url()
        if not url or not is_private_host(_host_of(url)):
            return None
        return url
    if not _valid(mode):
        return None
    url = _normalized(mode)
    if plaintext_to_public(url):
        _warn_once("plaintext", "mcp.remote_turn.plaintext", url)
    return url


def _auto_public(*, remote_backend: bool) -> bool:
    """`auto` with a remote backend whose host is not private: it does not ask (review of #502)."""
    if _mode() not in ("", "auto") or not remote_backend:
        return False
    url = config.remote_panel_url()
    return bool(url) and not is_private_host(_host_of(url))


def plaintext_to_public(url: str) -> bool:
    """`http://` to a host that is not private: the credential would cross a network in clear."""
    parts = urlsplit(url)
    return parts.scheme == "http" and not is_private_host(parts.hostname or "")


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
    """The guard by address (REQ-020): this machine's address on this process's own web port."""
    parts = urlsplit(url)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    return _is_this_machine(parts.hostname or "") and port == config.WEB_PORT


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
    #: URLs that granted a turn at least once in this process.
    reached: ClassVar[set[str]] = set()


def remembered(url: str) -> str | None:
    """The reason `url` is unusable, while it is remembered; `None` otherwise."""
    with _Memory.lock:
        found = _Memory.unusable.get(url)
        if found is None:
            return None
        reason, until = found
        if _now() >= until:
            _Memory.unusable.pop(url, None)
            return None
        return reason


def _ttl(url: str, reason: str) -> float:
    if reason in (UNSUPPORTED, SELF):
        return UNSUPPORTED_TTL_S
    if reason == UNREACHABLE and url not in _Memory.reached:
        return NEVER_REACHED_TTL_S
    return UNUSABLE_TTL_S


def _warn_once(kind: str, key: str, url: str, **fields: str) -> None:
    with _Memory.lock:
        first = kind not in _Memory.logged
        _Memory.logged.add(kind)
    if first:
        logger.warning(i18n.t(key, url=display_url(url), **fields))


def remember(url: str, reason: str) -> None:
    """Remember `url` as unusable and say it once per process and reason (REQ-025 case 1)."""
    with _Memory.lock:
        _Memory.unusable[url] = (reason, _now() + _ttl(url, reason))
        _Memory.last[url] = reason
    if reason != SELF:
        _warn_once(reason, "mcp.remote_turn.unusable", url, reason=reason)


def note_result(url: str, result: str) -> None:
    """The last result against `url`, for `local_status`; a grant marks the URL as reached."""
    with _Memory.lock:
        _Memory.last[url] = result
        if result in (GRANTED, FORCED):
            _Memory.reached.add(url)


def last_result(url: str) -> str | None:
    with _Memory.lock:
        return _Memory.last.get(url)


def reset() -> None:
    """Forget everything (tests): reasons, what was logged and the shared client."""
    with _Memory.lock:
        _Memory.unusable.clear()
        _Memory.logged.clear()
        _Memory.last.clear()
        _Memory.reached.clear()
    _Transport.close()


# --- transport -------------------------------------------------------------------------------


def _new_client() -> httpx2.Client:
    # Its own client and not the backend's: other timeouts (REQ-025), never redirects (a 3xx is a
    # bad answer), no cookies kept between requests and no proxy from the environment: the
    # credential goes to the daemon named here and nowhere else.
    return httpx2.Client(
        timeout=httpx2.Timeout(DEFAULT_HEARTBEAT_S + READ_MARGIN_S, connect=CONNECT_TIMEOUT_S),
        follow_redirects=False,
        trust_env=False,
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


def _finite(value: Any, default: float) -> float:
    number = float(value) if value is not None else default
    return number if math.isfinite(number) else default


def _in_use(raw: Any) -> tuple[str, ...]:
    """The models in use as the daemon says them, cleaned: what is not a model name is dropped."""
    if not isinstance(raw, list):
        return ()
    names = [m for m in raw[:MAX_IN_USE] if isinstance(m, str) and _MODEL_NAME.fullmatch(m)]
    return tuple(names)


def _answer(data: dict) -> Answer:
    version = data.get("v")
    if not isinstance(version, int) or isinstance(version, bool):
        raise Unusable(BAD_RESPONSE)
    if version > API_VERSION:
        raise Unusable(UNSUPPORTED)  # REQ-041: a newer protocol degrades as unsupported
    status = data.get("status")
    if status not in _STATUSES:
        raise Unusable(BAD_RESPONSE)
    lease = data.get("lease")
    if lease is not None and not (isinstance(lease, str) and _LEASE.fullmatch(lease)):
        raise Unusable(BAD_RESPONSE)
    position = data.get("position")
    position = int(position) if position is not None else None
    model = data.get("model")
    daemon_id = data.get("daemon_id")
    return Answer(
        status=status,
        lease=lease,
        daemon_id=daemon_id if isinstance(daemon_id, str) else "",
        position=position,
        in_use=_in_use(data.get("in_use")),
        model=model if isinstance(model, str) and _MODEL_NAME.fullmatch(model) else None,
        forced=data.get("forced") is True,
        # Never 0, absurd or not a number: the loop and the thread wait this long between requests.
        heartbeat_s=min(max(_finite(data.get("heartbeat_s"), DEFAULT_HEARTBEAT_S), 0.05), 60.0),
        stalled_s=max(0.0, _finite(data.get("stalled_s"), 0.0)),
    )


def _parse(status_code: int, body: bytes) -> Answer:
    """An answer of the daemon, or the exception that says what to do with it."""
    if status_code in (404, 405):
        raise Unusable(UNSUPPORTED)
    if status_code == 401:
        raise Unusable(UNAUTHORIZED)
    if status_code == 429:
        raise _Busy
    try:
        data = json.loads(body)
    except Exception:  # broken, too deep (`RecursionError`), not UTF-8: all unreadable
        data = None
    if status_code == 403:
        error = data.get("error") if isinstance(data, dict) else None
        raise Unusable(NEEDS_SECRET if error == "turn_needs_secret" else UNAUTHORIZED)
    if status_code != 200 or not isinstance(data, dict):
        raise Unusable(BAD_RESPONSE)
    try:
        return _answer(data)
    except Unusable:
        raise
    except Exception:  # `1e999` (OverflowError), a list where a number goes...: unreadable
        raise Unusable(BAD_RESPONSE) from None


def _lease_in(body: bytes) -> str | None:
    """The lease named by a (maybe partial) answer, if it can be read; `None` otherwise."""
    try:
        data = json.loads(body)
        lease = data.get("lease") if isinstance(data, dict) else None
    except Exception:  # a partial answer is unreadable more often than not
        return None
    return lease if isinstance(lease, str) and _LEASE.fullmatch(lease) else None


def _post(
    url: str,
    path: str,
    body: dict[str, Any],
    *,
    read_s: float,
    total_s: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Answer:
    """One request to the daemon. `Unusable`, `_Busy`, `_Lost` or `_Stopped` without an answer.

    The whole answer must arrive within `total_s` (by default, connection plus `read_s`) and weigh
    at most `MAX_ANSWER_BYTES`; `should_stop` is looked at between two pieces of it.
    """
    deadline = time.monotonic() + (total_s if total_s is not None else CONNECT_TIMEOUT_S + read_s)
    connect_s = min(CONNECT_TIMEOUT_S, total_s) if total_s is not None else CONNECT_TIMEOUT_S
    data = bytearray()
    try:
        with _Transport.get().stream(
            "POST",
            url + path,
            json=body,
            headers={"Authorization": f"Bearer {credential()}"},
            timeout=httpx2.Timeout(read_s, connect=connect_s),
        ) as response:
            status_code = response.status_code
            for piece in response.iter_bytes():
                data += piece
                if len(data) > MAX_ANSWER_BYTES:
                    raise Unusable(BAD_RESPONSE)
                if should_stop is not None and should_stop():
                    raise _Stopped(_lease_in(bytes(data)))
                if time.monotonic() > deadline:
                    raise _Lost
    except (Unusable, _Lost, _Stopped):
        raise
    except httpx2.ConnectTimeout:
        # Nothing arrived (a filtered port): no lease can be at stake, so no retry either.
        raise Unusable(UNREACHABLE) from None
    except httpx2.TimeoutException:
        raise _Lost from None
    except Exception:
        # `HTTPError` and anything else the transport may raise (a bad proxy setting, a TLS
        # library error): the turn is a nicety, and a failure here never fails the delegation.
        raise Unusable(UNREACHABLE) from None
    return _parse(status_code, bytes(data))


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
        asked_to_stop = should_stop or (lambda: False)

        def stop() -> bool:
            # A release from another thread ends the wait too: nothing may beat after it.
            return self._released or asked_to_stop()

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
                    path, body = ACQUIRE_PATH, self._request
                else:
                    path, body = HEARTBEAT_PATH, self._beat_body()
                answer = _post(self.url, path, body, read_s=self._read_s(), should_stop=stop)
            except _Stopped as stopped:
                if self.lease_id is None:
                    self.lease_id = stopped.lease
                self._give_back()
                raise turn.AbandonedWait from None
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
            if self._released:
                self._give_back()  # released while the grant was on its way
                raise turn.AbandonedWait
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
        self._thread = threading.Thread(
            target=self._beat_loop, name="remote-turn-heartbeat", daemon=True
        )
        self._thread.start()

    def _beat_loop(self) -> None:
        try:
            self._beating()
        except Exception:
            # Never dies in silence: whatever broke the beat, the lease cannot be counted on any
            # more, and the next send asks for the turn again (REQ-025 case 3).
            self.lost.set()

    def _beating(self) -> None:
        # The only sender while granted: the heartbeats of a lease go one after the other.
        while not self._stop.wait(self.heartbeat_s):
            if self.lease_id is None:
                return
            try:
                answer = _post(
                    self.url,
                    HEARTBEAT_PATH,
                    self._beat_body(),
                    read_s=self._read_s(),
                    should_stop=self._stop.is_set,
                )
            except _Stopped:
                return
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
            _post(
                self.url,
                RELEASE_PATH,
                {"lease": lease},
                read_s=RELEASE_READ_S,
                total_s=RELEASE_READ_S,
            )
        except (Unusable, _Busy, _Lost, _Stopped):
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
    if _auto_public(remote_backend=remote_backend):
        return i18n.t("mcp.status.remote_turn.unavailable", reason=PUBLIC_HOST)
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
    if plaintext_to_public(url):
        return i18n.t("mcp.status.remote_turn.active_plaintext", url=display_url(url))
    return i18n.t("mcp.status.remote_turn.active", url=display_url(url))


# --- `doctor` ---------------------------------------------------------------------------------

#: The lease `probe` gives back. No daemon hands it out (theirs are 43 characters of
#: `token_urlsafe(32)`), so its `release` changes nothing and still walks the whole authentication.
PROBE_LEASE = "doctor-probe"
#: What `probe` answers when the daemon took the request.
REACHABLE = "reachable"
#: `probe` with the credential, but this machine has none to send.
NO_CREDENTIAL = "no_credential"


def probe(url: str, *, with_credential: bool = True) -> str:
    """REQ-027 (`doctor`): does the daemon at `url` serve the turn, and does it take this request?

    A `release` of `PROBE_LEASE`: idempotent, it touches no lease, no queue and no file. Answers
    `REACHABLE`, `SELF` (the daemon is this machine's own, by `daemon_id`), `NO_CREDENTIAL` or a
    reason of REQ-025 (`unreachable`, `unsupported`, `unauthorized`, `needs_secret`,
    `bad_response`). Without the credential it tells the PC's `doctor` whether its daemon has a
    secret: `unauthorized` (it has one) or `needs_secret` (it has none). Never raises, and never
    says the credential.
    """
    headers: dict[str, str] = {}
    if with_credential:
        secret = credential()
        if not secret:
            return NO_CREDENTIAL
        headers["Authorization"] = f"Bearer {secret}"
    data = bytearray()
    deadline = time.monotonic() + CONNECT_TIMEOUT_S + RELEASE_READ_S
    try:
        with _Transport.get().stream(
            "POST",
            url + RELEASE_PATH,
            json={"lease": PROBE_LEASE},
            headers=headers,
            timeout=httpx2.Timeout(RELEASE_READ_S, connect=CONNECT_TIMEOUT_S),
        ) as response:
            status_code = response.status_code
            for piece in response.iter_bytes():
                data += piece
                if len(data) > MAX_ANSWER_BYTES:
                    return BAD_RESPONSE
                if time.monotonic() > deadline:
                    return UNREACHABLE
    except Exception:  # whatever the transport raises: the daemon could not be asked
        return UNREACHABLE
    return _probe_verdict(status_code, bytes(data))


def _probe_verdict(status_code: int, body: bytes) -> str:
    """What a `release` answer says about the daemon (see `probe`)."""
    if status_code != 200:
        try:
            _parse(status_code, body)
        except Unusable as unusable:
            return unusable.reason
        except Exception:  # `_Busy`: `release` is never limited, so it is not the daemon we know
            return BAD_RESPONSE
        return BAD_RESPONSE
    try:
        data = json.loads(body)
    except Exception:  # broken, too deep (`RecursionError`), not UTF-8: all unreadable
        return BAD_RESPONSE
    if not isinstance(data, dict):
        return BAD_RESPONSE
    version = data.get("v")
    if not isinstance(version, int) or isinstance(version, bool):
        return BAD_RESPONSE
    if version > API_VERSION:
        return UNSUPPORTED
    if data.get("status") != "released":
        return BAD_RESPONSE
    daemon_id = data.get("daemon_id")
    if isinstance(daemon_id, str) and daemon_id and daemon_id == local_daemon_id():
        return SELF
    return REACHABLE
