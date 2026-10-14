"""El sondeo del backend dice la causa, conserva la lista buena y `local_status` no miente.

REQ-012, REQ-013, REQ-015 y REQ-021 (parte de servidor) de
`.sdd/changes/panel-cuentas-y-estados-honestos/`. Las pruebas de red real van sin dobles: el plazo
de conexión y la clasificación solo se prueban de verdad contra un socket de verdad.
"""

from __future__ import annotations

import socket

import backend_mock
import httpx2
import pytest

from local_delegate import config, server

MODELS = "http://test-backend/v1/models"
RUNNING = "http://test-backend/running"


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")


@pytest.fixture
def status_without_extras(monkeypatch):
    """`local_status` también mira GPU, RAM, grupos y el puerto web: aquí solo cuenta el backend."""
    for name in ("_vram_info", "_ram_info", "_llamaswap_groups"):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)


def _backend_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.startswith("Backend:")]
    assert len(lines) == 1, text
    return lines[0]


def _state_of(line: str) -> str:
    """Lo que va detrás de la URL: `arriba`, `CAÍDO: …`, `SIN ACCESO: …`…"""
    return line.split(" — ", 1)[1]


# --- local_status (REQ-015, REQ-013) -------------------------------------------------------------


@backend_mock.mock
def test_local_status_says_no_access_with_a_401(remote, status_without_extras):
    """Un 401 es un backend VIVO: decir «CAÍDO» manda a arrancar lo que ya corre."""
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(401, text="no"))
    # Registrada a propósito: una ruta sin registrar hace fallar el test, y lo que se mira aquí es
    # la línea `Backend:`, no si se pidió `/running`.
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json={"running": []}))

    text = server.local_status()

    assert "SIN ACCESO" in text
    assert _state_of(_backend_line(text)).startswith("SIN ACCESO: test-backend responde 401")


@backend_mock.mock
def test_local_status_does_not_call_down_whoever_answers(remote, status_without_extras):
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(500, text="boom"))
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json={"running": []}))

    backend_line = _backend_line(server.local_status())

    assert "CAÍDO" not in backend_line
    assert _state_of(backend_line).startswith("RESPONDE CON ERROR:")
    assert "HTTP 500" in backend_line


def test_local_status_says_it_does_not_resolve(monkeypatch, status_without_extras):
    """Red real: un nombre `.invalid` no resuelve nunca (RFC 6761)."""
    monkeypatch.setattr(config, "BASE_URL", "http://no-existe.invalid:9292/v1")

    text = server.local_status()

    assert "no se resuelve el nombre no-existe.invalid:9292" in text
    assert _state_of(_backend_line(text)).startswith("CAÍDO: ")


@backend_mock.mock
def test_local_status_does_not_request_running_if_models_fails(remote, status_without_extras):
    """REQ-013: con el backend inalcanzable, un plazo de conexión y no dos."""
    backend_mock.get(MODELS).mock(side_effect=httpx2.ConnectError("down"))
    running_route = backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": []})
    )

    server.local_status()

    assert running_route.call_count == 0


# --- probe_backend (REQ-012, REQ-021) ------------------------------------------------------------


@backend_mock.mock
def test_poll_keeps_the_last_good_list(remote):
    backend_mock.get(MODELS).mock(
        side_effect=[
            httpx2.Response(
                200, json={"data": [{"id": "b", "status": {"value": "loaded"}}, {"id": "a"}]}
            ),
            httpx2.ConnectError("down"),
        ]
    )

    first_up, _ = server._models_with_status()
    up, models = server._models_with_status()

    assert first_up is True
    assert up is False
    assert [m["id"] for m in models] == ["a", "b"]
    # La lista guardada no afirma un estado que ya no se puede saber.
    assert all(m["status"] is None for m in models)


@backend_mock.mock
def test_the_failed_poll_marks_the_list_as_stale(remote):
    backend_mock.get(MODELS).mock(
        side_effect=[httpx2.Response(200, json={"data": [{"id": "a"}]}), httpx2.ConnectError("x")]
    )

    good = server.probe_backend()
    bad = server.probe_backend()

    assert good.models_stale is False and good.cause is None and good.detail is None
    assert bad.models_stale is True
    assert bad.cause == "transport"
    assert bad.status_http is None


@backend_mock.mock
def test_the_saved_list_belongs_to_its_url(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://a/v1")
    backend_mock.get("http://a/v1/models").mock(
        return_value=httpx2.Response(200, json={"data": [{"id": "de-a"}]})
    )
    backend_mock.get("http://b/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    assert server.probe_backend().available is True

    monkeypatch.setattr(config, "BASE_URL", "http://b/v1")
    state = server.probe_backend()
    models = state.models

    assert state.available is False
    assert models == []


@pytest.mark.parametrize(
    "body", [[], {}, {"data": "no es una lista"}], ids=["lista", "sin-data", "data-text"]
)
@backend_mock.mock
def test_a_body_with_another_shape_is_an_invalid_response(remote, body):
    """REQ-012: un 2xx sin un objeto con una lista `data` no es «disponible sin modelos»."""
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(200, json=body))

    state = server.probe_backend()

    assert state.available is False
    assert state.cause == "invalid_response"
    assert "/models" in state.detail


@backend_mock.mock
def test_loose_entries_are_tolerated_as_today(remote):
    backend_mock.get(MODELS).mock(
        return_value=httpx2.Response(
            200, json={"data": ["texto suelto", {"status": {"value": "loaded"}}]}
        )
    )

    state = server.probe_backend()

    assert state.available is True
    assert state.models == [{"id": "?", "status": "loaded"}]


@backend_mock.mock
def test_a_401_is_credential_and_not_unavailable(remote):
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(401, text="no"))

    state = server.probe_backend()

    assert state.available is False
    assert state.cause == "credential"
    assert state.status_http == 401
    assert state.detail == "test-backend responde 401: está arriba pero rechaza la credencial"


@backend_mock.mock
def test_the_poll_never_raises(remote):
    """Regla 12: lo que se escape del clasificable también tiene causa, y no revienta a nadie."""
    backend_mock.get(MODELS).mock(side_effect=RuntimeError("inesperado"))

    try:
        state = server.probe_backend()
    except Exception as exc:  # que el fallo se lea como fallo del test, no como un error suelto
        raise AssertionError(f"el sondeo lanzó {exc!r}") from exc

    assert state.available is False
    assert state.cause == "unknown"


@backend_mock.mock
def test_a_connect_timeout_on_loopback_is_refused(monkeypatch):
    """Regla 7 con el host SIN puerto: con `backend_host()` («127.0.0.1:9292») no se aplicaría."""
    monkeypatch.setattr(config, "BASE_URL", "http://127.0.0.1:9292/v1")
    backend_mock.get("http://127.0.0.1:9292/v1/models").mock(
        side_effect=httpx2.ConnectTimeout("timed out")
    )

    state = server.probe_backend()

    assert state.cause == "refused"


def _outbound_ip() -> str:
    """La IP de la interfaz por la que sale el tráfico. Un UDP «conectado» no envía nada."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]


def test_a_closed_remote_port_does_not_look_like_a_vpn(monkeypatch):
    """Red real, sin `skip`: un puerto cerrado en una IP que no es de loopback es `rechazada`.

    En Windows el rechazo tarda ~2,1 s (medido en el paso 0 de T3): con un plazo de conexión de 1 s
    llegaría como `ConnectTimeout` y, al no ser loopback, como `timeout_conexion`, que manda a
    mirar la VPN. En Linux y macOS el rechazo es inmediato.
    """
    ip = _outbound_ip()
    assert not ip.startswith("127."), ip
    with socket.socket() as s:
        s.bind((ip, 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(config, "BASE_URL", f"http://{ip}:{port}/v1")

    state = server.probe_backend()

    assert state.cause == "refused"
