"""T13: `llamaswap residency` antes y después de escribir (REQ-034, REQ-038, REQ-039).

Las negativas (delegaciones propias, peticiones de cualquier cliente, modelos cargados, «no se
sabe»), la vigía abierta antes de escribir y sus cuatro salidas. Lo que necesita un llama-swap de
verdad usa el de prueba de T2 (`fake_llamaswap.py`): su propio puerto, su propia config en
`tmp_path` y su control de PID. Toda orden del CLI lleva `--config` y apunta a esa config; el
llama-swap real (127.0.0.1:9292) no recibe nada: la consulta al daemon la corta la fixture autouse
`conftest.real_daemon_down` y, cuando un test pone una key falsa para el camino directo, también
mueve `BASE_URL` al llama-swap de prueba (`_direct_to`).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from conftest import DEAD_PORT
from fake_llamaswap import FakeModel, binary_available, fake_llamaswap

from local_delegate import checks, cli, config, llamaswap_api, server
from local_delegate.web import metrics

FIXTURES = Path(__file__).parent / "fixtures" / "residencia"
TODAY = FIXTURES / "hoy.yaml"

needs_llamaswap = pytest.mark.skipif(
    not binary_available(), reason="falta llama-swap-v255 de prueba"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _residency(*argv: str) -> int:
    return cli.run(["llamaswap", "residency", *argv])


def _direct_to(ls, monkeypatch) -> None:
    """El camino directo de REQ-039 contra el llama-swap de prueba, con una key falsa."""
    assert ls.port != 9292
    monkeypatch.setattr(config, "BASE_URL", f"{ls.url}/v1")
    monkeypatch.setattr(config, "API_KEY", "clave-falsa-1")


def _live_delegation() -> None:
    """Una entrada de `inflight.json` con un pid vivo y que no es el nuestro (otro proceso MCP)."""
    other = os.getppid()
    server._atomic_write_json(
        server._inflight_file(),
        {
            f"{other}:1": {
                "tool": "local_summarize",
                "model": "gemma4-26b-a4b",
                "source": "path",
                "chars_in": 1,
                "started_at": time.time(),
                "pid": other,
            }
        },
    )


def _output(capsys) -> str:
    read = capsys.readouterr()
    return read.out + read.err


# --- La comprobación previa sin llama-swap ----------------------------------------------------


def test_without_credential_it_does_not_write_blind(tmp_path, capsys):
    """Daemon apagado (la fixture autouse) y shell sin key: «no se sabe», y no se pide la key."""
    path = tmp_path / "config.yaml"
    path.write_bytes(TODAY.read_bytes())
    before = _sha(path)

    rc = _residency("--config", str(path), "--ttl", "gemma4-12b=60")

    output = _output(capsys)
    assert rc == 2
    assert "no se sabe si hay delegaciones en curso" in output
    assert "LOCAL_DELEGATE_API_KEY" not in output
    assert _sha(path) == before
    assert not list(tmp_path.glob("config.yaml.*.bak"))


def test_status_query_does_not_wait_for_a_daemon_that_never_answers(tmp_path, monkeypatch, capsys):
    """El limitador de hilos del daemon agotado: acepta la conexión y no contesta nunca.

    El test pone su propio tope: a los 12 s cierra el servidor, para que un CLI sin plazo también
    termine (y falle por tiempo, no se quede colgado).
    """
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    accepted: list[socket.socket] = []

    def accept_loop() -> None:
        with contextlib.suppress(OSError):
            while True:
                conn, _ = srv.accept()
                accepted.append(conn)

    def close_all() -> None:
        for s in [*accepted, srv]:
            with contextlib.suppress(OSError):
                s.close()

    threading.Thread(target=accept_loop, daemon=True).start()
    cap = threading.Timer(12.0, close_all)
    cap.start()
    monkeypatch.setattr(cli, "_daemon_target", lambda: ("127.0.0.1", port, {}))
    path = tmp_path / "config.yaml"
    path.write_bytes(TODAY.read_bytes())
    before = _sha(path)
    try:
        start = time.monotonic()
        rc = _residency("--config", str(path), "--ttl", "gemma4-12b=60")
        elapsed = time.monotonic() - start
    finally:
        cap.cancel()
        close_all()

    output = _output(capsys)
    assert accepted, "el CLI no llegó a conectar: el test no comprobaría nada"
    assert elapsed < 5
    assert rc == 2
    assert "no se sabe si hay delegaciones en curso" in output
    assert _sha(path) == before


# --- Negativas con el llama-swap de prueba ----------------------------------------------------


@pytest.mark.llamaswap_real
@needs_llamaswap
def test_no_write_with_own_delegations_in_flight(tmp_path, monkeypatch, capsys):
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)]) as ls:
        _direct_to(ls, monkeypatch)
        _live_delegation()
        before = _sha(ls.config)

        rc = _residency("--config", str(ls.config), "--ttl", "m=61")
        output = _output(capsys)
        assert rc == 2
        assert "hay 1 delegación de local-delegate en curso" in output
        assert "descargaría" in output
        assert _sha(ls.config) == before

        assert _residency("--config", str(ls.config), "--ttl", "m=61", "--now") == 0
        output = _output(capsys)
    assert _sha(ls.config) != before
    assert "escrito con --now" in output
    assert "recargó" in output


@pytest.mark.llamaswap_real
@needs_llamaswap
def test_no_write_with_a_request_from_another_client(tmp_path, monkeypatch, capsys):
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)]) as ls:
        _direct_to(ls, monkeypatch)
        other = ls.launch_client("m", delay_s=6)
        deadline = time.monotonic() + 10
        while not ls.inflight_snapshot().requests and time.monotonic() < deadline:
            time.sleep(0.2)
        before = _sha(ls.config)

        rc = _residency("--config", str(ls.config), "--ttl", "m=61")
        output = _output(capsys)
        other.wait(timeout=30)
    assert rc == 2
    assert "hay 1 petición en vuelo en llama-swap (m: 1)" in output
    assert "descargaría" in output
    assert _sha(ls.config) == before


# --- Las salidas de la vigía --------------------------------------------------------------------


@pytest.mark.llamaswap_real
@needs_llamaswap
def test_llamaswap_rejects_the_config_and_the_copy_is_restored(tmp_path, monkeypatch, capsys):
    """El fichero se escribe por la función interna, sin la autocomprobación del editor."""
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)]) as ls:
        _direct_to(ls, monkeypatch)
        original = ls.config.read_bytes()
        rejectable = original.replace(b"cmd:", b"cmdx:")
        assert rejectable != original

        rc = cli._write_residency(argparse.Namespace(now=False), ls.config, rejectable, original)
        output = _output(capsys)
        # La segunda recarga (la de la config restaurada) ya terminó: la vigiló el CLI.
        serves = ls.chat("m").status_code
    (copy_path,) = [p for p in tmp_path.glob("config.yaml.*.bak") if p.read_bytes() == original]
    assert rc == 1
    assert "rechazó" in output
    assert "failed to reload config" in output
    assert _sha(ls.config) == _sha(copy_path)
    assert any(p.read_bytes() == rejectable for p in tmp_path.glob("config.yaml.*.bak"))
    assert "al restaurar, llama-swap vuelve a recargar y corta las peticiones en curso" in output
    assert "recarga de la config restaurada: recargó" in output
    assert serves == 200


@pytest.mark.llamaswap_real
@needs_llamaswap
def test_llamaswap_that_does_not_watch_the_file(tmp_path, monkeypatch, capsys):
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)], watch_config=False) as ls:
        _direct_to(ls, monkeypatch)
        start = time.monotonic()
        rc = _residency("--config", str(ls.config), "--ttl", "m=61")
        elapsed = time.monotonic() - start
        output = _output(capsys)
    assert elapsed < 15
    assert rc == 0
    assert "no vigila el fichero" in output
    assert "próximo arranque" in output


@pytest.mark.llamaswap_real
@needs_llamaswap
def test_restoring_a_copy_end_to_end(tmp_path, monkeypatch, capsys):
    """REQ-038: byte a byte, copia del actual, y la recarga informada (en T11 no había vigía)."""
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)]) as ls:
        _direct_to(ls, monkeypatch)
        original = ls.config.read_bytes()
        # Con --now las dos órdenes: lo que se mira aquí es la restauración y lo que se informa
        # después; las negativas tienen sus propios tests.
        assert _residency("--config", str(ls.config), "--ttl", "m=61", "--now") == 0
        (copy_path,) = tmp_path.glob("config.yaml.*.bak")
        changed = ls.config.read_bytes()
        capsys.readouterr()

        rc = _residency("--config", str(ls.config), "--restore", str(copy_path), "--now")
        output = _output(capsys)
    assert rc == 0
    assert ls.config.read_bytes() == copy_path.read_bytes() == original
    others = [p for p in tmp_path.glob("config.yaml.*.bak") if p != copy_path]
    assert len(others) == 1 and others[0].read_bytes() == changed
    assert "recargó" in output


# --- A través del daemon ------------------------------------------------------------------------


@contextlib.contextmanager
def _test_daemon(monkeypatch):
    """La app del panel servida con uvicorn en un puerto libre: el daemon que ve el CLI."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(
        uvicorn.Config(
            metrics.app, host="127.0.0.1", port=port, log_level="warning", access_log=False
        )
    )
    srv.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert srv.started, "el daemon de prueba no arrancó"
    monkeypatch.setattr(cli, "_daemon_target", lambda: ("127.0.0.1", port, {}))
    monkeypatch.setattr(checks, "_llamaswap_daemon_destination", lambda: ("127.0.0.1", port, {}))
    try:
        yield
    finally:
        srv.should_exit = True
        thread.join(timeout=10)


@pytest.mark.llamaswap_real
@needs_llamaswap
def test_through_the_daemon_without_a_key_in_the_shell(tmp_path, monkeypatch, capsys):
    """El shell no tiene key (la suite la borra): el estado y la vigía los da el daemon."""
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)]) as ls:
        monkeypatch.setattr(config, "BASE_URL", f"{ls.url}/v1")  # lo que ve el daemon
        assert config.API_KEY == ""
        with _test_daemon(monkeypatch):
            rc = _residency("--config", str(ls.config), "--ttl", "m=61")
            output = _output(capsys)
    assert rc == 0
    assert "recargó" in output


@pytest.mark.llamaswap_real
@needs_llamaswap
def test_daemon_that_starts_llamaswap_without_watch_config_says_what_is_missing(
    tmp_path, monkeypatch, capsys
):
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)], watch_config=False) as ls:
        monkeypatch.setattr(config, "BASE_URL", f"{ls.url}/v1")
        monkeypatch.setattr(config, "AUTOSTART", True)
        monkeypatch.delenv("LLAMASWAP_WATCH_CONFIG", raising=False)
        with _test_daemon(monkeypatch):
            rc = _residency("--config", str(ls.config), "--ttl", "m=61")
            output = _output(capsys)
    assert rc == 0
    assert "no vigila el fichero" in output
    assert "LLAMASWAP_WATCH_CONFIG=1" in output


def test_the_daemon_tells_the_cli_which_config_it_uses(monkeypatch):
    """`cli._daemon_path` lee `config_path` del estado del daemon (la constante de T11).

    Con llama-swap caído para el daemon (un puerto sin nadie): en Windows tarda ~2,1 s en saberlo,
    y el CLI tiene que esperar a esa respuesta, que trae la ruta igual.
    """
    monkeypatch.setattr(config, "BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLAMASWAP_CONFIG", "D:/configs/llama-swap.yaml")
    with _test_daemon(monkeypatch):
        assert cli._daemon_path() == Path("D:/configs/llama-swap.yaml")


# --- Corrección tras la revisión de la ola 7 ----------------------------------------------------


def _ok_status(path: Path | None = None) -> llamaswap_api.Status:
    """Un estado de llama-swap sin nada en curso: ninguna negativa."""
    return llamaswap_api.Status(
        llamaswap_api.STATE_OK, config_path=str(path) if path is not None else None
    )


def test_a_change_made_while_the_watch_opens_is_not_overwritten(tmp_path, monkeypatch, capsys):
    """La vigía puede tardar hasta 8 s en abrirse: el fichero se compara DESPUÉS, no antes."""
    path = tmp_path / "config.yaml"
    path.write_bytes(TODAY.read_bytes())
    someone_elses = TODAY.read_bytes().replace(b"    ttl: 30\n", b"    ttl: 45\n")
    assert someone_elses != TODAY.read_bytes()
    real_open_watch = cli._open_watch

    def open_watch_while_someone_edits(origin, why):
        result = real_open_watch(origin, why)
        path.write_bytes(someone_elses)  # otro editor guarda mientras se abre la vigía
        return result

    monkeypatch.setattr(cli, "_open_watch", open_watch_while_someone_edits)

    rc = _residency("--config", str(path), "--ttl", "gemma4-12b=60", "--now")

    assert path.read_bytes() == someone_elses
    assert rc == 2
    assert "cambió mientras se editaba" in _output(capsys)
    assert not list(tmp_path.glob("config.yaml.*.bak"))


def test_without_a_watch_it_does_not_write_unless_now(tmp_path, monkeypatch, capsys):
    """El daemon dice que no hay nada en curso, pero no puede abrir la vigía (502): no se escribe a
    ciegas (REQ-034); con --now, sí."""
    monkeypatch.setattr(
        llamaswap_api, "query_status", lambda backend, own_delegations: _ok_status()
    )

    def cannot_open(backend):
        raise llamaswap_api.QueryError("ya hay 4 vigías abiertas")

    monkeypatch.setattr(llamaswap_api.watches, "open", cannot_open)
    monkeypatch.setattr(config, "BASE_URL", "http://127.0.0.1:9/v1")
    path = tmp_path / "config.yaml"
    path.write_bytes(TODAY.read_bytes())
    before = _sha(path)
    with _test_daemon(monkeypatch):
        rc = _residency("--config", str(path), "--ttl", "gemma4-12b=60")
        output = _output(capsys)
        assert rc == 2
        assert "no se puede vigilar la recarga" in output
        assert "ya hay 4 vigías abiertas" in output
        assert "--now" in output
        assert _sha(path) == before

        assert _residency("--config", str(path), "--ttl", "gemma4-12b=60", "--now") == 0
    assert _sha(path) != before
    assert "no se puede confirmar la recarga" in _output(capsys)


def test_without_config_one_status_query_serves_path_and_refusals(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.yaml"
    path.write_bytes(TODAY.read_bytes())
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    queries: list[int] = []

    def daemon_status():
        queries.append(1)
        return _ok_status(path), ""

    monkeypatch.setattr(cli, "_daemon_status", daemon_status)

    rc = _residency("--ttl", "gemma4-12b=60", "--now")

    assert rc == 0
    assert _sha(path) != _sha(TODAY)
    assert len(queries) == 1


def test_doctor_reads_the_daemon_config_and_turn_when_the_shell_has_none(
    tmp_path, monkeypatch, request
):
    """`doctor` desde un shell sin `LLAMASWAP_CONFIG`: la config y el turno los dice el daemon."""
    # Loopback y sin nadie: el servidor que corta de `conftest` (un RST en el acto).
    monkeypatch.setattr(config, "BASE_URL", f"http://127.0.0.1:{request.node.stash[DEAD_PORT]}/v1")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(TODAY))  # el entorno del daemon
    with _test_daemon(monkeypatch):
        ctx = checks.Context(home=tmp_path, config_path=None)  # el shell, sin config
        topology = checks._probe_topology(ctx)
        residency = checks._probe_residency(ctx)
    assert topology.status == checks.OK
    assert "turno activo según el daemon" in topology.detail
    assert residency.status == checks.OK
    assert "sin residente" in residency.detail
    assert "la config del daemon" in residency.detail
