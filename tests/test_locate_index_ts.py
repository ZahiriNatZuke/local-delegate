"""REQ-004, REQ-013 and REQ-022: the TS/JS index of `locate` (`locate_ts`), with exact lines.

Inputs are synthetic with the SHAPE of the reports (#698: a `.ts` of 906 lines and 60 functions
and methods; #694: an Angular component with a JSDoc of bullets), never their content. Expected
lines are recorded while each fixture is written, never read from the index under test.
"""

from __future__ import annotations

import perf
import pytest

from local_delegate import locate

#: Ten times the input: linear grows ~10x, quadratic ~100x (`tests/perf.py`).
SIZE_RATIO = 10

FUNCTION_KINDS = {"function", "method", "function_property"}


def _big_ts() -> tuple[str, dict[str, tuple[str, int, int]]]:
    """A `.ts` of exactly 906 lines: 15 module functions and a class with 45 function members
    (methods, accessors, arrow and `computed`/`signal` properties), plus a second class, two
    interfaces, a type, constants and plain properties that are not functions."""
    out: list[str] = []
    expected: dict[str, tuple[str, int, int]] = {}

    def add(line: str) -> int:
        out.append(line)
        return len(out)

    add("import { Injectable, computed, signal } from '@angular/core';")
    add("")
    start = add("export interface Step {")
    add("  id: string;")
    expected["Step"] = ("type", start, add("}"))
    start = add("export interface Order { ids: string[] }")
    expected["Order"] = ("type", start, start)
    start = add("export type StepId = string | number;")
    expected["StepId"] = ("type", start, start)
    start = add("export const MAX_STEPS = 40;")
    expected["MAX_STEPS"] = ("variable", start, start)
    start = add("const PATTERN = /\\{[^}]*\\}/g;")
    expected["PATTERN"] = ("variable", start, start)
    add("")
    for k in range(15):
        add("/**")
        add(f" * Helper {k} " + "{ with a brace in its JSDoc.")
        add(" * - a bullet: `onSaveOrder()` is not here")
        add(" */")
        start = add(f"export function helper{k}(a: {{ x: number }}): {{ y: number }} {{")
        add("  const text = `value ${a.x} } and ${ `inner ${'{'}` }`;")
        add("  // a } in a comment")
        add(f"  return {{ y: a.x + {k} }};")
        expected[f"helper{k}"] = ("function", start, add("}"))
        add("")
    start = add("@Injectable({ providedIn: 'root' })")
    add("export class StepsService {")
    add("  private readonly cache = new Map<string, Step>();")
    expected["StepsService.cache"] = ("property", len(out), len(out))
    add("  count = 0;")
    expected["StepsService.count"] = ("property", len(out), len(out))
    class_start = start
    for k in range(25):
        add(f"  /** Method {k}. */")
        s = add(f"  async method{k}(id: string, options?: {{ force: boolean }}): Promise<void> {{")
        add("    if (id === '}') { return; }")
        add(f"    await this.load(id, {k});")
        add("    const re = /}/;")
        expected[f"StepsService.method{k}"] = ("method", s, add("  }"))
    for k in range(10):
        s = add(f"  handler{k} = (event: Event) => {{")
        add("    event.preventDefault();")
        expected[f"StepsService.handler{k}"] = ("function_property", s, add("  };"))
    for k in range(5):
        s = add(f"  total{k} = computed(() => this.count + {k});")
        expected[f"StepsService.total{k}"] = ("function_property", s, s)
    for k in range(5):
        s = add(f"  get size{k}(): number {{")
        add(f"    return this.cache.size + {k};")
        expected[f"StepsService.size{k}"] = ("method", s, add("  }"))
    expected["StepsService"] = ("class", class_start, add("}"))
    add("")
    start = add("export class Plain {")
    add("  name = 'plain';")
    expected["Plain.name"] = ("property", len(out), len(out))
    expected["Plain"] = ("class", start, add("}"))
    while len(out) < 905:
        add("// trailing comment line")
    add("")
    text = "\n".join(out) + "\n"
    assert len(text.split("\n")) - 1 == 906
    return text, expected


def test_a_big_file_gives_every_declaration_with_its_exact_lines():
    text, expected = _big_ts()
    index = locate.build_index(text, "src/app/steps.service.ts")
    assert index.language == "typescript"
    assert index.unavailable_reason is None
    got = {b.name: (b.kind, b.start, b.end) for b in index.blocks}
    assert got == expected
    functions = [name for name, (kind, _, _) in expected.items() if kind in FUNCTION_KINDS]
    assert len(functions) == 60


def test_functions_with_lines_is_exactly_the_sixty_functions_and_methods():
    text, expected = _big_ts()
    index = locate.build_index(text, "steps.service.ts")
    items = locate.answer_by_program(locate.classify_field("funciones_con_lineas"), index, text)
    want = sorted(
        (start, end, name)
        for name, (kind, start, end) in expected.items()
        if kind in FUNCTION_KINDS
    )
    assert sorted((it.start, it.end, it.name) for it in items) == want
    assert len(items) == 60
    assert all(it.source == "program" and it.index == "typescript" for it in items)


COMPONENT = """import { Component, computed, signal } from '@angular/core';

/**
 * Panel de pasos:
 * - localOrder: el orden local de los pasos
 * - orderDirty: si el orden cambió
 * - onSaveOrder(): guarda el orden { y avisa }
 * - onDiscardOrder(): descarta
 */
@Component({
  selector: 'app-steps-panel',
  template: `
    <div class="bar" *ngIf="orderDirty()">
      <button (click)="onSaveOrder()">{{ 'Guardar' }}</button>
    </div>
  `,
})
export class StepsPanel {
  /**
   * El orden local.
   * - una viñeta
   */
  localOrder = signal<string[]>([]);

  /** Si hay cambios sin guardar. */
  orderDirty = computed(() => this.localOrder().length > 0);

  /**
   * Guarda.
   */
  onSaveOrder(): void {
    const ids = this.localOrder();
    this.api.save(ids, `orden ${ids.join('}')}`);
  }

  // Descarta.
  onDiscardOrder(): void {
    this.localOrder.set([]);
  }
}
"""


def test_a_component_with_jsdoc_bullets():
    lines = COMPONENT.split("\n")
    index = locate.build_index(COMPONENT, "steps-panel.component.ts")
    blocks = {b.name: b for b in index.blocks}

    def line(marker: str) -> int:
        (hit,) = [n for n, text in enumerate(lines, 1) if text.startswith(marker)]
        return hit

    assert (blocks["StepsPanel.localOrder"].start, blocks["StepsPanel.localOrder"].end) == (
        line("  localOrder ="),
        line("  localOrder ="),
    )
    assert blocks["StepsPanel.orderDirty"].start == line("  orderDirty =")
    assert blocks["StepsPanel.orderDirty"].kind == "function_property"
    assert (blocks["StepsPanel.onSaveOrder"].start, blocks["StepsPanel.onSaveOrder"].end) == (
        line("  onSaveOrder()"),
        line("  onSaveOrder()") + 3,
    )
    assert (
        blocks["StepsPanel.onDiscardOrder"].start,
        blocks["StepsPanel.onDiscardOrder"].end,
    ) == (line("  onDiscardOrder()"), line("  onDiscardOrder()") + 2)
    assert blocks["StepsPanel"].start == line("@Component(")
    # no entry starts inside a JSDoc or on a comment line, and every JSDoc line is a comment line
    jsdoc = {n for n, text in enumerate(lines, 1) if text.strip().startswith(("/**", "*", "//"))}
    assert jsdoc <= index.comment_lines
    assert all(b.start not in index.comment_lines for b in index.blocks)


@pytest.mark.parametrize(
    "tricky",
    [
        "const s = '}';",
        'const s = "{{";',
        "const s = `}${'{'}`;",
        "const s = `a ${ `b ${ '}' } }` } c`;",
        "const re = /[}]{2}/g;",
        "const re = /\\}/;",
        "// } in a line comment",
        "/* { in a block comment */",
        "/*\n   } across lines\n*/",
        "const x = a / b / c; // division, not a regex: }",
    ],
)
def test_braces_inside_strings_templates_regex_and_comments_do_not_move_any_end(tricky):
    text = (
        "export function first(): void {\n"
        f"  {tricky}\n"
        "}\n"
        "\n"
        "export function second(): number {\n"
        "  return 2;\n"
        "}\n"
    )
    lines = text.split("\n")
    index = locate.build_index(text, "x.ts")
    assert index.unavailable_reason is None, tricky
    blocks = {b.name: (b.start, b.end) for b in index.blocks}
    closing = [n for n, t in enumerate(lines, 1) if t == "}"]
    assert blocks["first"] == (1, closing[0]), tricky
    assert blocks["second"] == (closing[0] + 2, closing[1]), tricky


def test_unbalanced_braces_drop_the_index():
    text = "export function broken() {\n  if (x) {\n    return 1;\n}\n"
    index = locate.build_index(text, "broken.ts")
    assert index.language == "typescript"
    assert index.blocks == ()
    assert index.unavailable_reason == "unbalanced"
    assert (
        locate.build_index("const s = `never closed\n", "t.js").unavailable_reason == "unbalanced"
    )
    assert locate.build_index("/* never closed\n", "t.mjs").unavailable_reason == "unbalanced"


@pytest.mark.parametrize("blank", [" ", " ", "　"])
def test_a_unicode_blank_is_skipped_like_a_space(blank):
    """A Unicode blank before `{`, `}`, a regex or a string is a blank, never a word: the index is
    the one of the same text with plain spaces."""
    template = (
        "export function first(a: number){B}{{\n"
        "  const r ={B}/}}/;\n"
        "  const s ={B}'}}';\n"
        "  return a;{B}}}\n"
        "export class Second {{\n"
        "  run(){B}{{ return `x`; }}\n"
        "}}\n"
    )
    with_blank = locate.build_index(template.format(B=blank), "u.ts")
    with_space = locate.build_index(template.format(B=" "), "u.ts")
    assert with_space.unavailable_reason is None
    assert [(b.name, b.start, b.end) for b in with_space.blocks] == [
        ("first", 1, 4),
        ("Second", 5, 7),
        ("Second.run", 6, 6),
    ]
    assert with_blank.unavailable_reason is None
    assert with_blank.blocks == with_space.blocks


def test_module_declarations_of_every_form():
    text = (
        "export default class {\n}\n"
        "export const enum Mode { A, B }\n"
        "export async function* gen() {\n  yield 1;\n}\n"
        "declare function declared(a: string): void;\n"
        "export const arrow = async (x: number) => {\n  return x;\n};\n"
        "let plain = { a: 1 };\n"
        "type Pair<T> = {\n  a: T;\n  b: T;\n};\n"
    )
    index = locate.build_index(text, "forms.tsx")
    got = {b.name: (b.kind, b.start, b.end) for b in index.blocks}
    assert got == {
        "default": ("class", 1, 2),
        "Mode": ("type", 3, 3),
        "gen": ("function", 4, 6),
        "declared": ("function", 7, 7),
        "arrow": ("function", 8, 10),
        "plain": ("variable", 11, 11),
        "Pair": ("type", 12, 15),
    }


def test_pieces_cut_at_top_level_blocks():
    text, expected = _big_ts()
    small = "\n".join(
        f"export function f{k}(a: number): number {{\n  return a + {k};\n}}\n" for k in range(300)
    )
    index = locate.build_index(small, "small.ts")
    top = {b.start for b in index.blocks if b.top_level}
    pieces = locate.split_at_blocks(small, index, 2000)
    assert len(pieces) > 5
    lines = locate._lines(small)
    previous_end = 0
    for piece, (first, last) in pieces:
        assert first == previous_end + 1
        assert first == 1 or first in top
        assert len(piece) <= 2000
        assert piece == "\n".join(lines[first - 1 : last])
        previous_end = last
    assert previous_end == len(lines)
    # a class longer than the budget is cut before its members, never inside one; only the run of
    # trailing comment lines after the last class, longer than the budget too, is cut by lines
    index = locate.build_index(text, "big.ts")
    starts = {b.start for b in index.blocks}
    pieces = locate.split_at_blocks(text, index, 3000)
    last_class_end = expected["Plain"][2]
    inside = [first for _, (first, _) in pieces if first <= last_class_end]
    assert len(inside) > 5
    assert all(first == 1 or first in starts for first in inside)
    assert pieces[-1][1][1] == len(locate._lines(text))
    assert all(len(piece) <= 3000 for piece, _ in pieces)


def _classes_of_ts(units: int) -> str:
    unit = (
        "/** Doc { */\n"
        "export class C{k} {{\n"
        "  value = `t ${{1}} }}`;\n"
        "  run(a: string): void {{ if (a === '}}') {{ return; }} }}\n"
        "  handle = () => {{ /}}/.test('x'); }};\n"
        "}}\n"
    )
    return "".join(
        unit.replace("{k}", str(k)).replace("{{", "{").replace("}}", "}") for k in range(units)
    )


@pytest.mark.perf
def test_typescript_index_cost_grows_linearly():
    """REQ-022: indexing 1 MB costs about ten times 100 KB, never the hundred of a quadratic
    cost."""
    small_text, big_text = _classes_of_ts(680), _classes_of_ts(680 * SIZE_RATIO)
    assert len(small_text) > 100_000 and len(big_text) > 1_000_000
    index = locate.build_index(big_text, "huge.ts")
    assert index.unavailable_reason is None
    assert len(index.blocks) == 6800 * 4
    perf.assert_linear(
        lambda: locate.build_index(small_text, "huge.ts"),
        lambda: locate.build_index(big_text, "huge.ts"),
        size_ratio=SIZE_RATIO,
    )
