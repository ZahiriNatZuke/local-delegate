"""Las 16 formas de terminar `_post_chat`, cubiertas a la vez.

Este fichero es lo que queda del `retry_exhausted` que se eliminó: aquella línea prometía que la
función siempre devuelve un `ChatResult`, y nunca se ejecutaba, así que la promesa no la
comprobaba nadie. Aquí sí. Se enumeran todas las salidas del `try` —camino feliz, cuerpo
inservible, cada rama del `except`, y el autoarranque con sus cuatro desenlaces— y de todas se
exige lo mismo: un `ChatResult`, jamás `None` ni una excepción que se escape.

La demostración de que la línea no se alcanzaba, con su control positivo, está en
`.sdd/changes/delegacion-precisa-y-fiable/verification.md`.
"""

from __future__ import annotations

import backend_mock
import httpx2
import pytest

from local_delegate import autostart, config, preguntas, server
from local_delegate.server import ChatResult

URL = "http://test-backend/v1/chat/completions"
BUENA = {"choices": [{"message": {"content": "hola"}}]}


class _RespuestaDelUsuario:
    def __init__(self, arrancar: bool) -> None:
        self.arrancar = arrancar


#: (nombre, kwargs de la ruta, autostart, arranca, responde)
CAMINOS = [
    ("200 correcto", {"return_value": httpx2.Response(200, json=BUENA)}, False, False, None),
    (
        "200 con content nulo",
        {"return_value": httpx2.Response(200, json={"choices": [{"message": {}}]})},
        False,
        False,
        None,
    ),
    (
        "200 que no es json",
        {"return_value": httpx2.Response(200, text="<html>")},
        False,
        False,
        None,
    ),
    ("200 sin choices", {"return_value": httpx2.Response(200, json={})}, False, False, None),
    ("400", {"return_value": httpx2.Response(400, text="malo")}, False, False, None),
    ("500", {"return_value": httpx2.Response(500, text="boom")}, False, False, None),
    ("ReadTimeout", {"side_effect": httpx2.ReadTimeout("x")}, False, False, None),
    ("RemoteProtocolError", {"side_effect": httpx2.RemoteProtocolError("x")}, False, False, None),
    ("ConnectError + arranca", {"side_effect": httpx2.ConnectError("x")}, True, True, None),
    ("ConnectError + no arranca", {"side_effect": httpx2.ConnectError("x")}, True, False, None),
    ("ConnectTimeout + arranca", {"side_effect": httpx2.ConnectTimeout("x")}, True, True, None),
    (
        "ConnectTimeout + no arranca",
        {"side_effect": httpx2.ConnectTimeout("x")},
        True,
        False,
        None,
    ),
    ("dice que sí y arranca", {"side_effect": httpx2.ConnectError("x")}, False, True, True),
    ("dice que sí y no arranca", {"side_effect": httpx2.ConnectError("x")}, False, False, True),
    ("dice que no", {"side_effect": httpx2.ConnectError("x")}, False, False, False),
    ("no hay a quién preguntar", {"side_effect": httpx2.ConnectError("x")}, False, False, None),
]


@pytest.mark.parametrize(
    "ruta_kwargs,autoarranque,arranca,responde",
    [c[1:] for c in CAMINOS],
    ids=[c[0] for c in CAMINOS],
)
@backend_mock.mock
def test_todos_los_caminos_devuelven_un_resultado(
    monkeypatch, ruta_kwargs, autoarranque, arranca, responde
):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "AUTOSTART", autoarranque)
    monkeypatch.setattr(autostart, "ensure_backend", lambda wait=0: arranca)
    monkeypatch.setattr(
        preguntas,
        "preguntar",
        lambda *a, **k: None if responde is None else _RespuestaDelUsuario(responde),
    )
    backend_mock.post(URL).mock(**ruta_kwargs)

    resultado = server._post_chat("modelo", {"model": "modelo"})

    assert isinstance(resultado, ChatResult)
    assert isinstance(resultado.text, str) and resultado.text
    # Un fallo siempre trae su clase, y un éxito nunca la trae: es lo que hace utilizable el campo.
    assert (resultado.clase is None) is resultado.ok


def test_la_lista_de_caminos_cubre_todas_las_ramas():
    """Guarda de «esto llegó a comprobar algo»: si alguien añade una rama, que se note aquí.

    Cuenta los `return ChatResult(` de `_post_chat` y exige al menos un camino por cada uno. No es
    una prueba de cobertura fina, es un despertador: el fichero de arriba se escribió para una
    función con seis salidas distintas, y una séptima sin caso propio pasaría desapercibida.
    """
    import inspect

    fuente = inspect.getsource(server._post_chat)
    salidas = fuente.count("return ChatResult(") + fuente.count("return _fallo_de_cuerpo(")
    assert salidas == 7, (
        f"`_post_chat` tiene {salidas} salidas y esta lista se escribio para 7. Si has anadido "
        "una, enumera aqui el camino que la produce; si has quitado otra, baja el numero."
    )
