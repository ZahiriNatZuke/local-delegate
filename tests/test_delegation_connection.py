"""Una delegación que no puede conectar: cuánto tarda en rendirse, qué dice y qué no ofrece.

REQ-017, REQ-018, REQ-019 y REQ-022 (`local_wait`) de
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

from local_delegate import autostart, config, questions, server

CHAT = "http://test-backend/v1/chat/completions"


def _connect_timeout(t) -> float:
    """El plazo de conexión, venga como `httpx2.Timeout` o como un número."""
    return t.connect if isinstance(t, httpx2.Timeout) else t


@pytest.fixture
def new_client():
    """`_get_client` cachea el cliente: el test necesita uno creado con la config del test."""
    server._client = None
    yield
    if server._client is not None:
        server._client.close()
    server._client = None


@pytest.fixture
def recorders(monkeypatch):
    """Sustituye la pregunta y el autoarranque por registradores que no hacen nada."""
    questions_asked: list[str] = []
    starts: list[int] = []

    def _ask(message, _schema):
        questions_asked.append(message)

    def _ensure_backend(wait=0):
        starts.append(wait)
        return False

    monkeypatch.setattr(questions, "ask", _ask)
    monkeypatch.setattr(autostart, "ensure_backend", _ensure_backend)
    return questions_asked, starts


def _last_log_line() -> dict:
    lines = server._current_log_path().read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


# --- REQ-019: el plazo de conexión de las delegaciones -------------------------------------------


def test_the_delegation_connect_timeout_is_10_s(new_client):
    timeout = server._get_client().timeout

    assert _connect_timeout(timeout) == 10.0
    # Solo cambia la conexión: la espera de carga de un modelo es de lectura y sigue igual.
    assert timeout.read == config.HTTP_TIMEOUT
    assert timeout.write == config.HTTP_TIMEOUT
    assert timeout.pool == config.HTTP_TIMEOUT


def test_the_connect_timeout_does_not_exceed_the_total(new_client, monkeypatch):
    monkeypatch.setattr(config, "HTTP_TIMEOUT", 5.0)

    assert _connect_timeout(server._get_client().timeout) == 5.0


def test_a_delegation_without_route_gives_up_in_10_s(monkeypatch, recorders, new_client):
    """Red real: `192.0.2.1` (TEST-NET-1) no contesta nunca.

    En esta PC, con el plazo del kernel de Windows, tardaba ~21 s. En un CI sin ruta hacia esa red
    el fallo es inmediato (`sin_ruta`) y pasa antes: el control de este test es el de Windows.
    """
    monkeypatch.setattr(config, "BASE_URL", "http://192.0.2.1:9292/v1")
    questions_asked, starts = recorders

    t0 = time.monotonic()
    text = server.local_summarize(text="hola")
    elapsed = time.monotonic() - t0

    assert elapsed < 13, f"tardó {elapsed:.1f} s en rendirse"
    line = _last_log_line()
    assert line.get("connection_failure") in {"connect_timeout", "no_route"}
    assert line["error"] == "connect_error"
    assert text.startswith("[local-delegate error] no se pudo conectar con el backend: ")
    assert questions_asked == [] and starts == []


# --- REQ-018: no se ofrece arrancar un backend remoto --------------------------------------------


@pytest.mark.parametrize("autostart", [False, True], ids=["sin-autoarranque", "con-autoarranque"])
@backend_mock.mock
def test_remote_delegation_neither_asks_nor_starts(monkeypatch, recorders, autostart):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "AUTOSTART", autostart)
    backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectTimeout("timed out"))
    questions_asked, starts = recorders

    text = server.local_summarize(text="hola")

    if autostart:
        assert starts == []
    else:
        assert questions_asked == []
    assert questions_asked == [] and starts == []
    assert "[local-delegate error]" in text


@backend_mock.mock
def test_local_delegation_keeps_asking(monkeypatch, recorders):
    """Guarda de regresión: con origen local, la pregunta de siempre."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", "local")
    monkeypatch.setattr(config, "AUTOSTART", False)
    rejection = httpx2.ConnectError("refused")
    rejection.__cause__ = OSError(errno.ECONNREFUSED, "refused")
    backend_mock.post(CHAT).mock(side_effect=rejection)
    questions_asked, _starts = recorders

    server.local_summarize(text="hola")

    assert len(questions_asked) == 1


# --- REQ-017: el error dice la causa y el log la guarda, en los cuatro caminos -------------------


def _minimal_png(dest) -> str:
    """Un PNG de 1×1 válido, escrito a mano para no depender de Pillow."""

    def block(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + block(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + block(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + block(b"IEND", b"")
    )
    dest.write_bytes(png)
    return str(dest)


def _simple(_tmp_path, _monkeypatch):
    return server.local_summarize(text="hola")


def _chunked_map_reduce(_tmp_path, monkeypatch):
    # Un tope pequeño fuerza el map-reduce sin tener que fabricar un texto enorme.
    monkeypatch.setattr(config, "max_chars_for_role", lambda rol: 2000)
    text = "\n\n".join(f"Párrafo {i}: " + "palabra " * 60 for i in range(12))
    used: list[bool] = []
    original = server._chat_map_reduce

    def _spy(*args, **kwargs):
        used.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(server, "_chat_map_reduce", _spy)
    result = server.local_summarize(text=text)
    # Guarda: sin ella, un cambio de umbral mandaría este caso por el camino simple en silencio.
    assert used, "el caso «troceada» no pasó por el map-reduce"
    return result


def _chunked_by_chunks(_tmp_path, _monkeypatch):
    return server.local_translate(target_lang="inglés", text="hola")


def _image(tmp_path, _monkeypatch):
    return server.local_describe_image(path=_minimal_png(tmp_path / "dot.png"))


@pytest.mark.parametrize(
    "path",
    [_simple, _chunked_map_reduce, _chunked_by_chunks, _image],
    ids=["simple", "chunked-map-reduce", "chunked-per-chunk", "imagen"],
)
@backend_mock.mock
def test_the_connection_error_states_the_cause_and_goes_to_the_log(
    tmp_path, monkeypatch, recorders, path
):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectTimeout("timed out"))

    text = path(tmp_path, monkeypatch)

    line = _last_log_line()
    assert line.get("connection_failure") == "connect_timeout"
    assert line["error"] == "connect_error"
    # Compatibilidad del log y del enfriamiento: la clase no cambia.
    assert line.get("error_class") == "endpoint"
    assert "no contesta a la conexión" in text
    assert "test-backend no contesta a la conexión (ruta, cortafuegos o VPN)" in text


@backend_mock.mock
def test_a_non_connection_failure_does_not_write_the_key(monkeypatch):
    """`connection_failure` solo aparece cuando hay causa: el log no engorda en cada evento."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.post(CHAT).mock(return_value=httpx2.Response(500, text="boom"))

    server.local_summarize(text="hola")

    assert "connection_failure" not in _last_log_line()


# --- REQ-022: la espera de plaza se ve en «En curso» ---------------------------------------------


def _inflight_entry(tmp_path) -> dict | None:
    file = tmp_path / "inflight.json"
    if not file.is_file():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except ValueError:
        return None  # se está reescribiendo
    entries = [v for v in data.values() if isinstance(v, dict)]
    return entries[0] if entries else None


def _wait(condition, timeout_s: float = 3.0):
    limit = time.monotonic() + timeout_s
    while time.monotonic() < limit:
        value = condition()
        if value:
            return value
        time.sleep(0.02)
    return condition()


@backend_mock.mock
def test_inflight_marks_the_local_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    reached_backend = threading.Event()
    keep_going = threading.Event()

    def _backend(_request):
        reached_backend.set()
        keep_going.wait(5)
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    backend_mock.post(CHAT).mock(side_effect=_backend)

    # Se toman TODAS las plazas del semáforo, sin suponer cuántas son.
    taken = 0
    while server._chat_slots.acquire(blocking=False):
        taken += 1
    thread = threading.Thread(target=server.local_summarize, kwargs={"text": "hola"}, daemon=True)
    try:
        thread.start()
        assert _wait(lambda: _inflight_entry(tmp_path)), "la delegación no apareció en curso"
        entry = _wait(
            lambda: (e := _inflight_entry(tmp_path)) and e.get("local_wait") and e
        ) or _inflight_entry(tmp_path)
        assert entry.get("local_wait") == "slot"
    finally:
        for _ in range(taken):
            server._chat_slots.release()

    try:
        assert reached_backend.wait(5), "la delegación no llegó al backend al liberar la plaza"
        entry = _inflight_entry(tmp_path)
        assert entry is not None
        assert entry.get("local_wait") is None
    finally:
        keep_going.set()
        thread.join(10)
    assert not thread.is_alive()


def test_without_wait_nothing_extra_is_written(tmp_path, monkeypatch):
    """En el caso normal (hay plaza) la entrada en vuelo es la de siempre."""
    views: list[dict] = []
    original = server._with_fallback

    def _spy(*args, **kwargs):
        views.append(dict(_inflight_entry(tmp_path) or {}))
        return original(*args, **kwargs)

    monkeypatch.setattr(server, "_with_fallback", _spy)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    with backend_mock.mock:
        backend_mock.post(CHAT).mock(
            return_value=httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        )
        server.local_summarize(text="hola")

    assert views and "local_wait" not in views[0]


def test_the_in_flight_snapshot_carries_the_local_wait(tmp_path):
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
                    "local_wait": "slot",
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

    by_id = {e["id"]: e for e in server.inflight_snapshot()}

    assert by_id[f"{os.getpid()}:1"].get("local_wait") == "slot"
    assert "local_wait" not in by_id[f"{os.getpid()}:2"]
