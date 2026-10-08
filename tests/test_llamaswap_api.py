"""T13: llama-swap visto desde el daemon y el CLI (REQ-034, REQ-039): `llamaswap_api.py`.

Dos clases de test: con `backend_mock` (forma de los datos, qué se descarta, cómo se clasifica un
fallo) y contra el llama-swap v255 de prueba de T2 (`fake_llamaswap.py`), en su propio puerto
y con su control de PID. Nada aquí habla con el llama-swap real ni mata procesos por nombre.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import backend_mock
import httpx2
import pytest
from fake_llamaswap import FakeModel, binary_available, fake_llamaswap

from local_delegate import llamaswap_api
from local_delegate.llamaswap_api import Backend, Status

BASE = "http://test-backend"
RUNNING = f"{BASE}/running"
EVENTS = f"{BASE}/api/events"

needs_llamaswap = pytest.mark.skipif(
    not binary_available(), reason="falta llama-swap-v255 de prueba"
)


def sse(*messages: tuple[str, object]) -> bytes:
    """Un flujo `/api/events` como lo manda v255: `data:` con `type` y `data` (JSON en texto)."""
    return "".join(
        f"event: message\ndata: {json.dumps({'type': t, 'data': json.dumps(d)})}\n\n"
        for t, d in messages
    ).encode()


def running_row(model: str, key: str) -> dict:
    return {
        "model": model,
        "state": "ready",
        "ttl": 120,
        "cmd": f"llama-server -m MODELOS/{model}.gguf --api-key {key} --port 5800",
        "proxy": "http://localhost:5800",
        "name": "",
        "description": "",
    }


def inflight_request(model: str, key: str) -> dict:
    return {
        "id": "7",
        "model": model,
        "req_path": "/v1/chat/completions",
        "req_headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    }


# --- Con el mock ------------------------------------------------------------------------------


@backend_mock.mock
def test_running_keeps_only_id_state_and_ttl():
    backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": [running_row("m", "clave-falsa-1")]})
    )
    assert llamaswap_api.running(Backend(BASE)) == [{"id": "m", "state": "ready", "ttl": 120}]


@backend_mock.mock
def test_running_with_null_is_nothing_loaded():
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json={"running": None}))
    assert llamaswap_api.running(Backend(BASE)) == []


@backend_mock.mock
def test_in_flight_counts_by_model_and_drops_everything_else():
    backend_mock.get(EVENTS).mock(
        return_value=httpx2.Response(
            200,
            content=sse(
                ("logData", {"source": "proxy", "data": "[INFO] arranque\n"}),
                ("logData", {"source": "upstream", "data": ""}),
                (
                    "inflight",
                    {
                        "operation": "snapshot",
                        "requests": [
                            inflight_request("a", "clave-falsa-2"),
                            inflight_request("a", "clave-falsa-2"),
                            inflight_request("b", "clave-falsa-2"),
                        ],
                    },
                ),
            ),
        )
    )
    assert llamaswap_api.in_flight(Backend(BASE)) == {"a": 2, "b": 1}


@backend_mock.mock
def test_in_flight_without_snapshot_is_an_error_not_an_empty_photo():
    backend_mock.get(EVENTS).mock(
        return_value=httpx2.Response(200, content=sse(("logData", {"data": "x"})))
    )
    with pytest.raises(llamaswap_api.QueryError, match="inflight"):
        llamaswap_api.in_flight(Backend(BASE))


@backend_mock.mock
def test_activity_returns_the_last_row_without_request_data():
    row = {
        "id": 3,
        "model": "m",
        "timestamp": "2026-10-07T15:44:51-03:00",
        "duration_ms": 1200,
        "resp_status_code": 200,
        "req_path": "/v1/chat/completions",
        "metadata": {"x": "clave-falsa-3"},
    }
    backend_mock.get(f"{BASE}/api/metrics/activity?model=m&limit=1").mock(
        return_value=httpx2.Response(200, json={"data": [row]})
    )
    assert llamaswap_api.activity(Backend(BASE), "m") == {
        "model": "m",
        "timestamp": "2026-10-07T15:44:51-03:00",
        "duration_ms": 1200,
        "resp_status_code": 200,
    }


@backend_mock.mock
def test_query_status_tells_down_from_unknown():
    backend_mock.get(RUNNING).mock(side_effect=httpx2.ConnectError("rechazada"))
    assert llamaswap_api.query_status(Backend(BASE), 0).llamaswap == llamaswap_api.STATE_DOWN


@backend_mock.mock
def test_query_status_with_401_is_unknown():
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(401))
    status = llamaswap_api.query_status(Backend(BASE), 0)
    assert status.llamaswap == llamaswap_api.STATE_UNKNOWN
    assert "401" in status.detail


def test_refusals_name_each_reason():
    status = Status(
        llamaswap_api.STATE_OK,
        models=[{"id": "m", "state": "ready", "ttl": 60}],
        in_flight={"m": 2},
        own_delegations=1,
    )
    reasons = llamaswap_api.refusals(status)
    assert reasons == [
        "hay 1 delegación de local-delegate en curso",
        "hay 2 peticiones en vuelo en llama-swap (m: 2)",
        "hay modelos cargados en llama-swap: m",
    ]
    assert llamaswap_api.refusals(Status(llamaswap_api.STATE_OK)) == []
    # Con llama-swap caído no hay nada que cortar; con «no se sabe», sí es una negativa.
    assert llamaswap_api.refusals(Status(llamaswap_api.STATE_DOWN)) == []
    assert llamaswap_api.refusals(Status(llamaswap_api.STATE_UNKNOWN, "401"))


def test_status_round_trips_through_json():
    status = Status(
        llamaswap_api.STATE_OK,
        models=[{"id": "m", "state": "ready", "ttl": 60}],
        in_flight={"m": 1},
        own_delegations=2,
        config_path="config.yaml",
        watch_config=True,
        autostart=False,
    )
    assert Status.from_json(status.to_json()) == status
    with pytest.raises(llamaswap_api.QueryError):
        Status.from_json({"llamaswap": "other cosa"})


@backend_mock.mock
def test_registry_caps_open_watchers(monkeypatch):
    backend_mock.get(EVENTS).mock(side_effect=httpx2.ConnectError("rechazada"))
    registry = llamaswap_api.WatchRegistry(max_watchers=1)
    down_watcher = registry.open(Backend(BASE))
    # Una vigía resuelta («caído») no ocupa plaza.
    assert registry.result(down_watcher)["outcome"] == llamaswap_api.DOWN
    other = registry.open(Backend(BASE))
    assert registry.result(other)["outcome"] == llamaswap_api.DOWN
    assert registry.result("no-existe") is None


@backend_mock.mock
def test_registry_refuses_when_the_live_watchers_fill_the_cap():
    """Una vigía viva (`outcome` `None`) ocupa su plaza: con tope 1, la siguiente se niega."""
    route = backend_mock.get(EVENTS).mock(side_effect=httpx2.ConnectError("rechazada"))
    registry = llamaswap_api.WatchRegistry(max_watchers=1)
    alive = llamaswap_api.Watcher(Backend(BASE))
    assert alive.outcome is None
    registry._watchers["viva"] = (alive, time.monotonic())

    with pytest.raises(llamaswap_api.QueryError, match="vigías abiertas"):
        registry.open(Backend(BASE))
    assert route.call_count == 0  # se negó antes de abrir nada
    assert registry._reserved == 0


def _history(*lines: str) -> bytes:
    """Una carga inicial de `/api/events`: el historial del proxy y la foto `inflight`, y se cierra."""
    return sse(
        ("logData", {"source": "proxy", "data": "".join(f"{x}\n" for x in lines)}),
        ("inflight", {"operation": "snapshot", "requests": []}),
    )


@backend_mock.mock
def test_watcher_with_rotated_history_never_concludes_from_counts():
    """El historial rotó entre la carga inicial y la reconexión, y en el hueco hubo un rechazo.

    Las cuentas no cambian (salió un «reloading» y un rechazo viejos, entraron uno nuevo de cada):
    sin la marca de historial perdido, a los `not_watching_after` saldría «no vigila» y el CLI
    diría que el cambio se aplicará en el próximo arranque, con el fichero rechazado en disco.
    """
    first = _history(
        "[INFO] arranque",
        "[INFO] reloading configuration",
        "[WARN] failed to reload config: viejo",
        "[INFO] linea vieja que luego sale del historial",
    )
    rotated = _history(
        "[INFO] relleno nuevo " + "x" * 200,
        "[INFO] reloading configuration",
        "[WARN] failed to reload config: escondido",
    )
    # Abrir, y cada reconexión (la última respuesta se repite): el flujo se cierra tras la carga
    # inicial, como en una recarga.
    route = backend_mock.get(EVENTS)
    route.mock(
        side_effect=lambda _request: httpx2.Response(
            200, content=first if route.call_count == 0 else rotated
        )
    )
    watcher = llamaswap_api.Watcher(Backend(BASE), not_watching_after=0.3, total=1.0)
    watcher.open()

    outcome = watcher.wait()

    assert route.call_count >= 2, "no llegó a reconectar: el test no comprobaría la rama"
    assert outcome == llamaswap_api.UNRESOLVED
    assert "revisa el log de llama-swap" in watcher.line


# --- Contra el llama-swap de prueba -----------------------------------------------------------


@needs_llamaswap
@pytest.mark.llamaswap_real
def test_in_flight_reads_past_100_kb_of_log_in_under_a_second(tmp_path: Path):
    model = "gemma4-26b-a4b"
    with fake_llamaswap(tmp_path, [FakeModel(model, ttl=60)]) as ls:
        for _ in range(12):  # ~120 KB de log antes de la photo: el historial llega lleno
            assert ls.chat(model, log_kb=10).status_code == 200
        other_client = ls.launch_client(model, delay_s=4)
        time.sleep(1.0)
        start = time.monotonic()
        photo = llamaswap_api.in_flight(Backend(ls.url))
        elapsed = time.monotonic() - start
        # Guarda: la carga inicial de verdad traía el historial lleno (el tope ronda los 100 KB).
        log_chars = ls.inflight_snapshot().log_chars
        other_client.wait(timeout=30)
    assert log_chars >= 90_000
    assert photo[model] == 1
    assert elapsed < 1.0


@needs_llamaswap
@pytest.mark.llamaswap_real
def test_watcher_reloaded_and_then_down(tmp_path: Path):
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=2)]) as ls:
        watcher = llamaswap_api.Watcher(Backend(ls.url))
        watcher.open()
        ls.write_config(ls.config_text([FakeModel("m", ttl=3)]))
        assert llamaswap_api.OUTCOME_TEXT[watcher.wait()] == "recargó"
        assert "configuration reloaded" in watcher.line

        ls.stop()
        start = time.monotonic()
        down_watcher = llamaswap_api.Watcher(Backend(ls.url))
        down_watcher.open()
        outcome_text = llamaswap_api.OUTCOME_TEXT[down_watcher.wait()]
    assert outcome_text == "caído"
    assert time.monotonic() - start < 5
