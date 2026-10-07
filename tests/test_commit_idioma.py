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

VARIABLE = "LOCAL_DELEGATE_COMMIT_IDIOMA"
ORDEN_DEL_DIFF = "en el idioma predominante de los textos del diff"
DIFF_CHICO = "diff --git a/uno.py b/uno.py\n--- a/uno.py\n+++ b/uno.py\n@@ -1 +1 @@\n-a\n+b\n"


def _diff_grande(archivos: int = 30, lineas: int = 60) -> str:
    return "".join(
        f"diff --git a/paquete/mod{i}.py b/paquete/mod{i}.py\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/paquete/mod{i}.py\n"
        f"+++ b/paquete/mod{i}.py\n"
        f"@@ -1,{lineas} +1,{lineas} @@\n"
        + "".join(f"+linea {j} del modulo {i} con relleno de sobra\n" for j in range(lineas))
        for i in range(archivos)
    )


@backend_mock.mock
def _pedir(monkeypatch, tmp_path, **kwargs) -> list[dict]:
    """Llama a `local_commit_msg` con el backend simulado y devuelve las peticiones vistas."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    vistas: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        vistas.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "feat: algo"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    server.local_commit_msg(**kwargs)
    return vistas


def _system(peticion: dict) -> str:
    return peticion["messages"][0]["content"]


def test_la_variable_entra_en_el_inventario_del_entorno():
    """El aislamiento de la suite se alimenta de `config.VARIABLES_DE_ENTORNO`.

    Mutante: leerla con `os.environ.get` en vez de por `_env`. Dispara este assert (y, además, el
    guardián de `test_aislamiento_entorno.py`): la variable no queda en el inventario y la suite
    heredaría la de la máquina.
    """
    assert VARIABLE in config.VARIABLES_DE_ENTORNO


@pytest.mark.parametrize("estilo", ["conventional", "plain"])
def test_con_la_variable_en_es_el_prompt_pide_espanol(monkeypatch, tmp_path, estilo):
    """Mutante «no leer la variable» (`config.commit_idioma()` devuelve siempre `""`): dispara el
    primer assert, `en español.` no está en el system y sí la orden del idioma del diff."""
    monkeypatch.setenv(VARIABLE, "es")
    vistas = _pedir(monkeypatch, tmp_path, diff=DIFF_CHICO, style=estilo)

    assert len(vistas) == 1
    system = _system(vistas[0])
    assert "Escribe el mensaje de commit entero (primera línea y cuerpo) en español." in system
    assert ORDEN_DEL_DIFF not in system


@pytest.mark.parametrize("estilo", ["conventional", "plain"])
def test_sin_la_variable_el_prompt_pide_el_idioma_del_diff(monkeypatch, tmp_path, estilo):
    """Control de que la suite corre limpia, y mutante «quitar la rama» (siempre se arma la orden
    con nombre, o sea `en .` sin variable): dispara el primer assert."""
    assert VARIABLE not in os.environ
    vistas = _pedir(monkeypatch, tmp_path, diff=DIFF_CHICO, style=estilo)

    system = _system(vistas[0])
    assert (
        "Escribe el mensaje de commit entero (primera línea y cuerpo) "
        "en el idioma predominante de los textos del diff (comentarios, documentación y mensajes)."
    ) in system
    assert "en español" not in system


def test_el_formato_de_cada_estilo_sigue_donde_estaba(monkeypatch, tmp_path):
    """La orden se SUMA al formato; no lo sustituye ni lo parte (la guarda sigue siendo la misma)."""
    monkeypatch.setenv(VARIABLE, "es")
    conventional = _system(_pedir(monkeypatch, tmp_path, diff=DIFF_CHICO, style="conventional")[0])
    plain = _system(_pedir(monkeypatch, tmp_path, diff=DIFF_CHICO, style="plain")[0])

    assert "Conventional Commits" in conventional
    assert "Conventional Commits" not in plain
    assert conventional.startswith("Responde directo desde el input.")
    assert "Nada fuera del formato." in conventional


@pytest.mark.parametrize(
    ("valor", "nombre"),
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
def test_el_codigo_se_traduce_a_un_nombre_legible(monkeypatch, valor, nombre):
    """Mutante: devolver siempre el valor crudo. Dispara el assert en `es`, `EN`, `es-CU`…"""
    monkeypatch.setenv(VARIABLE, valor)
    assert server._orden_de_idioma_de_commit().endswith(f" en {nombre}.")


def test_el_map_reduce_redacta_en_el_idioma_pedido_y_las_notas_no_llevan_la_orden(
    monkeypatch, tmp_path
):
    """El reduce es quien escribe el mensaje: lleva la orden. El map produce notas intermedias.

    Mutante: pasar `_guard(fmt)` como `reduce_system`, o sea el reduce sin la orden. Dispara el
    primer assert (la orden de español no está en el system del último request).
    """
    monkeypatch.setenv(VARIABLE, "es")
    diff = _diff_grande()
    assert len(diff) > config.max_chars_for_role("code"), "el diff tiene que exceder el techo"
    vistas = _pedir(monkeypatch, tmp_path, diff=diff)

    assert len(vistas) > 2
    orden = "Escribe el mensaje de commit entero (primera línea y cuerpo) en español."
    assert orden in _system(vistas[-1])
    # Los trozos del map describen archivos, no redactan el mensaje.
    assert all(orden not in _system(v) for v in vistas[:-1])
    assert all("ni redactes ningún mensaje de commit todavía" in _system(v) for v in vistas[:-1])


def test_el_map_reduce_sin_variable_pide_el_idioma_del_diff_en_la_redaccion_final(
    monkeypatch, tmp_path
):
    """Mutante «quitar la rama» en el camino del map-reduce: dispara este assert."""
    vistas = _pedir(monkeypatch, tmp_path, diff=_diff_grande())

    assert len(vistas) > 2
    assert ORDEN_DEL_DIFF in _system(vistas[-1])
    assert all(ORDEN_DEL_DIFF not in _system(v) for v in vistas[:-1])
