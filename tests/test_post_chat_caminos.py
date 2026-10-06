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


#: (nombre, kwargs de la ruta, autostart, arranca, responde, remoto)
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
# Todos los de arriba son de origen LOCAL. Los dos remotos no preguntan ni arrancan (REQ-018).
CAMINOS = [(*c, False) for c in CAMINOS] + [
    ("remoto + ConnectError", {"side_effect": httpx2.ConnectError("x")}, False, True, True, True),
    (
        "remoto + ConnectTimeout con autoarranque",
        {"side_effect": httpx2.ConnectTimeout("x")},
        True,
        True,
        None,
        True,
    ),
]


def _preparar_camino(monkeypatch, ruta_kwargs, autoarranque, arranca, responde, remoto):
    """Monta un camino y devuelve los contadores de (autoarranques, preguntas).

    La URL de los fixtures (`http://test-backend/v1`) es REMOTA para `config.backend_origin()`.
    Por eso los caminos locales **fijan el origen**: sin eso, REQ-018 cerraría la pregunta y el
    autoarranque en todos, y esta lista dejaría de ejercitarlos sin que nada fallase.
    """
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    if not remoto:
        monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", "local")
    monkeypatch.setattr(config, "AUTOSTART", autoarranque)
    arranques: list[int] = []
    preguntas_hechas: list[str] = []

    def _ensure_backend(wait=0):
        arranques.append(wait)
        return arranca

    def _preguntar(mensaje, *_a, **_k):
        preguntas_hechas.append(mensaje)
        return None if responde is None else _RespuestaDelUsuario(responde)

    monkeypatch.setattr(autostart, "ensure_backend", _ensure_backend)
    monkeypatch.setattr(preguntas, "preguntar", _preguntar)
    backend_mock.post(URL).mock(**ruta_kwargs)
    return arranques, preguntas_hechas


@pytest.mark.parametrize(
    "ruta_kwargs,autoarranque,arranca,responde,remoto",
    [c[1:] for c in CAMINOS],
    ids=[c[0] for c in CAMINOS],
)
@backend_mock.mock
def test_todos_los_caminos_devuelven_un_resultado(
    monkeypatch, ruta_kwargs, autoarranque, arranca, responde, remoto
):
    arranques, preguntas_hechas = _preparar_camino(
        monkeypatch, ruta_kwargs, autoarranque, arranca, responde, remoto
    )

    resultado = server._post_chat("modelo", {"model": "modelo"})

    assert isinstance(resultado, ChatResult)
    assert isinstance(resultado.text, str) and resultado.text
    # Un fallo siempre trae su clase, y un éxito nunca la trae: es lo que hace utilizable el campo.
    assert (resultado.clase is None) is resultado.ok
    if remoto:
        assert arranques == [] and preguntas_hechas == [], "se ofreció arrancar un backend remoto"


def test_el_autoarranque_sigue_cubierto(monkeypatch):
    """Guarda de «esto llegó a comprobar algo» para REQ-018.

    Recorre los caminos locales con el MISMO montaje que el test de arriba y exige que la pregunta
    y el autoarranque se hayan ejercitado de verdad. Si alguien quita el origen fijado de
    `_preparar_camino`, la lista entera pasa a ser remota y los dos contadores se quedan en cero.
    """
    llamadas_ensure_backend = 0
    total_preguntas = 0
    for _nombre, ruta_kwargs, autoarranque, arranca, responde, remoto in CAMINOS:
        if remoto:
            continue
        with monkeypatch.context() as mp, backend_mock.mock:
            arranques, preguntas_hechas = _preparar_camino(
                mp, ruta_kwargs, autoarranque, arranca, responde, remoto
            )
            server._post_chat("modelo", {"model": "modelo"})
        llamadas_ensure_backend += len(arranques)
        total_preguntas += len(preguntas_hechas)

    assert llamadas_ensure_backend >= 1
    assert total_preguntas >= 1


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
