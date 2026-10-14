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
    lines = [
        line
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [json.loads(line) for line in lines]


def test_short_document_still_makes_a_single_call(monkeypatch, tmp_path):
    """Sin regresión: lo que ya cabía se resuelve igual que siempre."""
    _out, seen = _run(monkeypatch, tmp_path, server.local_summarize, text="hola mundo")
    assert len(seen) == 1
    assert _events(tmp_path)[0].get("chunks") in (None, 1)


def test_document_that_does_not_fit_is_summarized_in_parts_without_truncating(
    monkeypatch, tmp_path
):
    limit = config.max_chars_for_role("long")
    text = _document(60, 2000)
    assert len(text) > limit, "el documento de prueba tiene que exceder el techo del modelo"

    _out, seen = _run(monkeypatch, tmp_path, server.local_summarize, text=text)

    # map (varias) + reduce (una): más de una llamada, y ninguna con el documento entero.
    assert len(seen) > 1
    for payload in seen:
        assert len(payload["messages"][1]["content"]) <= limit

    event = _events(tmp_path)[0]
    assert event["chunks"] == len(seen)
    assert event["chars_in"] == len(text)  # entró completo…
    assert event["raw_len"] == len(text)  # …y no se descartó nada
    assert not event.get("truncated_in")


def test_the_last_stretch_of_the_document_reaches_the_model(monkeypatch, tmp_path):
    """El final es justo lo que se perdía al truncar; en un log de CI es lo que importa."""
    text = _document(60, 2000) + "\n\n## FINAL\n\nEND-MARK"
    _out, seen = _run(monkeypatch, tmp_path, server.local_summarize, text=text)
    sent = "\n".join(p["messages"][1]["content"] for p in seen)
    assert "END-MARK" in sent


def test_lint_summary_also_processes_the_whole_log(monkeypatch, tmp_path):
    text = _document(60, 2000) + "\n\nERROR-THAT-MATTERS en el ultimo archivo"
    _out, seen = _run(monkeypatch, tmp_path, server.local_lint_summary, text=text)
    sent = "\n".join(p["messages"][1]["content"] for p in seen)
    assert "ERROR-THAT-MATTERS" in sent
    assert _events(tmp_path)[0]["chars_in"] == len(text)


def test_a_backend_failure_is_not_reported_as_a_correct_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    text = _document(60, 2000)

    with backend_mock.mock:
        backend_mock.post("http://test-backend/v1/chat/completions").mock(
            return_value=httpx2.Response(500, json={"error": "boom"})
        )
        server.local_summarize(text=text)

    assert _events(tmp_path)[0]["ok"] is False


# --- local_commit_msg: el diff entra entero ----------------------------------
# Reportado desde un cliente remoto: para un diff de 71k chars la tool devolvió
# `docs: update angular agents documentation`, o sea el primer archivo por orden alfabético de
# rutas. Reproducido aquí con un diff de 164 585 chars: veía 20 027 y los otros 144 558 se
# descartaban con un aviso que parecía inocuo.
def _large_diff(files: int = 30, lines: int = 60) -> str:
    return "".join(
        f"diff --git a/paquete/mod{i}.py b/paquete/mod{i}.py\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/paquete/mod{i}.py\n"
        f"+++ b/paquete/mod{i}.py\n"
        f"@@ -1,{lines} +1,{lines} @@\n"
        + "".join(f"+linea {j} del modulo {i} con relleno de sobra\n" for j in range(lines))
        for i in range(files)
    )


def test_a_diff_that_does_not_fit_goes_in_whole_without_truncating(monkeypatch, tmp_path):
    limit = config.max_chars_for_role("code")
    diff = _large_diff()
    assert len(diff) > limit, "el diff de prueba tiene que exceder el techo del modelo"

    output, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)

    assert len(seen) > 1  # map (varias) + reduce (una)
    event = _events(tmp_path)[0]
    assert event["chunks"] == len(seen)
    assert event["chars_in"] == len(diff)  # entró completo…
    assert not event.get("truncated_in")  # …y no se descartó nada
    assert "entrada truncada" not in output


def test_the_last_file_of_the_diff_reaches_the_model(monkeypatch, tmp_path):
    """Lo que se perdía al truncar: `src/` va al final por orden alfabético de rutas."""
    diff = _large_diff() + (
        "diff --git a/zzz/ultimo.py b/zzz/ultimo.py\n--- a/zzz/ultimo.py\n+++ b/zzz/ultimo.py\n"
        "@@ -1 +1 @@\n+LAST-FILE-MARK\n"
    )
    _output, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)
    sent = "\n".join(p["messages"][1]["content"] for p in seen)
    assert "LAST-FILE-MARK" in sent


def test_the_step_that_drafts_the_message_receives_the_full_inventory(monkeypatch, tmp_path):
    """REQ-003: el reduce ve la lista COMPLETA de archivos, no solo los de su último trozo."""
    diff = _large_diff()
    _output, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)

    reduce = seen[-1]["messages"][1]["content"]
    assert "30 en total" in reduce
    # El inventario nombra tanto el primer archivo como el último: es lo que impide que el
    # mensaje se redacte sobre el principio del diff.
    assert "paquete/mod0.py" in reduce
    assert "paquete/mod29.py" in reduce


def test_the_message_says_how_much_it_was_drafted_from(monkeypatch, tmp_path):
    """REQ-007: sin esto, procesar de más o de menos vuelve a ser invisible."""
    diff = _large_diff()
    output, _seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)
    assert "30 archivos" in output
    assert f"{len(diff)} chars" in output  # REQ-026: sin separador de miles


def test_a_small_diff_still_makes_a_single_call(monkeypatch, tmp_path):
    """Sin regresión: lo que ya cabía se resuelve igual que siempre, y sin nota de alcance."""
    diff = "diff --git a/uno.py b/uno.py\n--- a/uno.py\n+++ b/uno.py\n@@ -1 +1 @@\n-a\n+b\n"
    output, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)
    assert len(seen) == 1
    assert _events(tmp_path)[0].get("chunks") in (None, 1)
    assert "alcance:" not in output


def test_an_empty_diff_is_not_sent_to_the_model(monkeypatch, tmp_path):
    output, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff="   \n  ")
    assert output.startswith("[local-delegate error]")
    assert seen == []


def test_a_chunk_that_does_not_fit_in_tokens_is_retried_split(monkeypatch, tmp_path):
    """El presupuesto de troceado está en chars y el límite del modelo en tokens.

    Medido contra el backend real: la prosa de un `.md` da 3,12 chars/token y `uv.lock` —hashes
    y URLs— da 1,57, así que el mismo presupuesto que sirve para un documento revienta con otro.
    Once trozos pasaron y el doceavo, el de `uv.lock`, mandó 15 750 chars = 10 193 tokens contra
    8 192 de contexto. El que manda tiene que ser el límite real, no la estimación.
    """
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    diff = _large_diff()
    seen: list[int] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        content = json.loads(request.content)["messages"][1]["content"]
        seen.append(len(content))
        # El backend rechaza cualquier envío por encima de este tamaño, como haría un modelo
        # cuyo contexto real es menor que el presupuesto en chars.
        if len(content) > 9_000:
            return httpx2.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "request (10193 tokens) exceeds the available context size "
                        "(8192 tokens), try increasing it",
                        "type": "exceed_context_size_error",
                    }
                },
            )
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "PARTE"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    with backend_mock.mock:
        backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
        output = server.local_commit_msg(diff=diff)

    assert not output.startswith("[local-delegate error]"), output
    assert any(length > 9_000 for length in seen), "el test no llegó a provocar ningún desborde"
    assert _events(tmp_path)[0]["ok"] is True


def test_an_overflow_that_cannot_be_split_is_still_an_error(monkeypatch, tmp_path):
    """Control: el reintento no puede convertir un fallo real en un resultado que parezca bueno."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    calls: list[int] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(len(json.loads(request.content)["messages"][1]["content"]))
        return httpx2.Response(
            400, json={"error": {"message": "exceeds the available context size (8192 tokens)"}}
        )

    with backend_mock.mock:
        backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
        output = server.local_commit_msg(diff=_large_diff())

    assert output.startswith("[local-delegate error]")
    assert _events(tmp_path)[0]["ok"] is False
    # Sin esto el test pasaría igual sin reintento ninguno, o sea no comprobaría lo que dice:
    # tiene que haberse reintentado —con envíos más pequeños— y AUN ASÍ reportar el error.
    assert len(calls) > 1
    assert min(calls) < max(calls)


def test_the_map_names_the_real_files_of_each_chunk(monkeypatch, tmp_path):
    """Medido: con el formato descrito como plantilla, el modelo devolvía `- ruta: qué cambió`.

    Anclar el prompt con las rutas reales —que se saben sin preguntarle a nadie— quita la
    plantilla que se podía copiar.
    """
    _output, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=_large_diff())
    first_map = seen[0]["messages"][1]["content"]
    # Las rutas están dentro del propio diff, así que buscarlas en el prompt entero no
    # distinguiría nada: se mira el ENCABEZADO, o sea lo que se añadió delante del fragmento.
    header_text = first_map.split("Di qué cambia en este fragmento")[0]
    assert "Archivos de este fragmento:" in header_text
    assert "paquete/mod0.py" in header_text
    # Y el system ya no lleva una plantilla que se pueda devolver copiada.
    assert "qué cambió y para qué" not in seen[0]["messages"][0]["content"]


def test_a_continuation_chunk_says_which_file_it_belongs_to(monkeypatch, tmp_path):
    """Un archivo mayor que el presupuesto se subdivide y las piezas 2..N no llevan cabecera.

    Sin decirlo, el modelo inventa la ruta: medido, devolvió `- ruta: archivo.py`.
    """
    # Un solo archivo, lo bastante grande como para que haya que partirlo.
    large = (
        "diff --git a/paquete/enorme.py b/paquete/enorme.py\n"
        "--- a/paquete/enorme.py\n+++ b/paquete/enorme.py\n@@ -1,900 +1,900 @@\n"
    ) + "".join(f"+linea {j} con relleno de sobra para ocupar espacio\n" for j in range(900))
    assert len(large) > config.max_chars_for_role("code")

    _output, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=large)

    maps = [p["messages"][1]["content"] for p in seen[:-1]]
    continuations = [m for m in maps if "CONTINÚA" in m]
    assert continuations, "el diff de prueba tiene que producir algún trozo de continuación"
    assert all("paquete/enorme.py" in m for m in continuations)


# --- El reintento tiene que reconocer el desborde diga lo que diga el backend --------------
#
# El mecanismo de reintento existe desde el principio y estaba bien pensado, pero la puerta de
# entrada comparaba contra tres literales de un proveedor. El backend de referencia dice
# `Context size has been exceeded.` y no casa con ninguno, así que el reintento estaba anulado y
# `local_summarize(path="CHANGELOG.md")` —122 435 chars— se rendía. Medido y reproducido.


def _backend_with_ceiling(ceiling: int, message: str, kind: str | None = None):
    """Backend que rechaza cualquier envío por encima de `ceiling` chars con `message`.

    Devuelve el handler y la lista donde va anotando los tamaños que vio, para poder exigir que
    la prueba llegó a provocar el desborde: sin eso pasaría igual sin reintento ninguno.
    """
    seen: list[int] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        content = json.loads(request.content)["messages"][1]["content"]
        seen.append(len(content))
        if len(content) > ceiling:
            error: dict = {"code": 400, "message": message}
            if kind:
                error["type"] = kind
            return httpx2.Response(400, json={"error": error})
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "PARTE"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    return _handler, seen


def test_the_real_message_of_this_backend_triggers_the_retry(monkeypatch, tmp_path):
    """Regresión del bug: con `Context size has been exceeded` el reintento estaba ciego.

    Reproduce el caso del `CHANGELOG.md`: documento muy por encima del presupuesto, trozos que
    caben en chars y no en tokens. Contra el código anterior este test falla —la salida es el
    error crudo del backend—, que es lo que lo hace medir algo.
    """
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    document = _document(40, 3_000)
    assert len(document) > config.max_chars_for_role("long")
    # El techo se elige entre el presupuesto (38 400) y su mitad: el trozo entero no cabe y la
    # mitad sí, o sea un solo nivel de reintento, como en el caso real.
    handler, seen = _backend_with_ceiling(25_000, "Context size has been exceeded.")

    with backend_mock.mock:
        backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=handler)
        output = server.local_summarize(text=document)

    assert any(length > 25_000 for length in seen), "el test no llegó a provocar ningún desborde"
    assert not output.startswith("[local-delegate error]"), output
    assert _events(tmp_path)[0]["ok"] is True


def test_overflow_detection_covers_the_catalog_forms():
    """REQ-024: no puede depender de la redacción de un proveedor.

    El catálogo son endpoints OpenAI-compatible distintos (llama-swap, Ollama, LM Studio, vLLM)
    y cada uno dice lo mismo con otras palabras. El control negativo es la mitad del test: si
    reconociera cualquier error, el reintento se dispararía siempre y no mediría nada.
    """
    overflows = [
        "Context size has been exceeded.",  # llama.cpp reciente — el de este backend
        "request (10193 tokens) exceeds the available context size (8192 tokens)",
        '{"type": "exceed_context_size_error"}',
        "This model's maximum context length is 8192 tokens. However, you requested 10193.",
        "context_length_exceeded",
        "Model context length exceeded",
        "the input exceeds the context window of this model",
        "CONTEXT SIZE HAS BEEN EXCEEDED",  # insensible a mayúsculas
    ]
    for message in overflows:
        assert server._is_context_overflow(server.ChatResult(text=message, ok=False)), message

    no_overflows = [
        "[local-delegate error] no se pudo conectar al endpoint (http://x/v1).",
        "[local-delegate error] modelo respondió 500: internal server error",
        "model 'qwen' not found, try pulling it first",
        "",
    ]
    for message in no_overflows:
        assert not server._is_context_overflow(server.ChatResult(text=message, ok=False)), message
    assert not server._is_context_overflow(None)


def test_an_exhausted_overflow_is_explained_instead_of_dumping_the_raw_error(monkeypatch, tmp_path):
    """REQ-026: cuando ni partiendo cabe, el usuario tiene que saber qué hacer.

    Antes veía `respondió 400: {"error":{"message":"Context size has been exceeded"...}}`, que no
    dice ni que el problema es el tamaño ni qué tocar.
    """
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    # Techo por debajo del mínimo de troceado: no hay reintento que lo salve.
    handler, seen = _backend_with_ceiling(10, "Context size has been exceeded.")

    with backend_mock.mock:
        backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=handler)
        output = server.local_summarize(text=_document(40, 3_000))

    assert len(seen) > 1, "sin reintento el mensaje nuevo no estaría probando el caso agotado"
    assert output.startswith("[local-delegate error]")
    assert "no cabe" in output
    assert config.MODEL_LONG in output  # qué modelo se quedó corto
    assert "Context size has been exceeded" in output  # el detalle del backend no se pierde
    event = _events(tmp_path)[0]
    assert event["ok"] is False
    assert event["error"] == "context_overflow"
