"""Las salidas de las tools MCP y de `local_status` en inglés (ola B2a; REQ-019, 023, 026, 033, 034).

El humo de REQ-034 para la superficie MCP: con `LOCAL_DELEGATE_LANG=en` y un backend falso, lo que
devuelven las tools (camino feliz, recibos, troceado, avisos, errores) y `local_status` no lleva
ninguna palabra que solo exista en el catálogo español. Más los formatos de número de las salidas
MCP (REQ-026: sin separador de miles y con punto decimal en los dos idiomas), la cabecera de idioma de
`local_status` (REQ-019) y las piezas que se movieron al catálogo (`failures`, `chains`, `sections`).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from importlib.resources import files
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import chains, config, failures, i18n, sections, server, topology

ROOT = Path(__file__).parents[1]
#: Los catálogos cuyos textos puede imprimir la superficie MCP.
SURFACES = ("mcp", "common", "cli")
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
_ACCENTS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡«»]")
#: Marcadores de contrato que aún llevan una palabra española: su forma la cambia B2b-1 (REQ-010),
#: en la misma versión. Se quitan de la salida antes de buscar; `test_the_pending_markers_are_live`
#: obliga a borrarlos de aquí en cuanto B2b-1 los cambie.
PENDING_MARKERS = (server.WARNING_MARKER, server.FALLBACK_MARKER)


def _catalog(lang: str, surface: str) -> dict[str, str]:
    path = files("local_delegate").joinpath("resources", "i18n", lang, f"{surface}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _distinctive_spanish_words() -> set[str]:
    """Palabras de los textos españoles que difieren del inglés y que ningún texto inglés usa."""
    english: set[str] = set()
    spanish: set[str] = set()
    for surface in SURFACES:
        es, en = _catalog("es", surface), _catalog("en", surface)
        for text in en.values():
            english.update(w.lower() for w in _WORD.findall(text))
        for key, text in es.items():
            if text != en[key]:
                spanish.update(w.lower() for w in _WORD.findall(text))
    return spanish - english


def _spanish_in(text: str, words: set[str]) -> list[str]:
    for marker in PENDING_MARKERS:
        text = text.replace(marker, "[")
    # Las rutas son datos, no texto.
    text = " ".join(token for token in text.split() if "/" not in token and "\\" not in token)
    return sorted({w for w in (m.lower() for m in _WORD.findall(text)) if w in words})


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()


def _reply(text: str = "the summary", finish: str = "stop") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5},
        },
    )


def _backend(monkeypatch, reply: httpx2.Response | Exception) -> None:
    """Cada escenario con su propio host: `backend_mock` responde con la PRIMERA ruta que casa."""
    _backend.n = getattr(_backend, "n", 0) + 1
    base = f"http://test-backend-{_backend.n}/v1"
    monkeypatch.setattr(config, "BASE_URL", base)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    monkeypatch.setattr(config, "FALLBACK", False)
    route = backend_mock.post(f"{base}/chat/completions")
    if isinstance(reply, Exception):
        route.mock(side_effect=reply)
    else:
        route.mock(return_value=reply)
    backend_mock.get(f"{base}/models").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get(f"{base.removesuffix('/v1')}/running").mock(
        side_effect=httpx2.ConnectError("down")
    )


def _outputs(monkeypatch, tmp_path) -> str:
    """Lo que ve el cliente MCP de una tanda de llamadas que recorren recibos, avisos y errores."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    small = tmp_path / "small.md"
    small.write_text("Some text to summarize.\n" * 20, encoding="utf-8")
    big = tmp_path / "big.md"
    big.write_text(("# Part\n\n" + "A paragraph of text. " * 40 + "\n\n") * 150, encoding="utf-8")
    out: list[str] = []

    _backend(monkeypatch, _reply())
    out.append(server.local_summarize(path=str(small)))  # recibo de lectura server-side
    out.append(server.local_summarize(path=str(big)))  # map-reduce y su recibo
    out.append(server.local_translate(target_lang="Spanish", path=str(big)))  # troceado
    out.append(json.dumps(server.local_extract(fields=["a"], text="a=1")))  # no es JSON
    out.append(server.local_commit_msg(diff="   "))  # diff vacío
    out.append(server.local_commit_msg(diff="x", style="weird"))  # style inválido
    out.append(server.local_delegate(task="t", input="i", output_format="f", chunk="maybe"))
    for call in (
        lambda: server.local_summarize(path=str(tmp_path / "missing.md")),
        lambda: server.local_boilerplate(spec="s", language="python", target="relative.py"),
        lambda: server.local_describe_image(path=str(tmp_path / "x.bmp")),
    ):
        try:
            out.append(call())
        except ValueError as exc:  # el cliente MCP lo ve como el error de la tool
            out.append(str(exc))

    _backend(monkeypatch, _reply("cut", finish="length"))
    out.append(server.local_summarize(text="short text"))  # aviso de salida truncada

    _backend(monkeypatch, httpx2.ConnectError("refused"))
    out.append(server.local_summarize(text="short text"))  # error de conexión con su causa

    _backend(monkeypatch, httpx2.Response(500, text="boom"))
    out.append(server.local_summarize(text="short text"))  # error HTTP

    out.append(server.local_status())
    out.append(sections.complete("## One\nbody text here\n", ["One", "Two"]).text)
    return "\n".join(out)


@backend_mock.mock
def test_tool_outputs_have_no_spanish_in_english(monkeypatch, tmp_path):
    """REQ-023/REQ-034. Control: el mismo recorrido en español sí trae palabras de la lista (el
    test puede fallar), y dejar un recibo fuera del catálogo hace fallar el de inglés."""
    words = _distinctive_spanish_words()
    _set_language(monkeypatch, "en")
    english = _outputs(monkeypatch, tmp_path / "en")
    assert not _spanish_in(english, words), _spanish_in(english, words)
    paths = {tok for tok in english.split() if "/" in tok or "\\" in tok}
    assert not _ACCENTS.search(" ".join(t for t in english.split() if t not in paths)), english
    # Guarda de «esto llegó a comprobar algo»: cada familia de salida está en el texto.
    for expected in (
        "read server-side",
        "summarized from",
        "processed in",
        "response is not parseable as JSON",
        "the diff is empty",
        "invalid style",
        "invalid chunk",
        "File not found",
        "'target' must be an absolute path",
        "Unsupported image extension",
        "output truncated by max_tokens",
        "could not connect to the backend",
        "answered 500",
        "Language: en (variable;",
        "Role catalog:",
        "(not summarized)",
        "sections not summarized",
        "input truncated",
    ):
        assert expected in english, expected

    _set_language(monkeypatch, "es")
    spanish = _outputs(monkeypatch, tmp_path / "es")
    assert _spanish_in(spanish, words)


def test_the_pending_markers_are_live():
    """Mientras un marcador esté en `PENDING_MARKERS`, tiene que seguir en español; cuando B2b-1 lo
    cambie, este test obliga a sacarlo de la lista (y la búsqueda vuelve a verlo)."""
    for marker in PENDING_MARKERS:
        assert re.search(r"aviso|respaldo", marker), marker


@pytest.mark.parametrize("lang", ["es", "en"])
@backend_mock.mock
def test_numbers_are_machine_format(monkeypatch, tmp_path, lang):
    """REQ-026: en una salida MCP los enteros van sin separador de miles y los decimales con punto,
    en los dos idiomas. Control: `format_number(…, machine=False)` daría `20,027` en inglés y
    `20.027` en español, y fallan las dos negaciones."""
    _set_language(monkeypatch, lang)
    _backend(monkeypatch, _reply())
    doc = tmp_path / "doc.md"
    doc.write_text("x" * 20027, encoding="utf-8")
    text = server.local_summarize(path=str(doc))
    assert "20027" in text
    assert "20,027" not in text and "20.027" not in text
    monkeypatch.setattr(
        server,
        "_pace_references",
        type("R", (), {"summary": lambda self: [{"model": "m", "median": 1.5, "samples": 3}]}),
    )
    pace_line = server._describe_pace()
    assert "1.5 tok/s" in pace_line and "1,5" not in pace_line


def test_status_shows_language_source_and_path(monkeypatch):
    """REQ-019: `local_status` dice el idioma del proceso servidor, su origen y el `language.json`."""
    _set_language(monkeypatch, "en")
    lines = server._describe_language()
    assert lines[0].startswith("Language: en (variable; ")
    assert str(i18n.current().pref_path) in lines[0]


def test_status_warns_about_an_invalid_variable(monkeypatch):
    """Con `LOCAL_DELEGATE_LANG=english` (no válido) avisa con el texto común del catálogo.
    Control: sin los avisos de `language_report`, la segunda línea no existe y falla."""
    _set_language(monkeypatch, "english")
    lines = server._describe_language()
    assert len(lines) >= 2
    assert "LOCAL_DELEGATE_LANG" in lines[1] and "english" in lines[1]


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "Turn: no (remote backend)"), ("es", "Turno: no (backend remoto)")],
)
def test_remote_backend_reason_has_its_text(monkeypatch, lang, expected):
    """B1c dejó el motivo de REQ-002 crudo en `local_status`. Control: volver a
    `snapshot.reason` deja «backend remoto» en la salida inglesa y falla."""
    _set_language(monkeypatch, lang)
    monkeypatch.setattr(
        server, "_topology", lambda: topology.NoTopology(server.NO_TURN_REMOTE_BACKEND)
    )
    assert server._describe_turn() == expected
    # El valor de máquina no cambia: lo comparan otros procesos (`checks._no_turn_is_fine`).
    assert server.NO_TURN_REMOTE_BACKEND == "backend remoto"


def test_residents_text_says_the_reason_in_the_current_language(monkeypatch):
    _set_language(monkeypatch, "en")
    monkeypatch.setattr(topology, "snapshot", lambda: topology.NoTopology(topology.NO_CONFIG))
    assert chains.residents_text() == "no resident (unknown: no LLAMASWAP_CONFIG)"


@pytest.mark.parametrize("cause", list(failures.ConnectionCause))
def test_failure_texts_follow_the_requested_language(cause):
    """D6: el panel (B4) pedirá el idioma del visitante; sin él, el del proceso. Control: ignorar
    `language` da el mismo texto en los dos y falla la desigualdad."""
    for text in (
        lambda lang: failures.label(cause, language=lang),
        lambda lang: failures.detail(cause, host="h", language=lang),
        lambda lang: failures.hint(cause, origin="local", source="mcp", host="h", language=lang),
    ):
        assert text("en") != text("es"), cause
    assert failures.label(cause) == failures.label(cause, language=i18n.lang())


def test_failure_texts_keep_the_spanish_of_before():
    """En español, byte a byte lo de antes de B2a (un muestreo de las tres familias)."""
    assert failures.label("refused", language="es") == "nadie escucha"
    assert (
        failures.detail("http_error", host="h", status=503, language="es") == "h responde HTTP 503"
    )
    assert (
        failures.detail("invalid_response", host="h", endpoint="/m", language="es")
        == "h responde a /m, pero con un cuerpo que no se entiende"
    )
    assert (
        failures.hint("dns", origin="remote", source="mcp", host="h", language="es")
        == "revisa el nombre en LOCAL_DELEGATE_BASE_URL o usa la IP (p. ej. la 100.x de la tailnet)"
    )


def _measure_script():
    spec = importlib.util.spec_from_file_location(
        "measure_structured_summary_b2a", ROOT / "scripts" / "measure_structured_summary.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_structured_summary_b2a"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("placeholder", "receipt"),
    [
        ("(sin resumir)", "(resumido de 3 partes en 3 pasadas por local-delegate)"),
        ("(not summarized)", "(summarized from 3 parts in 3 passes by local-delegate)"),
    ],
)
def test_the_measurement_reads_both_forms(placeholder, receipt):
    """REQ-033: las salidas guardadas pueden estar en cualquiera de los dos idiomas. Control:
    comparar solo con la forma vigente deja de contar la sección completada en una de las dos."""
    sentence = "word " * 12
    output = f"## One\n{sentence}\n\n## Two\n{placeholder}\n\n{receipt}"
    r = _measure_script().measure(output, ["One", "Two"], 500)
    assert (r["paired"], r["completed_by_server"]) == (1, 1)
    assert r["words"] == 12
