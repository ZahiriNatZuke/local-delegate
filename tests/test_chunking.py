"""Tests del chunking de salida (local_translate / local_delegate) y del origen del cómputo.

El caso que motivó el chunking: un documento de ~20k caracteres se procesaba en UNA llamada
con `max_tokens<=2048`, así que el backend devolvía la salida cortada y el usuario recibía
`[salida truncada]` a mitad del documento.
"""

from __future__ import annotations

import json
import threading

import backend_mock
import httpx2
import pytest

from local_delegate import config, server


# --- Partido por límites naturales -------------------------------------------
def _document(paragraphs: int = 12, size: int = 400) -> str:
    return "".join(f"## Sección {i}\n\n{'palabra ' * (size // 8)}\n\n" for i in range(paragraphs))


def _log_records(log_dir) -> list[dict]:
    """Eventos escritos, sin depender de si el log rota por mes o es fijo."""
    records: list[dict] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def test_chunk_text_preserves_the_document_exactly():
    text = _document()
    chunks = server._chunk_text(text, 1000)
    assert len(chunks) > 1
    assert "".join(chunks) == text  # invariante: no se pierde ni se inventa un solo carácter


def test_chunk_text_respects_the_size_limit():
    chunks = server._chunk_text(_document(20, 300), 1200)
    assert all(len(c) <= 1200 for c in chunks)


def test_chunk_text_cuts_on_markdown_headers_first():
    text = "# A\n\nuno\n\n# B\n\ndos\n\n# C\n\ntres\n"
    chunks = server._chunk_text(text, 12)
    assert [c.startswith("#") for c in chunks] == [True] * len(chunks)


def test_chunk_text_falls_back_to_paragraphs_then_lines():
    parrafos = "uno " * 30 + "\n\n" + "dos " * 30 + "\n\n"
    assert len(server._chunk_text(parrafos, 130)) > 1
    lineas = "".join(f"linea {i} con texto\n" for i in range(40))
    chunks = server._chunk_text(lineas, 100)
    assert all(c.endswith("\n") for c in chunks)


def test_chunk_text_hard_splits_when_there_is_no_natural_boundary():
    blob = "x" * 5000
    chunks = server._chunk_text(blob, 1000)
    assert len(chunks) == 5
    assert "".join(chunks) == blob


def test_short_text_is_a_single_chunk():
    assert server._chunk_text("corto", 1000) == ["corto"]


def test_reattach_separator_keeps_paragraph_and_line_seams():
    assert server._reattach_separator("uno\n\n", " UNO ") == "UNO\n\n"
    assert server._reattach_separator("item\n", "ITEM") == "ITEM\n"
    assert server._reattach_separator("final", "FINAL") == "FINAL"


# --- Ejecución por trozos -----------------------------------------------------
@backend_mock.mock
def _run_translate(monkeypatch, tmp_path, text: str, *, finish_reason: str = "stop"):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        # devuelve el trozo recibido con una marca, para poder comprobar el orden final
        content = payload["messages"][1]["content"].split(":\n\n", 1)[-1]
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "[T] " + content}, "finish_reason": finish_reason}
                ]
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    result = server.local_translate("inglés", text=text)
    return result, seen


def test_long_document_is_translated_in_several_calls_and_comes_back_whole(monkeypatch, tmp_path):
    text = _document(30, 800)  # ~24k chars: antes salía cortado en una sola llamada
    result, seen = _run_translate(monkeypatch, tmp_path, text)

    assert len(seen) > 1, "el documento largo debería partirse en varias llamadas"
    assert all(p["max_tokens"] <= config.CHUNK_MAX_TOKENS for p in seen)
    assert "[local-delegate aviso: salida truncada" not in result
    # cada trozo aporta su parte, en orden
    assert result.count("[T]") == len(seen)
    assert result.index("Sección 0") < result.index("Sección 29")


def test_chunked_call_logs_one_event_with_the_chunk_count(monkeypatch, tmp_path):
    _result, seen = _run_translate(monkeypatch, tmp_path, _document(30, 800))
    lines = _log_records(tmp_path)
    assert len(lines) == 1, "una operación por chunks es UN evento, no N"
    assert lines[0]["chunks"] == len(seen)
    assert lines[0]["tool"] == "local_translate"
    assert lines[0]["ok"] is True


def test_short_translation_still_uses_a_single_call_without_chunks_field(monkeypatch, tmp_path):
    _result, seen = _run_translate(monkeypatch, tmp_path, "hola mundo")
    assert len(seen) == 1
    record = _log_records(tmp_path)[0]
    assert "chunks" not in record


@backend_mock.mock
def test_backend_error_in_a_chunk_aborts_and_reports(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    calls = {"n": 0}

    def _handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] >= 2:
            return httpx2.Response(500, text="boom")
        return httpx2.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    result = server.local_translate("inglés", text=_document(20, 600))
    assert "[local-delegate error]" in result
    record = _log_records(tmp_path)[0]
    assert record["ok"] is False


@backend_mock.mock
def test_local_delegate_chunk_off_does_a_single_call(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    long_input = _document(30, 800)
    server.local_delegate("Reescribe", long_input, "texto", chunk="off")
    assert len(seen) == 1
    seen.clear()
    server.local_delegate("Reescribe", long_input, "texto")  # auto
    assert len(seen) > 1


def test_local_delegate_rejects_an_invalid_chunk_mode():
    assert "chunk inválido" in server.local_delegate("t", "i", "f", chunk="quizá")


# --- Origen del cómputo (local vs remoto) ------------------------------------
@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:9292/v1", "local"),
        ("http://localhost:11434/v1", "local"),
        ("http://[::1]:9292/v1", "local"),
        ("https://pc.tailnet.ts.net:9292/v1", "remote"),
        ("http://192.168.1.50:9292/v1", "remote"),
    ],
)
def test_backend_origin_classifies_by_host(url, expected):
    assert config.backend_origin(url) == expected


def test_backend_host_drops_scheme_and_path():
    assert config.backend_host("https://pc.ts.net:9292/v1") == "pc.ts.net:9292"


@pytest.mark.parametrize("override", ["local", "remote"])
def test_backend_origin_override_gana_a_la_heuristica(monkeypatch, override):
    """El caso del túnel: `ssh -L 9292:...` enseña un backend remoto en 127.0.0.1."""
    monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", override)
    assert config.backend_origin("http://127.0.0.1:9292/v1") == override
    assert config.backend_origin("https://pc.ts.net:9292/v1") == override


@pytest.mark.parametrize("value", ["auto", "", "AUTO", "sí", "1"])
def test_backend_origin_cae_a_la_heuristica_si_el_override_no_sirve(monkeypatch, value):
    """Una errata en la variable no debe romper el arranque ni mentir: se deduce por host."""
    monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", value)
    assert config.backend_origin("http://127.0.0.1:9292/v1") == "local"
    assert config.backend_origin("https://pc.ts.net:9292/v1") == "remote"


@backend_mock.mock
def test_log_records_where_the_inference_ran(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "https://pc.ts.net:9292/v1")
    backend_mock.post("https://pc.ts.net:9292/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )
    )
    server._chat(config.MODEL_MECHANICAL, "s", "u", max_tokens=8)
    record = _log_records(tmp_path)[0]
    assert record["backend"] == "remote"
    assert record["backend_host"] == "pc.ts.net:9292"


# --- Inflight: progreso por trozos y robustez multiproceso --------------------
def test_inflight_reports_chunk_progress(tmp_path, monkeypatch):
    """El panel 'En curso' ve la delegación mientras corre, con el trozo actual."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    text = _document(20, 600)
    expected_chunks = len(server._chunk_text(text, config.CHUNK_CHARS))
    assert expected_chunks > 2, "el documento de prueba tiene que partirse en varios trozos"

    in_call = threading.Event()
    resume = threading.Event()
    calls = {"n": 0}

    def _blocking_post(_model, _payload):
        calls["n"] += 1
        if calls["n"] == 2:  # bloquea a mitad de la operación para poder observarla
            in_call.set()
            resume.wait(timeout=5)
        return server.ChatResult(text="ok", ok=True, finish_reason="stop")

    monkeypatch.setattr(server, "_post_chat", _blocking_post)
    worker = threading.Thread(
        target=server.local_translate, args=("inglés",), kwargs={"text": text}
    )
    worker.start()
    assert in_call.wait(timeout=5)
    snapshot = server.inflight_snapshot()
    resume.set()
    worker.join(timeout=10)

    assert len(snapshot) == 1
    entry = snapshot[0]
    assert entry["tool"] == "local_translate"
    assert entry["chunks"] == expected_chunks
    assert entry["chunk"] == 2  # va por el segundo trozo
    assert entry["backend"] in {"local", "remote"}
    assert server.inflight_snapshot() == []  # se limpia al terminar


def test_inflight_snapshot_does_not_rewrite_the_file_when_nothing_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=1)
    path = server._inflight_file()
    before = path.stat().st_mtime_ns
    for _ in range(3):
        assert len(server.inflight_snapshot()) == 1
    assert path.stat().st_mtime_ns == before, "sondear no debe reescribir el archivo compartido"
    server._inflight_end(entry_id)
    assert server.inflight_snapshot() == []


def test_inflight_temp_file_is_per_process(tmp_path, monkeypatch):
    """El temporal lleva el pid: dos procesos escribiendo a la vez no se pisan."""
    import os

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = server._inflight_start(tool="t", model="m", source="inline", chars_in=1)
    assert not (tmp_path / "inflight.json.tmp").exists()
    assert not list(tmp_path.glob("inflight.json.*.tmp"))  # se limpia tras el replace
    assert (
        f"{os.getpid()}:"
        in json.loads((tmp_path / "inflight.json").read_text(encoding="utf-8")).popitem()[0]
    )
    server._inflight_end(entry_id)


def test_inflight_prunes_entries_of_dead_processes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    path = tmp_path / "inflight.json"
    path.write_text(
        json.dumps(
            {
                "999999:1": {
                    "tool": "local_summarize",
                    "model": "m",
                    "source": "path",
                    "chars_in": 10,
                    "started_at": 1.0,
                    "pid": 999999,
                }
            }
        ),
        encoding="utf-8",
    )
    assert server.inflight_snapshot() == []
    assert json.loads(path.read_text(encoding="utf-8")) == {}


# --- Partido de diffs por archivo (local_commit_msg) -------------------------
# Un diff no tiene headers Markdown, así que sin un splitter propio caía a párrafos: medido
# sobre un diff real de 44 archivos, 1 de 11 trozos empezaba en frontera de archivo y los otros
# arrancaban a mitad de hunk, con líneas `+` cuya cabecera quedó en el trozo anterior.
def _diff(archivos: int = 6, lineas: int = 40) -> str:
    return "".join(
        f"diff --git a/src/mod{i}.py b/src/mod{i}.py\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/src/mod{i}.py\n"
        f"+++ b/src/mod{i}.py\n"
        f"@@ -1,{lineas} +1,{lineas} @@\n"
        + "".join(f"+linea {j} del modulo {i} con relleno suficiente\n" for j in range(lineas))
        for i in range(archivos)
    )


def test_diff_se_parte_solo_en_fronteras_de_archivo():
    texto = _diff(archivos=6, lineas=10)
    # Cada archivo cabe holgadamente en el presupuesto: si aquí se partiera dentro de uno sería
    # por el splitter, no porque no quedara más remedio.
    assert len(texto) // 6 < 900
    trozos = server._chunk_text(texto, 900)
    assert len(trozos) > 1, "el diff de prueba tiene que dar más de un trozo"
    assert all(t.lstrip().startswith("diff --git ") for t in trozos)


def test_el_partido_de_un_diff_no_pierde_ni_inventa_nada():
    texto = _diff(archivos=6, lineas=10)
    assert "".join(server._chunk_text(texto, 900)) == texto


def test_un_archivo_mas_grande_que_el_presupuesto_se_subdivide_sin_perder_contenido():
    """REQ-002 admite partir dentro de un archivo solo cuando él solo excede el presupuesto."""
    texto = _diff(archivos=1, lineas=200)
    trozos = server._chunk_text(texto, 900)
    assert len(trozos) > 1
    assert "".join(trozos) == texto


def test_un_markdown_con_un_diff_embebido_se_sigue_partiendo_por_headers():
    """El splitter de diff se autoinhibe: no puede degradar translate/summarize sobre docs."""

    def seccion(i: int) -> str:
        return f"## Seccion {i}\n\n" + ("palabra " * 60) + "\n\n"

    texto = (
        seccion(1)
        + seccion(2)
        + "## Con diff\n\n```\ndiff --git a/x b/x\n--- a/x\n+++ b/x\n+una linea\n```\n\n"
        + seccion(3)
    )
    trozos = server._chunk_text(texto, 600)
    assert len(trozos) > 1
    assert all(t.lstrip().startswith("##") for t in trozos)


def test_en_un_diff_git_no_se_corta_por_las_cabeceras_de_archivo():
    """Cada archivo trae también su `--- a/x`: cortar por ahí lo partiría en dos."""
    piezas = server._split_by_diff_files(_diff(archivos=3, lineas=2))
    assert len(piezas) == 3
    assert all(p.startswith("diff --git ") for p in piezas)


def test_un_diff_sin_git_se_parte_por_la_cabecera_clasica():
    texto = (
        "--- viejo/a.txt\n+++ nuevo/a.txt\n@@ -1 +1 @@\n-uno\n+dos\n"
        "--- viejo/b.txt\n+++ nuevo/b.txt\n@@ -1 +1 @@\n-tres\n+cuatro\n"
    )
    piezas = server._split_by_diff_files(texto)
    assert len(piezas) == 2
    assert "".join(piezas) == texto
