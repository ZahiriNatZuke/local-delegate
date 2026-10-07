"""Idioma del mensaje de `local_commit_msg` (daemon-reparte-el-backend, REQ-044).

Medido en la tanda de afinidad del 2026-10-07: con un prompt que no pedía idioma, el 26B escribió 17
de 30 mensajes en inglés y Qwen3.6 6 de 30. Lo que se comprueba aquí es que la orden está en el
prompt de sistema de la llamada que REDACTA el mensaje —la única, o el reduce del map-reduce—, no
que el modelo la obedezca, que lo decide el modelo.

Cada test dice, en su docstring, qué mutante lo hace fallar y con qué assert: un test que no puede
fallar no comprueba nada.
"""

from __future__ import annotations

import json
import os

import backend_mock
import httpx2
import pytest

from local_delegate import config, server

VARIABLE = "LOCAL_DELEGATE_COMMIT_LANGUAGE"
DIFF_ORDER = "en el idioma predominante de los textos del diff"
SMALL_DIFF = "diff --git a/uno.py b/uno.py\n--- a/uno.py\n+++ b/uno.py\n@@ -1 +1 @@\n-a\n+b\n"


def _big_diff(files: int = 30, lines: int = 60) -> str:
    return "".join(
        f"diff --git a/paquete/mod{i}.py b/paquete/mod{i}.py\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/paquete/mod{i}.py\n"
        f"+++ b/paquete/mod{i}.py\n"
        f"@@ -1,{lines} +1,{lines} @@\n"
        + "".join(f"+linea {j} del modulo {i} con relleno de sobra\n" for j in range(lines))
        for i in range(files)
    )


@backend_mock.mock
def _request(monkeypatch, tmp_path, **kwargs) -> list[dict]:
    """Llama a `local_commit_msg` con el backend simulado y devuelve las peticiones vistas."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    views: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        views.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "feat: algo"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    server.local_commit_msg(**kwargs)
    return views


def _system(request: dict) -> str:
    return request["messages"][0]["content"]


def test_variable_is_in_env_inventory():
    """El aislamiento de la suite se alimenta de `config.VARIABLES_DE_ENTORNO`.

    Mutante: leerla con `os.environ.get` en vez de por `_env`. Dispara este assert (y, además, el
    guardián de `test_aislamiento_entorno.py`): la variable no queda en el inventario y la suite
    heredaría la de la máquina.
    """
    assert VARIABLE in config.VARIABLES_DE_ENTORNO


@pytest.mark.parametrize("style", ["conventional", "plain"])
def test_with_spanish_variable_prompt_asks_spanish(monkeypatch, tmp_path, style):
    """Mutante «no leer la variable» (`config.commit_language()` devuelve siempre `""`): dispara el
    primer assert, `en español.` no está en el system y sí la orden del idioma del diff."""
    monkeypatch.setenv(VARIABLE, "es")
    views = _request(monkeypatch, tmp_path, diff=SMALL_DIFF, style=style)

    assert len(views) == 1
    system = _system(views[0])
    assert "Escribe el mensaje de commit entero (primera línea y cuerpo) en español." in system
    assert DIFF_ORDER not in system


@pytest.mark.parametrize("style", ["conventional", "plain"])
def test_without_variable_prompt_asks_diff_language(monkeypatch, tmp_path, style):
    """Control de que la suite corre limpia, y mutante «quitar la rama» (siempre se arma la orden
    con nombre, o sea `en .` sin variable): dispara el primer assert."""
    assert VARIABLE not in os.environ
    views = _request(monkeypatch, tmp_path, diff=SMALL_DIFF, style=style)

    system = _system(views[0])
    assert (
        "Escribe el mensaje de commit entero (primera línea y cuerpo) "
        "en el idioma predominante de los textos del diff (comentarios, documentación y mensajes)."
    ) in system
    assert "en español" not in system


def test_each_style_format_stays_in_place(monkeypatch, tmp_path):
    """La orden se SUMA al formato; no lo sustituye ni lo parte (la guarda sigue siendo la misma)."""
    monkeypatch.setenv(VARIABLE, "es")
    conventional = _system(
        _request(monkeypatch, tmp_path, diff=SMALL_DIFF, style="conventional")[0]
    )
    plain = _system(_request(monkeypatch, tmp_path, diff=SMALL_DIFF, style="plain")[0])

    assert "Conventional Commits" in conventional
    assert "Conventional Commits" not in plain
    assert conventional.startswith("Responde directo desde el input.")
    assert "Nada fuera del formato." in conventional


@pytest.mark.parametrize(
    ("value", "name"),
    [
        ("es", "español"),
        ("EN", "inglés"),
        ("es-CU", "español"),
        ("pt_BR", "portugués"),
        (" fr ", "francés"),
        ("catalán", "catalán"),  # no está en el mapa: se usa tal cual
        ("ca", "ca"),
    ],
)
def test_code_translates_to_readable_name(monkeypatch, value, name):
    """Mutante: devolver siempre el valor crudo. Dispara el assert en `es`, `EN`, `es-CU`…"""
    monkeypatch.setenv(VARIABLE, value)
    assert server._commit_language_instruction().endswith(f" en {name}.")


def test_map_reduce_writes_in_requested_language_and_notes_lack_instruction(monkeypatch, tmp_path):
    """El reduce es quien escribe el mensaje: lleva la orden. El map produce notas intermedias.

    Mutante: pasar `_guard(fmt)` como `reduce_system`, o sea el reduce sin la orden. Dispara el
    primer assert (la orden de español no está en el system del último request).
    """
    monkeypatch.setenv(VARIABLE, "es")
    diff = _big_diff()
    assert len(diff) > config.max_chars_for_role("code"), "el diff tiene que exceder el techo"
    views = _request(monkeypatch, tmp_path, diff=diff)

    assert len(views) > 2
    order = "Escribe el mensaje de commit entero (primera línea y cuerpo) en español."
    assert order in _system(views[-1])
    # Los trozos del map describen archivos, no redactan el mensaje.
    assert all(order not in _system(v) for v in views[:-1])
    assert all("ni redactes ningún mensaje de commit todavía" in _system(v) for v in views[:-1])


def test_map_reduce_without_variable_asks_diff_language_in_final_write(monkeypatch, tmp_path):
    """Mutante «quitar la rama» en el camino del map-reduce: dispara este assert."""
    views = _request(monkeypatch, tmp_path, diff=_big_diff())

    assert len(views) > 2
    assert DIFF_ORDER in _system(views[-1])
    assert all(DIFF_ORDER not in _system(v) for v in views[:-1])
