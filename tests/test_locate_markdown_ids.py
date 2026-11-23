"""REQ-005, REQ-006, REQ-007: the Markdown, diff and id indexes of `locate`, with exact lines.

The inputs are synthetic and carry the SHAPE of the reports (#696: a spec of ~55 KB with 60
requirements that cite each other; #697: a patch), never their content. Expected lines are
recorded while each fixture is built, never by reading the index under test.
"""

from __future__ import annotations

import time

import pytest

from local_delegate import line_check, locate


def _line_of(text: str, marker: str) -> int:
    """The only line that IS `marker`, or else the only one that holds it."""
    lines = text.split("\n")
    hits = [n for n, line in enumerate(lines, 1) if line == marker]
    hits = hits or [n for n, line in enumerate(lines, 1) if marker in line]
    assert len(hits) == 1, marker
    return hits[0]


# --- REQ-005: sections and blocks ----------------------------------------------------------------

DOC = """# Title

Intro line.

## Alpha

Alpha text.

### Alpha one

Deep text.

```python
# not a heading
x = {"a": 1}
```

## Beta

| key | value |
| --- | ----- |
| a   | 1     |
| b   | 2     |

- item one
  - nested one
    continuation of nested
- item two

  paragraph of item two

Closing paragraph.


# Second top

Last line.
"""


def _doc_blocks(kind: str) -> dict[str, locate.Block]:
    index = locate.build_index(DOC, "docs/a.md")
    assert index.language == "markdown"
    return {b.name: b for b in index.blocks if b.kind == kind}


def test_sections_end_before_the_next_heading_of_same_or_higher_level():
    sections = _doc_blocks("section")
    assert set(sections) == {"# Title", "## Alpha", "### Alpha one", "## Beta", "# Second top"}
    assert (sections["# Title"].start, sections["# Title"].end) == (
        1,
        _line_of(DOC, "Closing paragraph."),
    )  # the blank lines before `# Second top` are not part of it
    assert (sections["## Alpha"].start, sections["## Alpha"].end) == (
        _line_of(DOC, "## Alpha"),
        _line_of(DOC, "```python") + 3,
    )
    assert sections["### Alpha one"].end == sections["## Alpha"].end
    assert sections["## Beta"].end == _line_of(DOC, "Closing paragraph.")
    assert (sections["# Second top"].start, sections["# Second top"].end) == (
        _line_of(DOC, "# Second top"),
        _line_of(DOC, "Last line."),
    )
    # `# not a heading` inside the fence is no section
    assert all("not a heading" not in name for name in sections)


def test_blocks_at_a_line():
    index = locate.build_index(DOC, "docs/a.md")
    by_kind = {}
    for block in index.blocks:
        by_kind.setdefault(block.kind, []).append(block)
    (table,) = by_kind["table"]
    assert (table.start, table.end) == (_line_of(DOC, "| key |"), _line_of(DOC, "| b   |"))
    (fence,) = by_kind["fence"]
    assert (fence.start, fence.end) == (_line_of(DOC, "```python"), _line_of(DOC, "```python") + 3)
    items = {b.name: b for b in by_kind["list_item"]}
    assert (items["- item one"].start, items["- item one"].end) == (
        _line_of(DOC, "- item one"),
        _line_of(DOC, "continuation of nested"),
    )
    assert (items["- nested one"].start, items["- nested one"].end) == (
        _line_of(DOC, "- nested one"),
        _line_of(DOC, "continuation of nested"),
    )
    assert items["- item two"].end == _line_of(DOC, "paragraph of item two")


def test_a_plain_text_file_has_no_sections():
    index = locate.build_index(DOC, "notes.txt")
    assert index.language is None
    assert not [b for b in index.blocks if b.kind == "section"]
    assert [b for b in index.blocks if b.kind == "table"]


# --- REQ-007: ids --------------------------------------------------------------------------------


def _spec_with_sixty_requirements() -> tuple[str, dict[int, tuple[int, int]]]:
    """A Markdown of about 55 KB: 60 `- **REQ-0NN** — …` with nested bullets that cite other
    requirements, `MD013` and `UTF8` in the text, and a table of 40 rows. Returns the text and
    the (start, end) of each requirement, recorded while writing it."""
    out: list[str] = ["# Specification", "", "## Requirements", ""]
    expected: dict[int, tuple[int, int]] = {}
    filler = (
        "the rule holds for every input that the reader gives, with the encoding in UTF8 and "
        "the lint rule MD013 left as it is, and nothing else changes in the output "
    )
    for n in range(1, 61):
        start = len(out) + 1
        out.append(f"- **REQ-{n:03d}** — Requirement number {n}: {filler * 3}")
        out.append(f"  - Request: derived from REQ-{(n % 60) + 1:03d} and {filler}")
        out.append(f"    and its continuation line, see REQ-{((n + 6) % 60) + 1:03d}.")
        out.append(f"  - Verify: test `test_req_{n}` ({filler})")
        expected[n] = (start, len(out))
        out.append("")
    out += ["## Parameters", "", "| name | value | note |", "| --- | --- | --- |"]
    for row in range(40):
        out.append(f"| param_{row} | {row * 3} | applies to REQ-{(row % 60) + 1:03d} |")
    out += ["", "## Notes", "", "Closing words about MD013 and UTF8.", ""]
    text = "\n".join(out)
    assert 52_000 < len(text.encode()) < 62_000
    return text, expected


SIXTY_PICKS = [1, 2, 5, 9, 12, 17, 23, 30, 31, 38, 44, 47, 52, 59, 60]


def test_sixty_requirements_get_their_exact_lines():
    text, expected = _spec_with_sixty_requirements()
    index = locate.build_index(text, "spec.md")
    assert len(SIXTY_PICKS) == 15
    for n in SIXTY_PICKS:
        req = locate.classify_field(f"REQ_{n:03d}_linea")
        items = locate.answer_by_program(req, index, text)
        assert items is not None and len(items) == 1, n
        (item,) = items
        assert (item.name, item.start, item.end) == (f"REQ-{n:03d}", *expected[n]), n
        assert item.reason is None
        assert item.index == "ids"
    every = locate.answer_by_program(locate.classify_field("requisitos_con_lineas"), index, text)
    assert [it.name for it in every] == [f"REQ-{n:03d}" for n in range(1, 61)]
    assert [(it.start, it.end) for it in every] == [expected[n] for n in range(1, 61)]
    assert not any(it.name.startswith(("MD", "UTF")) for it in every)


def test_a_cited_id_without_definition_is_ambiguous():
    text = "# Doc\n\nWe cite ADR-007 here.\n\nAnd ADR-007 again, never defined.\n"
    (item,) = locate.answer_by_program(
        locate.classify_field("ADR_007_linea"), locate.build_index(text, "a.md"), text
    )
    assert (item.start, item.end, item.reason) == (None, None, "ambiguous")
    assert item.candidates == (3, 5)


def test_a_cited_id_seen_once_is_that_line():
    text = "# Doc\n\nOnly ADR-008 is cited here.\n"
    (item,) = locate.answer_by_program(
        locate.classify_field("ADR_008_linea"), locate.build_index(text, "a.md"), text
    )
    assert (item.start, item.end) == (3, 3)


def test_a_missing_id_is_not_found():
    text = "# Doc\n\nNothing.\n"
    (item,) = locate.answer_by_program(
        locate.classify_field("REQ_099_linea"), locate.build_index(text, "a.md"), text
    )
    assert (item.start, item.reason) == (None, "not_found")


@pytest.mark.parametrize("written", ["REQ-012", "REQ_012", "req-012", "REQ012"])
@pytest.mark.parametrize("field", ["REQ_012_linea", "req012_line_number"])
def test_id_case_and_separator_do_not_matter(written, field):
    text = f"# Doc\n\n- **{written}** — the one.\n  - nested\n\n- **REQ-013** — next.\n"
    (item,) = locate.answer_by_program(
        locate.classify_field(field), locate.build_index(text, "a.md"), text
    )
    assert (item.name, item.start, item.end) == ("REQ-012", 3, 4)


def test_a_heading_and_a_table_row_define_ids():
    text = "# Doc\n\n## D-01 First\n\nBody.\n\n| D-02 | second |\n| D-03 | third |\n"
    index = locate.build_index(text, "a.md")
    items = locate.answer_by_program(locate.classify_field("ids_con_lineas"), index, text)
    assert items == []  # `D-01` is not of strict form: one capital
    (one,) = locate.answer_by_program(locate.classify_field("D_01_linea"), index, text)
    assert (one.start, one.end) == (3, 8)  # its section runs to the end of the file
    (two,) = locate.answer_by_program(locate.classify_field("D_02_linea"), index, text)
    assert (two.start, two.end) == (7, 7)


def test_ids_are_offered_by_name():
    text, expected = _spec_with_sixty_requirements()
    index = locate.build_index(text, "spec.md")
    ids = {b.name: b for b in index.blocks if b.kind == "id"}
    assert len(ids) == 60
    assert (ids["REQ-030"].start, ids["REQ-030"].end) == expected[30]


def test_a_large_markdown_is_fast():
    parts = []
    for n in range(2500):
        parts.append(f"## Section {n}\n\n- **TASK-{n:04d}** — do it\n  - detail {n}\n")
        parts.append("| a | b |\n| - | - |\n| 1 | 2 |\n\nSome paragraph text here to fill.\n\n")
    text = "".join(parts) * 2
    assert len(text) > 400_000
    started = time.process_time()
    index = locate.build_index(text, "big.md")
    items = locate.answer_by_program(locate.classify_field("secciones_con_lineas"), index, text)
    assert time.process_time() - started < 2.0
    assert len(items) == 5000


# --- REQ-006: diff -------------------------------------------------------------------------------

PATCH = """Subject: [PATCH] two files

Some preamble that is not a diff.

diff --git a/src/a.ts b/src/a.ts
index 111..222 100644
--- a/src/a.ts
+++ b/src/a.ts
@@ -1,3 +1,4 @@
 one
+two
 three
 four
@@ -10,2 +11,2 @@ export function f() {
-old
+new
 same
diff --git a/docs/b.md b/docs/b.md
new file mode 100644
--- /dev/null
+++ b/docs/b.md
@@ -0,0 +1,2 @@
+# B
+--- not a header
--
2.40.0
"""


def test_the_diff_index_is_the_one_of_diff_file_hunks():
    index = locate.build_index(PATCH, "changes.patch")
    assert index.language == "diff"
    expected = line_check.diff_file_hunks(PATCH)
    assert len(expected) == 2
    got = [(b.start, b.end, b.name, list(b.hunks)) for b in index.blocks]
    assert got == expected
    assert all(b.kind == "file" and b.top_level for b in index.blocks)
    assert index.blocks[0].start == _line_of(PATCH, "diff --git a/src/a.ts")


def test_a_file_that_starts_as_a_diff_is_one_without_suffix():
    body = PATCH[PATCH.index("diff --git") :]
    assert locate.build_index(body, "changes.txt").language == "diff"
    assert locate.build_index(body, "notes.md").language == "markdown"


@pytest.mark.parametrize(
    "field", ["ficheros_con_lineas", "lista_de_ficheros_con_sus_lineas", "files_with_lines"]
)
def test_file_fields_over_a_patch_get_every_file(field):
    index = locate.build_index(PATCH, "changes.patch")
    items = locate.answer_by_program(locate.classify_field(field), index, PATCH)
    assert [(it.name, it.start, it.end) for it in items] == [
        (path, first, last) for first, last, path, _ in line_check.diff_file_hunks(PATCH)
    ]
    assert all(it.source == "program" and it.index == "diff" for it in items)


def test_hunks_come_with_the_files_when_asked():
    index = locate.build_index(PATCH, "changes.patch")
    req = locate.classify_field("ficheros_y_hunks_con_lineas")
    value = locate.to_value(req, locate.answer_by_program(req, index, PATCH))
    assert value[0]["hunks"] == [
        [_line_of(PATCH, "@@ -1,3"), _line_of(PATCH, "@@ -10,2") - 1],
        [_line_of(PATCH, "@@ -10,2"), _line_of(PATCH, "@@ -10,2") + 3],
    ]


def test_a_patch_without_files_is_left_to_the_model():
    text = "just some words\nin a patch file\n"
    index = locate.build_index(text, "empty.patch")
    assert index.language == "diff" and index.blocks == ()
    assert (
        locate.answer_by_program(locate.classify_field("ficheros_con_lineas"), index, text) is None
    )
