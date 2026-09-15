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

import importlib

import backend_mock
import httpx2
import pytest

from local_delegate import config, server

URL_CHAT = "http://test-backend/v1/chat/completions"
MODELO_LARGO = "llama31-8b"  # el defecto de MODEL_LONG


@pytest.fixture
def recargar_config(tmp_path):
    """Recarga `config` con variables reales, y lo deja todo como estaba al terminar.

    La recarga deshace el aislamiento de logs de `conftest` (`LOG_DIR` y `USAGE_LOG` volverían a
    las rutas reales del usuario), así que se vuelve a aplicar después de cada recarga.
    """
    mp = pytest.MonkeyPatch()

    def aislar_logs() -> None:
        config.LOG_DIR = tmp_path
        config.USAGE_LOG = tmp_path / "usage.jsonl"

    def aplicar(**variables: str) -> None:
        mp.setenv("LOCAL_DELEGATE_BASE_URL", "http://test-backend/v1")
        for nombre, valor in variables.items():
            mp.setenv(nombre, valor)
        importlib.reload(config)
        aislar_logs()

    yield aplicar
    mp.undo()
    importlib.reload(config)
    aislar_logs()


def _respuesta(contenido: str) -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": {"content": contenido}, "finish_reason": "stop"}]}
    )


def _texto(caracteres: int, *, final: str = "") -> str:
    linea = "Una linea de relleno para medir los topes de entrada por rol.\n"
    return (linea * (caracteres // len(linea) + 1))[:caracteres] + final


# --- Sin colisión, nada cambia ----------------------------------------------------------------


def test_con_la_config_por_defecto_los_topes_son_los_de_siempre(recargar_config):
    recargar_config()
    assert config.max_chars_for_role("mechanical") == 20000
    assert config.max_chars_for_role("long") == 48000
    assert config.max_chars_for_role("code") == 20000
    assert config.max_chars_for_role("fast") == 12000
    assert config.max_chars_for(config.MODEL_LONG) == 48000
    assert config.max_chars_for(config.MODEL_MECHANICAL) == 20000


# --- Largo = código ---------------------------------------------------------------------------


@backend_mock.mock
def test_largo_igual_a_codigo_no_trocea_un_resumen_que_cabe(recargar_config):
    """30 000 caracteres caben en los 48 000 del rol largo: una llamada, no un map-reduce."""
    recargar_config(LOCAL_DELEGATE_MODEL_CODE=MODELO_LARGO)
    ruta = backend_mock.post(URL_CHAT).mock(return_value=_respuesta("resumen"))
    server.local_summarize(text=_texto(30000))
    assert ruta.call_count == 1, "el rol largo heredó el tope de código y troceó"


@backend_mock.mock
def test_largo_igual_a_codigo_no_trocea_un_log_que_cabe(recargar_config):
    recargar_config(LOCAL_DELEGATE_MODEL_CODE=MODELO_LARGO)
    ruta = backend_mock.post(URL_CHAT).mock(return_value=_respuesta("resumen"))
    server.local_lint_summary(text=_texto(30000))
    assert ruta.call_count == 1


@backend_mock.mock
def test_largo_igual_a_codigo_no_trunca_una_traduccion_que_cabe(recargar_config):
    """`local_translate` trunca la entrada al tope antes de trocear: el final no puede perderse."""
    recargar_config(LOCAL_DELEGATE_MODEL_CODE=MODELO_LARGO)
    ruta = backend_mock.post(URL_CHAT).mock(return_value=_respuesta("traducido"))
    server.local_translate(target_lang="inglés", text=_texto(30000, final="FIN-DEL-TEXTO\n"))
    assert any(b"FIN-DEL-TEXTO" in llamada.request.content for llamada in ruta.calls), (
        "el final del texto no llegó al backend: se truncó con el tope de otro rol"
    )


@backend_mock.mock
def test_largo_igual_a_codigo_no_trunca_una_extraccion_que_cabe(recargar_config):
    recargar_config(LOCAL_DELEGATE_MODEL_CODE=MODELO_LARGO)
    backend_mock.post(URL_CHAT).mock(return_value=_respuesta('{"a": 1}'))
    datos = server.local_extract(fields=["a"], text=_texto(30000))
    assert "_local_delegate" not in datos, "se truncó una entrada que cabía en el rol largo"


def test_largo_igual_a_codigo_valida_candidatos_contra_el_minimo(recargar_config):
    """El tope POR MODELO sirve para validar un respaldo (REQ-003): ahí prometer de más es el fallo."""
    recargar_config(LOCAL_DELEGATE_MODEL_CODE=MODELO_LARGO)
    assert config.max_chars_for_role("long") == 48000
    assert config.max_chars_for_role("code") == 20000
    assert config.max_chars_for(MODELO_LARGO) == 20000


# --- Largo = rápido ---------------------------------------------------------------------------


@backend_mock.mock
def test_largo_igual_a_rapido_no_trocea_un_resumen_que_cabe(recargar_config):
    """Con rápido encima, el literal del dict dejaba el rol largo en 12 000."""
    recargar_config(LOCAL_DELEGATE_MODEL_FAST=MODELO_LARGO)
    ruta = backend_mock.post(URL_CHAT).mock(return_value=_respuesta("resumen"))
    server.local_summarize(text=_texto(30000))
    assert ruta.call_count == 1


def test_largo_igual_a_rapido_valida_candidatos_contra_el_minimo(recargar_config):
    recargar_config(LOCAL_DELEGATE_MODEL_FAST=MODELO_LARGO)
    assert config.max_chars_for(MODELO_LARGO) == 12000


# --- Control positivo: lo que no cabe se sigue troceando --------------------------------------


@backend_mock.mock
def test_un_resumen_que_no_cabe_en_el_rol_largo_se_sigue_troceando(recargar_config):
    """Sin esto, un tope infinito pasaría todos los tests de arriba."""
    recargar_config(LOCAL_DELEGATE_MODEL_CODE=MODELO_LARGO)
    ruta = backend_mock.post(URL_CHAT).mock(return_value=_respuesta("resumen"))
    server.local_summarize(text=_texto(60000))
    assert ruta.call_count > 1
