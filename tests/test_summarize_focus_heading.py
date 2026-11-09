"""#593: a summary heading that holds the focus term, with a body under it, is a mention.

The issue: `local_summarize(path=..., focus="local_extract")` over a Markdown catalogue gave a
summary with a `` ## `local_extract` `` section and seven bullets under it, and still warned that the
summary mentioned no word of the focus. Every heading line of the summary was dropped before the
search (#561: copying a title is not summarizing its section), also the ones with a real body. A
heading copied with nothing, or only a placeholder, under it still does not count.
"""

from __future__ import annotations

from test_summarize_focus_coverage import DOC, FOCUS_WARNING, _summarize, _warning, _write

from local_delegate import sections, server


def _catalogue() -> str:
    tools = ["local_summarize", "local_extract", "local_lint_summary", "local_commit_msg"]
    parts = ["# Catálogo de tools\n\nLas tools del servidor y lo que hace cada una.\n\n"]
    for tool in tools:
        parts.append(f"## `{tool}`\n\n")
        parts += [
            f"- Punto {n} de la tool, con su detalle y su ejemplo de uso.\n" for n in range(8)
        ]
        parts.append("\n")
    return "".join(parts)


CATALOGUE = _catalogue()
#: The shape of the issue's summary: the section of the focus, its bullets name it only in the title.
ISSUE_SUMMARY = (
    "## `local_extract`\n\n"
    "- Devuelve un objeto JSON con exactamente las claves pedidas.\n"
    "- Lee el fichero del lado del servidor con `path`.\n"
    "- Marca como null los marcadores de «sin dato».\n"
)


def _missing(summary: str, content: str, focus: str) -> list[str]:
    clean = sections.sanitize_focus(focus)
    return server._focus_missing(
        summary, content, sections.focus_terms(clean), sections.literal_focus_terms(clean)
    )


def test_the_issue_heading_with_bullets_is_a_mention():
    assert _missing(ISSUE_SUMMARY, CATALOGUE, "local_extract") == []


def test_case_backticks_and_level_do_not_matter_in_the_heading():
    summary = "### LOCAL_EXTRACT\n\nExtrae campos de un fichero como JSON.\n"
    assert _missing(summary, CATALOGUE, "`local_extract`") == []


def test_accents_and_plural_in_the_heading(monkeypatch):
    monkeypatch.setattr(server, "_summary_language", lambda: "es")
    summary = "## Configuración del hook\n\nEl hook lee la entrada en la página del sistema.\n"
    # A plain word (not a literal token) is judged only when the input is in the summary's
    # language: DOC is a long Spanish report, and the section added holds the focus.
    content = DOC + "\n## Configuración\n\nLa configuración se guarda en el perfil del usuario.\n"
    assert _missing(summary, content, "CONFIGURACIONES") == []


def test_a_heading_with_only_a_placeholder_or_nothing_still_warns():
    placeholders = ("(sin datos)\n", "_(sin resumir)_\n", "_(sin datos)_ _(sin datos)_\n")
    for body in ("", *placeholders, "Ver abajo.\n"):
        summary = f"## `local_extract`\n\n{body}\n## Cierre\n\nNo quedan procesos en el servidor.\n"
        assert _missing(summary, CATALOGUE, "local_extract") == ["local_extract"], body


def test_three_words_under_the_heading_are_enough():
    summary = "## `local_extract`\n\nDevuelve JSON exacto.\n"
    assert _missing(summary, CATALOGUE, "local_extract") == []


def test_a_level_one_title_never_counts():
    # The document's title copied on top, with an introduction: it names the whole summary.
    summary = (
        "# Revisión de `local_extract`\n\nEl documento revisa las tools del servidor.\n\n"
        "## `local_summarize`\n\nResume un fichero con el modelo largo del servidor.\n"
    )
    assert _missing(summary, CATALOGUE, "local_extract") == ["local_extract"]


def test_a_title_over_subsections_does_not_hide_a_miss():
    # The document's title copied on top of the summary: its own body is empty.
    summary = (
        "# Revisión de `local_extract`\n\n"
        "## `local_summarize`\n\nResume un fichero con el modelo largo del servidor.\n"
    )
    assert _missing(summary, CATALOGUE, "local_extract") == ["local_extract"]


def test_the_issue_through_the_tool(monkeypatch, tmp_path):
    for structured in (False, True):
        output, _seen = _summarize(
            monkeypatch,
            tmp_path,
            ISSUE_SUMMARY,
            structured=structured,
            path=_write(tmp_path, CATALOGUE),
            focus="local_extract",
        )
        assert FOCUS_WARNING not in output, structured


def test_a_copied_heading_still_warns_through_the_tool(monkeypatch, tmp_path):
    answer = (
        "## `local_extract`\n\n(sin datos)\n\n## Cierre\n\nNo quedan procesos en el servidor.\n"
    )
    for structured in (False, True):
        output, _seen = _summarize(
            monkeypatch,
            tmp_path,
            answer,
            structured=structured,
            path=_write(tmp_path, CATALOGUE),
            focus="local_extract",
        )
        assert _warning("local_extract") in output, structured
