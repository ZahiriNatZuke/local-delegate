"""#667: `local_extract` warns when a value says the opposite of its source.

The mechanical model (gemma3-4b) rewrote «revisar el código real del mod y los adaptadores de
ambos clientes, no inferir la respuesta desde las skills o hooks» as «Do not review code real of
the mod and adapters of both clients, do not infer response from the skills or hooks»: the
negation of the second clause leaked into the first. The program never touches the words of a
value (the first tests below show it hands the model's text back as it came), so the flip is the
model's. `polarity.flipped` finds it from the source and the answer and `local_extract` reports it
in `_local_delegate.polarity_flipped_keys`, with a warning, without changing the value.

Every rule has a case that fires and one that stays quiet; the false-positive gate runs the
detector over the 177 answers of `tests/data/cross_fill/` (hand-written and recorded from the local
models), none of them flipped. Backend faked (`_run_chat` doubled), no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import perf
import pytest

from local_delegate import config, i18n, polarity, server

#: The shape of the issue's source (its content was not published): one instruction to do, one
#: not to do, in the same sentence.
SOURCE_667 = (
    "# Relevo\n\n## Siguiente acción\n\n"
    "Revisar el código real del mod y los adaptadores de ambos clientes, no inferir la respuesta "
    "desde las skills o hooks.\n\n## No reintentar\n\nNada.\n"
)
#: The exact wrong text of the issue.
FLIPPED_667 = (
    "Do not review code real of the mod and adapters of both clients, do not infer response "
    "from the skills or hooks."
)
FAITHFUL_667 = (
    "Review the real code of the mod and the adapters of both clients; do not infer the answer "
    "from the skills or hooks."
)

FLIPS = [
    pytest.param(SOURCE_667, FLIPPED_667, "added", id="issue-667-translated"),
    pytest.param(
        SOURCE_667,
        "No revisar el código real del mod y los adaptadores de ambos clientes.",
        "added",
        id="added-verbatim",
    ),
    pytest.param(
        "Publica la release cuando el CI de main esté en verde.",
        "Nunca publiques la release cuando el CI de main esté en verde.",
        "added",
        id="added-never",
    ),
    pytest.param(
        SOURCE_667,
        "Inferir la respuesta desde las skills o hooks.",
        "removed",
        id="removed-verbatim",
    ),
    pytest.param(
        "No toques el instalador de la Mac ni sus scripts.",
        "Toca el instalador de la Mac.",
        "removed",
        id="removed-conjugated",
    ),
    pytest.param(
        "Do not commit the generated lockfile changes.",
        "Commit the generated lockfile changes.",
        "removed",
        id="removed-english",
    ),
]

FAITHFUL = [
    pytest.param(SOURCE_667, FAITHFUL_667, id="issue-667-faithful-translation"),
    pytest.param(SOURCE_667, SOURCE_667.split("\n")[4], id="verbatim"),
    pytest.param(
        # The negation scopes forward over the list: the second item is denied too. Without the
        # scope this one would fire (the denied word `adapters` sits in the second clause).
        "No revises el código, los adaptadores de ambos clientes y sus hooks.",
        "Not the adapters of both clients and their hooks.",
        id="negation-scoping-a-list",
    ),
    pytest.param(
        # «X, no Y» joined as «X and not Y»: the denied word sits in the negated clause too.
        "Revisar el código real del mod, no el código de los hooks.",
        "Review the real code of the mod and not the code of the hooks.",
        id="x-and-not-y",
    ),
    pytest.param(
        "| Función | Básico | Pro |\n| --- | --- | --- |\n"
        "| SSO | No incluido | Incluido (SAML y OIDC) |\n",
        "| SSO | No incluido | Incluido (SAML y OIDC) |",
        id="markdown-row-copied",
    ),
    pytest.param(
        "<tr><td>SSO</td><td>No incluido</td><td>Incluido (SAML y OIDC)</td></tr>",
        "<td>SSO</td><td>No incluido</td><td>Incluido (SAML y OIDC)</td>",
        id="html-row-copied",
    ),
    pytest.param(
        # A negated heading covers its list.
        "## No hacer\n\n- Tocar los hooks del mod de Codex.\n- Reiniciar el daemon.\n",
        "No tocar los hooks del mod de Codex.",
        id="negated-heading",
    ),
    pytest.param(
        # A negated `...:` line covers the list after it.
        "Cosas que no hay que hacer:\n- Tocar los hooks del mod de Codex.\n",
        "No tocar los hooks del mod de Codex.",
        id="negated-colon-line",
    ),
    pytest.param(
        # The shared stems are only the denied word and one more.
        "Hay errores en el build de main.",
        "No hay errores en los tests.",
        id="negation-about-another-object",
    ),
    pytest.param(
        # A double negation says the same as the positive answer.
        "No mezclar el PR de la release sin el CI de main en verde.",
        "Mezclar el PR de la release cuando el CI de main esté en verde.",
        id="double-negation",
    ),
    pytest.param(
        # Two cells of one Markdown row: the negated one is not the value's.
        "| Función | Básico | Pro |\n| --- | --- | --- |\n"
        "| SSO | No incluido | Incluido (SAML y OIDC) |\n",
        "Incluido (SAML y OIDC)",
        id="markdown-cells",
    ),
    pytest.param(
        # The source denies `falla`, which the answer does not say.
        "El exportador de informes ya no falla cuando la hoja está vacía.",
        "El exportador de informes se ha corregido para hojas vacías.",
        id="denied-word-absent",
    ),
    pytest.param(
        # Two cells of one row: the negated one is not the value's.
        "<tr><td>Inicio de sesión único</td><td>No incluido</td>"
        "<td>Incluido (SAML y OIDC)</td></tr>",
        "Incluido (SAML y OIDC)",
        id="table-cells",
    ),
    pytest.param(
        # The source says both: no contradiction to report.
        "Revisa los hooks del mod antes de publicar. No revises los hooks del mod tras publicar.",
        "Do not review the hooks of the mod.",
        id="both-polarities-in-source",
    ),
    pytest.param(
        # A negation about something the source does not say.
        SOURCE_667,
        "The document does not mention any deadline.",
        id="unrelated-negation",
    ),
    pytest.param(SOURCE_667, "No adapters.", id="two-word-clause"),
]


# --- Root cause: the program hands the model's words back as they came -------------------------


def _ok(text: str):
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


@pytest.fixture
def backend(monkeypatch, tmp_path):
    state = {"answer": "{}"}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        return _ok(state["answer"]), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    yield state
    i18n.reset()


@pytest.mark.parametrize("answer", [FLIPPED_667, FAITHFUL_667])
def test_the_value_comes_back_word_for_word(backend, answer):
    backend["answer"] = json.dumps({"next_action": answer})
    data = server.local_extract(fields=["next_action"], text=SOURCE_667)
    assert data["next_action"] == answer


def test_the_value_comes_back_word_for_word_with_path_and_lines(backend, tmp_path):
    # With a location field the other values pass through `_strip_extract_prefixes`: it must not
    # cut a leading «Do not» either.
    source = tmp_path / "handoff.md"
    source.write_text(SOURCE_667, encoding="utf-8")
    backend["answer"] = json.dumps({"next_action": FLIPPED_667, "section_line": "3"})
    data = server.local_extract(fields=["next_action", "section_line"], path=str(source))
    assert data["next_action"] == FLIPPED_667


# --- The detector ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "answer", "kind"), FLIPS)
def test_a_flipped_clause_is_flagged(source, answer, kind):
    flagged = polarity.flipped(source, ["next_action"], {"next_action": answer})
    assert set(flagged) == {"next_action"}
    assert flagged["next_action"]["flip"] == kind


@pytest.mark.parametrize(("source", "answer"), FAITHFUL)
def test_a_faithful_clause_is_not_flagged(source, answer):
    assert polarity.flipped(source, ["next_action"], {"next_action": answer}) == {}


SENTENCE_667 = SOURCE_667.split("\n")[4]


@pytest.mark.parametrize("cut", range(1, len(SENTENCE_667.split(" "))))
def test_a_line_wrap_anywhere_keeps_a_faithful_copy_quiet(cut):
    words = SENTENCE_667.split(" ")
    wrapped = " ".join(words[:cut]) + "\n" + " ".join(words[cut:])
    source = SOURCE_667.replace(SENTENCE_667, wrapped)
    for answer in (SENTENCE_667, wrapped, FAITHFUL_667):
        assert polarity.flipped(source, ["a"], {"a": answer}) == {}, answer
    # And the flip is still caught across the wrap.
    assert set(polarity.flipped(source, ["a"], {"a": FLIPPED_667})) == {"a"}


@pytest.mark.parametrize("name", ["no_retry", "do_not_retry", "forbiddenActions", "avoid_steps"])
def test_a_key_that_names_a_ban_is_not_checked(name):
    source = "- No reinstalar el daemon con uv tool desde el worktree.\n"
    answer = {name: "Reinstalar el daemon con uv tool desde el worktree."}
    assert polarity.flipped(source, [name], answer) == {}
    # The same answer under a neutral key fires: the skip is the name's.
    assert set(polarity.flipped(source, ["next_step"], {"next_step": answer[name]})) == {
        "next_step"
    }


@pytest.mark.perf
def test_many_negations_stay_linear():
    # 400 000 characters of «no no no …» in one clause: one pass, never a quadratic scan.
    big = ("no " * 133_000)[: polarity.MAX_SOURCE_CHARS]
    small = big[: len(big) // 10]
    perf.assert_linear(
        lambda: polarity.flipped(small, ["a"], {"a": FLIPPED_667}),
        lambda: polarity.flipped(big, ["a"], {"a": FLIPPED_667}),
        size_ratio=10,
    )


def test_the_issue_flag_names_both_clauses():
    flagged = polarity.flipped(SOURCE_667, ["next_action"], {"next_action": FLIPPED_667})
    assert flagged["next_action"] == {
        "value": "Do not review code real of the mod and adapters of both clients",
        "source": "Revisar el código real del mod y los adaptadores de ambos clientes",
        "flip": "added",
    }


def test_strings_inside_a_list_or_an_object_are_checked():
    data = {"a": ["Nada.", FLIPPED_667], "b": {"inner": FLIPPED_667}, "c": 3, "d": None}
    assert set(polarity.flipped(SOURCE_667, ["a", "b", "c", "d"], data)) == {"a", "b"}


def test_skipped_keys_are_not_checked():
    data = {"a": FLIPPED_667}
    assert polarity.flipped(SOURCE_667, ["a"], data, skip=["a"]) == {}


def test_a_huge_or_empty_source_is_not_scanned():
    data = {"a": FLIPPED_667}
    huge = SOURCE_667 + "x" * polarity.MAX_SOURCE_CHARS
    assert polarity.flipped(huge, ["a"], data) == {}
    assert polarity.flipped("", ["a"], data) == {}


def test_an_unexpected_error_never_breaks_the_answer(monkeypatch):
    def boom(*_):
        raise RuntimeError("boom")

    monkeypatch.setattr(polarity, "_scan", boom)
    assert polarity.flipped(SOURCE_667, ["a"], {"a": FLIPPED_667}) == {}


def test_the_budget_stops_the_scan(monkeypatch):
    monkeypatch.setattr(polarity, "_BUDGET", 0)
    assert polarity.flipped(SOURCE_667, ["a"], {"a": FLIPPED_667}) == {}


def test_a_long_clause_is_cut_in_the_flag():
    long_tail = " ".join(["adaptadores"] * 40)
    source = f"Revisar el código real del mod {long_tail}."
    answer = f"Do not review the real code of the mod {' '.join(['adapters'] * 40)}."
    flagged = polarity.flipped(source, ["a"], {"a": answer})["a"]
    assert len(flagged["value"]) <= polarity._LABEL_CHARS
    assert len(flagged["source"]) <= polarity._LABEL_CHARS
    assert flagged["value"].endswith("…")


# --- False-positive gate: the recorded answers of `tests/data/cross_fill/` -------------------------

DATA = Path(__file__).parent / "data" / "cross_fill"


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _gate_answers():
    for case in _load("new_cases.json")["cases"]:
        for index, answer in enumerate(case["answers"]):
            yield f"new-{case['id']}-{index}", case["source"], case["fields"], answer["answer"]
    for case in _load("holdout/cases.json")["cases"]:
        source = _read(DATA / "holdout" / case["input"])
        yield f"holdout-{case['id']}", source, case["fields"], case["expected"]
        if case.get("crossed"):
            crossed = case["crossed"]["answer"]
            yield f"holdout-{case['id']}-crossed", source, case["fields"], crossed
    for row in _load("recorded/recorded_runs.json")["runs"]:
        source = _read(DATA / "recorded" / "inputs" / row["file"])
        yield f"recorded-{row['run']}-{row['case']}", source, row["fields"], row["answer"]


def test_no_answer_of_the_gate_is_flagged():
    answers = list(_gate_answers())
    flagged = {
        name: hit
        for name, source, fields, data in answers
        if (hit := polarity.flipped(source, fields, data))
    }
    assert len(answers) >= 170, "the gate lost its data"
    assert flagged == {}


ROOT = Path(__file__).parent.parent
SELF_COPY_FILES = sorted((ROOT / "docs" / "wiki").glob("*.md")) + [ROOT / "CHANGELOG.md"]


@pytest.mark.parametrize("doc", SELF_COPY_FILES, ids=lambda p: p.name)
def test_every_sentence_copied_from_the_docs_stays_quiet(doc):
    # Prose wrapped at a fixed width and full of negations: each sentence, copied word for word
    # (its line breaks joined), against its own file.
    source = _read(doc)
    sentences = []
    for paragraph in source.split("\n\n"):
        joined = " ".join(line.strip() for line in paragraph.split("\n"))
        sentences.extend(s for s in joined.split(". ") if s.strip())
    assert len(sentences) > 10
    flagged = [s for s in sentences if polarity.flipped(source, ["a"], {"a": s})]
    assert flagged == []


def test_an_input_of_the_issue_size_is_one_call(monkeypatch, tmp_path):
    # The issue's input (3219 characters) is a single call: no chunk can cut the sentence.
    calls = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append(user)
        answer = json.dumps({"next_action": FLIPPED_667})
        return _ok(answer), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    padding = "\n\n## Hechos\n\n" + "- Un hecho del relevo sin relación con la acción.\n" * 80
    source = (SOURCE_667 + padding)[:3219]
    assert len(source) == 3219
    path = tmp_path / "handoff.md"
    path.write_text(source, encoding="utf-8")
    data = server.local_extract(fields=["next_action", "section_line"], path=str(path))
    assert len(calls) == 1
    assert "chunked" not in data["_local_delegate"]
    assert data["_local_delegate"]["polarity_flipped_keys"]["next_action"]["flip"] == "added"


# --- `local_extract` ------------------------------------------------------------------------------


def test_local_extract_reports_a_flip_and_keeps_the_value(backend):
    backend["answer"] = json.dumps({"next_action": FLIPPED_667, "open_fronts": None})
    data = server.local_extract(fields=["next_action", "open_fronts"], text=SOURCE_667)
    assert data["next_action"] == FLIPPED_667
    meta = data["_local_delegate"]
    assert meta["polarity_flipped_keys"]["next_action"]["flip"] == "added"
    assert "polarity_flipped_keys" in meta["warning"]
    assert "next_action" in meta["warning"]


def test_local_extract_says_nothing_when_the_answer_is_faithful(backend):
    backend["answer"] = json.dumps({"next_action": FAITHFUL_667})
    data = server.local_extract(fields=["next_action"], text=SOURCE_667)
    assert "_local_delegate" not in data


def test_the_warning_is_appended_after_an_earlier_one(backend):
    # The model left out `open_fronts`: its warning keeps its text, the flip is appended.
    backend["answer"] = json.dumps({"next_action": FLIPPED_667})
    data = server.local_extract(fields=["next_action", "open_fronts"], text=SOURCE_667)
    warning = data["_local_delegate"]["warning"]
    assert warning.startswith(i18n.t("mcp.warning.extract_missing_keys", fields="open_fronts"))
    assert warning.endswith(
        i18n.t("mcp.warning.extract_polarity_flipped_keys", fields="next_action")
    )


def test_location_fields_are_not_checked(backend, tmp_path):
    source = tmp_path / "handoff.md"
    source.write_text(SOURCE_667, encoding="utf-8")
    backend["answer"] = json.dumps({"next_action_lines": FLIPPED_667})
    data = server.local_extract(fields=["next_action_lines"], path=str(source))
    assert "polarity_flipped_keys" not in data.get("_local_delegate", {})


def test_both_catalogs_carry_the_warning(monkeypatch):
    for lang in ("es", "en"):
        monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
        i18n.reset()
        text = i18n.t("mcp.warning.extract_polarity_flipped_keys", fields="next_action")
        assert "polarity_flipped_keys" in text
        assert "next_action" in text
    i18n.reset()


def test_the_docstring_names_polarity_flipped_keys():
    assert "polarity_flipped_keys" in (server.local_extract.__doc__ or "")
