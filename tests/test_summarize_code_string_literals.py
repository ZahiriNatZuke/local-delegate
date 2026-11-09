"""#539: `local_summarize` over code does not turn the lines of its string literals into headings.

The issue: a `node:test` file (~6.9 KB, so the `long` role) builds a Markdown document inside a
template literal (`## Specs`, `## Tasks`, `## Log`, a `field: ${variable}` line over `---`). The
structured path (`sections.detect`) took those lines for the sections of the file, gave them to the
model as the list to follow and `sections.complete` put back the ones the model left out: the
summary came out with the fixture as its structure and the test cases under `## Verify`, with no
warning. The fixture here is synthetic, with the shape of the issue.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2

from local_delegate import config, sections, server

FIXTURE_DOC = """\
function sddDocument(slug, status) {
  return `# Change ${slug}

state: ${status}
---

## Specs

- REQ-001 the thing

## Plan

1. do it

## Tasks

- [ ] T1

## Log

- L1 started

## Verify

- run the suite
`;
}
"""


def _test_case(n: int) -> str:
    return (
        f"test('case {n}: a change in state {n} reports its status', async () => {{\n"
        f"  const doc = sddDocument('slug-{n}', 'state-{n}');\n"
        f"  const result = await check(doc, {{ strict: {str(n % 2 == 0).lower()} }});\n"
        f"  assert.equal(result.status, 'state-{n}');\n"
        f"  assert.ok(result.sections.includes('Specs'), 'the specs section is found');\n"
        f"  assert.deepEqual(result.warnings, []);\n"
        "});\n\n"
    )


MJS = (
    "import { test } from 'node:test';\n"
    "import assert from 'node:assert/strict';\n"
    "import { check } from '../src/check.mjs';\n\n"
    + FIXTURE_DOC
    + "\n"
    + "".join(_test_case(n) for n in range(1, 21))
)

#: What the model did in the issue: the fixture lines as headings, the tests under the last one.
COPYING_SUMMARY = (
    "## state: ${status}\n\nThe document of a change.\n\n## Specs\n\nRequirements.\n\n"
    "## Verify\n\n- case 1: reports its status\n- case 2: reports its status\n"
)
#: A correct summary of the same file: prose, no heading from the fixture.
GOOD_SUMMARY = (
    "The file tests `check` with 20 cases; each builds an SDD document and checks its status."
)

MARKDOWN_DOC = """\
# Guide

Use `uv` to install. Press the ` key to open the console, then run `make`.

## Install

Run `uv tool install local-delegate-mcp`. The '''quotes''' here are prose.

```js
const doc = `
## Not a heading
`;
```

## Configure

Set `LOCAL_DELEGATE_LOG` (it's optional) and "restart" the daemon.

## Use

Call the tool with `path`.
"""


@backend_mock.mock
def _summarize(monkeypatch, tmp_path, answer: str, *, structured: bool = True, **kwargs):
    # The issue's file is above `LONG_INPUT_CHARS` (6000): the `long` role, where the structured
    # path lives. The switch is on here, as the structured tests do.
    monkeypatch.setattr(config, "STRUCTURED_SUMMARY", structured)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    return server.local_summarize(**kwargs), seen


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


# --- The scanner -----------------------------------------------------------------------------------


def test_the_fixture_has_the_shape_of_the_issue():
    assert config.LONG_INPUT_CHARS < len(MJS) < config.max_chars_for_role("long")
    # Without the fix this is what the structured path saw as the structure of the file.
    assert sections.detect(MJS) is not None


def test_lines_inside_a_template_literal_are_found():
    inside = sections.string_literal_lines(MJS)
    assert "## Specs" in inside
    assert "state: ${status}" in inside
    assert "## Verify" in inside
    # The code around the literal is not part of it: neither the opening nor the closing line.
    assert not any("function sddDocument" in line or line.startswith("test(") for line in inside)
    assert "  return `# Change ${slug}" not in inside


def test_lines_inside_a_python_triple_quoted_string_are_found():
    source = 'FIXTURE = """\n## Specs\n\nbody\n"""\n\n\ndef test_it():\n    assert True\n'
    assert sections.string_literal_lines(source) == ["## Specs", "", "body"]


def test_markdown_prose_with_stray_backticks_and_quotes_has_no_literal_lines():
    # A lone backtick, inline code, an apostrophe and a fence with a template inside: the fence is
    # skipped and nothing in the prose opens a literal that swallows the real headings.
    inside = sections.string_literal_lines(MARKDOWN_DOC)
    assert "## Install" not in inside
    assert "## Configure" not in inside
    assert "## Use" not in inside


def test_copied_headings_are_named_once_in_output_order():
    output = COPYING_SUMMARY + "\n## Specs\n\nagain\n"
    assert sections.string_literal_headings(output, MJS, kind="code") == [
        "state: ${status}",
        "Specs",
        "Verify",
    ]


def test_a_heading_with_an_unresolved_interpolation_counts_only_in_a_code_file():
    # Outside any literal (a broken one the scanner cannot see), the `${...}` is the strong signal,
    # and only for a code file.
    source = "const x = 1;\nconsole.log('field: ${variable}')\n"
    output = "## field: ${variable}\n\ntext\n"
    assert sections.string_literal_headings(output, source, kind="code") == ["field: ${variable}"]
    assert sections.string_literal_headings(output, source, kind="unknown") == []


def test_a_good_summary_of_the_code_has_no_copied_heading():
    assert sections.string_literal_headings(GOOD_SUMMARY, MJS, kind="code") == []
    named = "## Test cases\n\n- case 1\n\n## Helpers\n\n`sddDocument` builds a document.\n"
    assert sections.string_literal_headings(named, MJS, kind="code") == []


# --- local_summarize end to end, with a fake backend -----------------------------------------------


def test_a_code_file_does_not_take_the_structured_path(monkeypatch, tmp_path):
    path = _write(tmp_path, "check.test.mjs", MJS)
    output, seen = _summarize(
        monkeypatch,
        tmp_path,
        GOOD_SUMMARY,
        path=str(path),
        max_words=250,
        focus="list each test case: input situation and expected outcome",
    )
    (payload,) = seen
    system, user = payload["messages"][0]["content"], payload["messages"][1]["content"]
    assert "Secciones, en orden" not in user
    assert "un resumen en prosa clara" in system
    assert user == f"Resume el siguiente contenido:\n\n{MJS}"
    # No heading was put back by `sections.complete`, and a correct summary carries no warning.
    assert "## Specs" not in output
    assert server.WARNING_MARKER not in output
    assert output.startswith(GOOD_SUMMARY)


def test_a_summary_that_copies_the_fixture_is_warned(monkeypatch, tmp_path):
    path = _write(tmp_path, "check.test.mjs", MJS)
    output, _seen = _summarize(monkeypatch, tmp_path, COPYING_SUMMARY, path=str(path))
    assert server.WARNING_MARKER in output
    warning = output[output.index(server.WARNING_MARKER) :]
    assert "«state: ${status}»" in warning
    assert "«Specs»" in warning
    assert "«Verify»" in warning
    # The notice goes before the savings receipt, which stays the last thing.
    assert output.rstrip().endswith("que no entraron a tu contexto)")
    assert output.index(server.WARNING_MARKER) < output.index("(leído server-side")


def test_inline_code_on_the_structured_path_is_warned(monkeypatch, tmp_path):
    # Without `path` there is no extension: the text still takes the structured path, and the
    # guard is what tells the caller that the headings came from a string literal.
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 0)
    output, seen = _summarize(monkeypatch, tmp_path, COPYING_SUMMARY, text=MJS)
    assert "Secciones, en orden" in seen[0]["messages"][1]["content"]
    assert server.WARNING_MARKER in output
    assert "«Specs»" in output[output.index(server.WARNING_MARKER) :]


def test_a_real_markdown_document_is_not_warned(monkeypatch, tmp_path):
    # The false-positive control: a correct structured summary of a real `.md`, with stray
    # backticks, inline code, quotes and a fence holding a template literal.
    monkeypatch.setattr(config, "LONG_INPUT_CHARS", 0)
    path = _write(tmp_path, "guide.md", MARKDOWN_DOC)
    answer = (
        "## Install\n\nInstall it with uv tool install.\n\n"
        "## Configure\n\nSet the log variable and restart the daemon.\n\n"
        "## Use\n\nCall the tool with a path.\n"
    )
    output, seen = _summarize(monkeypatch, tmp_path, answer, path=str(path))
    assert "Secciones, en orden" in seen[0]["messages"][1]["content"]
    assert server.WARNING_MARKER not in output


# --- Review of the PR: time, docstrings and real headings ----------------------------------------


def test_the_scan_is_linear_on_a_long_line_of_literals():
    """Copying the line up to each backtick made it quadratic: 1.2 MB of `x=`a`;` on one line
    took 9.4 s and 2.4 MB 73 s. The test compares how the time grows instead of a fixed number
    of seconds: four times the input costs about four times as much when linear and about
    sixteen when quadratic. A busy CI runner can slow one measurement, so the two sizes are
    timed alternately (best of five each) and a round that lands under the bound is enough out
    of three; a quadratic scan misses it in every round."""
    import time

    def timed(text: str) -> float:
        start = time.perf_counter()
        sections.string_literal_headings("## a\n\ntext\n", text, kind="code")
        return time.perf_counter() - start

    for unit in ("x=`a`;", '"a`"', "f(`a`, '`', \"`\");"):
        small = unit * (500_000 // len(unit))
        big = small * 4
        rounds = []
        for _ in range(3):
            small_times, big_times = [], []
            for _ in range(5):
                small_times.append(timed(small))
                big_times.append(timed(big))
            rounds.append((min(small_times), min(big_times)))
            if rounds[-1][1] < 9 * rounds[-1][0]:
                break
        assert rounds[-1][1] < 9 * rounds[-1][0], (unit, rounds)


PY_MODULE_DOCSTRING = '''\
"""Tools to sync the mirror.

Uso
---

Run it from cron.

## Configuración

Set MIRROR_URL.
"""


def sync(url):
    """Sync one mirror.

    Parameters
    ----------
    url : str
        Where to read.

    Returns
    -------
    int
        Files copied.

    Examples
    --------
    >>> sync("x")

    Notes
    -----
    Idempotent.
    """
    return 0
'''


def test_python_docstrings_are_not_data():
    # Module docstring with sections (setext and ATX) and a numpy-style function docstring: they
    # document the code, and a summary that uses their sections as headings is not warned.
    assert sections.string_literal_lines(PY_MODULE_DOCSTRING) == []
    output = (
        "## Uso\n\nFrom cron.\n\n## Configuración\n\nMIRROR_URL.\n\n"
        "## Parameters\n\nurl.\n\n## Returns\n\nint.\n\n## Examples\n\nsync.\n\n## Notes\n\nok\n"
    )
    assert sections.string_literal_headings(output, PY_MODULE_DOCSTRING, kind="code") == []


def test_a_python_string_assigned_to_a_name_is_still_data():
    source = PY_MODULE_DOCSTRING + '\n\nFIXTURE = """\n## Specs\n\nbody\n"""\n'
    output = "## Uso\n\nFrom cron.\n\n## Specs\n\nbody\n"
    assert sections.string_literal_headings(output, source, kind="code") == ["Specs"]


MARKDOWN_WITH_EXAMPLE = """\
# Proyecto

## Instalación

Con uv.

## Uso

```js
const readme = `
## Uso

Llama a la función.
`;
```

## Licencia

MIT.
"""


def test_a_real_heading_also_in_a_fenced_template_is_not_warned():
    output = "## Instalación\n\nCon uv.\n\n## Uso\n\nUn ejemplo en JS.\n\n## Licencia\n\nMIT.\n"
    for kind in ("prose", "unknown"):
        assert sections.string_literal_headings(output, MARKDOWN_WITH_EXAMPLE, kind=kind) == []


def test_a_heading_only_in_the_fenced_template_is_still_warned():
    source = MARKDOWN_WITH_EXAMPLE.replace("const readme = `\n## Uso", "const readme = `\n## Demo")
    output = "## Uso\n\nUn ejemplo.\n\n## Demo\n\nCopiado.\n"
    assert sections.string_literal_headings(output, source, kind="prose") == ["Demo"]


def test_an_unclosed_backtick_in_a_markdown_paragraph_does_not_cross_the_line():
    # `y = `x` opens a "template" by the opener rule; in a Markdown file it ends with its line, so
    # the headings below are not taken for its content.
    source = "# Doc\n\nSet y = `x and go on.\n\n## Paso uno\n\nA.\n\n## Paso dos\n\nB.\n"
    assert sections.string_literal_lines(source, prose=True) == []
    output = "## Paso uno\n\nA.\n\n## Paso dos\n\nB.\n"
    assert sections.string_literal_headings(output, source, kind="prose") == []
