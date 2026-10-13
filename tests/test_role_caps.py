"""Tarea 25 de F3: el tope de entrada es del ROL, no del nombre del modelo.

`config.MAX_CHARS` era un dict indexado por nombre de modelo. REQ-004 prevé que dos roles resuelvan
al mismo modelo (por ejemplo, largo y código consolidados en uno), y con esa forma el literal del
dict hacía ganar al último: el rol largo heredaba el tope de código o de rápido **sin avisar**, y
`local_summarize` troceaba, o `local_translate` truncaba, una entrada que cabía de sobra.

La colisión solo existe si las variables están puestas **al importar** `config`: parchear
`config.MODEL_CODE` en caliente no reconstruye el dict y el test saldría verde con el defecto vivo.
Por eso el fixture recarga el módulo con las variables de verdad.
"""

from __future__ import annotations

import backend_mock
import httpx2

from local_delegate import config, server

URL_CHAT = "http://test-backend/v1/chat/completions"
LONG_MODEL = "gemma4-26b-a4b"  # el defecto de MODEL_LONG

# El fixture `reload_config` vive en `conftest.py`: lo comparten estos tests y los de las cadenas.


def _response(content: str) -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    )


def _text(chars: int, *, final: str = "") -> str:
    line = "Una linea de relleno para medir los topes de entrada por rol.\n"
    return (line * (chars // len(line) + 1))[:chars] + final


# --- Sin colisión, nada cambia ----------------------------------------------------------------


def test_with_the_default_config_the_caps_are_the_usual_ones(reload_config):
    reload_config()
    assert config.max_chars_for_role("mechanical") == 20000
    assert config.max_chars_for_role("long") == 48000
    assert config.max_chars_for_role("code") == 20000
    assert config.max_chars_for(config.MODEL_LONG) == 48000
    assert config.max_chars_for(config.MODEL_MECHANICAL) == 20000


# --- Largo = código ---------------------------------------------------------------------------


@backend_mock.mock
def test_long_equal_to_code_does_not_chunk_a_summary_that_fits(reload_config):
    """30 000 caracteres caben en los 48 000 del rol largo: una llamada, no un map-reduce."""
    reload_config(LOCAL_DELEGATE_MODEL_CODE=LONG_MODEL)
    path = backend_mock.post(URL_CHAT).mock(return_value=_response("resumen"))
    server.local_summarize(text=_text(30000))
    assert path.call_count == 1, "el rol largo heredó el tope de código y troceó"


@backend_mock.mock
def test_long_equal_to_code_does_not_chunk_a_log_that_fits(reload_config):
    reload_config(LOCAL_DELEGATE_MODEL_CODE=LONG_MODEL)
    path = backend_mock.post(URL_CHAT).mock(return_value=_response("resumen"))
    server.local_lint_summary(text=_text(30000))
    assert path.call_count == 1


@backend_mock.mock
def test_long_equal_to_code_does_not_truncate_a_translation_that_fits(reload_config):
    """`local_translate` trunca la entrada al tope antes de trocear: el final no puede perderse."""
    reload_config(LOCAL_DELEGATE_MODEL_CODE=LONG_MODEL)
    path = backend_mock.post(URL_CHAT).mock(return_value=_response("traducido"))
    server.local_translate(target_lang="inglés", text=_text(30000, final="FIN-DEL-TEXTO\n"))
    assert any(b"FIN-DEL-TEXTO" in call.request.content for call in path.calls), (
        "el final del texto no llegó al backend: se truncó con el tope de otro rol"
    )


@backend_mock.mock
def test_long_equal_to_code_does_not_truncate_an_extraction_that_fits(reload_config):
    reload_config(LOCAL_DELEGATE_MODEL_CODE=LONG_MODEL)
    backend_mock.post(URL_CHAT).mock(return_value=_response('{"a": 1}'))
    data = server.local_extract(fields=["a"], text=_text(30000))
    assert "_local_delegate" not in data, "se truncó una entrada que cabía en el rol largo"


def test_long_equal_to_code_validates_candidates_against_the_minimum(reload_config):
    """El tope POR MODELO sirve para validar un respaldo (REQ-003): ahí prometer de más es el fallo."""
    reload_config(LOCAL_DELEGATE_MODEL_CODE=LONG_MODEL)
    assert config.max_chars_for_role("long") == 48000
    assert config.max_chars_for_role("code") == 20000
    assert config.max_chars_for(LONG_MODEL) == 20000


# El bloque «Largo = rápido» se retiró con el rol `fast` (0.30.0). Cubría lo mismo que el de
# «Largo = código» de arriba —dos roles sobre un modelo, y el tope menor mandando en
# `max_chars_for`— con el agravante de que su tope era el más bajo del dict. La colisión sigue
# probada; lo que desapareció es el tercer rol con el que provocarla.


# --- Control positivo: lo que no cabe se sigue troceando --------------------------------------


@backend_mock.mock
def test_a_summary_that_does_not_fit_the_long_role_is_still_chunked(reload_config):
    """Sin esto, un tope infinito pasaría todos los tests de arriba."""
    reload_config(LOCAL_DELEGATE_MODEL_CODE=LONG_MODEL)
    path = backend_mock.post(URL_CHAT).mock(return_value=_response("resumen"))
    server.local_summarize(text=_text(60000))
    assert path.call_count > 1
