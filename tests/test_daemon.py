"""Tests del daemon singleton MCP HTTP + dashboard."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from filelock import FileLock

from local_delegate import cli, config, daemon, server


class _RespuestaFalsa:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _doblar_get(monkeypatch, payload, registro=None):
    """Dobla el GET de httpx2 para que `query_backend` reciba `payload`.

    `registro` recoge las cabeceras de cada llamada. Se pasa como lista y no se lee del doble
    porque lo que interesa comprobar es **lo que sale hacia el daemon**, no cómo se construyó.
    """

    class _ClienteFalso:
        def __init__(self, *_a, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get(self, _url, headers=None):
            if registro is not None:
                registro.append(headers or {})
            return _RespuestaFalsa(payload)

    monkeypatch.setattr(daemon.httpx2, "Client", _ClienteFalso)


def test_query_backend_devuelve_lo_que_ve_el_daemon(monkeypatch):
    _doblar_get(monkeypatch, {"available": True, "models": []})
    assert daemon.query_backend("127.0.0.1", 9393) == {"available": True, "models": []}


def test_query_backend_sin_el_campo_available_es_none(monkeypatch):
    """Sin el campo que responde la pregunta, «no se pudo preguntar» es más honesto que inventar.

    Si se devolviera el dict igualmente, `available` saldría ausente y quien llama lo leería como
    un backend caído — un diagnóstico falso a partir de una respuesta que no dice nada.
    """
    _doblar_get(monkeypatch, {"models": []})
    assert daemon.query_backend("127.0.0.1", 9393) is None


def test_query_backend_con_respuesta_que_no_es_un_objeto_es_none(monkeypatch):
    _doblar_get(monkeypatch, [1, 2, 3])
    assert daemon.query_backend("127.0.0.1", 9393) is None


# --- El token del puerto: el CLI tiene que poder hablar con su propio daemon ---


def test_el_cli_se_autentica_contra_su_propio_daemon(monkeypatch):
    """Con token puesto, quien pregunta por el daemon manda la cabecera.

    Es el fallo que no se ve hasta desplegar: poner el token protege el puerto y, de paso, deja
    al propio CLI fuera. `doctor` reportaría el daemon caído y el singleton levantaría un segundo
    daemon sobre un puerto ocupado, los dos por un 401 que nadie relaciona con el token.
    """
    monkeypatch.setattr(config, "WEB_TOKEN", "el-token-del-puerto")
    enviadas: list[dict] = []
    _doblar_get(monkeypatch, {"available": True, "models": []}, registro=enviadas)

    daemon.query_backend("127.0.0.1", 9393)

    assert enviadas == [{"Authorization": "Bearer el-token-del-puerto"}]


def test_el_estado_del_daemon_tambien_va_autenticado(monkeypatch):
    """`query_daemon` y `query_backend` son dos caminos al mismo puerto: los dos necesitan token.

    Doblados por separado a propósito. Con un solo test, una de las dos funciones podría quedarse
    sin cabecera y aprobar por la del otro camino — el error que ya costó un día en este repo.
    """
    monkeypatch.setattr(config, "WEB_TOKEN", "el-token-del-puerto")
    enviadas: list[dict] = []
    _doblar_get(
        monkeypatch,
        {"service": "local-delegate", "mode": "daemon", "pid": 1},
        registro=enviadas,
    )

    daemon.query_daemon("127.0.0.1", 9393)

    assert enviadas == [{"Authorization": "Bearer el-token-del-puerto"}]


def test_sin_token_no_se_manda_cabecera(monkeypatch):
    """Quien no configura token no empieza a mandar cabeceras vacías por ahí."""
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    enviadas: list[dict] = []
    _doblar_get(monkeypatch, {"available": True, "models": []}, registro=enviadas)

    daemon.query_backend("127.0.0.1", 9393)

    assert enviadas == [{}]


class _RespuestaHTTP:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


def _doblar_get_crudo(monkeypatch, respuesta, registro=None):
    class _ClienteFalso:
        def __init__(self, *_a, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get(self, _url, headers=None):
            if registro is not None:
                registro.append(headers)
            if isinstance(respuesta, Exception):
                raise respuesta
            return respuesta

    monkeypatch.setattr(daemon.httpx2, "Client", _ClienteFalso)


def test_la_pregunta_por_el_token_va_SIN_credencial(monkeypatch):
    """Lo mira por el camino del que NO lleva llave, aunque este entorno sí la tenga.

    Es la lección más cara de este repo, aplicada aquí: un diagnóstico solo vale para el camino
    por el que mira. Si esta pregunta se hiciera con la cabecera puesta, en la máquina que tiene
    el token respondería 200 y el check concluiría «no exige token» — tapando exactamente el caso
    que existe para detectar, y solo en las máquinas donde todo parece ir bien.

    El test se escribe con `WEB_TOKEN` **puesto** a propósito: con la variable vacía pasaría igual
    aunque el código estuviera mal, que es como este agujero sobrevivió a la primera tanda de
    mutantes.
    """
    monkeypatch.setattr(config, "WEB_TOKEN", "el-token-del-puerto")
    enviadas: list = []
    _doblar_get_crudo(monkeypatch, _RespuestaHTTP(200, {}), registro=enviadas)

    daemon.daemon_requires_token("127.0.0.1", 9393)

    assert enviadas, "no se llegó a preguntar"
    assert not enviadas[0], f"la pregunta llevaba credencial: {enviadas[0]}"


def test_un_401_nuestro_se_reconoce_por_el_realm(monkeypatch):
    _doblar_get_crudo(
        monkeypatch,
        _RespuestaHTTP(401, {"www-authenticate": 'Basic realm="local-delegate", charset="UTF-8"'}),
    )
    assert daemon.daemon_requires_token("127.0.0.1", 9393) is True


def test_un_401_ajeno_no_se_atribuye_a_nuestro_daemon(monkeypatch):
    """Otro servicio en ese puerto también puede pedir credencial, y no es nuestro.

    Sin mirar el `realm`, cualquier cosa que respondiera 401 haría que el diagnóstico dijera «es
    tu daemon, te falta el token» sobre un proceso ajeno — cambiar un diagnóstico falso por otro
    distinto no arregla nada.
    """
    _doblar_get_crudo(monkeypatch, _RespuestaHTTP(401, {"www-authenticate": 'Basic realm="nginx"'}))
    assert daemon.daemon_requires_token("127.0.0.1", 9393) is False


def test_un_401_sin_cabecera_de_reto_tampoco_se_atribuye(monkeypatch):
    _doblar_get_crudo(monkeypatch, _RespuestaHTTP(401, {}))
    assert daemon.daemon_requires_token("127.0.0.1", 9393) is False


def test_si_no_se_pudo_preguntar_no_hay_veredicto(monkeypatch):
    """`None` y `False` son distintos: «no lo sé» no es «no lo exige»."""
    _doblar_get_crudo(monkeypatch, daemon.httpx2.ConnectError("nadie escucha"))
    assert daemon.daemon_requires_token("127.0.0.1", 9393) is None


def test_un_puerto_que_responde_sin_pedir_nada_no_exige_token(monkeypatch):
    _doblar_get_crudo(monkeypatch, _RespuestaHTTP(200, {}))
    assert daemon.daemon_requires_token("127.0.0.1", 9393) is False


def test_con_token_el_puerto_entero_pide_credencial(monkeypatch):
    """Las tres superficies del puerto tras una sola puerta, montada sobre la app real.

    `test_web_auth.py` prueba el middleware sobre una app de juguete; esto prueba que está
    **enchufado** a la que se sirve de verdad, con el dashboard montado debajo. Son dos preguntas
    distintas y la segunda es la que se olvida.
    """
    monkeypatch.setattr(config, "WEB_TOKEN", "el-token-del-puerto")
    app = daemon.build_app("127.0.0.1", 19393)

    with TestClient(app) as client:
        for ruta in (daemon.DAEMON_STATUS_PATH, "/", "/api/status"):
            assert client.get(ruta).status_code == 401, f"{ruta} quedó sin proteger"

        cabecera = {"Authorization": "Bearer el-token-del-puerto"}
        assert client.get(daemon.DAEMON_STATUS_PATH, headers=cabecera).status_code == 200


def test_sin_token_el_puerto_sigue_abierto_como_siempre(monkeypatch):
    """El default no cambia para nadie: sin variable, el daemon se comporta como hasta hoy."""
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    app = daemon.build_app("127.0.0.1", 19393)

    with TestClient(app) as client:
        assert client.get(daemon.DAEMON_STATUS_PATH).status_code == 200


def test_combined_app_serves_daemon_status_dashboard_and_mcp_route():
    app = daemon.build_app("127.0.0.1", 19393)

    with TestClient(app) as client:
        status = client.get(daemon.DAEMON_STATUS_PATH)
        assert status.status_code == 200
        assert status.json()["service"] == "local-delegate"
        assert status.json()["mcp_url"] == "http://127.0.0.1:19393/mcp"

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "<!doctype html>" in dashboard.text.lower()

        # Sin un payload MCP válido debe fallar como protocolo, no como ruta ausente.
        mcp = client.post("/mcp")
        assert mcp.status_code != 404


def _handshake(client: TestClient, host: str):
    """Manda un `initialize` al MCP con un header Host concreto."""
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        headers={
            "Host": host,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )


def test_mcp_en_loopback_acepta_localhost_y_rechaza_hosts_ajenos():
    """Con host de loopback el SDK activa solo la protección contra DNS rebinding."""
    app = daemon.build_app("127.0.0.1", 19393)

    with TestClient(app) as client:
        for host in ("127.0.0.1:19393", "localhost:19393"):
            assert _handshake(client, host).status_code == 200, host

        # Un Host que no es loopback es justo el vector del ataque: 421, no 200.
        assert _handshake(client, "atacante.example:19393").status_code == 421


def test_mcp_publicado_en_la_lan_no_rechaza_por_host():
    """`LOCAL_DELEGATE_WEB_HOST=0.0.0.0` publica en la red local, y el proyecto lo permite.

    La protección del SDK solo se auto-activa con loopback; si se activara aquí, el daemon
    respondería 421 a todo cliente que llegara por la IP de la LAN.
    """
    app = daemon.build_app("0.0.0.0", 19393)

    with TestClient(app) as client:
        assert _handshake(client, "192.168.1.50:19393").status_code == 200


def test_handshake_declara_la_version_del_paquete():
    """`serverInfo.version` reportaba la del SDK, que no dice qué local-delegate corre."""
    app = daemon.build_app("127.0.0.1", 19393)

    with TestClient(app) as client:
        respuesta = _handshake(client, "127.0.0.1:19393")

    carga = next(
        json.loads(linea[6:]) for linea in respuesta.text.splitlines() if linea.startswith("data: ")
    )
    info = carga["result"]["serverInfo"]
    assert info["name"] == "local-delegate"
    assert info["version"] == server._get_version()


def test_serve_writes_state_holds_singleton_and_cleans_up(tmp_path, monkeypatch):
    observed = {}

    class FakeUvicornServer:
        def __init__(self, uvicorn_config):
            self.config = uvicorn_config
            self.started = False

        def run(self):
            observed["state"] = json.loads((tmp_path / "daemon.json").read_text(encoding="utf-8"))
            observed["lock_exists"] = (tmp_path / "daemon.lock").exists()
            self.started = True

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTOSTART", False)
    monkeypatch.setattr(daemon, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(daemon.uvicorn, "Server", FakeUvicornServer)

    assert daemon.serve("127.0.0.1", 19393) == 0
    assert observed["state"]["pid"] > 0
    assert observed["state"]["mcp_url"] == "http://127.0.0.1:19393/mcp"
    assert observed["lock_exists"] is True
    assert not (tmp_path / "daemon.json").exists()


def test_serve_is_idempotent_when_daemon_lock_is_held(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    current = {
        "service": "local-delegate",
        "mode": "daemon",
        "pid": 4321,
        "mcp_url": "http://127.0.0.1:19393/mcp",
    }
    monkeypatch.setattr(daemon, "query_daemon", lambda _host, _port: current)

    lock = FileLock(str(tmp_path / "daemon.lock"))
    with lock.acquire(timeout=0):
        assert daemon.serve("127.0.0.1", 19393) == 0

    output = capsys.readouterr().out
    assert "ya está activo" in output
    assert "pid=4321" in output


def test_serve_treats_ctrl_c_as_clean_shutdown(tmp_path, monkeypatch):
    class InterruptingServer:
        started = True

        def __init__(self, _uvicorn_config):
            pass

        def run(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTOSTART", False)
    monkeypatch.setattr(daemon, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(daemon.uvicorn, "Server", InterruptingServer)

    assert daemon.serve("127.0.0.1", 19393) == 0
    assert not (tmp_path / "daemon.json").exists()


def test_serve_without_stdout_supports_pythonw(tmp_path, monkeypatch):
    class FakeUvicornServer:
        started = True

        def __init__(self, _uvicorn_config):
            pass

        def run(self):
            pass

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTOSTART", False)
    monkeypatch.setattr(daemon, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(daemon.uvicorn, "Server", FakeUvicornServer)
    monkeypatch.setattr(daemon.sys, "stdout", None)

    assert daemon.serve("127.0.0.1", 19393) == 0
    assert not (tmp_path / "daemon.json").exists()


def test_cli_serve_dispatches_daemon(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daemon,
        "serve",
        lambda **kwargs: calls.append(kwargs) or 7,
    )

    result = cli.run(["serve", "--host", "127.0.0.1", "--port", "19393", "--log-level", "info"])

    assert result == 7
    assert calls == [{"host": "127.0.0.1", "port": 19393, "log_level": "info"}]
