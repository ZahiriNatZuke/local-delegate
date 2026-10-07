"""Tests del turno (T8): núcleo puro con reloj simulado y envoltura con hilos.

Los del núcleo no duermen. Los de la envoltura usan latencias de milisegundos y un tope propio
de 2 s por test. Los nombres de modelo son los de hoy; lo que se comprueba es la topología.
"""

from __future__ import annotations

import threading
import time

import pytest

from local_delegate import turn
from local_delegate.turn import Active, PendingRequest, State, Turn, Wait

M4B = "gemma3-4b"
M26B = "gemma4-26b-a4b"
QWEN = "qwen3.6-35b-a3b"

CAP_S = 2.0


def clashes_today(a: str, b: str) -> bool:
    """La topología de hoy: todo en un grupo `swap`, así que dos modelos distintos chocan."""
    return a != b


def clashes_resident(a: str, b: str) -> bool:
    """Escenario E-1: el 4B en un grupo `persistent, swap: false, exclusive: false`; los demás
    en uno `swap: true, exclusive: false`. El 4B no choca con nada; 26B y Qwen chocan entre sí."""
    if M4B in (a, b):
        return False
    return a != b


def clashes_4b_with_qwen(a: str, b: str) -> bool:
    """El 4B no choca con el 26B pero sí con Qwen; 26B y Qwen chocan."""
    return {a, b} in ({M4B, QWEN}, {M26B, QWEN})


def never_clashes(a: str, b: str) -> bool:
    return False


def pet(op_id: str, role: str, *alternatives: str, **kw) -> PendingRequest:
    return PendingRequest(op_id, frozenset({role, *alternatives}), role, **kw)


def active(op_id: str, *reserve: str, since: float = 0.0) -> Active:
    return Active(Wait(pet(op_id, reserve[0]), since), frozenset(reserve))


def wait(request: PendingRequest, since: float = 0.0) -> Wait:
    return Wait(request, since)


def evaluate(state: State, clashes=clashes_today, now: float = 0.0, no_progress_since=0.0):
    return turn.evaluate(state, clashes, now, no_progress_since, 600.0)


def arrive(state: State, request: PendingRequest, now: float = 0.0) -> State:
    return State(state.actives, (*state.queue, Wait(request, now)))


# --------------------------------------------------------------------------------------------
# Núcleo puro
# --------------------------------------------------------------------------------------------


def test_nobody_waits_forever():
    """Escenario «nadie se queda esperando para siempre»."""
    state = State(actives=(active("larga", M26B),), queue=(wait(pet("qwen", QWEN)),))
    order = ["larga"]

    def serve(state: State) -> State:
        decision = evaluate(state)
        order.extend(c.id for c in decision.grants)
        return decision.state

    for n in (1, 2, 3):
        state = serve(arrive(state, pet(f"26b-{n}", M26B)))
    state = serve(turn.release_slot(state, "larga"))
    state = serve(turn.release_slot(state, "qwen"))

    assert order == ["larga", "qwen", "26b-1", "26b-2", "26b-3"]
    assert state.queue == ()


def test_affinity_does_not_jump_queue_if_someone_waits():
    """Escenario «la afinidad no se cuela si alguien espera», con `A` sintético {4B, 26B}."""
    state = State(actives=(active("propia", M26B),), queue=(wait(pet("qwen", QWEN)),))
    state = arrive(state, pet("classify", M4B, M26B))

    granted = evaluate(state).grant_for("classify")

    assert granted is None


def test_affinity_joins_if_nobody_waits():
    """Escenario «la afinidad se une si nadie espera» (guarda del mutante anterior)."""
    state = arrive(State(actives=(active("propia", M26B),)), pet("classify", M4B, M26B))

    granted = evaluate(state).grant_for("classify")

    assert granted is not None
    assert granted.reserve == {"gemma4-26b-a4b"}


def test_compatible_resident_does_not_wait_e1():
    """Escenario «un residente compatible no espera (E-1)»."""
    state = State(actives=(active("propia", M26B),), queue=(wait(pet("qwen", QWEN)),))
    state = arrive(state, pet("classify", M4B))

    decision = evaluate(state, clashes=clashes_resident)
    granted = decision.grant_for("classify")

    assert granted is not None and granted.id == "classify"
    assert granted.reserve == {M4B}
    assert decision.state.queue[0].id == "qwen"


def test_e1_not_applied_if_it_clashes_with_queue():
    """El 4B es compatible con `actives` (26B) pero choca con lo que pide la cabeza (Qwen)."""
    state = State(actives=(active("propia", M26B),), queue=(wait(pet("qwen", QWEN)),))
    state = arrive(state, pet("classify", M4B))

    granted = evaluate(state, clashes=clashes_4b_with_qwen).grant_for("classify")

    assert granted is None


def test_without_progress_head_is_force_granted_at_600():
    state = State(actives=(active("larga", M26B),), queue=(wait(pet("qwen", QWEN), 0.0),))

    assert evaluate(state, now=599.0, no_progress_since=0.0).grant_for("qwen") is None
    decision = evaluate(state, now=600.0, no_progress_since=0.0).grant_for("qwen")

    assert decision is not None
    assert decision.forced
    assert decision.model == QWEN


def test_call_ending_at_599_prevents_forcing_at_600():
    """Mutante 2: medir la espera total en vez de la falta de progreso."""
    state = State(actives=(active("larga", M26B),), queue=(wait(pet("qwen", QWEN), 0.0),))

    decision = evaluate(state, now=600.0, no_progress_since=599.0).grant_for("qwen")

    assert not (decision is not None and decision.forced)
    assert decision is None


@pytest.mark.parametrize(
    ("acceptable", "chain_order"),
    [
        # Salto con `A = {destino}`: el destino, aunque el rol sea otro.
        ({M26B}, (QWEN, M26B)),
        # Paso `loaded`: el primero del conjunto en el orden de la cadena (no el primero por id).
        ({M4B, M26B}, (QWEN, M26B, M4B)),
    ],
)
def test_forced_hop_uses_chain_order(acceptable, chain_order):
    hop = PendingRequest("salto", frozenset(acceptable), QWEN, chain_order)
    state = State(actives=(active("otra", QWEN),), queue=(wait(hop, 0.0),))

    decision = evaluate(state, now=600.0, no_progress_since=0.0).grant_for("salto")

    assert decision is not None and decision.forced
    assert decision.model == "gemma4-26b-a4b"


def test_choice_after_forced_returns_to_head():
    """REQ-003, «Elección»: ningún modelo de `A'` cabe sin contar la propia operación."""
    op = pet("op", M4B, M26B)
    forced = Active(Wait(pet("forzada", QWEN), 0.0), frozenset({QWEN}), forced=True)
    state = State(
        actives=(Active(Wait(op, 0.0), frozenset({M4B, M26B})), forced),
        queue=(wait(pet("detras", M26B), 5.0),),
    )

    assert turn.compatible_when_choosing(state, "op", clashes_today) == frozenset()
    state = turn.back_to_head(state, "op")

    assert state.queue[0].id == op.id
    assert state.active("op") is None
    assert state.queue[0].since == 0.0  # no pierde su puesto


def test_choose_reduces_to_first_fitting_candidate():
    """`choose` respeta el orden de los candidatos y se salta los que chocan."""
    op = pet("op", M4B, M26B, QWEN)
    other = active("otro", M26B)
    state = State(actives=(Active(Wait(op, 0.0), frozenset({M4B, M26B, QWEN})), other))

    state, model = turn.choose(state, "op", [QWEN, M26B, M4B], clashes_4b_with_qwen)

    assert model == M26B  # Qwen choca con el 26B de `other`; el 26B es el siguiente
    own = state.active("op")
    assert own is not None and own.reserve == {M26B}
    assert state.queue == ()


def test_choose_returns_to_head_if_none_fits():
    """Tras una forzada de otra, `choose` no reduce: devuelve la operación a la cabeza."""
    op = pet("op", M4B, M26B)
    forced = Active(Wait(pet("forzada", QWEN), 0.0), frozenset({QWEN}), forced=True)
    state = State(
        actives=(Active(Wait(op, 0.0), frozenset({M4B, M26B})), forced),
        queue=(wait(pet("detras", M26B), 5.0),),
    )

    state, model = turn.choose(state, "op", [M4B, M26B], clashes_today)

    assert model is None
    assert [e.id for e in state.queue] == ["op", "detras"]
    assert state.active("op") is None


def test_choose_without_reserve_candidates_fails():
    state = State(actives=(active("op", M4B),))
    with pytest.raises(ValueError):
        turn.choose(state, "op", [QWEN], clashes_today)


def test_with_empty_active_reserve_is_all_a():
    granted = evaluate(arrive(State(), pet("w1", M4B, M26B, QWEN))).grant_for("w1")

    assert granted is not None
    assert granted.reserve == {M4B, M26B, QWEN}
    assert granted.model is None


# --------------------------------------------------------------------------------------------
# Envoltura con hilos
# --------------------------------------------------------------------------------------------


class Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Request:
    """Un `request` en su propio hilo, con la concesión y su instante (reloj real)."""

    def __init__(self, t: Turn, request: PendingRequest) -> None:
        self.grant: turn.Grant | None = None
        self.error: BaseException | None = None
        self.instant: float | None = None
        self.warnings: list[tuple[int, tuple[str, ...]]] = []
        self.ready = threading.Event()

        def run() -> None:
            try:
                self.grant = t.request(request, lambda *a: self.warnings.append(a))
                self.instant = time.monotonic()
            except BaseException as exc:
                self.error = exc
            finally:
                self.ready.set()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()


def wait_in_queue(t: Turn, op_id: str) -> None:
    limit = time.monotonic() + CAP_S
    while t.snapshot().queued(op_id) is None:
        assert time.monotonic() < limit, f"{op_id} no llegó a la cola"
        time.sleep(0.002)


def test_wrapper_no_progress_forced_by_periodic_check():
    """Mutante 1: `wait()` sin tope no despierta nunca si nadie llega ni sale."""
    clock = Clock()
    t = Turn(clashes_today, tick=0.02, clock=clock)
    t.request(pet("larga", M26B))
    w = Request(t, pet("qwen", QWEN))
    wait_in_queue(t, "qwen")

    clock.t = 600.0
    w.ready.wait(CAP_S)

    decision = w.grant
    assert decision is not None and decision.forced


def test_wrapper_long_call_in_flight_not_forced():
    """Escenario «llamada larga con plazo HTTP mayor que 600 s»: 700 s en vuelo."""
    clock = Clock()
    t = Turn(clashes_today, tick=0.02, clock=clock)
    t.request(pet("larga", M26B))
    call = t.in_flight()
    call.__enter__()
    w = Request(t, pet("qwen", QWEN))
    wait_in_queue(t, "qwen")

    clock.t = 650.0
    w.ready.wait(0.2)  # varios tics a 650 s simulados
    assert w.grant is None, "forzada con una llamada en vuelo"

    clock.t = 700.0
    call.__exit__(None, None, None)
    t.release_slot("larga")
    w.ready.wait(CAP_S)
    decision = w.grant
    assert decision is not None
    assert not decision.forced


def test_when_a_reserve_shrinks_queue_is_rechecked():
    """Escenario «cuando una reserva se reduce, la cola se vuelve a mirar»."""
    t = Turn(clashes_today, tick=5.0)
    w1 = t.request(pet("w1", M4B, M26B, QWEN))
    assert w1.reserve == {M4B, M26B, QWEN}
    w2 = Request(t, pet("w2", M26B))
    wait_in_queue(t, "w2")

    t.reduce("w1", M26B)
    for _ in range(3):  # W1 sigue con sus 3 trozos de 50 ms
        with t.in_flight():
            time.sleep(0.05)
    w1_done = time.monotonic()
    t.release_slot("w1")
    w2.ready.wait(CAP_S)

    assert w2.instant is not None
    w2_started = w2.instant
    assert w2_started < w1_done


def test_abandoned_wait_lets_next_compatible_pass():
    t = Turn(clashes_today, tick=5.0)
    t.request(pet("larga", M26B))
    head = Request(t, pet("qwen", QWEN))
    wait_in_queue(t, "qwen")
    next_item = Request(t, pet("26b", M26B))
    wait_in_queue(t, "26b")

    assert t.abandon("qwen")
    granted_in_time = next_item.ready.wait(0.2) and next_item.grant is not None

    assert granted_in_time
    head.ready.wait(CAP_S)
    assert isinstance(head.error, turn.AbandonedWait)
    assert t.snapshot().queued("qwen") is None


def test_topology_change_grants_a_wait_that_now_fits():
    t = Turn(clashes_today, tick=5.0)
    t.request(pet("larga", M26B))
    w = Request(t, pet("qwen", QWEN))
    wait_in_queue(t, "qwen")

    t.topology_change(never_clashes)
    granted_in_time = w.ready.wait(0.2) and w.grant is not None

    assert granted_in_time


def test_tick_hook_shows_new_topology_to_waiters():
    """T10 (revisión): nadie llega ni sale y nadie llama a `topology_change` desde fuera.

    El gancho `on_tick` (fuera del cerrojo) es el único que trae la topología nueva, y la
    reevaluación de ese mismo tic la usa. Mutante: `_wait` no llama al gancho → la espera sigue
    con el `clashes` viejo y falla `assert granted_in_time`.
    """
    calls: list[bool] = []
    t: Turn

    def on_tick() -> None:
        calls.append(t._cond._is_owned())  # type: ignore[attr-defined]
        t.topology_change(never_clashes)

    t = Turn(clashes_today, tick=0.02, on_tick=on_tick)
    t.request(pet("larga", M26B))
    w = Request(t, pet("qwen", QWEN))
    wait_in_queue(t, "qwen")

    granted_in_time = w.ready.wait(CAP_S) and w.grant is not None

    assert granted_in_time
    assert calls and not any(calls)  # siempre fuera del cerrojo


def test_acquisition_order_request_with_slot_raises():
    t = Turn(clashes_today)
    with turn.slot_taken(), pytest.raises(AssertionError):
        t.request(pet("op", M26B))
    assert not turn.has_slot()
    assert t.request(pet("op", M26B)).model == M26B  # sin la marca, se concede


def test_wait_warnings_and_back_to_head_with_threads():
    """`on_wait` recibe posición y modelos en uso; `back` re-espera en la cabeza."""
    t = Turn(clashes_today, tick=0.02)
    op = t.request(pet("op", M4B, M26B))
    assert op.model is None
    # Una forzada de otra deja la reserva de `op` sin modelo que quepa.
    forced = Active(Wait(pet("f", QWEN), 0.0), frozenset({QWEN}), forced=True)
    with t._cond:  # montaje directo del estado tras una forzada
        t._state = State(actives=(*t._state.actives, forced))
    assert t.compatible_models("op") == frozenset()
    another = Request(t, pet("otra", M26B))
    wait_in_queue(t, "otra")

    result: list[turn.Grant] = []
    thread = threading.Thread(target=lambda: result.append(t.back("op")), daemon=True)
    thread.start()
    limit = time.monotonic() + CAP_S
    while t.snapshot().queue[:1] == () or t.snapshot().queue[0].id != "op":
        assert time.monotonic() < limit
        time.sleep(0.002)
    assert [e.id for e in t.snapshot().queue] == ["op", "otra"]
    while len(another.warnings) < 2:
        assert time.monotonic() < limit, another.warnings
        time.sleep(0.002)
    assert another.warnings[:2] == [(1, (M4B, M26B, QWEN)), (2, (QWEN,))]

    t.release_slot("f")
    thread.join(CAP_S)
    assert result and result[0].reserve == {M4B, M26B}
    assert another.grant is None  # el 26B choca con la reserva {4B, 26B} de `op`


def test_abandon_by_exception_in_hook_cleans_queue():
    t = Turn(clashes_today, tick=5.0)
    t.request(pet("larga", M26B))

    def hook(position, in_use):
        raise RuntimeError("fallo del gancho")

    with pytest.raises(RuntimeError):
        t.request(pet("qwen", QWEN), hook)
    assert t.snapshot().queue == ()


def test_wrapper_choose_after_forced_waits_and_chooses():
    """`Turn.choose`: sin modelo que quepa vuelve a la cabeza, espera y elige al concederse."""
    t = Turn(clashes_today, tick=0.02)
    t.request(pet("op", M4B, M26B))
    forced = Active(Wait(pet("f", QWEN), 0.0), frozenset({QWEN}), forced=True)
    with t._cond:  # montaje directo del estado tras una forzada
        t._state = State(actives=(*t._state.actives, forced))

    result: list[str] = []
    thread = threading.Thread(target=lambda: result.append(t.choose("op", [M26B, M4B])))
    thread.daemon = True
    thread.start()
    wait_in_queue(t, "op")
    assert result == []

    t.release_slot("f")
    thread.join(CAP_S)
    assert result == [M26B]
    own = t.snapshot().active("op")
    assert own is not None and own.reserve == {M26B}
