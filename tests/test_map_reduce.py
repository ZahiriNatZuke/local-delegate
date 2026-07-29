"""Map-reduce de las tools de reducción (`local_summarize`, `local_lint_summary`).

Lo que se comprueba no es que el resumen sea bueno —eso lo decide el modelo— sino que el
documento entre **entero**: antes se truncaba a `max_chars_for(modelo)` y el resto se
descartaba con un aviso, que en un log de CI significa perderse justo los errores del final.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2

from local_delegate import config, server


def _document(sections: int, chars: int) -> str:
    return "\n\n".join(
        f"## Sección {i}\n\n" + ("contenido " * (chars // 10)) for i in range(sections)
    )


@backend_mock.mock
def _run(monkeypatch, tmp_path, fn, **kwargs):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "RESUMEN"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return fn(**kwargs), seen


def _events(tmp_path) -> list[dict]:
    """El log rota por mes (`usage-YYYYMM.jsonl`), así que se recoge cualquier JSONL del dir."""
    lineas = [
        line
        for archivo in sorted(tmp_path.glob("*.jsonl"))
        for line in archivo.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [json.loads(line) for line in lineas]


def test_documento_corto_sigue_haciendo_una_sola_llamada(monkeypatch, tmp_path):
    """Sin regresión: lo que ya cabía se resuelve igual que siempre."""
    _out, seen = _run(monkeypatch, tmp_path, server.local_summarize, text="hola mundo")
    assert len(seen) == 1
    assert _events(tmp_path)[0].get("chunks") in (None, 1)


def test_documento_que_no_cabe_se_resume_por_partes_sin_truncar(monkeypatch, tmp_path):
    limite = config.max_chars_for(config.MODEL_LONG)
    texto = _document(60, 2000)
    assert len(texto) > limite, "el documento de prueba tiene que exceder el techo del modelo"

    _out, seen = _run(monkeypatch, tmp_path, server.local_summarize, text=texto)

    # map (varias) + reduce (una): más de una llamada, y ninguna con el documento entero.
    assert len(seen) > 1
    for payload in seen:
        assert len(payload["messages"][1]["content"]) <= limite

    evento = _events(tmp_path)[0]
    assert evento["chunks"] == len(seen)
    assert evento["chars_in"] == len(texto)  # entró completo…
    assert evento["raw_len"] == len(texto)  # …y no se descartó nada
    assert not evento.get("truncated_in")


def test_el_ultimo_tramo_del_documento_llega_al_modelo(monkeypatch, tmp_path):
    """El final es justo lo que se perdía al truncar; en un log de CI es lo que importa."""
    texto = _document(60, 2000) + "\n\n## FINAL\n\nMARCA-DEL-FINAL"
    _out, seen = _run(monkeypatch, tmp_path, server.local_summarize, text=texto)
    enviado = "\n".join(p["messages"][1]["content"] for p in seen)
    assert "MARCA-DEL-FINAL" in enviado


def test_lint_summary_tambien_procesa_el_log_completo(monkeypatch, tmp_path):
    texto = _document(60, 2000) + "\n\nERROR-QUE-IMPORTA en el ultimo archivo"
    _out, seen = _run(monkeypatch, tmp_path, server.local_lint_summary, text=texto)
    enviado = "\n".join(p["messages"][1]["content"] for p in seen)
    assert "ERROR-QUE-IMPORTA" in enviado
    assert _events(tmp_path)[0]["chars_in"] == len(texto)


def test_un_fallo_del_backend_no_se_reporta_como_resumen_correcto(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    texto = _document(60, 2000)

    with backend_mock.mock:
        backend_mock.post("http://test-backend/v1/chat/completions").mock(
            return_value=httpx2.Response(500, json={"error": "boom"})
        )
        server.local_summarize(text=texto)

    assert _events(tmp_path)[0]["ok"] is False
