"""REQ-009 to REQ-013, REQ-018 and REQ-022: what the program answers, names and anchors.

An anchor is a literal piece of ONE line, compared after normalizing blanks, with case and
accents kept (D5): no likeness by words, no tolerance of a line. Every expected line is found in
the text by a unique marker, never written by hand.
"""

from __future__ import annotations

import time

import pytest

from local_delegate import locate

DOC_LINES = [
    "# Guide",
    "",
    "## Setup",
    "",
    "Install the tool with\tthe   installer script.",
    "Then run the checker once.",
    "",
    "## Parameters",
    "",
    "| name | value |",
    "| ---- | ----- |",
    *[f"| param_{k:02d} | value {k * 7} |" for k in range(40)],
    "",
    "- first item of the list",
    "  - nested detail of the first item",
    "- second item of the list",
    "",
    "```text",
    "inside the fenced block",
    "```",
    "",
    "## Repeated",
    "",
    "the same sentence again",
    "the same sentence again",
    "Then run the checker twice.",
    "",
]
DOC = "\n".join(DOC_LINES)


def _line(marker: str, text: str = DOC) -> int:
    hits = [n for n, line in enumerate(text.split("\n"), 1) if marker in line]
    assert len(hits) == 1, marker
    return hits[0]


def _resolve(entries, text=DOC, path="guide.md", field="pasos_de_instalacion_con_lineas", **kw):
    index = locate.build_index(text, path)
    return locate.resolve(locate.classify_field(field), entries, index, text, **kw)


# --- REQ-011: anchors ----------------------------------------------------------------------------


def test_a_unique_anchor_gives_its_line():
    (item,) = _resolve([{"name": "checker", "anchor": "Then run the checker once."}])
    assert (item.start, item.end, item.reason, item.source) == (
        _line("checker once"),
        _line("checker once"),
        None,
        "anchor",
    )
    assert item.name == "checker"


def test_blanks_are_normalized_but_case_is_kept():
    (same,) = _resolve([{"name": "x", "anchor": "  Install the tool with the installer script. "}])
    assert same.start == _line("Install the tool")
    (other_case,) = _resolve([{"name": "x", "anchor": "install the tool with the installer"}])
    assert (other_case.start, other_case.reason) == (None, "not_found")


def test_an_anchor_with_a_line_break_is_cut_at_the_first_one():
    (item,) = _resolve([{"name": "x", "anchor": "Then run the checker once.\nunrelated text"}])
    assert item.start == _line("checker once")


def test_anchor_end_is_the_first_line_after_the_start_that_holds_it():
    (item,) = _resolve(
        [{"name": "setup", "anchor": "Install the tool", "anchor_end": "the same sentence again"}]
    )
    assert (item.start, item.end) == (_line("Install the tool"), _line("## Repeated") + 2)
    assert not item.anchor_end_ignored


def test_an_anchor_end_found_only_before_is_ignored():
    (item,) = _resolve(
        [{"name": "x", "anchor": "Then run the checker twice.", "anchor_end": "Install the tool"}]
    )
    assert (item.start, item.end) == (_line("checker twice"), _line("checker twice"))
    assert item.anchor_end_ignored


def test_a_line_inside_a_table_gives_the_whole_table():
    (item,) = _resolve([{"name": "params", "anchor": "| param_17 | value 119 |"}])
    assert (item.start, item.end) == (_line("| name | value |"), _line("param_39"))


def test_a_line_inside_a_list_item_gives_the_item_and_a_fence_the_block():
    (item,) = _resolve([{"name": "first", "anchor": "first item of the list"}])
    assert (item.start, item.end) == (_line("first item of"), _line("nested detail"))
    (fence,) = _resolve([{"name": "code", "anchor": "inside the fenced block"}])
    assert (fence.start, fence.end) == (_line("```text"), _line("```text") + 2)


def test_a_line_that_starts_a_section_gives_the_section():
    (item,) = _resolve([{"name": "setup", "anchor": "## Setup"}])
    assert (item.start, item.end) == (_line("## Setup"), _line("checker once"))


def test_unlocated_anchors_say_why():
    items = _resolve(
        [
            {"name": "missing", "anchor": "this sentence is nowhere"},
            {"name": "twice", "anchor": "the same sentence again"},
            {"name": "short", "anchor": "  ab c "},
        ]
    )
    reasons = {it.name: (it.start, it.end, it.reason, it.candidates) for it in items}
    first = _line("## Repeated") + 2
    assert reasons == {
        "missing": (None, None, "not_found", ()),
        "twice": (None, None, "ambiguous", (first, first + 1)),
        "short": (None, None, "too_short", ()),
    }


def test_candidates_are_at_most_five():
    text = "\n".join(["# T", *["repeated line of text"] * 9])
    (item,) = _resolve([{"name": "r", "anchor": "repeated line of text"}], text=text)
    assert item.reason == "ambiguous"
    assert item.candidates == (2, 3, 4, 5, 6)


CODE = """import os


def load(path):
    # read the file and parse its header
    data = open(path).read()
    return data


class Store:
    def save(self, value):
        return value

    def init(self):
        return None


class Cache:
    def init(self):
        return 1
"""


def _resolve_code(entries, field="metodos_que_guardan_con_lineas", **kw):
    return _resolve(entries, text=CODE, path="store.py", field=field, **kw)


def test_an_anchor_on_a_whole_comment_line_of_code_is_in_comment():
    (item,) = _resolve_code([{"name": "lectura", "anchor": "read the file and parse its header"}])
    assert (item.start, item.reason) == (None, "in_comment")


def test_an_anchor_on_a_comment_line_of_text_is_not_in_comment():
    text = "# Title\n\n# a hash line that is a heading here\n"
    (item,) = _resolve([{"name": "x", "anchor": "a hash line that is a heading"}], text=text)
    assert item.start == 3


def test_a_line_that_starts_a_declaration_gives_the_declaration():
    (item,) = _resolve_code([{"name": "", "anchor": "class Store:"}])
    assert (item.start, item.end) == (_line("class Store", CODE), _line("return None", CODE))
    assert item.name == "class Store:"


def test_a_line_inside_a_body_gives_only_that_line():
    (item,) = _resolve_code([{"name": "", "anchor": "data = open(path).read()"}])
    assert (item.start, item.end) == (_line("data = open", CODE), _line("data = open", CODE))


# --- REQ-010 and REQ-011: names first --------------------------------------------------------------


def test_a_name_of_the_index_gives_its_lines():
    (full, segment) = _resolve_code([{"name": "Store.save"}, {"name": "load()"}])
    assert (full.name, full.start, full.end, full.source) == (
        "Store.save",
        _line("def save", CODE),
        _line("return value", CODE),
        "selection",
    )
    assert (segment.name, segment.start) == ("load", _line("def load", CODE))


def test_a_segment_shared_by_two_blocks_is_ambiguous():
    (item,) = _resolve_code([{"name": "init"}])
    inits = tuple(n for n, line in enumerate(CODE.split("\n"), 1) if "def init" in line)
    assert len(inits) == 2
    assert (item.start, item.reason, item.candidates) == (None, "ambiguous", inits)


def test_a_name_outside_the_index_is_not_in_index():
    (item,) = _resolve_code([{"name": "Store.delete"}])
    assert (item.start, item.end, item.reason) == (None, None, "not_in_index")


def test_the_name_wins_over_an_anchor_elsewhere_and_says_so():
    (item,) = _resolve_code([{"name": "Store.save", "anchor": "data = open(path).read()"}])
    assert (item.start, item.end) == (_line("def save", CODE), _line("return value", CODE))
    assert item.conflict
    (agree,) = _resolve_code([{"name": "Store.save", "anchor": "return value"}])
    assert not agree.conflict


def test_a_heading_is_matched_without_its_marks():
    (item,) = _resolve([{"name": "Parameters"}], field="seccion_con_lineas")
    assert (item.name, item.start) == ("## Parameters", _line("## Parameters"))


@pytest.mark.parametrize(
    "answer",
    [
        "Store.save: líneas 5-9",
        {"name": "Store.nothing", "start": 5, "end": 9},
        {"start": 5, "end": 9},
        [5, 9],
        5,
        {"name": "x", "anchor": "líneas 5-9"},
    ],
)
def test_a_number_the_model_wrote_never_gives_a_line(answer):
    items = _resolve_code([answer])
    for item in items:
        assert item.start is None and item.end is None


# --- REQ-013: pieces -----------------------------------------------------------------------------


def test_an_anchor_is_searched_in_its_piece_first():
    first, second = _line("## Repeated") + 2, _line("## Repeated") + 3
    (in_piece,) = _resolve(
        [{"name": "s", "anchor": "the same sentence again"}], piece_range=(second, second + 1)
    )
    assert (in_piece.start, in_piece.reason) == (second, None)
    (twice_in_piece,) = _resolve(
        [{"name": "s", "anchor": "the same sentence again"}], piece_range=(first, second)
    )
    assert (twice_in_piece.reason, twice_in_piece.candidates) == ("ambiguous", (first, second))
    (elsewhere,) = _resolve(
        [{"name": "s", "anchor": "Then run the checker once."}], piece_range=(first, second)
    )
    assert elsewhere.start == _line("checker once")


def test_merge_joins_pieces_without_repeats_in_file_order():
    a = locate.Item("b", 10, 12)
    b = locate.Item("a", 3, 4)
    lost = locate.Item("a", None, None, reason="not_found")
    other = locate.Item("z", None, None, reason="ambiguous", candidates=(1, 2))
    merged = locate.merge([[a, lost, other], [b, a, other]])
    assert [(it.name, it.start) for it in merged] == [("a", 3), ("b", 10), ("z", None)]


# --- REQ-009 and REQ-010: the program alone, or a choice -----------------------------------------


def test_answer_by_program_by_category_and_kind():
    index = locate.build_index(CODE, "store.py")
    functions = locate.answer_by_program(locate.classify_field("funciones_con_lineas"), index, CODE)
    assert [it.name for it in functions] == ["load", "Store.save", "Store.init", "Cache.init"]
    classes = locate.answer_by_program(locate.classify_field("clases_con_lineas"), index, CODE)
    assert [it.name for it in classes] == ["Store", "Cache"]
    every = locate.answer_by_program(locate.classify_field("declaraciones_con_lineas"), index, CODE)
    assert len(every) == 6


@pytest.mark.parametrize(
    "field",
    ["funcion_con_lineas", "heading_line", "funciones_que_guardan_con_lineas", "pasos_con_lineas"],
)
def test_a_singular_or_a_residual_or_no_category_needs_the_model(field):
    index = locate.build_index(CODE, "store.py")
    assert locate.answer_by_program(locate.classify_field(field), index, CODE) is None


def test_a_category_without_its_index_here_needs_the_model():
    index = locate.build_index(DOC, "guide.md")
    assert (
        locate.answer_by_program(locate.classify_field("funciones_con_lineas"), index, DOC) is None
    )
    assert locate.answer_by_program(locate.classify_field("secciones_con_lineas"), index, DOC)


def test_an_unavailable_index_needs_the_model_and_anchors_still_work():
    text = "def broken(:\n    unique marker line here\n"
    index = locate.build_index(text, "b.py")
    req = locate.classify_field("funciones_con_lineas")
    assert locate.answer_by_program(req, index, text) is None
    assert locate.selectable_names(req, index) == []
    (item,) = locate.resolve(req, [{"name": "x", "anchor": "unique marker line"}], index, text)
    assert (item.start, item.end, item.index) == (2, 2, "python")


def test_selectable_names_with_and_without_residual():
    index = locate.build_index(CODE, "store.py")
    names = locate.selectable_names(
        locate.classify_field("funciones_que_guardan_con_lineas"), index
    )
    assert names == ["load", "Store.save", "Store.init", "Cache.init"]
    assert locate.selectable_names(locate.classify_field("pasos_con_lineas"), index) == []
    md = locate.build_index(DOC, "guide.md")
    assert locate.selectable_names(locate.classify_field("heading_line"), md) == [
        "# Guide",
        "## Setup",
        "## Parameters",
        "## Repeated",
    ]


def test_the_catalogue_has_no_line_numbers_and_a_cap():
    index = locate.build_index(CODE, "store.py")
    text = locate.catalogue(index, 10_000)
    assert text.splitlines() == [
        "- function: load",
        "- class: Store",
        "- method: Store.save",
        "- method: Store.init",
        "- class: Cache",
        "- method: Cache.init",
    ]
    assert not any(ch.isdigit() for ch in text)
    assert locate.catalogue(index, len(text) - 1) == ""
    assert locate.catalogue(locate.build_index("plain words\n", "a.txt"), 10_000) == ""


def test_the_catalogue_of_a_markdown_leaves_out_tables_lists_and_fences():
    text = locate.catalogue(locate.build_index(DOC, "guide.md"), 10_000)
    assert text.splitlines() == [
        "- section: # Guide",
        "- section: ## Setup",
        "- section: ## Parameters",
        "- section: ## Repeated",
    ]


# --- REQ-018: section_only -----------------------------------------------------------------------


def test_section_only_over_items():
    index = locate.build_index(DOC, "guide.md")
    setup, params = _line("## Setup"), _line("## Parameters")
    sections = [locate.Item("a", setup, setup + 3), locate.Item("b", params + 2, params + 40)]
    tasks = locate.classify_field("tareas_con_lineas")
    assert locate.section_only(tasks, sections, index)
    items = [locate.Item("a", setup + 4, setup + 4)]
    assert not locate.section_only(tasks, items, index)
    assert not locate.section_only(locate.classify_field("secciones_con_lineas"), sections, index)
    assert not locate.section_only(
        locate.classify_field("tabla_de_pasos_con_lineas"), sections, index
    )
    assert not locate.section_only(tasks, [locate.Item("x", None, None)], index)


# --- line breaks and cost -------------------------------------------------------------------------


def test_a_lone_cr_keeps_read_lines():
    text = "# T\n\nfirst line\rstill the same line\nunique target sentence\n"
    (item,) = _resolve([{"name": "t", "anchor": "unique target sentence"}], text=text)
    assert item.start == text.split("\n").index("unique target sentence") + 1 == 4
    (inside,) = _resolve([{"name": "t", "anchor": "still the same line"}], text=text)
    assert inside.start == 3


def test_one_megabyte_under_a_second():
    unit = (
        "/** Doc of block {k}. */\n"
        "export class Block{k} {\n"
        "  value = `t ${1} }`;\n"
        "  run(a: string): void { if (a === '}') { return; } }\n"
        "  handle{k} = () => { /}/.test('x'); };\n"
        "}\n"
    )
    text = "".join(unit.replace("{k}", str(k)) for k in range(6500))
    assert len(text) > 1_000_000
    entries = [{"name": "", "anchor": f"handle{k} = () =>"} for k in range(0, 6500, 160)]
    assert len(entries) >= 40
    # the best of three CPU times: another process on the same core inflates one run, never all
    timings = []
    for _ in range(3):
        started = time.process_time()
        index = locate.build_index(text, "huge.ts")
        items = locate.resolve(
            locate.classify_field("manejadores_con_lineas"), entries, index, text
        )
        timings.append(time.process_time() - started)
    assert all(it.start is not None for it in items)
    assert min(timings) < 1.0, timings
