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
def remoto(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")


@pytest.fixture
def status_sin_extras(monkeypatch):
    """`local_status` también mira GPU, RAM, grupos y el puerto web: aquí solo cuenta el backend."""
    for nombre in ("_vram_info", "_ram_info", "_llamaswap_groups"):
        monkeypatch.setattr(server, nombre, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)


def _linea_backend(texto: str) -> str:
    lineas = [linea for linea in texto.splitlines() if linea.startswith("Backend:")]
    assert len(lineas) == 1, texto
    return lineas[0]


def _estado_de(linea: str) -> str:
    """Lo que va detrás de la URL: `arriba`, `CAÍDO: …`, `SIN ACCESO: …`…"""
    return linea.split(" — ", 1)[1]


# --- local_status (REQ-015, REQ-013) -------------------------------------------------------------


@backend_mock.mock
def test_local_status_dice_sin_acceso_con_un_401(remoto, status_sin_extras):
    """Un 401 es un backend VIVO: decir «CAÍDO» manda a arrancar lo que ya corre."""
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(401, text="no"))
    # Registrada a propósito: una ruta sin registrar hace fallar el test, y lo que se mira aquí es
    # la línea `Backend:`, no si se pidió `/running`.
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json={"running": []}))

    texto = server.local_status()

    assert "SIN ACCESO" in texto
    assert _estado_de(_linea_backend(texto)).startswith("SIN ACCESO: test-backend responde 401")


@backend_mock.mock
def test_local_status_no_llama_caido_a_quien_contesta(remoto, status_sin_extras):
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(500, text="boom"))
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json={"running": []}))

    linea_backend = _linea_backend(server.local_status())

    assert "CAÍDO" not in linea_backend
    assert _estado_de(linea_backend).startswith("RESPONDE CON ERROR:")
    assert "HTTP 500" in linea_backend


def test_local_status_dice_que_no_se_resuelve(monkeypatch, status_sin_extras):
    """Red real: un nombre `.invalid` no resuelve nunca (RFC 6761)."""
    monkeypatch.setattr(config, "BASE_URL", "http://no-existe.invalid:9292/v1")

    texto = server.local_status()

    assert "no se resuelve el nombre no-existe.invalid:9292" in texto
    assert _estado_de(_linea_backend(texto)).startswith("CAÍDO: ")


@backend_mock.mock
def test_local_status_no_pide_running_si_models_falla(remoto, status_sin_extras):
    """REQ-013: con el backend inalcanzable, un plazo de conexión y no dos."""
    backend_mock.get(MODELS).mock(side_effect=httpx2.ConnectError("down"))
    ruta_running = backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": []})
    )

    server.local_status()

    assert ruta_running.call_count == 0


# --- sondear_backend (REQ-012, REQ-021) ----------------------------------------------------------


@backend_mock.mock
def test_sondeo_conserva_la_ultima_lista_buena(remoto):
    backend_mock.get(MODELS).mock(
        side_effect=[
            httpx2.Response(
                200, json={"data": [{"id": "b", "status": {"value": "loaded"}}, {"id": "a"}]}
            ),
            httpx2.ConnectError("down"),
        ]
    )

    primero_up, _ = server._models_with_status()
    up, modelos = server._models_with_status()

    assert primero_up is True
    assert up is False
    assert [m["id"] for m in modelos] == ["a", "b"]
    # La lista guardada no afirma un estado que ya no se puede saber.
    assert all(m["status"] is None for m in modelos)


@backend_mock.mock
def test_el_sondeo_fallido_marca_la_lista_como_vieja(remoto):
    backend_mock.get(MODELS).mock(
        side_effect=[httpx2.Response(200, json={"data": [{"id": "a"}]}), httpx2.ConnectError("x")]
    )

    bueno = server.sondear_backend()
    malo = server.sondear_backend()

    assert bueno.models_stale is False and bueno.causa is None and bueno.detalle is None
    assert malo.models_stale is True
    assert malo.causa == "transporte"
    assert malo.status_http is None


@backend_mock.mock
def test_la_lista_guardada_es_de_su_url(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://a/v1")
    backend_mock.get("http://a/v1/models").mock(
        return_value=httpx2.Response(200, json={"data": [{"id": "de-a"}]})
    )
    backend_mock.get("http://b/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    assert server.sondear_backend().available is True

    monkeypatch.setattr(config, "BASE_URL", "http://b/v1")
    estado = server.sondear_backend()
    modelos = estado.models

    assert estado.available is False
    assert modelos == []


@pytest.mark.parametrize(
    "cuerpo", [[], {}, {"data": "no es una lista"}], ids=["lista", "sin-data", "data-texto"]
)
@backend_mock.mock
def test_un_cuerpo_con_otra_forma_es_respuesta_invalida(remoto, cuerpo):
    """REQ-012: un 2xx sin un objeto con una lista `data` no es «disponible sin modelos»."""
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(200, json=cuerpo))

    estado = server.sondear_backend()

    assert estado.available is False
    assert estado.causa == "respuesta_invalida"
    assert "/models" in estado.detalle


@backend_mock.mock
def test_las_entradas_sueltas_se_toleran_como_hoy(remoto):
    backend_mock.get(MODELS).mock(
        return_value=httpx2.Response(
            200, json={"data": ["texto suelto", {"status": {"value": "loaded"}}]}
        )
    )

    estado = server.sondear_backend()

    assert estado.available is True
    assert estado.models == [{"id": "?", "status": "loaded"}]


@backend_mock.mock
def test_un_401_es_credencial_y_no_disponible(remoto):
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(401, text="no"))

    estado = server.sondear_backend()

    assert estado.available is False
    assert estado.causa == "credencial"
    assert estado.status_http == 401
    assert estado.detalle == "test-backend responde 401: está arriba pero rechaza la credencial"


@backend_mock.mock
def test_el_sondeo_nunca_lanza(remoto):
    """Regla 12: lo que se escape del clasificable también tiene causa, y no revienta a nadie."""
    backend_mock.get(MODELS).mock(side_effect=RuntimeError("inesperado"))

    try:
        estado = server.sondear_backend()
    except Exception as exc:  # que el fallo se lea como fallo del test, no como un error suelto
        pytest.fail(f"el sondeo lanzó {exc!r}")

    assert estado.available is False
    assert estado.causa == "desconocida"


@backend_mock.mock
def test_un_connect_timeout_en_loopback_es_rechazada(monkeypatch):
    """Regla 7 con el host SIN puerto: con `backend_host()` («127.0.0.1:9292») no se aplicaría."""
    monkeypatch.setattr(config, "BASE_URL", "http://127.0.0.1:9292/v1")
    backend_mock.get("http://127.0.0.1:9292/v1/models").mock(
        side_effect=httpx2.ConnectTimeout("timed out")
    )

    estado = server.sondear_backend()

    assert estado.causa == "rechazada"


def _ip_de_salida() -> str:
    """La IP de la interfaz por la que sale el tráfico. Un UDP «conectado» no envía nada."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]


def test_un_puerto_cerrado_remoto_no_parece_una_vpn(monkeypatch):
    """Red real, sin `skip`: un puerto cerrado en una IP que no es de loopback es `rechazada`.

    En Windows el rechazo tarda ~2,1 s (medido en el paso 0 de T3): con un plazo de conexión de 1 s
    llegaría como `ConnectTimeout` y, al no ser loopback, como `timeout_conexion`, que manda a
    mirar la VPN. En Linux y macOS el rechazo es inmediato.
    """
    ip = _ip_de_salida()
    assert not ip.startswith("127."), ip
    with socket.socket() as s:
        s.bind((ip, 0))
        puerto = s.getsockname()[1]
    monkeypatch.setattr(config, "BASE_URL", f"http://{ip}:{puerto}/v1")

    estado = server.sondear_backend()

    assert estado.causa == "rechazada"
