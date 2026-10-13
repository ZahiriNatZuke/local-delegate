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

from local_delegate import autostart, config, questions, server
from local_delegate.server import ChatResult

URL = "http://test-backend/v1/chat/completions"
GOOD = {"choices": [{"message": {"content": "hola"}}]}


class _UserAnswer:
    def __init__(self, start: bool) -> None:
        self.start = start


#: (nombre, kwargs de la ruta, autostart, arranca, responde, remoto)
PATHS = [
    ("200 correcto", {"return_value": httpx2.Response(200, json=GOOD)}, False, False, None),
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
PATHS = [(*c, False) for c in PATHS] + [
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


def _prepare_path(monkeypatch, route_kwargs, autostart_on, start_ok, answers, remote):
    """Monta un camino y devuelve los contadores de (autoarranques, preguntas).

    La URL de los fixtures (`http://test-backend/v1`) es REMOTA para `config.backend_origin()`.
    Por eso los caminos locales **fijan el origen**: sin eso, REQ-018 cerraría la pregunta y el
    autoarranque en todos, y esta lista dejaría de ejercitarlos sin que nada fallase.
    """
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    if not remote:
        monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", "local")
    monkeypatch.setattr(config, "AUTOSTART", autostart_on)
    start_calls: list[int] = []
    questions_asked: list[str] = []

    def _ensure_backend(wait=0):
        start_calls.append(wait)
        return start_ok

    def _ask(message, *_a, **_k):
        questions_asked.append(message)
        return None if answers is None else _UserAnswer(answers)

    monkeypatch.setattr(autostart, "ensure_backend", _ensure_backend)
    monkeypatch.setattr(questions, "ask", _ask)
    backend_mock.post(URL).mock(**route_kwargs)
    return start_calls, questions_asked


@pytest.mark.parametrize(
    "route_kwargs,autostart_on,start_ok,answers,remote",
    [c[1:] for c in PATHS],
    ids=[c[0] for c in PATHS],
)
@backend_mock.mock
def test_every_path_returns_a_result(
    monkeypatch, route_kwargs, autostart_on, start_ok, answers, remote
):
    start_calls, questions_asked = _prepare_path(
        monkeypatch, route_kwargs, autostart_on, start_ok, answers, remote
    )

    result = server._post_chat("modelo", {"model": "modelo"})

    assert isinstance(result, ChatResult)
    assert isinstance(result.text, str) and result.text
    # Un fallo siempre trae su clase, y un éxito nunca la trae: es lo que hace utilizable el campo.
    assert (result.error_class is None) is result.ok
    if remote:
        assert start_calls == [] and questions_asked == [], "se ofreció arrancar un backend remoto"


def test_autostart_is_still_covered(monkeypatch):
    """Guarda de «esto llegó a comprobar algo» para REQ-018.

    Recorre los caminos locales con el MISMO montaje que el test de arriba y exige que la pregunta
    y el autoarranque se hayan ejercitado de verdad. Si alguien quita el origen fijado de
    `_prepare_path`, la lista entera pasa a ser remota y los dos contadores se quedan en cero.
    """
    ensure_backend_calls = 0
    total_questions = 0
    for _name, route_kwargs, autostart_on, start_ok, answers, remote in PATHS:
        if remote:
            continue
        with monkeypatch.context() as mp, backend_mock.mock:
            start_calls, questions_asked = _prepare_path(
                mp, route_kwargs, autostart_on, start_ok, answers, remote
            )
            server._post_chat("modelo", {"model": "modelo"})
        ensure_backend_calls += len(start_calls)
        total_questions += len(questions_asked)

    assert ensure_backend_calls >= 1
    assert total_questions >= 1


def test_the_path_list_covers_every_branch():
    """Guarda de «esto llegó a comprobar algo»: si alguien añade una rama, que se note aquí.

    Cuenta los `return ChatResult(` de `_post_chat` y exige al menos un camino por cada uno. No es
    una prueba de cobertura fina, es un despertador: el fichero de arriba se escribió para una
    función con seis salidas distintas, y una séptima sin caso propio pasaría desapercibida.
    """
    import inspect

    source = inspect.getsource(server._post_chat)
    exits = source.count("return ChatResult(") + source.count("return _body_failure(")
    assert exits == 7, (
        f"`_post_chat` tiene {exits} salidas y esta lista se escribio para 7. Si has anadido "
        "una, enumera aqui el camino que la produce; si has quitado otra, baja el numero."
    )
