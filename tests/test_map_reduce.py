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


# --- local_commit_msg: el diff entra entero ----------------------------------
# Reportado desde un cliente remoto: para un diff de 71k chars la tool devolvió
# `docs: update angular agents documentation`, o sea el primer archivo por orden alfabético de
# rutas. Reproducido aquí con un diff de 164 585 chars: veía 20 027 y los otros 144 558 se
# descartaban con un aviso que parecía inocuo.
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


def test_un_diff_que_no_cabe_entra_entero_y_sin_truncar(monkeypatch, tmp_path):
    limite = config.max_chars_for(config.MODEL_CODE)
    diff = _diff_grande()
    assert len(diff) > limite, "el diff de prueba tiene que exceder el techo del modelo"

    salida, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)

    assert len(seen) > 1  # map (varias) + reduce (una)
    evento = _events(tmp_path)[0]
    assert evento["chunks"] == len(seen)
    assert evento["chars_in"] == len(diff)  # entró completo…
    assert not evento.get("truncated_in")  # …y no se descartó nada
    assert "entrada truncada" not in salida


def test_el_ultimo_archivo_del_diff_llega_al_modelo(monkeypatch, tmp_path):
    """Lo que se perdía al truncar: `src/` va al final por orden alfabético de rutas."""
    diff = _diff_grande() + (
        "diff --git a/zzz/ultimo.py b/zzz/ultimo.py\n--- a/zzz/ultimo.py\n+++ b/zzz/ultimo.py\n"
        "@@ -1 +1 @@\n+MARCA-DEL-ULTIMO-ARCHIVO\n"
    )
    _salida, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)
    enviado = "\n".join(p["messages"][1]["content"] for p in seen)
    assert "MARCA-DEL-ULTIMO-ARCHIVO" in enviado


def test_el_paso_que_redacta_el_mensaje_recibe_el_inventario_completo(monkeypatch, tmp_path):
    """REQ-003: el reduce ve la lista COMPLETA de archivos, no solo los de su último trozo."""
    diff = _diff_grande()
    _salida, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)

    reduce = seen[-1]["messages"][1]["content"]
    assert "30 en total" in reduce
    # El inventario nombra tanto el primer archivo como el último: es lo que impide que el
    # mensaje se redacte sobre el principio del diff.
    assert "paquete/mod0.py" in reduce
    assert "paquete/mod29.py" in reduce


def test_el_mensaje_dice_sobre_cuanto_se_redacto(monkeypatch, tmp_path):
    """REQ-007: sin esto, procesar de más o de menos vuelve a ser invisible."""
    diff = _diff_grande()
    salida, _seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)
    assert "30 archivos" in salida
    assert f"{len(diff):,} chars" in salida


def test_un_diff_pequeno_sigue_haciendo_una_sola_llamada(monkeypatch, tmp_path):
    """Sin regresión: lo que ya cabía se resuelve igual que siempre, y sin nota de alcance."""
    diff = "diff --git a/uno.py b/uno.py\n--- a/uno.py\n+++ b/uno.py\n@@ -1 +1 @@\n-a\n+b\n"
    salida, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=diff)
    assert len(seen) == 1
    assert _events(tmp_path)[0].get("chunks") in (None, 1)
    assert "alcance:" not in salida


def test_un_diff_vacio_no_se_le_pide_al_modelo(monkeypatch, tmp_path):
    salida, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff="   \n  ")
    assert salida.startswith("[local-delegate error]")
    assert seen == []


def test_un_trozo_que_no_cabe_en_tokens_se_reintenta_partido(monkeypatch, tmp_path):
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
    diff = _diff_grande()
    vistos: list[int] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        contenido = json.loads(request.content)["messages"][1]["content"]
        vistos.append(len(contenido))
        # El backend rechaza cualquier envío por encima de este tamaño, como haría un modelo
        # cuyo contexto real es menor que el presupuesto en chars.
        if len(contenido) > 9_000:
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
        salida = server.local_commit_msg(diff=diff)

    assert not salida.startswith("[local-delegate error]"), salida
    assert any(largo > 9_000 for largo in vistos), "el test no llegó a provocar ningún desborde"
    assert _events(tmp_path)[0]["ok"] is True


def test_un_desborde_que_no_se_puede_partir_sigue_siendo_un_error(monkeypatch, tmp_path):
    """Control: el reintento no puede convertir un fallo real en un resultado que parezca bueno."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    llamadas: list[int] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        llamadas.append(len(json.loads(request.content)["messages"][1]["content"]))
        return httpx2.Response(
            400, json={"error": {"message": "exceeds the available context size (8192 tokens)"}}
        )

    with backend_mock.mock:
        backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
        salida = server.local_commit_msg(diff=_diff_grande())

    assert salida.startswith("[local-delegate error]")
    assert _events(tmp_path)[0]["ok"] is False
    # Sin esto el test pasaría igual sin reintento ninguno, o sea no comprobaría lo que dice:
    # tiene que haberse reintentado —con envíos más pequeños— y AUN ASÍ reportar el error.
    assert len(llamadas) > 1
    assert min(llamadas) < max(llamadas)


def test_el_map_nombra_los_archivos_reales_de_cada_trozo(monkeypatch, tmp_path):
    """Medido: con el formato descrito como plantilla, el modelo devolvía `- ruta: qué cambió`.

    Anclar el prompt con las rutas reales —que se saben sin preguntarle a nadie— quita la
    plantilla que se podía copiar.
    """
    _salida, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=_diff_grande())
    primer_map = seen[0]["messages"][1]["content"]
    # Las rutas están dentro del propio diff, así que buscarlas en el prompt entero no
    # distinguiría nada: se mira el ENCABEZADO, o sea lo que se añadió delante del fragmento.
    encabezado = primer_map.split("Di qué cambia en este fragmento")[0]
    assert "Archivos de este fragmento:" in encabezado
    assert "paquete/mod0.py" in encabezado
    # Y el system ya no lleva una plantilla que se pueda devolver copiada.
    assert "qué cambió y para qué" not in seen[0]["messages"][0]["content"]


def test_un_trozo_de_continuacion_dice_a_que_archivo_pertenece(monkeypatch, tmp_path):
    """Un archivo mayor que el presupuesto se subdivide y las piezas 2..N no llevan cabecera.

    Sin decirlo, el modelo inventa la ruta: medido, devolvió `- ruta: archivo.py`.
    """
    # Un solo archivo, lo bastante grande como para que haya que partirlo.
    grande = (
        "diff --git a/paquete/enorme.py b/paquete/enorme.py\n"
        "--- a/paquete/enorme.py\n+++ b/paquete/enorme.py\n@@ -1,900 +1,900 @@\n"
    ) + "".join(f"+linea {j} con relleno de sobra para ocupar espacio\n" for j in range(900))
    assert len(grande) > config.max_chars_for(config.MODEL_CODE)

    _salida, seen = _run(monkeypatch, tmp_path, server.local_commit_msg, diff=grande)

    mapas = [p["messages"][1]["content"] for p in seen[:-1]]
    continuaciones = [m for m in mapas if "CONTINÚA" in m]
    assert continuaciones, "el diff de prueba tiene que producir algún trozo de continuación"
    assert all("paquete/enorme.py" in m for m in continuaciones)
