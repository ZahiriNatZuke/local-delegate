"""llama-swap visto desde el daemon y desde el CLI: estado, peticiones en vuelo y vigía de recarga.

Es la mitad «de red» de `llamaswap residency` (REQ-034, REQ-039). La otra mitad, la que edita el
fichero, vive en `residency.py` y no sabe nada de HTTP.

Qué se le pregunta a llama-swap (v255) y qué se descarta:

* `GET /running` da cada modelo con su `cmd`, su `proxy` y más. De ahí solo sale `{id, state,
  ttl}`: el `cmd` lleva las rutas y, en la config real, la `--api-key` del servidor del modelo.
* `GET /api/events` es un flujo SSE. Al abrirlo manda una **carga inicial**: el historial de logs
  (`logData`, primero el del proxy, con un tope de unos 100 KB), el estado de los modelos y una foto
  `inflight` con las peticiones en curso **de cualquier cliente** (`operation: "snapshot"`). Cada
  petición de esa foto trae sus cabeceras (`req_headers`), así que de ella solo se cuenta cuántas
  hay por modelo y, de las cabeceras, solo se lee `X-Local-Delegate-Host` (la máquina de origen que
  manda este paquete desde la 0.45: `in_flight_requests`). Nunca la credencial.
* La recarga con `-watch-config` (sondeo de 2 s) se ve en el log del proxy: «reloading
  configuration», y luego «configuration reloaded» o un rechazo («failed to reload config»,
  «failed to build new server during reload»). En una recarga válida el servidor viejo se apaga y
  **cierra el flujo** antes de que el nuevo escriba «configuration reloaded» (T2, hallazgo 2), así
  que la vigía se reconecta y busca en el historial lo que llegó después de lo último que vio.

La credencial es la del proceso que pregunta (`config.backend_headers()`, que suma el origen): en el daemon, la de su
lanzador; en el CLI sin daemon, la del shell. El CLI no pregunta directamente sin ella (REQ-039,
punto 3): sin key, «no se sabe». Nada de este módulo imprime ni devuelve la key.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx2

from . import config, i18n
from .residency import CONFIG_PATH_FIELD

# --- Salidas de la vigía (REQ-034) -----------------------------------------------------------
RELOADED = "reloaded"
REJECTED = "rejected"
NOT_WATCHING = "not_watching"
DOWN = "down"
UNRESOLVED = "unresolved"
# Los valores de arriba son los del JSON del daemon; `outcome_text` los dice a la persona.
_OUTCOME_KEYS = {
    RELOADED: "cli.llamaswap_api.outcome.reloaded",
    REJECTED: "cli.llamaswap_api.outcome.rejected",
    NOT_WATCHING: "cli.llamaswap_api.outcome.not_watching",
    DOWN: "cli.llamaswap_api.outcome.down",
    UNRESOLVED: "cli.llamaswap_api.outcome.unresolved",
}
OUTCOMES = frozenset(_OUTCOME_KEYS)


def outcome_text(outcome: str) -> str:
    """La salida de la vigía en palabras, en el idioma vigente («recargó», «reloaded»)."""
    return i18n.t(_OUTCOME_KEYS[outcome])


# --- Estado de llama-swap en una consulta ----------------------------------------------------
STATE_OK = "ok"
STATE_DOWN = "down"
STATE_UNKNOWN = "unknown"

PHRASE_RELOADING = "reloading configuration"
PHRASE_RELOADED = "configuration reloaded"
PHRASES_REJECTED = ("failed to reload config", "failed to build new server during reload")

# Plazos (REQ-034 y REQ-039). «No vigila»: sin «reloading configuration» en 10 s; en total, 45 s
# (sondeo de 2 s más el apagado del servidor viejo, de hasta 30 s).
NOT_WATCHING_AFTER_S = 10.0
WATCH_TOTAL_S = 45.0
# La foto `inflight` llega a los 0,016-0,031 s de abrir, con el historial lleno (T2, punto (e)).
IN_FLIGHT_CAP_S = 1.0
# Conectar: 3 s, porque en Windows un puerto cerrado tarda ~2,1 s en rechazarse y con menos llegaría
# como `ConnectTimeout` en vez de «caído» (el mismo criterio que `config.PROBE_CONNECT_TIMEOUT`).
CONNECT_S = config.PROBE_CONNECT_TIMEOUT
READ_S = 1.0
# Lo que el CLI espera al daemon. Más que lo que tarda el daemon en el peor caso (conectar a un
# llama-swap que no contesta, 3 s, y la foto, 1 s) y menos de 5 s en total con un daemon que acepta
# la conexión y no contesta (el limitador de hilos agotado): así el CLI no se queda colgado.
CLI_TO_DAEMON = httpx2.Timeout(4.0, connect=CONNECT_S)
# Abrir la vigía: conectar y tragarse la carga inicial.
CLI_TO_DAEMON_WATCH = httpx2.Timeout(8.0, connect=CONNECT_S)
# Cada consulta del CLI por el resultado de la vigía, mientras llama-swap recarga.
WATCH_POLL_S = 0.5
# Vigías vivas a la vez en el daemon, y cuánto se guarda un resultado ya resuelto.
MAX_WATCHERS = 4
FORGET_AFTER_S = 300.0
# Cuánto del final de lo ya visto se busca en el historial al reconectar.
_TAIL = 256


class QueryError(Exception):
    """llama-swap contestó, pero no se puede saber lo que se pedía (401, respuesta rara...)."""


class TooManyWatches(QueryError):
    """El daemon ya tiene abiertas todas las vigías que admite (`Watches.max_watchers`)."""


@dataclass(frozen=True)
class Backend:
    """Dónde está llama-swap (sin el `/v1`) y con qué cabeceras se le pregunta."""

    base: str
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)


def local_backend() -> Backend:
    """El llama-swap de `LOCAL_DELEGATE_BASE_URL`, con la credencial de este proceso."""
    return Backend(config.BASE_URL.removesuffix("/v1"), config.backend_headers())


def _client(read: float = READ_S, connect: float = CONNECT_S) -> httpx2.Client:
    return httpx2.Client(timeout=httpx2.Timeout(read, connect=connect))


def _caps(cap_s: float | None) -> tuple[float, float]:
    """(lectura, conexión): con `cap_s`, las dos con ese tope; sin él, las de siempre."""
    return (READ_S, CONNECT_S) if cap_s is None else (cap_s, cap_s)


def _check(response: httpx2.Response, what: str) -> None:
    if response.status_code in (401, 403):
        raise QueryError(
            i18n.t("cli.llamaswap_api.credential_rejected", what=what, code=response.status_code)
        )
    if not response.is_success:
        raise QueryError(i18n.t("cli.llamaswap_api.answered", what=what, code=response.status_code))


def running(backend: Backend, cap_s: float | None = None) -> list[dict[str, Any]]:
    """`/running` reducido a `{id, state, ttl}`. Todo lo demás (el `cmd` incluido) se descarta.

    `cap_s` es el tope de toda la consulta, también de la conexión (la foto de la afinidad, T15,
    con la plaza en la mano: REQ-004). Sin él, los plazos de siempre.
    """
    with _client(*_caps(cap_s)) as c:
        r = c.get(f"{backend.base}/running", headers=dict(backend.headers))
    _check(r, "/running")
    try:
        data = r.json()
    except ValueError:
        raise QueryError(i18n.t("cli.llamaswap_api.not_json", what="/running")) from None
    entries = data.get("running") if isinstance(data, dict) else None
    if entries is None:
        entries = []  # «nada cargado»: v255 manda `null`
    if not isinstance(entries, list):
        raise QueryError(i18n.t("cli.llamaswap_api.running_not_list"))
    models: list[dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("model"), str):
            continue
        ttl = e.get("ttl")
        models.append(
            {
                "id": e["model"],
                "state": e.get("state") if isinstance(e.get("state"), str) else None,
                "ttl": ttl if isinstance(ttl, int) and not isinstance(ttl, bool) else None,
            }
        )
    return models


def _messages(lines: Iterator[str]) -> Iterator[tuple[str, Any]]:
    """`(tipo, datos)` de cada `data:` del flujo SSE. Lo que no se entiende se salta."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        try:
            message = json.loads(line[5:])
            kind = message["type"]
            payload = message.get("data")
            data = json.loads(payload) if isinstance(payload, str) else payload
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(kind, str):
            yield kind, data


def _proxy_log(data: Any) -> str:
    """El texto de un `logData` del proxy; los de los servidores de modelos (`upstream`) no cuentan."""
    if isinstance(data, dict) and data.get("source", "proxy") == "proxy":
        text = data.get("data")
        return text if isinstance(text, str) else ""
    return ""


def _count_by_model(data: Any) -> dict[str, int]:
    """Peticiones por modelo de una foto `inflight`. De cada petición solo se mira `model`."""
    requests = data.get("requests") if isinstance(data, dict) else None
    counts: dict[str, int] = {}
    for req in requests or []:
        model = req.get("model") if isinstance(req, dict) else None
        if isinstance(model, str):
            counts[model] = counts.get(model, 0) + 1
    return counts


def _origin_host(headers: Any) -> str | None:
    """`X-Local-Delegate-Host` of one `inflight` request, or `None`. Nothing else is read.

    llama-swap is written in Go: its headers may come as `{name: [values]}` and with the canonical
    case, so the name is compared without case and a list gives its first value.
    """
    if not isinstance(headers, dict):
        return None
    wanted = config.HOST_HEADER.lower()
    for name, value in headers.items():
        if not isinstance(name, str) or name.lower() != wanted:
            continue
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, str):
            return config.clean_machine_name(value) or None
    return None


def _requests_of(data: Any) -> list[dict[str, str | None]]:
    """Each request of an `inflight` photo as `{model, host}`: `host` is `None` without the header."""
    requests = data.get("requests") if isinstance(data, dict) else None
    found: list[dict[str, str | None]] = []
    for req in requests or []:
        model = req.get("model") if isinstance(req, dict) else None
        if isinstance(model, str):
            found.append({"model": model, "host": _origin_host(req.get("req_headers"))})
    return found


class _Stream:
    """Una conexión a `/api/events`, abierta hasta que se cierre a mano."""

    def __init__(self, backend: Backend, read: float = READ_S, connect: float = CONNECT_S) -> None:
        self._client = _client(read, connect)
        try:
            request = self._client.build_request(
                "GET", f"{backend.base}/api/events", headers=dict(backend.headers)
            )
            self._response = self._client.send(request, stream=True)
        except BaseException:
            self._client.close()
            raise
        try:
            _check(self._response, "/api/events")
        except QueryError:
            self.close()
            raise
        self.lines = self._response.iter_lines()

    def initial_load(self, cap_s: float) -> tuple[str, dict[str, int]]:
        """Lee hasta la primera foto `inflight`: (log del proxy, peticiones por modelo)."""
        log, data = self._first_inflight(cap_s)
        return log, _count_by_model(data)

    def _first_inflight(self, cap_s: float) -> tuple[str, Any]:
        """Lee hasta la primera foto `inflight`: (log del proxy, la foto tal cual llegó)."""
        deadline = time.monotonic() + cap_s
        log: list[str] = []
        for kind, data in _messages(self.lines):
            if kind == "logData":
                log.append(_proxy_log(data))
            elif kind == "inflight":
                return "".join(log), data
            if time.monotonic() > deadline:
                break
        raise QueryError(_no_inflight(cap_s))

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._client.close()


def in_flight(
    backend: Backend, cap_s: float = IN_FLIGHT_CAP_S, connect_s: float = CONNECT_S
) -> dict[str, int]:
    """Peticiones en vuelo por modelo, de cualquier cliente: la foto de la carga inicial.

    Lee `/api/events` hasta el primer `inflight`, con tope de `cap_s` (la lectura de cada trozo
    también lo lleva), y cierra. Sin cabeceras ni nada más de cada petición.
    """
    stream = _Stream(backend, read=cap_s, connect=connect_s)
    try:
        return stream.initial_load(cap_s)[1]
    except httpx2.TimeoutException:
        raise QueryError(_no_inflight(cap_s)) from None
    finally:
        stream.close()


def in_flight_requests(
    backend: Backend, cap_s: float = IN_FLIGHT_CAP_S, connect_s: float = CONNECT_S
) -> list[dict[str, str | None]]:
    """Las peticiones en vuelo de cualquier cliente, una a una, como `{model, host}`.

    Lo mismo que `in_flight`, sin agrupar: `host` es la máquina de origen si la petición trae
    `X-Local-Delegate-Host` (este paquete desde la 0.45) y `None` si no (otro cliente, o un MCP viejo).
    """
    stream = _Stream(backend, read=cap_s, connect=connect_s)
    try:
        return _requests_of(stream._first_inflight(cap_s)[1])
    except httpx2.TimeoutException:
        raise QueryError(_no_inflight(cap_s)) from None
    finally:
        stream.close()


def activity(backend: Backend, model: str, cap_s: float | None = None) -> dict[str, Any] | None:
    """La última petición terminada de `model` en `/api/metrics/activity`, o `None` si no hay.

    v255 apunta el id real (no el alias) y la hora de fin en `timestamp`, truncada al segundo
    (T2, puntos (a) y (c)). Solo se devuelven los campos sin datos de la petición.
    """
    with _client(*_caps(cap_s)) as c:
        r = c.get(
            f"{backend.base}/api/metrics/activity",
            params={"model": model, "limit": 1},
            headers=dict(backend.headers),
        )
    _check(r, "/api/metrics/activity")
    try:
        rows = r.json().get("data") or []
    except (ValueError, AttributeError):
        raise QueryError(
            i18n.t("cli.llamaswap_api.not_json", what="/api/metrics/activity")
        ) from None
    row = rows[0] if rows and isinstance(rows[0], dict) else None
    if row is None:
        return None
    return {k: row.get(k) for k in ("model", "timestamp", "duration_ms", "resp_status_code")}


# --- Estado para la comprobación previa (REQ-034, REQ-039) ----------------------------------


@dataclass
class Status:
    """Lo que el CLI y `doctor` necesitan saber del daemon y de su llama-swap.

    Nunca lleva `cmd`, cabeceras ni claves. `turn_*` es lo que el daemon dice de su propio turno
    (REQ-002): si lo tiene y, si no, el motivo con las palabras del lector de topología.
    """

    llamaswap: str
    detail: str = ""
    models: list[dict[str, Any]] = field(default_factory=list)
    in_flight: dict[str, int] = field(default_factory=dict)
    own_delegations: int = 0
    config_path: str | None = None
    watch_config: bool | None = None
    autostart: bool | None = None
    turn_active: bool | None = None
    turn_reason: str = ""
    turn_detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "llamaswap": self.llamaswap,
            "detail": self.detail,
            "models": [dict(m) for m in self.models],
            "in_flight": dict(self.in_flight),
            "own_delegations": self.own_delegations,
            CONFIG_PATH_FIELD: self.config_path,
            "watch_config": self.watch_config,
            "autostart": self.autostart,
            "turn_active": self.turn_active,
            "turn_reason": self.turn_reason,
            "turn_detail": self.turn_detail,
        }

    @classmethod
    def from_json(cls, data: Any) -> Status:
        if not isinstance(data, dict) or data.get("llamaswap") not in (
            STATE_OK,
            STATE_DOWN,
            STATE_UNKNOWN,
        ):
            raise QueryError(i18n.t("cli.llamaswap_api.daemon_status_garbled"))
        models = [m for m in data.get("models") or [] if isinstance(m, dict)]
        flights = {
            str(k): int(v)
            for k, v in (data.get("in_flight") or {}).items()
            if isinstance(v, int) and not isinstance(v, bool)
        }
        own = data.get("own_delegations")

        def text(key: str) -> str:
            value = data.get(key)
            return value if isinstance(value, str) else ""

        def flag(key: str) -> bool | None:
            value = data.get(key)
            return value if isinstance(value, bool) else None

        return cls(
            llamaswap=data["llamaswap"],
            detail=text("detail"),
            models=models,
            in_flight=flights,
            own_delegations=own if isinstance(own, int) and not isinstance(own, bool) else 0,
            config_path=text(CONFIG_PATH_FIELD) or None,
            watch_config=flag("watch_config"),
            autostart=flag("autostart"),
            turn_active=flag("turn_active"),
            turn_reason=text("turn_reason"),
            turn_detail=text("turn_detail"),
        )


def daemon_status(host: str, port: int, headers: Mapping[str, str]) -> tuple[Status | None, str]:
    """`(estado, por qué no)` preguntando al daemon por `GET /api/llamaswap/status`.

    Para `doctor` (`checks`). El CLI hace la misma consulta en `cli._daemon_status`, por
    `cli._daemon_url()`, que es lo que vigila la guarda de T11 sobre las llamadas de `cli.py`.
    """
    try:
        r = httpx2.get(
            f"http://{host}:{port}/api/llamaswap/status",
            headers=dict(headers),
            timeout=CLI_TO_DAEMON,
        )
    except httpx2.TimeoutException:
        return None, i18n.t("cli.llamaswap_api.daemon_timeout")
    except httpx2.HTTPError:
        return None, i18n.t("cli.llamaswap_api.daemon_down")
    if r.status_code != 200:
        return None, i18n.t("cli.llamaswap_api.daemon_answered", code=r.status_code)
    try:
        return Status.from_json(r.json()), ""
    except (ValueError, QueryError):
        return None, i18n.t("cli.llamaswap_api.daemon_status_garbled")


def query_status(backend: Backend, own_delegations: int) -> Status:
    """Pregunta a llama-swap por `/running` y por la foto de peticiones en vuelo.

    «Caído» es que no se pudo conectar: no hay nada que cortar. Cualquier otra cosa que impida
    saberlo (un 401, un plazo vencido, una respuesta rara) es «no se sabe».
    """
    try:
        models = running(backend)
        flights = in_flight(backend)
    except httpx2.ConnectError as e:
        return Status(
            STATE_DOWN,
            i18n.t("cli.llamaswap_api.down_at", base=backend.base, error=e),
            [],
            {},
            own_delegations,
        )
    except httpx2.TimeoutException as e:
        return Status(
            STATE_UNKNOWN,
            i18n.t("cli.llamaswap_api.timeout", error=type(e).__name__),
            own_delegations=own_delegations,
        )
    except (QueryError, httpx2.HTTPError) as e:
        return Status(STATE_UNKNOWN, str(e) or type(e).__name__, own_delegations=own_delegations)
    return Status(STATE_OK, "", models, flights, own_delegations)


def _no_inflight(cap_s: float) -> str:
    return i18n.t("cli.llamaswap_api.no_inflight", seconds=i18n.format_number(cap_s, None))


def refusals(status: Status) -> list[str]:
    """Por qué no se puede escribir ahora (REQ-034), en palabras; vacía si se puede."""
    reasons: list[str] = []
    if status.own_delegations:
        n = status.own_delegations
        key = (
            "cli.llamaswap_api.refusal.delegation"
            if n == 1
            else "cli.llamaswap_api.refusal.delegations"
        )
        reasons.append(i18n.t(key, n=i18n.format_number(n)))
    if status.llamaswap == STATE_UNKNOWN:
        reasons.append(i18n.t("cli.llamaswap_api.refusal.unknown", detail=status.detail))
    elif status.llamaswap == STATE_OK:
        total = sum(status.in_flight.values())
        if total:
            per_model = ", ".join(f"{m}: {n}" for m, n in sorted(status.in_flight.items()))
            key = (
                "cli.llamaswap_api.refusal.request"
                if total == 1
                else "cli.llamaswap_api.refusal.requests"
            )
            reasons.append(i18n.t(key, n=i18n.format_number(total), per_model=per_model))
        loaded = [str(m.get("id")) for m in status.models]
        if loaded:
            reasons.append(i18n.t("cli.llamaswap_api.refusal.loaded", models=", ".join(loaded)))
    return reasons


# --- Vigía de recarga (REQ-034, REQ-039) ----------------------------------------------------


def _count(text: str) -> dict[str, int]:
    return {
        "reloading": text.count(PHRASE_RELOADING),
        "reloaded": text.count(PHRASE_RELOADED),
        "rejected": sum(text.count(p) for p in PHRASES_REJECTED),
    }


def _new_text(history: str, tail: str) -> str | None:
    """Lo del historial posterior a `tail` (lo último ya visto), o `None` si no se encuentra."""
    if not tail:
        return history
    at = history.rfind(tail)
    return history[at + len(tail) :] if at >= 0 else None


class Watcher:
    """Vigila una recarga: se suscribe ANTES de escribir y dice cuál de las cuatro salidas hubo.

    `open()` se conecta y se traga la carga inicial (el historial de logs que ya estaba). Desde
    ahí cuenta el reloj de «no vigila». `wait()` lee lo que llega después y lo clasifica:
    rechazo, recarga hecha, o nada de «reloading configuration» en `not_watching_after` segundos.
    Si el flujo se cierra o se calla, se reconecta y busca en el historial lo posterior a lo
    último que vio. Si llama-swap no responde al abrir, la salida es «caído» sin esperar.
    """

    def __init__(
        self,
        backend: Backend,
        *,
        not_watching_after: float = NOT_WATCHING_AFTER_S,
        total: float = WATCH_TOTAL_S,
    ) -> None:
        self.backend = backend
        self.not_watching_after = not_watching_after
        self.total = total
        self.outcome: str | None = None
        self.line = ""
        self._seen = ""  # todo el log del proxy visto: la carga inicial más lo nuevo
        self._new = ""  # lo llegado tras la carga inicial
        self._base: dict[str, int] = {}
        self._stream: _Stream | None = None
        self._msgs: Iterator[tuple[str, Any]] = iter(())
        self._start = 0.0
        # Al reconectar, lo último visto ya no estaba en el historial (tope de ~100 KB): lo que
        # pasó en el hueco no se sabe. Desde ahí solo valen frases nuevas explícitas.
        self._history_lost = False

    def open(self) -> None:
        try:
            stream = _Stream(self.backend)
        except httpx2.ConnectError as e:
            self.outcome, self.line = DOWN, i18n.t("cli.llamaswap_api.down", error=e)
            return
        try:
            history, _ = stream.initial_load(CONNECT_S + READ_S)
        except BaseException:
            stream.close()
            raise
        self._stream = stream
        self._msgs = _messages(stream.lines)
        self._seen = history
        self._base = _count(history)
        self._start = time.monotonic()

    def _reconnect(self) -> None:
        try:
            stream = _Stream(self.backend)
            history, _ = stream.initial_load(CONNECT_S + READ_S)
        except (httpx2.HTTPError, QueryError):
            time.sleep(WATCH_POLL_S)  # el servidor viejo ya cerró y el nuevo aún no escucha
            return
        self._stream = stream
        self._msgs = _messages(stream.lines)
        new = _new_text(history, self._seen[-_TAIL:])
        if new is None:
            # Lo último visto ya salió del historial: en el hueco pudo haber un rechazo, un
            # «reloading» o una recarga que ya no se ven. Las cuentas solo prueban lo que SUBE (la
            # rotación quita, no inventa): un rechazo de más es un rechazo. Lo demás, no se sabe.
            self._history_lost = True
            if _count(history)["rejected"] > self._base["rejected"]:
                rejected = [
                    x for x in history.splitlines() if any(p in x for p in PHRASES_REJECTED)
                ]
                new = f"\n{rejected[-1]}\n"
            else:
                new = ""
            # Se reancla en el historial nuevo: la próxima reconexión busca su final, no una cola
            # que nunca estuvo en el log (y así no vuelve a caer aquí en cada reconexión).
            self._seen = history
        else:
            self._seen += new
        self._new += new

    def close(self) -> None:
        """Abandona la vigía sin esperar (el CLI no llegó a escribir)."""
        self._close_stream()

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def _classify(self, elapsed: float) -> bool:
        counts = _count(self._new)
        if counts["rejected"]:
            self.outcome = REJECTED
            self.line = next(
                (
                    x.strip()
                    for x in self._new.splitlines()
                    if any(p in x for p in PHRASES_REJECTED)
                ),
                "",
            )
        elif counts["reloaded"]:
            self.outcome = RELOADED
            self.line = next(
                (x.strip() for x in self._new.splitlines() if PHRASE_RELOADED in x), ""
            )
        elif (
            not self._history_lost
            and not counts["reloading"]
            and elapsed >= self.not_watching_after
        ):
            self.outcome = NOT_WATCHING
            self.line = i18n.t(
                "cli.llamaswap_api.no_reloading_line",
                phrase=PHRASE_RELOADING,
                seconds=i18n.format_number(self.not_watching_after, None),
            )
        return self.outcome is not None

    def wait(self) -> str:
        """Bloquea hasta saber la salida (como mucho `total` segundos desde `open()`)."""
        try:
            while self.outcome is None:
                elapsed = time.monotonic() - self._start
                if self._classify(elapsed):
                    break
                if elapsed >= self.total:
                    self.outcome = UNRESOLVED
                    self.line = (
                        i18n.t("cli.llamaswap_api.history_lost")
                        if self._history_lost
                        else i18n.t(
                            "cli.llamaswap_api.reload_unfinished",
                            seconds=i18n.format_number(self.total, None),
                        )
                    )
                    break
                if self._stream is None:
                    self._reconnect()
                    continue
                try:
                    kind, data = next(self._msgs)
                except StopIteration:
                    self._close_stream()  # el servidor cerró el flujo
                    continue
                except httpx2.HTTPError:
                    self._close_stream()  # silencio de más de READ_S o conexión caída
                    continue
                if kind == "logData":
                    text = _proxy_log(data)
                    self._seen += text
                    self._new += text
        finally:
            self._close_stream()
        return self.outcome


class WatchRegistry:
    """Las vigías que el daemon tiene abiertas para el CLI (`POST/GET /api/llamaswap/watch`)."""

    def __init__(self, max_watchers: int = MAX_WATCHERS, forget_after: float = FORGET_AFTER_S):
        self.max_watchers = max_watchers
        self.forget_after = forget_after
        self._lock = threading.Lock()
        self._watchers: dict[str, tuple[Watcher, float]] = {}
        self._reserved = 0

    def _forget_old(self, now: float) -> None:
        for wid, (w, opened) in list(self._watchers.items()):
            if w.outcome is not None and now - opened > self.forget_after:
                del self._watchers[wid]

    def open(self, backend: Backend) -> str:
        """Abre una vigía y la deja leyendo en un hilo propio. Vuelve con la carga inicial leída.

        La plaza se reserva con el cerrojo puesto y ANTES de abrir: abrir tarda (conectar y leer
        la carga inicial), y sin la reserva varias peticiones a la vez pasarían todas el tope.
        """
        with self._lock:
            self._forget_old(time.monotonic())
            alive = sum(1 for w, _ in self._watchers.values() if w.outcome is None)
            if alive + self._reserved >= self.max_watchers:
                raise TooManyWatches(
                    i18n.t("cli.llamaswap_api.too_many_watches", n=alive + self._reserved)
                )
            self._reserved += 1
        try:
            watcher = Watcher(backend)
            watcher.open()
            wid = uuid.uuid4().hex
            with self._lock:
                self._watchers[wid] = (watcher, time.monotonic())
        finally:
            with self._lock:
                self._reserved -= 1
        if watcher.outcome is None:
            threading.Thread(target=watcher.wait, daemon=True, name=f"watcher-{wid[:8]}").start()
        return wid

    def result(self, wid: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._watchers.get(wid)
        if item is None:
            return None
        watcher = item[0]
        return {"outcome": watcher.outcome, "line": watcher.line if watcher.outcome else ""}


watches = WatchRegistry()
