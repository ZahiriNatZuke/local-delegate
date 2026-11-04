"""#558: `local_summarize` with `focus` names the sections that treat it, and warns when it is missed.

The issue: a review report in Markdown (~16 KB, so the `long` role and one single call) with an
introduction, ten `###` findings and a long closing list. `focus="cp1252 / utf8 stdin"` reached the
system prompt, and the model summarized the introduction and the closing list and left out the
finding whose title holds `cp1252`, with no warning. The document here is synthetic, with the shape
of the issue.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2

from local_delegate import config, i18n, sections, server

FOCUS = "cp1252 / utf8 stdin"
TARGET = "La entrada de los hooks se lee en cp1252 en Windows"


def _finding(n: int, title: str, body: str) -> str:
    filler = (
        f"El hallazgo {n} se reprodujo con un script propio. La severidad es media y el arreglo "
        "propuesto es pequeño y local. Se probó en Windows y en la Mac con la versión 0.41.1. "
    )
    return f"### {title}\n\n- Escenario: {body}\n- Evidencia: {filler * 6}\n\n"


def _document() -> str:
    parts = [
        "# Revisión de hooks y plugin\n\n",
        "Revisión de solo lectura. Recuento: **Alta 0 · Media 4 · Baja 6**.\n\n",
        _finding(1, "El registro de una decisión se da por escrito antes de tiempo", "el mod."),
        _finding(
            2,
            TARGET,
            "Claude Code manda UTF-8 y el hook lee stdin con la página cp1252 del sistema.",
        ),
    ]
    parts += [
        _finding(n, f"Hallazgo de severidad baja número {n}", "una ruta de la banda.")
        for n in range(3, 11)
    ]
    parts.append("## Revisado sin hallazgos\n\n")
    parts += [f"- **Componente {n}**: se revisó y no tiene fallos.\n" for n in range(1, 60)]
    parts.append("\n## Notas de cierre\n\nNo quedan procesos en segundo plano.\n")
    return "".join(parts)


DOC = _document()

#: What the model did in the issue: the introduction and the closing list, nothing of the target.
MISSING_SUMMARY = (
    "La revisión encontró 4 hallazgos de severidad media y 6 de baja. Una lista larga de "
    "componentes se revisó sin fallos y no quedan procesos en segundo plano."
)
#: A summary that does cover the focus.
GOOD_SUMMARY = (
    "El hallazgo principal: los hooks leen la entrada en CP1252 en Windows aunque Claude Code "
    "manda UTF-8. El resto son hallazgos menores."
)


@backend_mock.mock
def _summarize(monkeypatch, tmp_path, answer: str, *, structured: bool = False, status=200, **kw):
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", structured)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        if status != 200:
            return httpx2.Response(status, text="boom")
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return server.local_summarize(**kw), seen


def _write(tmp_path, text: str = DOC):
    path = tmp_path / "report.md"
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _warning(terms: str) -> str:
    return server.WARNING_MARKER + i18n.t("mcp.warning.focus_not_in_summary", terms=terms) + "]"


#: The start of the focus warning, without its terms. The structured path may carry other
#: warnings (sections not summarized), which are not this one.
FOCUS_WARNING = _warning("").split("(")[0]


# --- The pure functions ----------------------------------------------------------------------------


def test_the_document_has_the_shape_of_the_issue():
    # `long` role, one single call (it fits in the `long` cap), and the target near the top.
    assert config.LONG_INPUT_CHARS < len(DOC) < config.max_chars_for_role("long")
    assert 12000 < len(DOC.encode("utf-8")) < 20000


def test_focus_terms_drop_short_words_and_empty_words():
    assert sections.focus_terms(FOCUS) == ["cp1252", "utf8", "stdin"]
    assert sections.focus_terms("los riesgos de la UI y sobre Configuración") == [
        "riesgos",
        "configuracion",
    ]
    assert sections.focus_terms(None) == []
    assert sections.focus_terms("de la y o") == []


def test_focus_terms_in_ignores_case_accents_and_plural():
    assert sections.focus_terms_in(
        "La CONFIGURACIÓN y un riesgo.", ["configuracion", "riesgos"]
    ) == [
        "configuracion",
        "riesgos",
    ]
    # `utf8` is not in «UTF-8»: the word there is `utf`.
    assert sections.focus_terms_in(DOC, sections.focus_terms(FOCUS)) == ["cp1252", "stdin"]
    assert sections.focus_terms_in(MISSING_SUMMARY, ["cp1252", "stdin"]) == []
    assert sections.focus_terms_in(GOOD_SUMMARY, ["cp1252", "stdin"]) == ["cp1252"]


def test_focus_sections_names_the_section_that_treats_the_focus():
    assert sections.focus_sections(DOC, sections.focus_terms(FOCUS)) == [TARGET]
    assert sections.focus_sections(DOC, []) == []
    # A focus every section matches singles none out.
    assert sections.focus_sections(DOC, ["hallazgo", "componente"]) == []


# --- local_summarize end to end, with a fake backend -----------------------------------------------


def test_prose_path_names_the_section_and_warns_when_it_is_missed(monkeypatch, tmp_path):
    output, seen = _summarize(
        monkeypatch, tmp_path, MISSING_SUMMARY, path=_write(tmp_path), focus=FOCUS, max_words=200
    )
    (payload,) = seen
    user = payload["messages"][1]["content"]
    assert user.startswith(f"Secciones que tratan el aspecto prioritario: «{TARGET}».")
    assert user.endswith(f"Resume el siguiente contenido:\n\n{DOC}")
    assert _warning("cp1252, stdin") in output
    # The notice goes before the savings receipt, which stays the last thing.
    assert output.index(server.WARNING_MARKER) < output.index("(leído server-side")


def test_structured_path_names_the_section_and_warns_when_it_is_missed(monkeypatch, tmp_path):
    output, seen = _summarize(
        monkeypatch,
        tmp_path,
        "## Revisión de hooks y plugin\n\n" + MISSING_SUMMARY,
        structured=True,
        path=_write(tmp_path),
        focus=FOCUS,
        max_words=200,
    )
    (payload,) = seen
    user = payload["messages"][1]["content"]
    assert "Secciones, en orden" in user
    note = f"Secciones que tratan el aspecto prioritario: «{TARGET}»."
    assert user.index("Secciones, en orden") < user.index(note) < user.index("Resume el siguiente")
    assert _warning("cp1252, stdin") in output


def test_a_summary_that_covers_the_focus_is_not_warned(monkeypatch, tmp_path):
    for structured in (False, True):
        output, _seen = _summarize(
            monkeypatch,
            tmp_path,
            GOOD_SUMMARY,
            structured=structured,
            path=_write(tmp_path),
            focus=FOCUS,
        )
        assert FOCUS_WARNING not in output


def test_a_focus_absent_from_the_input_is_not_warned(monkeypatch, tmp_path):
    output, seen = _summarize(
        monkeypatch, tmp_path, MISSING_SUMMARY, path=_write(tmp_path), focus="kubernetes"
    )
    assert FOCUS_WARNING not in output
    assert seen[0]["messages"][1]["content"] == f"Resume el siguiente contenido:\n\n{DOC}"


def test_without_focus_nothing_changes(monkeypatch, tmp_path):
    for structured in (False, True):
        out_none, seen_none = _summarize(
            monkeypatch, tmp_path, MISSING_SUMMARY, structured=structured, path=_write(tmp_path)
        )
        assert FOCUS_WARNING not in out_none
        assert "aspecto prioritario" not in json.dumps(seen_none, ensure_ascii=False)
        if not structured:
            assert seen_none[0]["messages"][1]["content"] == (
                f"Resume el siguiente contenido:\n\n{DOC}"
            )


def test_each_chunk_names_only_the_sections_it_holds(monkeypatch, tmp_path):
    # A cap under the document: the prose map/reduce, one map call per piece.
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 6500)
    output, seen = _summarize(
        monkeypatch, tmp_path, MISSING_SUMMARY, path=_write(tmp_path), focus=FOCUS, max_words=200
    )
    users = [p["messages"][1]["content"] for p in seen]
    maps = [u for u in users if u.startswith(("Secciones que tratan", "Resume el siguiente"))]
    assert len(maps) >= 2
    named = [u for u in maps if u.startswith("Secciones que tratan")]
    assert len(named) == 1
    assert "cp1252" in named[0]
    assert _warning("cp1252, stdin") in output


def test_a_backend_error_carries_no_focus_warning(monkeypatch, tmp_path):
    output, _seen = _summarize(
        monkeypatch, tmp_path, "", status=500, path=_write(tmp_path), focus=FOCUS
    )
    assert output.startswith("[local-delegate error]")
    assert FOCUS_WARNING not in output


def test_a_heading_put_back_not_summarized_does_not_count_for_the_focus(monkeypatch, tmp_path):
    # `sections.complete` puts back a top-level heading the model left out, with «(sin resumir)»:
    # its title holds the focus term, and still nothing of that section was summarized.
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 0)
    doc = (
        "## Introducción\n\nUna revisión con tres partes.\n\n"
        "## Lectura de stdin en cp1252\n\nEl hook lee stdin con la página cp1252.\n\n"
        "## Cierre\n\nNo quedan procesos.\n"
    )
    answer = "## Introducción\n\nTres partes.\n\n## Cierre\n\nSin procesos.\n"
    output, _seen = _summarize(
        monkeypatch, tmp_path, answer, structured=True, path=_write(tmp_path, doc), focus=FOCUS
    )
    assert "## Lectura de stdin en cp1252" in output
    assert _warning("cp1252, stdin") in output
