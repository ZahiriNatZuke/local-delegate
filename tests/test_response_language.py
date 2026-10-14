"""El idioma en que las tools de texto libre piden responder al modelo (ola B2b-2; REQ-028, REQ-041).

Una sola regla, `i18n.response_language()`: `LOCAL_DELEGATE_OUTPUT_LANGUAGE` si vale y, si no, el
idioma vigente. La orden va DETRÁS de `_guard` (los prompts no se traducen) en `local_summarize`,
`local_lint_summary`, `local_explain_code` y `local_describe_image`, también en cada paso del
troceado; `local_commit_msg` tiene su propia regla (`tests/test_commit_language.py`). Los prompts se
capturan con un backend falso (`_run_chat` doblado), sin red.

Además: el idioma de respuesta en `local_status` y `doctor`, la versión `v` de las filas de uso y
el lector de fronteras de medición (`scripts/measurement_boundaries.py`).
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from local_delegate import config, doctor, i18n, server

ROOT = Path(__file__).parents[1]
OUTPUT = "LOCAL_DELEGATE_OUTPUT_LANGUAGE"
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _order(name: str) -> str:
    return f" Responde en {name}, aunque el contenido esté en otro idioma."


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    """Los `system` y `user` de cada llamada al backend, sin red ni log."""
    calls: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        result = server.ChatResult(text="resumen", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    return calls


def _single_calls(tmp_path) -> dict[str, list[dict]]:
    """Una llamada de cada una de las 4 tools; devuelve sus prompts por tool."""
    image = tmp_path / "x.png"
    image.write_bytes(_PNG)
    return {
        "local_summarize": lambda: server.local_summarize(text="texto corto"),
        "local_lint_summary": lambda: server.local_lint_summary(text="E1 fallo"),
        "local_explain_code": lambda: server.local_explain_code(code="x = 1"),
        "local_describe_image": lambda: server.local_describe_image(path=str(image)),
    }


@pytest.mark.parametrize(("value", "name"), [("fr", "francés"), ("português", "português")])
def test_the_output_variable_reaches_the_four_tools(monkeypatch, tmp_path, captured, value, name):
    """Mutante «ignorar la variable»: la orden pide español y falla el `endswith`."""
    monkeypatch.setenv(OUTPUT, value)
    for tool, call in _single_calls(tmp_path).items():
        captured.clear()
        call()
        assert len(captured) == 1, tool
        assert captured[0]["system"].endswith(_order(name)), tool


@pytest.mark.parametrize(("lang", "name"), [("es", "español"), ("en", "inglés")])
def test_without_the_variable_the_order_follows_the_current_language(
    monkeypatch, tmp_path, captured, lang, name
):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()
    for tool, call in _single_calls(tmp_path).items():
        captured.clear()
        call()
        assert captured[0]["system"].endswith(_order(name)), tool


@pytest.mark.parametrize("invalid", ["a\nb", "x" * 41, "   "])
def test_an_invalid_variable_falls_back_to_the_current_language(
    monkeypatch, tmp_path, captured, invalid
):
    monkeypatch.setenv(OUTPUT, invalid)
    for tool, call in _single_calls(tmp_path).items():
        captured.clear()
        call()
        assert captured[0]["system"].endswith(_order("español")), tool


def _summarize_in_chunks():
    return server.local_summarize(text="Un párrafo de texto corriente para resumir.\n\n" * 80)


def _structured_in_chunks():
    sections = "".join(f"## Parte {i}\n\n" + "Texto de la parte. " * 60 + "\n\n" for i in range(12))
    return server.local_summarize(text="# Documento\n\n" + sections)


def _lint_in_chunks():
    return server.local_lint_summary(text="tests/x.py:1: E1 fallo de prueba\n" * 120)


@pytest.mark.parametrize(
    "call", [_summarize_in_chunks, _structured_in_chunks, _lint_in_chunks], ids=lambda c: c.__name__
)
def test_the_order_is_in_every_step_of_the_chunking(monkeypatch, captured, call):
    """REQ-028: en el troceado la orden va en CADA paso, no solo en el de reducción. Mutante «solo
    en el reduce»: la primera llamada del map no la lleva y falla el `all`."""
    monkeypatch.setenv(OUTPUT, "fr")
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", True)
    call()
    assert len(captured) > 2  # guarda: de verdad troceó y redujo
    assert all(c["system"].endswith(_order("francés")) for c in captured), [
        c["system"][-60:] for c in captured
    ]


def test_the_other_tools_do_not_get_the_order(monkeypatch, captured):
    """Solo las 4 de texto libre. Mutante «la orden dentro de `_guard`»: la llevarían todas."""
    monkeypatch.setenv(OUTPUT, "fr")
    server.local_translate(target_lang="inglés", text="hola")
    server.local_classify(text="hola", labels=["a", "b"])
    server.local_extract(fields=["a"], text="a=1")
    server.local_delegate(task="t", input="i", output_format="f")
    assert captured and all("Responde en francés" not in c["system"] for c in captured)


# --- local_status y doctor ------------------------------------------------------------------------


def test_status_and_doctor_show_the_response_language_and_its_source(monkeypatch):
    monkeypatch.setenv(OUTPUT, "português")
    status = "\n".join(server._describe_language())
    head = "\n".join(doctor.language_lines())
    assert "Idioma de respuesta del modelo: português (variable de salida)" in status
    assert "Respuesta:        português (variable de salida)" in head
    monkeypatch.delenv(OUTPUT)
    status = "\n".join(server._describe_language())
    assert "Idioma de respuesta del modelo: es (variable)" in status


def test_status_and_doctor_warn_about_an_invalid_variable(monkeypatch):
    """Control: sin el aviso de `response_language_lines`, la línea no sale y falla."""
    monkeypatch.setenv(OUTPUT, "a\nb")
    status = "\n".join(server._describe_language())
    head = "\n".join(doctor.language_lines())
    for text in (status, head):
        assert "tiene saltos de línea o caracteres de control y se ignora" in text
    monkeypatch.setenv(OUTPUT, "x" * 41)
    assert "pasa de 40 caracteres y se ignora" in "\n".join(server._describe_language())


# --- REQ-041: la versión `v` de cada fila y las fronteras ------------------------------------------------------


def test_usage_rows_carry_the_version_in_v(tmp_path):
    """REQ-041 decide la frontera con `v` (desde F1): no hay una segunda clave con el mismo dato."""
    server._log_event(
        tool="local_summarize",
        model="m",
        source="inline",
        chars_in=1,
        chars_out=1,
        latency_ms=1,
        ok=True,
        error=None,
        finish_reason="stop",
    )
    (row,) = [json.loads(line) for line in server._current_log_path().read_text().splitlines()]
    assert row["v"] == server._get_version()
    assert "package_version" not in row


def _boundaries():
    spec = importlib.util.spec_from_file_location(
        "measurement_boundaries", ROOT / "scripts" / "measurement_boundaries.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measurement_boundaries"] = module
    spec.loader.exec_module(module)
    return module


def test_the_boundary_is_decided_by_version_not_by_date():
    """Dos máquinas: una fila con versión vieja y fecha posterior, y una sin versión y fecha
    posterior, caen en «antes». Control: clasificar por fecha hace fallar las dos."""
    mb = _boundaries()
    boundaries = mb.load()
    assert boundaries["package_version_after"] == "0.36.0"
    late = "2027-01-01T00:00:00+00:00"
    assert mb.usage_side({"ts": late, "v": "0.35.0"}, boundaries) == mb.BEFORE
    assert mb.usage_side({"ts": late}, boundaries) == mb.BEFORE
    early = "2026-01-01T00:00:00+00:00"
    assert mb.usage_side({"ts": early, "v": "0.36.0"}, boundaries) == mb.AFTER
    assert mb.usage_side({"ts": early, "v": "0.37.1"}, boundaries) == mb.AFTER


def test_without_the_hook_hashes_file_the_set_is_empty(tmp_path):
    """El fichero de hashes lo crea B3; hasta entonces el lector no falla y no hay frontera."""
    mb = _boundaries()
    assert mb.hook_hashes_after(mb.load(), root=tmp_path) == {}
