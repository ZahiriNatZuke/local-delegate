"""Parar el proceso con Ctrl+C es la forma normal de pararlo, no un fallo.

Había **dos** caminos hasta el mismo `Ctrl+C` y solo uno estaba preparado: `daemon.serve` capturaba
el `KeyboardInterrupt` desde hacía tiempo, con su comentario explicando por qué, y el camino stdio
—`local-delegate` a secas, que es como lo lanzan los hosts MCP y como se prueba a mano— lo dejaba
subir hasta arriba.

Lo que se veía entonces no era una línea: el SDK corre sobre anyio, así que Python imprime un
`ExceptionGroup` anidado con el rastro de las tareas. Un servidor que al pararse a propósito
escupe eso parece roto, y se reportó como tal.

Los dos casos se prueban **juntos y en el mismo módulo** a propósito: el defecto no fue no saber
qué hacer, fue arreglarlo en un camino y no en el otro.
"""

from __future__ import annotations

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
