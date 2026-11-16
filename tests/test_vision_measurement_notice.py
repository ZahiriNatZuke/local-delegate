"""#663: `local_describe_image` says that a vision model does not measure.

The issue: a review subagent asked whether two stacked filter bars had their right-hand button
aligned, and the vision model said they did not; `getBoundingClientRect` gave the same x in both.
A second case asked whether a value wrapped to another line: the model said a `.wallet` value left
its «t» alone on the next line, and the DOM gave one line. An agent with only the image would have
reported both as defects. The fix is a guard by program, not a prompt change: when the question or
the answer speaks of alignment, pixels, sizes or line wraps, the answer ends with a notice that it
is an impression to be checked by measuring. The description of the tool says the same.
"""

from __future__ import annotations

import base64
import json

import backend_mock
import httpx2
import pytest

from local_delegate import config, i18n, server

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _notice() -> str:
    return server.WARNING_MARKER + i18n.t("mcp.warning.image_not_a_measurement") + "]"


@backend_mock.mock
def _describe(monkeypatch, tmp_path, answer: str, question: str | None = None) -> str:
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    path = tmp_path / "capture.png"
    path.write_bytes(_TINY_PNG)
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 20},
            },
        )
    )
    return server.local_describe_image(str(path), question=question)


def test_the_alignment_question_of_the_issue_gets_the_notice(monkeypatch, tmp_path):
    answer = "El botón «Exportar» de la barra de arriba no está alineado con el de la de abajo."
    output = _describe(
        monkeypatch,
        tmp_path,
        answer,
        question="¿Están alineados los elementos de las dos filas?",
    )
    # The answer is kept as it came; the notice goes after it.
    assert answer in output
    assert output.index(answer) < output.index(_notice())
    assert output.count(server.WARNING_MARKER) == 1


def test_the_wrap_claim_of_the_comment_gets_the_notice_without_a_question(monkeypatch, tmp_path):
    answer = "El valor nombre123.wallet se corta y deja la «t» sola en otra línea."
    assert _notice() in _describe(monkeypatch, tmp_path, answer)


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        (None, "The two buttons are misaligned by about 4 px."),
        (None, "Hay un desplazamiento de unos pocos píxeles entre las tarjetas."),
        ("Is the text wrapping?", "No."),
        ("¿Tienen la misma altura las dos barras?", "Sí."),
        (None, "The left column has the same width as the right one."),
        (None, "El espaciado entre los iconos es irregular."),
        # The wording of the comment of the issue, as the CHANGELOG quotes it.
        (None, "Un valor se partía en dos líneas."),
        ("¿Hay saltos de línea en la tabla?", "No."),
        (None, "The value breaks onto the next line."),
        (None, "The two buttons don't line up."),
        (None, "The title is not centered over the card."),
        (None, "La distancia entre los botones es mayor arriba."),
        (None, "The left card is wider than the right one."),
    ],
)
def test_measurement_words_in_question_or_answer_get_the_notice(
    monkeypatch, tmp_path, question, answer
):
    assert _notice() in _describe(monkeypatch, tmp_path, answer, question=question)


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        (None, "Una captura de un panel con una tabla de facturas y un botón azul «Exportar»."),
        ("¿Qué texto se lee en el título?", "«Resumen de ventas de octubre»."),
        (None, "A photo of a cat sleeping on a red sofa next to a window."),
        # Words that hold a term without speaking of a measurement.
        (None, "Una frase corta en la cabecera y una barra de desplazamiento a la derecha."),
        (None, "A wrapper div holds the malignant cell images."),
    ],
)
def test_a_description_that_does_not_measure_has_no_notice(monkeypatch, tmp_path, question, answer):
    output = _describe(monkeypatch, tmp_path, answer, question=question)
    assert server.WARNING_MARKER not in output
    assert answer in output


@backend_mock.mock
def test_a_backend_error_gets_no_notice(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "FALLBACK", False)
    path = tmp_path / "capture.png"
    path.write_bytes(_TINY_PNG)
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(500, json={"error": "boom"})
    )
    output = server.local_describe_image(str(path), question="¿Están alineados?")
    assert output.startswith(server.ERROR_PREFIX)
    assert server.WARNING_MARKER not in output


def test_the_prompt_is_not_changed(monkeypatch, tmp_path):
    # The guard is by program: the system prompt of the vision call stays as it was.
    sent: list[dict] = []

    @backend_mock.mock
    def _run():
        monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
        monkeypatch.setattr(config, "LOG_DIR", tmp_path)
        monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
        path = tmp_path / "capture.png"
        path.write_bytes(_TINY_PNG)

        def _handler(request: httpx2.Request) -> httpx2.Response:
            sent.append(json.loads(request.content))
            return httpx2.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )

        backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
        server.local_describe_image(str(path), question="¿Están alineados?")

    _run()
    system = sent[0]["messages"][0]["content"]
    expected = (
        server._guard("una respuesta en prosa clara sobre la imagen", 200)
        + server._response_language_clause()
    )
    assert system == expected


def test_the_description_says_it_does_not_measure():
    doc = server.local_describe_image.__doc__ or ""
    assert "alignment" in doc and "measure" in doc and "getBoundingClientRect" in doc
