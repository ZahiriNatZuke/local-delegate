"""Una delegación que no puede conectar: cuánto tarda en rendirse, qué dice y qué no ofrece.

REQ-017, REQ-018, REQ-019 y REQ-022 (`espera_local`) de
`.sdd/changes/panel-cuentas-y-estados-honestos/`. El escenario de origen es la Mac con la VPN
caída: cada fallo bloqueaba la tool ~75–95 s, preguntaba «¿Lo arranco?» por un backend que vive en
otra máquina y el log no decía por qué había fallado.
"""

from __future__ import annotations

import errno
import json
import os
import struct
import threading
import time
import zlib

import backend_mock
import httpx2
import pytest

from local_delegate import autostart, config, preguntas, server

CHAT = "http://test-backend/v1/chat/completions"


def _plazo_conexion(t) -> float:
    """El plazo de conexión, venga como `httpx2.Timeout` o como un número."""
    return t.connect if isinstance(t, httpx2.Timeout) else t


@pytest.fixture
def cliente_nuevo():
    """`_get_client` cachea el cliente: el test necesita uno creado con la config del test."""
    server._client = None
    yield
    if server._client is not None:
        server._client.close()
    server._client = None


@pytest.fixture
def registradores(monkeypatch):
    """Sustituye la pregunta y el autoarranque por registradores que no hacen nada."""
    preguntas_hechas: list[str] = []
    arranques: list[int] = []

    def _preguntar(mensaje, _esquema):
        preguntas_hechas.append(mensaje)

    def _ensure_backend(wait=0):
        arranques.append(wait)
        return False

    monkeypatch.setattr(preguntas, "preguntar", _preguntar)
    monkeypatch.setattr(autostart, "ensure_backend", _ensure_backend)
    return preguntas_hechas, arranques


def _ultima_linea_del_log() -> dict:
    lineas = server._current_log_path().read_text(encoding="utf-8").splitlines()
    return json.loads(lineas[-1])


# --- REQ-019: el plazo de conexión de las delegaciones -------------------------------------------


def test_el_plazo_de_conexion_de_las_delegaciones_es_de_10_s(cliente_nuevo):
    plazo = server._get_client().timeout

    assert _plazo_conexion(plazo) == 10.0
    # Solo cambia la conexión: la espera de carga de un modelo es de lectura y sigue igual.
    assert plazo.read == config.HTTP_TIMEOUT
    assert plazo.write == config.HTTP_TIMEOUT
    assert plazo.pool == config.HTTP_TIMEOUT


def test_el_plazo_de_conexion_no_supera_el_total(cliente_nuevo, monkeypatch):
    monkeypatch.setattr(config, "HTTP_TIMEOUT", 5.0)

    assert _plazo_conexion(server._get_client().timeout) == 5.0


def test_una_delegacion_sin_ruta_se_rinde_en_10_s(monkeypatch, registradores, cliente_nuevo):
    """Red real: `192.0.2.1` (TEST-NET-1) no contesta nunca.

    En esta PC, con el plazo del kernel de Windows, tardaba ~21 s. En un CI sin ruta hacia esa red
    el fallo es inmediato (`sin_ruta`) y pasa antes: el control de este test es el de Windows.
    """
    monkeypatch.setattr(config, "BASE_URL", "http://192.0.2.1:9292/v1")
    preguntas_hechas, arranques = registradores

    t0 = time.monotonic()
    texto = server.local_summarize(text="hola")
    transcurrido = time.monotonic() - t0

    assert transcurrido < 13, f"tardó {transcurrido:.1f} s en rendirse"
    linea = _ultima_linea_del_log()
    assert linea.get("fallo_conexion") in {"timeout_conexion", "sin_ruta"}
    assert linea["error"] == "connect_error"
    assert texto.startswith("[local-delegate error] no se pudo conectar con el backend: ")
    assert preguntas_hechas == [] and arranques == []


# --- REQ-018: no se ofrece arrancar un backend remoto --------------------------------------------


@pytest.mark.parametrize(
    "autoarranque", [False, True], ids=["sin-autoarranque", "con-autoarranque"]
)
@backend_mock.mock
def test_delegacion_remota_no_pregunta_ni_arranca(monkeypatch, registradores, autoarranque):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "AUTOSTART", autoarranque)
    backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectTimeout("timed out"))
    preguntas_hechas, arranques = registradores

    texto = server.local_summarize(text="hola")

    if autoarranque:
        assert arranques == []
    else:
        assert preguntas_hechas == []
    assert preguntas_hechas == [] and arranques == []
    assert "[local-delegate error]" in texto


@backend_mock.mock
def test_delegacion_local_sigue_preguntando(monkeypatch, registradores):
    """Guarda de regresión: con origen local, la pregunta de siempre."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", "local")
    monkeypatch.setattr(config, "AUTOSTART", False)
    rechazo = httpx2.ConnectError("refused")
    rechazo.__cause__ = OSError(errno.ECONNREFUSED, "refused")
    backend_mock.post(CHAT).mock(side_effect=rechazo)
    preguntas_hechas, _arranques = registradores

    server.local_summarize(text="hola")

    assert len(preguntas_hechas) == 1


# --- REQ-017: el error dice la causa y el log la guarda, en los cuatro caminos -------------------


def _png_minimo(destino) -> str:
    """Un PNG de 1×1 válido, escrito a mano para no depender de Pillow."""

    def bloque(tipo: bytes, datos: bytes) -> bytes:
        return (
            struct.pack(">I", len(datos))
            + tipo
            + datos
            + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + bloque(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + bloque(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + bloque(b"IEND", b"")
    )
    destino.write_bytes(png)
    return str(destino)


def _simple(_tmp_path, _monkeypatch):
    return server.local_summarize(text="hola")


def _troceada_map_reduce(_tmp_path, monkeypatch):
    # Un tope pequeño fuerza el map-reduce sin tener que fabricar un texto enorme.
    monkeypatch.setattr(config, "max_chars_for_role", lambda rol: 2000)
    texto = "\n\n".join(f"Párrafo {i}: " + "palabra " * 60 for i in range(12))
    usado: list[bool] = []
    original = server._chat_map_reduce

    def _espia(*args, **kwargs):
        usado.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(server, "_chat_map_reduce", _espia)
    resultado = server.local_summarize(text=texto)
    # Guarda: sin ella, un cambio de umbral mandaría este caso por el camino simple en silencio.
    assert usado, "el caso «troceada» no pasó por el map-reduce"
    return resultado


def _troceada_por_trozos(_tmp_path, _monkeypatch):
    return server.local_translate(target_lang="inglés", text="hola")


def _imagen(tmp_path, _monkeypatch):
    return server.local_describe_image(path=_png_minimo(tmp_path / "punto.png"))


@pytest.mark.parametrize(
    "camino",
    [_simple, _troceada_map_reduce, _troceada_por_trozos, _imagen],
    ids=["simple", "troceada-map-reduce", "troceada-por-trozos", "imagen"],
)
@backend_mock.mock
def test_el_error_de_conexion_dice_la_causa_y_va_al_log(
    tmp_path, monkeypatch, registradores, camino
):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectTimeout("timed out"))

    texto = camino(tmp_path, monkeypatch)

    linea = _ultima_linea_del_log()
    assert linea.get("fallo_conexion") == "timeout_conexion"
    assert linea["error"] == "connect_error"
    # Compatibilidad del log y del enfriamiento: la clase no cambia.
    assert linea.get("error_class") == "endpoint"
    assert "no contesta a la conexión" in texto
    assert "test-backend no contesta a la conexión (ruta, cortafuegos o VPN)" in texto


@backend_mock.mock
def test_un_fallo_que_no_es_de_conexion_no_escribe_la_clave(monkeypatch):
    """`fallo_conexion` solo aparece cuando hay causa: el log no engorda en cada evento."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post(CHAT).mock(return_value=httpx2.Response(500, text="boom"))

    server.local_summarize(text="hola")

    assert "fallo_conexion" not in _ultima_linea_del_log()


# --- REQ-022: la espera de plaza se ve en «En curso» ---------------------------------------------


def _entrada_inflight(tmp_path) -> dict | None:
    fichero = tmp_path / "inflight.json"
    if not fichero.is_file():
        return None
    try:
        datos = json.loads(fichero.read_text(encoding="utf-8"))
    except ValueError:
        return None  # se está reescribiendo
    entradas = [v for v in datos.values() if isinstance(v, dict)]
    return entradas[0] if entradas else None


def _esperar(condicion, plazo_s: float = 3.0):
    limite = time.monotonic() + plazo_s
    while time.monotonic() < limite:
        valor = condicion()
        if valor:
            return valor
        time.sleep(0.02)
    return condicion()


@backend_mock.mock
def test_inflight_marca_la_espera_local(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    llego_al_backend = threading.Event()
    seguir = threading.Event()

    def _backend(_request):
        llego_al_backend.set()
        seguir.wait(5)
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    backend_mock.post(CHAT).mock(side_effect=_backend)

    # Se toman TODAS las plazas del semáforo, sin suponer cuántas son.
    tomadas = 0
    while server._chat_slots.acquire(blocking=False):
        tomadas += 1
    hilo = threading.Thread(target=server.local_summarize, kwargs={"text": "hola"}, daemon=True)
    try:
        hilo.start()
        assert _esperar(lambda: _entrada_inflight(tmp_path)), "la delegación no apareció en curso"
        entrada = _esperar(
            lambda: (e := _entrada_inflight(tmp_path)) and e.get("espera_local") and e
        ) or _entrada_inflight(tmp_path)
        assert entrada.get("espera_local") == "plaza"
    finally:
        for _ in range(tomadas):
            server._chat_slots.release()

    try:
        assert llego_al_backend.wait(5), "la delegación no llegó al backend al liberar la plaza"
        entrada = _entrada_inflight(tmp_path)
        assert entrada is not None
        assert entrada.get("espera_local") is None
    finally:
        seguir.set()
        hilo.join(10)
    assert not hilo.is_alive()


def test_sin_espera_no_se_escribe_nada_de_mas(tmp_path, monkeypatch):
    """En el caso normal (hay plaza) la entrada en vuelo es la de siempre."""
    vistas: list[dict] = []
    original = server._con_respaldo

    def _espia(*args, **kwargs):
        vistas.append(dict(_entrada_inflight(tmp_path) or {}))
        return original(*args, **kwargs)

    monkeypatch.setattr(server, "_con_respaldo", _espia)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    with backend_mock.mock:
        backend_mock.post(CHAT).mock(
            return_value=httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        )
        server.local_summarize(text="hola")

    assert vistas and "espera_local" not in vistas[0]


def test_el_snapshot_de_en_curso_lleva_la_espera_local(tmp_path):
    """`/api/inflight` sirve `inflight_snapshot()`: si la copia campo a campo no la lleva, el panel
    nunca ve la espera aunque esté escrita en `inflight.json`."""
    (tmp_path / "inflight.json").write_text(
        json.dumps(
            {
                f"{os.getpid()}:1": {
                    "tool": "local_summarize",
                    "model": "m",
                    "source": "inline",
                    "chars_in": 4,
                    "started_at": time.time(),
                    "pid": os.getpid(),
                    "backend": "local",
                    "espera_local": "plaza",
                },
                f"{os.getpid()}:2": {
                    "tool": "local_summarize",
                    "model": "m",
                    "source": "inline",
                    "chars_in": 4,
                    "started_at": time.time(),
                    "pid": os.getpid(),
                    "backend": "local",
                },
            }
        ),
        encoding="utf-8",
    )

    por_id = {e["id"]: e for e in server.inflight_snapshot()}

    assert por_id[f"{os.getpid()}:1"].get("espera_local") == "plaza"
    assert "espera_local" not in por_id[f"{os.getpid()}:2"]
