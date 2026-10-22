"""Puntos de parada de una llamada cancelada (SDD claude-plugin-and-mods, abandoned-calls).

Los escenarios de punta a punta están en `test_desktop_bridge.py`; aquí, las dos piezas que esos
escenarios no ejercitan por separado: salir de la cola del turno y abandonar un envío en curso.
"""

from __future__ import annotations

import threading
import time

import anyio
import pytest

from local_delegate import cancellation, turn


def _always_clash(_a: str, _b: str) -> bool:
    return True


def test_cancelled_wait_leaves_turn_queue_without_waiting_the_tick():
    # Tic de 30 s: si la espera solo mirara la parada en cada tic, el test lo vería.
    state = turn.Turn(_always_clash, tick=30.0)
    state.request(turn.PendingRequest("holder", frozenset({"big"}), "big"))
    token = cancellation.Token("local_classify")
    outcome: dict[str, object] = {}

    def waiter() -> None:
        try:
            state.request(
                turn.PendingRequest("waiter", frozenset({"small"}), "small"),
                should_stop=token.is_cancelled,
            )
            outcome["result"] = "granted"
        except turn.AbandonedWait:
            outcome["result"] = "abandoned"
        outcome["at"] = time.monotonic()

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while not state.snapshot().queue:
        assert time.monotonic() < deadline, "la espera no llegó a la cola"
        time.sleep(0.01)

    token.on_cancel(state.wake)
    cancelled_at = time.monotonic()
    token.cancel(cancellation.REASON_NOTIFICATION)
    thread.join(2)

    assert not thread.is_alive(), "la espera cancelada sigue en la cola"
    assert outcome["result"] == "abandoned"
    assert float(outcome["at"]) - cancelled_at < 1.0
    assert state.snapshot().queue == ()


def test_run_abandonable_returns_as_soon_as_cancelled():
    token = cancellation.Token("local_summarize")
    finished = threading.Event()

    def slow_post() -> str:
        time.sleep(1.5)
        finished.set()
        return "late"

    def run() -> None:
        cancellation._CURRENT.set(token)
        cancellation.run_abandonable(slow_post)

    errors: list[BaseException] = []

    def target() -> None:
        try:
            run()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    time.sleep(0.1)
    started = time.monotonic()
    token.cancel(cancellation.REASON_DISCONNECT)
    thread.join(1.0)

    assert not thread.is_alive(), "quien espera el envío no se enteró de la cancelación"
    assert time.monotonic() - started < 1.0
    assert len(errors) == 1 and isinstance(errors[0], cancellation.CallCancelled)
    assert errors[0].reason == cancellation.REASON_DISCONNECT
    assert token.observed
    assert not finished.is_set()  # guarda: se volvió antes de que el envío acabara
    assert finished.wait(3)  # y el envío abandonado terminó solo


def test_abandonable_send_can_still_reach_the_event_loop():
    """`questions.ask` corre dentro del envío y salta al bucle con `anyio.from_thread.run`."""

    async def answer() -> str:
        return "yes"

    def tool_thread() -> str:
        cancellation._CURRENT.set(cancellation.Token("local_summarize"))
        return cancellation.run_abandonable(lambda: anyio.from_thread.run(answer))

    async def main() -> str:
        return await anyio.to_thread.run_sync(tool_thread)

    assert anyio.run(main) == "yes"


def test_without_token_everything_runs_inline():
    assert cancellation.current() is None
    cancellation.checkpoint()  # no lanza
    caller = threading.get_ident()
    assert cancellation.run_abandonable(threading.get_ident) == caller


def test_run_abandonable_propagates_backend_errors():
    token = cancellation.Token("local_classify")

    def broken() -> str:
        raise ValueError("boom")

    def run() -> None:
        cancellation._CURRENT.set(token)
        cancellation.run_abandonable(broken)

    errors: list[BaseException] = []
    thread = threading.Thread(target=lambda: _capture(run, errors), daemon=True)
    thread.start()
    thread.join(2)
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert not token.observed


def _capture(function, errors: list[BaseException]) -> None:
    try:
        function()
    except Exception as exc:
        errors.append(exc)


@pytest.mark.parametrize("reason", ["first", "second"])
def test_first_reason_wins(reason):
    token = cancellation.Token()
    token.cancel(reason)
    token.cancel("other")
    assert token.reason == reason
    with pytest.raises(cancellation.CallCancelled):
        token.check()
