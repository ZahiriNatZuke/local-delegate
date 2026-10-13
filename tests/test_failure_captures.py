"""Clasificación contra respuestas REALES del backend (REQ-020), no escritas a mano.

Las fixtures de `tests/fixtures/backend/` se capturaron el 2026-09-15 contra llama-swap v255 y
llama-server b10909 (protocolo-f2.md §10, sesión 8), con la clase esperada escrita ANTES de capturar.
Cada una lleva sus versiones: si el backend cambia, se recapturan, no se retocan.

Lo que ve el cliente se reconstruye igual que en `_post_chat`: una respuesta HTTP se convierte en
`BackendResponse` con el cuerpo recortado a 300 caracteres, y un `ReadTimeout` se clasifica con la señal
de carga que daba `/running` al vencer.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest

from local_delegate.failures import BackendResponse, FailureClass, classify

FIXTURES = Path(__file__).parent / "fixtures" / "backend"


def _capture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _model_loaded_at_end(doc: dict) -> bool | None:
    """La señal de REQ-018 tal como la dio llama-swap cuando la petición terminó."""
    model = doc["request"]["model"]
    for entry in doc["running_at_end"].get("running", []):
        if entry.get("model") == model:
            return entry.get("state") == "ready"
    return None


def _classify_capture(doc: dict) -> FailureClass | None:
    if "exception" in doc:
        assert doc["exception"]["type"] == "ReadTimeout", (
            "solo se capturó ReadTimeout como excepción"
        )
        return classify(
            httpx2.ReadTimeout(doc["exception"]["message"]),
            model_loaded=_model_loaded_at_end(doc),
        )
    response = doc["response"]
    return classify(
        BackendResponse(
            status=response["status"], data=response["json"], text=response["text"][:300]
        )
    )


def test_every_capture_carries_version_and_expected_class():
    captures = sorted(FIXTURES.glob("*.json"))
    assert len(captures) == 6, "se capturaron seis casos; si cambia el número, cambia este test"
    for path in captures:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["versions"] == {
            "llama-swap": "v255 (7761aa1)",
            "llama-server": "b10909 (a2878d30d)",
        }
        assert doc["expected_class"], path.name


@pytest.mark.parametrize("name", ["oom-with-profile", "load-error"])
def test_the_model_that_cannot_be_loaded_is_capacity(name):
    """OOM con la política del driver y modelo inexistente: llama-swap da el MISMO 500 a los dos."""
    doc = _capture(name)
    # Las capturas guardan el valor viejo (`capacidad_o_carga`): el enum lo sigue leyendo (REQ-006).
    assert FailureClass(doc["expected_class"]) is FailureClass.CAPACITY
    assert _classify_capture(doc) is FailureClass.CAPACITY


def test_the_timeout_during_loading_is_capacity():
    """`/running` decía `starting` al vencer: no se le cuenta el fallo a un modelo lento de montar."""
    doc = _capture("timeout-during-load")
    assert _model_loaded_at_end(doc) is False
    assert _classify_capture(doc) is FailureClass.CAPACITY


def test_the_same_timeout_with_the_model_already_loaded_would_be_a_read_timeout():
    """Control positivo del anterior: la misma captura con la señal cambiada cambia de clase."""
    doc = _capture("timeout-during-load")
    assert (
        classify(httpx2.ReadTimeout(doc["exception"]["message"]), model_loaded=True)
        is FailureClass.READ_TIMEOUT
    )


def test_the_request_during_loading_ends_well_and_is_not_a_failure():
    doc = _capture("request-during-load")
    states = [
        entry["state"]
        for sample in doc["running_samples"]
        for entry in sample["running"].get("running", [])
    ]
    assert "starting" in states, "la captura tiene que haber visto la carga en curso"
    assert _model_loaded_at_end(doc) is True
    assert _classify_capture(doc) is None


def test_the_oom_without_profile_did_not_reach_timeout_and_stays_uncaptured():
    """Sin la política el modelo desbordó y RESPONDIÓ (200 en 8 s): no hay `ReadTimeout` que clasificar.

    La clase esperada (`timeout_lectura`) queda sin prueba real; este test fija que la captura no la
    demuestra, para que nadie la cite como si lo hiciera.
    """
    doc = _capture("oom-without-profile")
    assert FailureClass(doc["expected_class"]) is FailureClass.READ_TIMEOUT
    assert "exception" not in doc
    assert doc["response"]["status"] == 200
    assert _classify_capture(doc) is None


def test_reasoning_that_exhausts_max_tokens_is_configuration():
    """La captura real llega con `content: ""` (no nulo), `finish_reason: length` y razonamiento."""
    doc = _capture("length-with-reasoning")
    message = doc["response"]["json"]["choices"][0]["message"]
    assert message["content"] == "", "la captura es la que destapó el vacío: si cambia, recapturar"
    assert message["reasoning_content"].strip()
    assert _classify_capture(doc) is FailureClass.CONFIGURATION


def test_a_llama_swap_500_that_is_not_about_loading_is_still_the_models():
    """Control positivo del patrón: otro 500 del mismo origen, sin el texto de carga, no es capacidad."""
    body = '{"src":"llama-swap","error":{"message":"upstream error","type":"server_error"}}'
    assert classify(BackendResponse(status=500, text=body)) is FailureClass.MODEL


def test_no_capture_carries_paths_or_credentials():
    """`personal-security-check` busca datos personales, no cabeceras: esto lo comprueba aquí."""
    for path in FIXTURES.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        for leak in ("Projects", "Users", "Authorization", "Bearer", "apiKey"):
            assert leak not in text, f"{path.name} contiene {leak!r}"
