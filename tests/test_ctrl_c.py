"""Parar el proceso a mano es la forma normal de pararlo, no un fallo.

Había **dos** caminos hasta el mismo `Ctrl+C` y solo uno estaba preparado: `daemon.serve` capturaba
el `KeyboardInterrupt` desde hacía tiempo, con su comentario explicando por qué, y el camino stdio
—`local-delegate` a secas, que es como lo lanzan los hosts MCP y como se prueba a mano— lo dejaba
subir hasta arriba.

Lo que se veía entonces no era una línea: el SDK corre sobre anyio, así que Python imprime un
`ExceptionGroup` anidado con el rastro de las tareas. Un servidor que al pararse a propósito
escupe eso parece roto, y se reportó como tal.

Los dos casos se prueban **juntos y en el mismo módulo** a propósito: el defecto no fue no saber
qué hacer, fue arreglarlo en un camino y no en el otro.

**Y volvió a pasar un nivel más abajo.** Windows tiene dos eventos de consola y Python solo
convierte uno en `KeyboardInterrupt`: con `CTRL_BREAK_EVENT` los dos caminos morían igual de mal
—`serve` con código 3 y el stdio con `0xC000013A`— y ninguno de los tests de arriba podía verlo,
porque todos inyectan la excepción ya construida. Por eso los últimos tests de este módulo lanzan
**procesos de verdad** y le piden el código de salida al sistema operativo: es el único sitio donde
la diferencia entre los dos eventos existe.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

import httpx2
import pytest

from local_delegate import daemon, server


@pytest.fixture(autouse=True)
def _sin_web_ni_arranques(monkeypatch):
    """El MCP no debe levantar la web ni tocar el backend para probar cómo se para."""
    monkeypatch.setattr(server.config, "WEB_ENABLED", False)
    monkeypatch.setattr(server.config, "AUTOSTART", False)
    monkeypatch.setattr(server, "_aviso_de_terminal_interactiva", lambda: None)


def _interrumpir(*_a, **_kw):
    raise KeyboardInterrupt()


def test_ctrl_c_en_el_mcp_stdio_no_deja_escapar_la_excepcion(monkeypatch, capsys):
    """`local-delegate` a secas: lo que se lanza en una terminal y se corta con Ctrl+C."""
    monkeypatch.setattr(server.sys, "argv", ["local-delegate"])
    monkeypatch.setattr(server.mcp, "run", _interrumpir)

    server.main()  # si el KeyboardInterrupt escapara, este test fallaría aquí mismo

    salida = capsys.readouterr()
    assert "Traceback" not in (salida.out + salida.err)


def test_ctrl_c_en_el_daemon_tampoco(monkeypatch):
    """El camino que ya estaba bien. Se prueba igual para que no se caiga sin que nadie lo note."""
    monkeypatch.setattr(daemon, "_port_available", lambda host, port: True)
    monkeypatch.setattr(daemon.autostart, "ensure_backend", lambda wait=0: None)
    monkeypatch.setattr(daemon, "build_app", lambda host, port: object())
    monkeypatch.setattr(daemon.uvicorn, "Config", lambda *a, **kw: None)

    class _ServidorQueRecibeCtrlC:
        started = True

        def run(self):
            raise KeyboardInterrupt()

    monkeypatch.setattr(daemon.uvicorn, "Server", lambda _cfg: _ServidorQueRecibeCtrlC())

    assert daemon.serve(host="127.0.0.1", port=9499) == 0


def test_los_dos_caminos_tratan_igual_el_ctrl_c(monkeypatch, capsys, tmp_path):
    """La prueba de que no vuelven a divergir, que es el defecto real que hubo.

    Arreglar uno de los dos y dar el problema por cerrado es exactamente lo que pasó. Este test
    compara los **dos** en la misma corrida: ninguno propaga y ninguno imprime un traceback.
    """
    monkeypatch.setattr(daemon.config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(daemon, "_port_available", lambda host, port: True)
    monkeypatch.setattr(daemon.autostart, "ensure_backend", lambda wait=0: None)
    monkeypatch.setattr(daemon, "build_app", lambda host, port: object())
    monkeypatch.setattr(daemon.uvicorn, "Config", lambda *a, **kw: None)

    class _Servidor:
        started = True

        def run(self):
            raise KeyboardInterrupt()

    monkeypatch.setattr(daemon.uvicorn, "Server", lambda _cfg: _Servidor())
    monkeypatch.setattr(server.sys, "argv", ["local-delegate"])
    monkeypatch.setattr(server.mcp, "run", _interrumpir)

    resultados = []
    for nombre, llamada in (
        ("stdio", server.main),
        ("serve", lambda: daemon.serve(host="127.0.0.1", port=9499)),
    ):
        try:
            llamada()
            resultados.append((nombre, "limpio"))
        except KeyboardInterrupt:
            resultados.append((nombre, "PROPAGA"))

    assert resultados == [("stdio", "limpio"), ("serve", "limpio")], (
        f"los dos caminos deben tratar el Ctrl+C igual: {resultados}"
    )

    salida = capsys.readouterr()
    assert "Traceback" not in (salida.out + salida.err)


# --- Ctrl+Break: el otro evento de consola, con procesos de verdad --------------------------


def test_preparar_ctrl_break_no_pisa_un_handler_ajeno(monkeypatch):
    """Solo se toca `SIG_DFL`. Si alguien puso el suyo, manda el suyo."""
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is None:
        pytest.skip("SIGBREAK solo existe en Windows")

    ajeno = signal.getsignal(signal.SIGINT)  # cualquier callable válido que no sea SIG_DFL
    previo = signal.signal(sigbreak, ajeno)
    try:
        server.preparar_ctrl_break()
        assert signal.getsignal(sigbreak) is ajeno
    finally:
        signal.signal(sigbreak, previo)


def test_preparar_ctrl_break_no_revienta_fuera_del_hilo_principal():
    """`signal.signal` solo vale en el hilo principal; ahí «no toca hacer nada» no es un fallo."""
    import threading

    fallos: list[BaseException] = []

    def _en_otro_hilo() -> None:
        try:
            server.preparar_ctrl_break()
        except BaseException as exc:  # el test existe justo para atrapar cualquiera
            fallos.append(exc)

    hilo = threading.Thread(target=_en_otro_hilo)
    hilo.start()
    hilo.join()
    assert fallos == []


solo_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="CTRL_BREAK_EVENT es un evento de consola de Windows"
)


def _entorno_aislado(log_dir) -> dict[str, str]:
    """Entorno del hijo: su propio LOG_DIR, para que el lock del daemon real no interfiera."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # Sin esto el test se cuelga, y el motivo es el propio defecto que se está probando: con la
    # salida por tubería el hijo la almacena en buffer, y cuando el sistema lo mata de golpe ese
    # buffer se pierde sin llegar a escribirse. O sea que esperar por una línea suya sería esperar
    # para siempre. Se mide con la salida sin buffer.
    env["PYTHONUNBUFFERED"] = "1"
    env["LOCAL_DELEGATE_AUTOSTART"] = "0"
    # Solo afecta al camino stdio (la web embebida en un hilo). `serve` sirve la web por
    # definición y no la mira.
    env["LOCAL_DELEGATE_WEB"] = "0"
    env["LOCAL_DELEGATE_LOG_DIR"] = str(log_dir)
    return env


def _lanzar(args: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Lanza el paquete en **su propio grupo de procesos**.

    `CREATE_NEW_PROCESS_GROUP` no es un detalle: sin él, `CTRL_BREAK_EVENT` va al grupo del proceso
    que lo manda —o sea, a pytest— y el test se mataría a sí mismo.
    """
    return subprocess.Popen(
        [sys.executable, "-m", "local_delegate", *args],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def _romper_y_esperar(proc: subprocess.Popen) -> int:
    os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
    try:
        proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail("el proceso no terminó tras el CTRL_BREAK_EVENT")
    return proc.returncode


@solo_windows
def test_ctrl_break_sobre_el_daemon_sale_por_cero(tmp_path):
    """Salía con **3**, y el 3 no era nuestro.

    uvicorn captura `SIGBREAK` y al terminar restaura el handler original y **vuelve a lanzar la
    señal**; con `SIG_DFL` de original, la CRT mataba el proceso a mitad del apagado. Se midió que
    `serve()` no llegaba a retornar y que `atexit` no corría.
    """
    puerto = 9897
    proc = _lanzar(["serve", "--port", str(puerto)], _entorno_aislado(tmp_path))

    # Control positivo: no se manda nada hasta que el daemon RESPONDE. Sin esto, un proceso que
    # muriera por cualquier otro motivo daría un código de salida que el test leería como bueno.
    arrancado = False
    for _ in range(120):
        if proc.poll() is not None:
            break
        try:
            respuesta = httpx2.get(f"http://127.0.0.1:{puerto}/api/daemon", timeout=0.5)
            if respuesta.status_code == 200:
                arrancado = True
                break
        except httpx2.HTTPError:
            time.sleep(0.25)
    if not arrancado:
        proc.kill()
        proc.communicate()
        pytest.skip(f"el daemon no llegó a levantar en el {puerto}; no hay nada que interrumpir")

    assert _romper_y_esperar(proc) == 0


@solo_windows
def test_ctrl_break_sobre_el_mcp_stdio_sale_por_cero(tmp_path):
    """Moría con `0xC000013A` (`STATUS_CONTROL_C_EXIT`) y sin imprimir nada.

    Ahí no había ni handler: el manejador de consola por defecto se lo llevaba por delante.
    """
    proc = _lanzar([], _entorno_aislado(tmp_path))

    # Control positivo: se le habla MCP y se espera su respuesta. Es la única señal fiable de que
    # está sirviendo —el aviso por stderr NO sirve, porque `_aviso_de_terminal_interactiva` solo
    # lo imprime cuando stdin es una TTY y aquí es una tubería— y además prueba más: que lo que se
    # interrumpe es un servidor en marcha, no un proceso que todavía arranca.
    assert proc.stdin is not None and proc.stdout is not None
    peticion = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-ctrl-break", "version": "0"},
        },
    }
    proc.stdin.write((json.dumps(peticion) + "\n").encode("utf-8"))
    proc.stdin.flush()

    linea = proc.stdout.readline()
    assert b'"result"' in linea, f"el MCP stdio no llegó a responder al initialize: {linea!r}"

    assert _romper_y_esperar(proc) == 0
