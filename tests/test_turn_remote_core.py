"""Concurrencia PC+Mac, lote 2: API sin bloqueo del turno, vuelo remoto y cesión entre trozos.

REQ-011 (API de `Turn`), REQ-013 (vuelo remoto frente a la red de seguridad), REQ-030 (cesión),
REQ-031 (sin inanición, con una simulación de reloj falso) y REQ-032 (`turn_yields` en el log).

Los tests del núcleo no duermen. Los de la envoltura y del daemon esperan con tope propio y
fallan con mensaje propio. Cada uno lleva una guarda de que el guion llega de verdad a lo que mide.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import backend_mock
import pytest
from test_affinity import affinity  # noqa: F401  (fixture)

from local_delegate import config, server, turn
from local_delegate.turn import Active, Grant, PendingRequest, State, Turn, Wait

M4B = "gemma3-4b"
M26B = "gemma4-26b-a4b"
QWEN = "qwen3.6-35b-a3b"
CAP_S = 2.0


def clashes_today(a: str, b: str) -> bool:
    return a != b


def req(op_id: str, role: str, *alternatives: str) -> PendingRequest:
    return PendingRequest(op_id, frozenset({role, *alternatives}), role)


class Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _until(condition: Callable[[], object], cap: float = CAP_S) -> object:
    end = time.monotonic() + cap
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.005)
    return None


# --- `must_yield` puro (REQ-030) ------------------------------------------------------------


def _blocked_state(granted_at: float = 0.0, head_since: float = 10.0) -> State:
    """X activa con el 26B; Y (Qwen) en la cabeza, bloqueada por X."""
    x = Active(Wait(req("x", M26B), 0.0), frozenset({M26B}), granted_at=granted_at)
    return State(actives=(x,), queue=(Wait(req("y", QWEN), head_since),))


def test_must_yield_when_all_three_conditions_hold():
    assert turn.must_yield(_blocked_state(), "x", 130.0, 120.0, clashes_today)


@pytest.mark.parametrize(
    ("state", "op_id", "now", "yield_s", "clashes", "why"),
    [
        (_blocked_state(), "x", 129.9, 120.0, clashes_today, "(b) la cabeza no lleva 120 s"),
        (
            _blocked_state(granted_at=50.0),
            "x",
            130.0,
            120.0,
            clashes_today,
            "(c) la operación no lleva 120 s con el turno",
        ),
        (
            _blocked_state(),
            "x",
            130.0,
            120.0,
            lambda _a, _b: False,
            "(a) la cabeza es concedible",
        ),
        (_blocked_state(), "x", 10_000.0, 0.0, clashes_today, "TURN_YIELD_S=0 la apaga"),
        (_blocked_state(), "otra", 130.0, 120.0, clashes_today, "no está en actives"),
        (
            State(actives=_blocked_state().actives),
            "x",
            130.0,
            120.0,
            clashes_today,
            "sin cola",
        ),
    ],
)
def test_must_yield_each_condition_false_alone(state, op_id, now, yield_s, clashes, why):
    assert turn.must_yield(_blocked_state(), "x", 130.0, 120.0, clashes_today)  # guarda
    assert not turn.must_yield(state, op_id, now, yield_s, clashes), why


def test_must_yield_only_the_actives_that_clash_with_the_head():
    """(a): una activa con un modelo que no choca con la cabeza no cede (el 4B no choca con nada)."""

    def clashes(a: str, b: str) -> bool:
        return M4B not in (a, b) and a != b

    x = Active(Wait(req("x", M26B), 0.0), frozenset({M26B}), granted_at=0.0)
    small = Active(Wait(req("small", M4B), 0.0), frozenset({M4B}), granted_at=0.0)
    state = State(actives=(x, small), queue=(Wait(req("y", QWEN), 0.0),))
    assert turn.must_yield(state, "x", 200.0, 120.0, clashes)  # guarda: la cabeza sí está bloqueada
    assert not turn.must_yield(state, "small", 200.0, 120.0, clashes)


def test_two_actives_blocking_the_head_both_yield_each_on_its_own_clock():
    x1 = Active(Wait(req("x1", M26B), 0.0), frozenset({M26B}), granted_at=0.0)
    x2 = Active(Wait(req("x2", M26B), 0.0), frozenset({M26B}), granted_at=100.0)
    state = State(actives=(x1, x2), queue=(Wait(req("y", QWEN), 10.0),))
    assert turn.must_yield(state, "x1", 130.0, 120.0, clashes_today)
    assert not turn.must_yield(state, "x2", 130.0, 120.0, clashes_today)
    assert turn.must_yield(state, "x2", 220.0, 120.0, clashes_today)


def test_does_not_yield_right_after_getting_the_turn():
    """Control de (c): la cabeza lleva mucho esperando, pero la activa acaba de recibir el turno.

    Sin (c), la que entra tras una cesión cedería en su primer trozo y nadie avanzaría.
    """
    state = _blocked_state(granted_at=500.0, head_since=0.0)
    assert not turn.must_yield(state, "x", 501.0, 120.0, clashes_today)
    assert turn.must_yield(state, "x", 620.0, 120.0, clashes_today)  # guarda


def test_evaluate_stamps_granted_at_and_reduce_keeps_it():
    decision = turn.evaluate(
        State(queue=(Wait(req("a", M26B, QWEN), 0.0),)), clashes_today, 42.0, None, 600.0
    )
    own = decision.state.active("a")
    assert own is not None and own.granted_at == 42.0
    reduced = turn.reduce(decision.state, "a", M26B).active("a")
    assert reduced is not None and reduced.granted_at == 42.0
    # `compare=False`: dos `Active` que solo difieren en el instante siguen siendo iguales.
    assert Active(own.wait, own.reserve) == own


# --- API sin bloqueo (REQ-011) ------------------------------------------------------------


def test_enqueue_and_poll_grant_like_request():
    """La misma secuencia con `request` (hilos) y con `enqueue`/`poll`: las mismas concesiones."""

    def with_threads() -> list[set[str]]:
        t = Turn(clashes_today, tick=0.02)
        t.request(req("a", M26B))
        results: dict[str, Grant] = {}
        threads = []
        for op_id, model in (("b", QWEN), ("c", M26B)):
            r = req(op_id, model)
            th = threading.Thread(
                target=lambda r=r: results.__setitem__(r.id, t.request(r)), daemon=True
            )
            th.start()
            threads.append(th)
            assert _until(lambda op_id=op_id: t.snapshot().queued(op_id)), op_id
        steps = [set(results)]
        t.release_slot("a")
        assert _until(lambda: "b" in results)
        steps.append(set(results))
        t.release_slot("b")
        assert _until(lambda: "c" in results)
        steps.append(set(results))
        for th in threads:
            th.join(CAP_S)
        return steps

    def without_threads() -> list[set[str]]:
        t = Turn(clashes_today, tick=60.0)
        granted: set[str] = set()
        for op_id, model in (("a", M26B), ("b", QWEN), ("c", M26B)):
            if isinstance(t.enqueue(req(op_id, model)), Grant):
                granted.add(op_id)
        assert granted == {"a"}
        steps = [set()]
        t.release_slot("a")
        for op_id in ("b", "c"):
            if isinstance(t.poll(op_id), Grant):
                granted.add(op_id)
        steps.append(granted - {"a"})
        t.release_slot("b")
        if isinstance(t.poll("c"), Grant):
            granted.add("c")
        steps.append(granted - {"a"})
        return steps

    assert with_threads() == without_threads() == [set(), {"b"}, {"b", "c"}]


def test_poll_delivers_the_grant_once_and_reports_position():
    t = Turn(clashes_today, tick=60.0)
    assert isinstance(t.enqueue(req("a", M26B)), Grant)
    assert t.enqueue(req("b", QWEN)) == (1, (M26B,))
    assert t.poll("b") == (1, (M26B,))
    t.release_slot("a")
    grant = t.poll("b")
    assert isinstance(grant, Grant) and grant.model == QWEN
    assert t.poll("b") is None  # entregada una sola vez
    assert t.poll("nadie") is None


def test_enqueue_twice_raises():
    t = Turn(clashes_today)
    t.enqueue(req("a", M26B))
    with pytest.raises(ValueError):
        t.enqueue(req("a", M26B))


def test_wait_without_thread_is_granted_in_the_same_release_slot():
    """Sin la reevaluación en `release_slot`, B sigue en la cola hasta que alguien haga tic."""
    t = Turn(clashes_today, tick=60.0)
    t.enqueue(req("a", M26B))
    t.enqueue(req("b", QWEN))
    assert t.snapshot().queued("b") is not None  # guarda: B espera de verdad
    t.release_slot("a")
    assert t.snapshot().active("b") is not None, "B no se concedió en el mismo release_slot"


def test_wait_without_thread_is_granted_in_the_same_abandon():
    t = Turn(clashes_today, tick=60.0)
    t.enqueue(req("a", M26B))
    t.enqueue(req("head", QWEN))
    t.enqueue(req("c", M26B))
    assert t.snapshot().queued("c") is not None  # guarda: E-1 la frena detrás de la cabeza
    assert t.abandon("head")
    assert t.snapshot().active("c") is not None
    assert t.poll("head") is None


def test_expire_cleans_queue_actives_pending_grant_and_flight():
    t = Turn(clashes_today, tick=60.0)
    t.enqueue(req("a", M26B))
    t.remote_flight("a", True)
    t.enqueue(req("b", QWEN))
    t.enqueue(req("c", QWEN))
    assert t._flight.remote == {"a"}  # guarda

    assert t.expire("a")  # activa y en vuelo: sale, y B y C se conceden en el acto
    state = t.snapshot()
    assert state.active("a") is None and not t._flight.remote
    assert state.active("b") is not None and state.active("c") is not None

    assert t.expire("b")  # concedida pero sin entregar: también sale la concesión pendiente
    assert "b" not in t._granted and t.snapshot().active("b") is None

    t.enqueue(req("d", M26B))  # choca con C: en cola
    assert t.expire("d") and t.snapshot().queued("d") is None
    assert not t.expire("d")  # idempotente
    assert t.poll("d") is None


def test_wait_change_wakes_on_each_change_and_respects_its_deadline():
    t = Turn(clashes_today, tick=60.0)
    t0 = time.monotonic()
    assert not t.wait_change(0.05)
    assert time.monotonic() - t0 >= 0.05

    woke: list[bool] = []
    th = threading.Thread(target=lambda: woke.append(t.wait_change(5.0)), daemon=True)
    th.start()
    time.sleep(0.05)
    t.enqueue(req("a", M26B))
    th.join(CAP_S)
    assert woke == [True]

    seen = t.version()
    t.enqueue(req("b", QWEN))
    assert t.wait_change(5.0, since=seen)  # el cambio llegó antes de esperar: vuelve ya
    seen = t.version()
    t.remote_flight("a", True)
    assert t.version() != seen
    seen = t.version()
    t.release_slot("a")
    assert t.version() != seen


def test_remote_flight_prevents_forcing_and_expire_allows_it_again():
    """Una operación remota con `in_backend` cuenta como llamada en vuelo (REQ-013)."""
    clock = Clock()
    t = Turn(clashes_today, tick=60.0, clock=clock, turn_max_s=600.0)
    t.enqueue(req("local", M26B))  # tiene el turno pero no llama al backend
    t.enqueue(req("remote", M26B))  # misma reserva: concedida también
    t.remote_flight("remote", True)
    t.enqueue(req("head", QWEN))

    clock.t = 700.0
    assert t.poll("head") == (1, (M26B,)), "forzada con una llamada remota en vuelo"

    t.expire("remote")  # el arrendamiento caduca: deja de contar y el reloj arranca a 700
    clock.t = 1299.0
    assert t.poll("head") == (1, (M26B,))
    clock.t = 1300.0
    grant = t.poll("head")
    assert isinstance(grant, Grant) and grant.forced


def test_turn_must_yield_uses_its_clock_and_yield_s():
    clock = Clock()
    t = Turn(clashes_today, tick=60.0, clock=clock, yield_s=120.0)
    t.enqueue(req("x", M26B))
    t.enqueue(req("y", QWEN))
    clock.t = 119.0
    assert not t.must_yield("x")
    clock.t = 120.0
    assert t.must_yield("x")
    off = Turn(clashes_today, tick=60.0, clock=clock)  # `yield_s` de partida: 0, apagada
    off.enqueue(req("x", M26B))
    off.enqueue(req("y", QWEN))
    clock.t = 10_000.0
    assert not off.must_yield("x")


# --- Simulación de inanición (REQ-031) ------------------------------------------------------


@dataclass
class _Op:
    request: PendingRequest
    arrival: float
    chunks: int
    busy_until: float = 0.0
    granted: list[float] = field(default_factory=list)


@dataclass
class _Result:
    y_arrival: float
    y_granted: float
    yields: int
    overtook: list[str]
    x_end_before_y: float


def _simulate(yield_s: float, *, chunk_s: float = 20.0, x_chunks: int = 30) -> _Result:
    """«La Mac» abre una operación de X cada 5 s (30 trozos de 20 s: 600 s cada una); «la PC» pide
    Y a los 50 s. Paso de 1 s; antes de cada trozo, `must_yield`. Siempre hay llamadas en vuelo
    (`no_progress_since=None`), así que la red de seguridad no fuerza nada: se mide solo la cesión.
    """
    x_model, y_model = M26B, QWEN
    ops: dict[str, _Op] = {}
    state = State()
    yields = 0
    y_arrival = 50.0
    y_granted: float | None = None
    order: list[tuple[str, float]] = []
    now = 0.0
    while now <= 5000.0:
        if now < 3000.0 and now % 5.0 == 0.0:
            op_id = f"x{int(now)}"
            ops[op_id] = _Op(req(op_id, x_model), now, x_chunks)
            state = State(state.actives, (*state.queue, Wait(ops[op_id].request, now)))
        if now == y_arrival:
            ops["y"] = _Op(req("y", y_model), now, 1)
            state = State(state.actives, (*state.queue, Wait(ops["y"].request, now)))
        decision = turn.evaluate(state, clashes_today, now, None, 600.0)
        state = decision.state
        for g in decision.grants:
            ops[g.id].granted.append(now)
            order.append((g.id, now))
            if g.id == "y" and y_granted is None:
                y_granted = now
        for a in list(state.actives):
            op = ops[a.id]
            if op.busy_until > now:
                continue  # su trozo sigue en vuelo
            if op.chunks == 0:
                state = turn.release_slot(state, a.id)
                continue
            if turn.must_yield(state, a.id, now, yield_s, clashes_today):
                yields += 1
                state = turn.release_slot(state, a.id)
                state = State(state.actives, (*state.queue, Wait(op.request, now)))
                continue
            op.chunks -= 1
            op.busy_until = now + chunk_s
        if y_granted is not None:
            break
        now += 1.0
    assert y_granted is not None, "Y no obtuvo el turno en toda la simulación"
    overtook = [
        op_id
        for op_id, at in order
        if op_id != "y" and ops[op_id].arrival > y_arrival and at < y_granted
    ]
    x_before = [o for o in ops.values() if o.request.id != "y" and o.arrival < y_arrival]
    x_end = max(o.granted[0] + x_chunks * chunk_s for o in x_before)
    return _Result(y_arrival, y_granted, yields, overtook, x_end)


def test_starvation_simulation_bounds_the_wait_with_yield():
    chunk_s = 20.0
    result = _simulate(120.0, chunk_s=chunk_s)
    waited = result.y_granted - result.y_arrival
    assert result.yields > 0, "la simulación no llegó a ceder: no mide nada"  # guarda
    # Cota de REQ-031 en el núcleo: TURN_YIELD_S + el trozo en curso (+1 s de paso de la simulación).
    # En vivo se suman `heartbeat_s` y la carga del modelo.
    assert waited <= 120.0 + chunk_s + 1.0, waited
    assert result.overtook == [], "operaciones de X llegadas después adelantaron a Y"


def test_starvation_simulation_without_yield_waits_for_the_active_x():
    result = _simulate(0.0)
    waited = result.y_granted - result.y_arrival
    assert result.yields == 0
    assert result.overtook == []
    # Sin cesión, Y espera a que acaben TODAS las X que ya tenían el turno: depende de la más larga.
    assert result.y_granted >= result.x_end_before_y
    assert waited > 120.0 + 20.0 + 1.0  # guarda: la simulación distingue los dos casos


# --- En el daemon: `_OperationTurn.ensure` cede (REQ-030, REQ-032) --------------------------

BASE = "http://127.0.0.1:9292/v1"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"
TODAY = Path(__file__).parent / "fixtures" / "topology" / "today.yaml"


@pytest.fixture
def with_topology(tmp_path, monkeypatch) -> Path:
    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    monkeypatch.setattr(config, "BASE_URL", BASE)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(2))
    return copy


def _events(tmp_path: Path) -> list[dict]:
    lines: list[str] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        lines += file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _of_tool(events: list[dict], tool: str) -> dict:
    return next((e for e in events if e.get("tool") == tool), {})


class _Thread(threading.Thread):
    def __init__(self, name: str, function: Callable, *args, **kwargs) -> None:
        super().__init__(name=name, daemon=True)
        self._call = (function, args, kwargs)
        self.result: object = None
        self.error: Exception | None = None

    def run(self) -> None:
        function, args, kwargs = self._call
        try:
            self.result = function(*args, **kwargs)
        except Exception as e:  # el test lo mira
            self.error = e


def _paragraphs(n: int, long: int = 450) -> str:
    return "\n\n".join(f"p{i} " + ("palabra " * (long // 8)).strip() for i in range(1, n + 1))


def _long_op_with_one_waiting(monkeypatch, tmp_path, yield_s: float) -> tuple[dict, dict, bool]:
    """X (26B) trocea en 8 trozos de 0,1 s; Y (Qwen, choca) llega tras el primero."""
    monkeypatch.setattr(config, "TURN_YIELD_S", yield_s)
    server._reset_turn()
    first_chunk = threading.Event()
    calls: list[tuple[str, float, float]] = []  # (hilo, inicio, fin) de cada envío al backend

    def post_chat(model, _payload):
        start = time.monotonic()
        if threading.current_thread().name == "X":
            first_chunk.set()
            time.sleep(0.1)
        calls.append((threading.current_thread().name, start, time.monotonic()))
        return server.ChatResult(text="ok", ok=True, finish_reason="stop")

    monkeypatch.setattr(server, "_post_chat", post_chat)
    x = _Thread(
        "X",
        server._chat_chunked,
        LONG,
        "s",
        _paragraphs(8),
        lambda piece: piece,
        tool="op_x",
        source="inline",
        role="long",
        chunk_chars=500,
    )
    y = _Thread("Y", server._chat, CODE, "s", "u", 8, tool="op_y", role="code")
    try:
        x.start()
        assert first_chunk.wait(CAP_S), "X no llegó al backend"
        y.start()
        x.join(10)
        y.join(10)
    finally:
        x.join(5)
        y.join(5)
    assert x.error is None and y.error is None, (x.error, y.error)
    x_ends = [end for name, _start, end in calls if name == "X"]
    y_starts = [start for name, start, _end in calls if name == "Y"]
    assert len(x_ends) >= 8 and len(y_starts) == 1, calls  # guarda: X troceó de verdad
    events = _events(tmp_path)
    # Por los envíos y no por el fin de los hilos: X suelta el turno antes de escribir su evento,
    # así que Y puede acabar antes que el hilo de X sin que nadie haya cedido.
    return _of_tool(events, "op_x"), _of_tool(events, "op_y"), y_starts[0] < max(x_ends)


def test_long_local_operation_yields_to_a_waiting_one(with_topology, monkeypatch, tmp_path):
    x_line, y_line, y_first = _long_op_with_one_waiting(monkeypatch, tmp_path, 0.3)
    assert y_line.get("turn_wait_ms", 0) > 0  # guarda: Y esperó turno de verdad
    assert x_line.get("turn_yields") == 1
    assert x_line.get("turn_wait_ms", 0) > 0  # la espera tras ceder suma en la de X
    assert y_first, "Y no llegó al backend antes del último trozo de X"


def test_without_yield_nobody_yields(with_topology, monkeypatch, tmp_path):
    x_line, y_line, y_first = _long_op_with_one_waiting(monkeypatch, tmp_path, 0.0)
    assert y_line.get("turn_wait_ms", 0) > 0  # guarda
    assert "turn_yields" not in x_line
    assert not y_first, "Y llegó al backend antes del último trozo de X sin cesión"


def test_operation_with_affinity_also_yields(with_topology, monkeypatch):
    """La salida temprana de la afinidad no se salta la cesión.

    El turno del daemon con reloj falso: X tiene el turno (con una afinidad puesta a mano), Y
    espera sin hilo. Mutante: comprobar la cesión después de la salida de afinidad → X no cede.
    """
    clock = Clock()
    server._reset_turn()
    fake = Turn(lambda _a, _b: False, tick=0.02, clock=clock, yield_s=120.0)
    monkeypatch.setattr(server, "_turn", fake)
    op = server._OperationTurn(4242, LONG)
    op.ensure(LONG)
    assert fake.in_use() == (LONG,)  # guarda: X tiene el turno y la topología rige
    op.affinity = "alternativo"  # los trozos siguientes saldrían por la salida de afinidad
    fake.enqueue(PendingRequest("y", frozenset({CODE}), CODE))
    clock.t = 120.0

    th = _Thread("X-ensure", op.ensure, LONG)
    th.start()
    try:
        granted_y = _until(lambda: isinstance(fake.poll("y"), Grant) or None)
        assert granted_y, "X no cedió: Y sigue en la cola"
        assert _until(lambda: fake.snapshot().queued(op.op_id))  # X, al final de la cola
        fake.expire("y")
        th.join(CAP_S)
        assert not th.is_alive() and th.error is None
    finally:
        fake.expire("y")
        th.join(CAP_S)
        op.release_slot()
    assert op.yields == 1
    assert op.affinity is None
    assert op.log_fields()["turn_yields"] == 1


# --- Ceder con afinidad real: se decide de nuevo y no deja `affinity_dropped` ----------------


@backend_mock.mock
@pytest.mark.usefixtures("affinity")
@pytest.mark.parametrize("still_loaded", [True, False])
def test_yield_with_real_affinity_decides_it_again_and_logs_no_drop(monkeypatch, still_loaded):
    """La afinidad la elige `ensure` + `pick` con la config y el llama-swap simulados (el 26B
    cargado, la tarea es del rol mecánico). Llega Qwen, que choca; la operación cede y, al volver,
    la afinidad se decide de nuevo: con el 26B aún cargado vuelve a él; si ya no lo está, va al
    rol. En ningún caso la cesión cuenta como fallo del alternativo (`affinity_dropped`).

    Mutante (código de la primera versión del lote): al volver pide solo el rol → `affinity` queda
    en `None` y `log_fields` escribe `affinity_dropped` como si el alternativo hubiera fallado.
    """
    from test_affinity import CODE as A_CODE
    from test_affinity import LONG as A_LONG
    from test_affinity import MECH as A_MECH
    from test_affinity import _Backend

    from local_delegate import matrix

    # Solo la celda del 26B: con la de Qwen, la operación entraría junto a Y en Qwen (E-1).
    monkeypatch.setattr(matrix, "CELLS", tuple(c for c in matrix.CELLS if c.alternative == A_LONG))
    _Backend().install(ready={A_LONG: 120}, ended_ago={A_LONG: 10})
    clock = Clock()
    server._reset_turn()
    fake = Turn(lambda _a, _b: False, tick=0.02, clock=clock, yield_s=120.0)
    monkeypatch.setattr(server, "_turn", fake)
    op = server._OperationTurn(4343, A_MECH, "local_translate", role_name="mechanical")

    op.ensure(A_MECH, size=10)
    model, skip = op.pick()
    assert (model, skip) == (A_LONG, False)  # guarda: la afinidad eligió el 26B de verdad
    op.note_attempt(server.Attempt(A_LONG, True, None, None, 5))
    assert op.affinity == A_LONG and op.affinity_tried == A_LONG

    fake.enqueue(PendingRequest("y", frozenset({A_CODE}), A_CODE))
    assert fake.snapshot().queued("y") is not None  # guarda: Qwen choca con el 26B en uso
    clock.t = 120.0
    assert fake.must_yield(op.op_id), (fake.snapshot(), op._turn is fake)

    if not still_loaded:
        backend_mock._routes.clear()  # la primera ruta que casa gana: fuera la del 26B cargado
        _Backend().install(ready={A_CODE: 120}, ended_ago={A_CODE: 1})
    th = _Thread("X-ensure", op.ensure, A_MECH, size=10)
    th.start()
    try:
        assert _until(lambda: isinstance(fake.poll("y"), Grant) or None), "X no cedió"
        assert _until(lambda: fake.snapshot().queued(op.op_id))
        fake.expire("y")
        th.join(CAP_S)
        assert not th.is_alive() and th.error is None, th.error
        model, skip = op.pick()
    finally:
        fake.expire("y")
        th.join(CAP_S)
        op.release_slot()
    assert op.yields == 1
    fields = op.log_fields()
    assert "affinity_dropped" not in fields, fields
    assert fields["turn_yields"] == 1
    if still_loaded:
        assert (model, skip) == (A_LONG, False), "tras ceder no volvió al alternativo cargado"
        assert op.affinity == A_LONG and fields.get("routing") == "affinity"
    else:
        assert (model, skip) == (A_MECH, False)  # guarda: esta vez la decisión es otra
        assert op.affinity is None and "routing" not in fields
