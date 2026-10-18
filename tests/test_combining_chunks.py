"""B2e: what is lost when the chunks of a map-reduce are combined (front B).

Born of `evidence/B2e/research.md` and its probes (`evidence/B2e/probes/`), which failed on `main`:

1. `local_explain_code` loses what a function registers (`sub.add_parser("doctor")`): the reduce
   inventory now carries the registered names, computed with `ast`.
2. The chunked `local_lint_summary` lost the format of the tool: its reduce asked for prose that
   does not enumerate. It now has its own reduce, with the lint format and an inventory of the
   files and rule codes of the log, without counts.
3. The usage log records every step of a chunked operation (kind, `chars_out`, `finish_reason`),
   never its text; the text goes only to the local dump of `LOCAL_DELEGATE_DUMP_CHUNK_NOTES`.
4. Four cases of the fidelity counter (`scripts/score_lint_fidelity.py`).

The backend is faked (`_run_chat`): no network. Each block names the mutant that makes it fail
(recorded in `evidence/B2e/mutants.json`).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from local_delegate import config, i18n, lint_patterns, server

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fidelity = _load_script("score_lint_fidelity")


@pytest.fixture
def captured(monkeypatch, tmp_path) -> list[dict]:
    """`_run_chat` doubled: the `system`, `user` and `max_tokens` of every call; log in tmp."""
    calls: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        result = server.ChatResult(text="- nota", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "DUMP_CHUNK_NOTES_DIR", None)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return calls


def _rows(tmp_path: Path, tool: str) -> list[dict]:
    return [
        json.loads(line)
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["tool"] == tool
    ]


# --- 1. explain_code: the registered names ------------------------------------------------------


def _cli_like(n_subcommands: int, filler_defs: int) -> str:
    filler = "".join(
        f"def helper_{i}(x):\n    '''Helper {i}.'''\n    return x + {i}  # " + "z" * 300 + "\n\n"
        for i in range(filler_defs)
    )
    subs = "".join(f'    sub.add_parser("cmd-zz{i}", help="h")\n' for i in range(n_subcommands))
    return filler + "def build_parser():\n    sub = make()\n" + subs + "    other.add_parser(sub)\n"


def test_the_explain_reduce_inventory_names_the_registered_subcommands(captured):
    """Mutant "the inventory of today" (`registered = ""`): the subcommands assert fails, not the
    guard that there was a reduce with its inventory."""
    code = _cli_like(14, 220)
    assert len(code) > config.max_chars_for_role("code")
    server.local_explain_code(code=code)
    assert len(captured) > 2  # guard: it really chunked
    reduce_user = captured[-1]["user"]
    assert "build_parser" in reduce_user  # guard: the inventory is there
    assert all(f"cmd-zz{i}" in reduce_user for i in range(14))
    assert "lo que registra el módulo `other`" in reduce_user


TODAY_REDUCE = (
    "Estas son notas EN ORDEN sobre los fragmentos de un mismo fichero de código. La lista de "
    "arriba es el inventario COMPLETO de sus definiciones de primer nivel; las notas pueden no "
    "cubrirlo entero. Explica el fichero completo:\n\n"
)


def test_a_file_without_registrations_keeps_the_inventory_of_today_byte_for_byte(captured):
    """Control: no `add_parser` in the file, so the reduce prompt is the one of `main`."""
    code = _cli_like(0, 220).replace("    other.add_parser(sub)\n", "    return sub\n")
    assert "add_parser" not in code
    server.local_explain_code(code=code)
    assert len(captured) > 2
    budget = server._map_budget(config.max_chars_for_role("code"))
    names = server._format_names(server._TOP_LEVEL_NAME.findall(code), int(budget * 0.25))
    joined = "\n\n".join(["- nota"] * (len(captured) - 1))  # one note per map call
    assert captured[-1]["user"] == f"{names}\n\n{TODAY_REDUCE}{joined}"


def test_registered_names_come_from_ast_with_their_function():
    code = (
        "import argparse\n\n"
        "def build(sub):\n"
        '    sub.add_parser("serve")\n'
        '    x = sub.add_parser("doctor", help="h")\n'
        "    bench.add_parser(sub)\n"
        "    def nested(s):\n"
        '        s.add_parser("inner")\n'
        '\nroot.add_parser("top")\n'
    )
    assert server._registered_names(code) == [
        ("build", ["serve", "doctor"], ["bench"]),
        ("nested", ["inner"], []),
        (None, ["top"], []),
    ]
    assert server._registered_names("def broken(:\n") == []
    assert server._registered_names("def f():\n    return 1\n") == []


def test_the_registered_inventory_is_cut_with_its_count():
    registered = [("build", [f"name-{i}" for i in range(50)], ["bench"])]
    text = server._format_registered(registered, 200)
    assert len(text) <= 200
    assert re.search(r" y \d+ más$", text)
    assert server._format_registered([], 200) == ""


# --- 2. lint_summary: the reduce keeps the lint format ------------------------------------------


def _ruff_log(files: int, per_file: int) -> str:
    rules = [
        "CPY001 Missing copyright notice",
        "D401 First line of docstring",
        "S603 subprocess call",
    ]
    return (
        "".join(
            f"src/pkg/mod_{f:02d}.py:{n + 1}:1: {rules[n % 3]}\n"
            for f in range(files)
            for n in range(per_file)
        )
        + f"Found {files * per_file} errors.\n"
    )


@pytest.mark.parametrize("product", ["es", "en"])
def test_the_chunked_lint_reduce_keeps_the_lint_format(monkeypatch, captured, product):
    """Mutant "the default reduce" (no `reduce_system`/`build_reduce`): the format assert fails,
    not the guard that it really chunked."""
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", product)
    i18n.reset()
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    server.local_lint_summary(text=_ruff_log(12, 6))
    assert len(captured) > 2  # guard: it really chunked
    reduce_step = captured[-1]
    assert "Resume la siguiente salida" not in reduce_step["user"]  # guard: the reduce
    assert "agrupados por archivo" in reduce_step["system"]
    assert "sin repetir ni enumerar" not in reduce_step["system"]
    assert reduce_step["system"] == server._lint_system(200)
    # Every step that is not the reduce (map and regroup) carries the lint system too.
    assert all(c["system"] == server._lint_system(200) for c in captured)
    assert "src/pkg/mod_00.py" in reduce_step["user"]
    assert "CPY001" in reduce_step["user"]
    assert "un único resumen de todo el log" in reduce_step["user"].lower()


def test_the_single_lint_call_is_unchanged(captured):
    """Control: a log that does not chunk gets the prompt of `main`, byte for byte."""
    log = _ruff_log(2, 3)
    server.local_lint_summary(text=log)
    (call,) = captured
    assert call["system"] == server._lint_system(200)
    assert call["user"] == f"Resume la siguiente salida de linter/tests:\n\n{log}"


def test_the_lint_inventory_has_no_counts_and_is_cut_without_figures():
    log = _ruff_log(30, 6)
    inventory = server._lint_inventory(log, 10_000)
    assert "src/pkg/mod_00.py" in inventory and "CPY001" in inventory
    names = lint_patterns.FILE.sub(" ", inventory)
    names = lint_patterns.RULE.sub(" ", names)
    assert not re.search(r"\d", names), names  # no figure outside a file or a code
    short = server._lint_inventory(log, 300)
    assert len(short) <= 300
    assert "y otros" in short
    assert not re.search(r"\d", lint_patterns.RULE.sub(" ", lint_patterns.FILE.sub(" ", short)))


def test_the_counter_uses_the_patterns_of_the_tool():
    assert fidelity.FILE is lint_patterns.FILE
    assert fidelity.CODE is lint_patterns.CODE


# --- 2b. Fallback: the program lists what the chunked summary left out (2026-10-17) -------------


@pytest.mark.parametrize(("product", "label"), [("es", "Sin mencionar"), ("en", "Not mentioned")])
def test_the_chunked_lint_answer_lists_what_it_does_not_mention(
    monkeypatch, captured, product, label
):
    """Mutant "no fallback" (no `postprocess`): the line is missing and this assert fails, not the
    guard that it really chunked. The fake model answers "- nota": it names nothing."""
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", product)
    i18n.reset()
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    log = _ruff_log(12, 6)
    out = server.local_lint_summary(text=log)
    assert len(captured) > 2  # guard: it really chunked
    (line,) = [ln for ln in out.splitlines() if ln.startswith(label)]
    assert "src/pkg/mod_00.py" in line and "CPY001" in line and "S603" in line
    assert "src/pkg/mod_10.py" not in line  # only the 10 most named files
    names = lint_patterns.RULE.sub(" ", lint_patterns.FILE.sub(" ", line))
    assert not re.search(r"\d", names), line  # no figure of its own


def test_a_named_item_is_not_listed_again():
    log = _ruff_log(2, 3)
    answer = r"**src/pkg/mod\_00.py**: CPY001 y D401. `mod_01.py`: S603."
    assert lint_patterns.not_mentioned(answer, log) == []
    assert lint_patterns.not_mentioned("CPY0011 en mod_000.py", log) == [
        "src/pkg/mod_00.py",
        "src/pkg/mod_01.py",
        "CPY001",
        "D401",
        "S603",
    ]


def test_the_single_lint_answer_gets_no_fallback_line(captured):
    """Control: a log that does not chunk has no inventory and no line."""
    out = server.local_lint_summary(text=_ruff_log(2, 3))
    assert "Sin mencionar" not in out


# --- 3. The steps of a chunked operation in the usage log ---------------------------------------


def _four_pieces() -> str:
    body = "    return 1  # " + "y" * 11_000 + "\n"
    return "".join(f"def part_{i}():\n{body}\n" for i in range(4))


def test_the_chunked_log_records_every_step_without_its_text(captured, tmp_path):
    """Mutant "one step only" (the list is replaced at each call): the `len == 5` fails."""
    code = _four_pieces()
    budget = server._map_budget(config.max_chars_for_role("code"))
    assert len(server._code_pieces(code, budget)) == 4  # guard: four chunks
    server.local_explain_code(code=code)
    (row,) = _rows(tmp_path, "local_explain_code")
    assert [s["kind"] for s in row["steps"]] == ["map"] * 4 + ["reduce"]
    assert all(s["chars_out"] == len("- nota") for s in row["steps"])
    assert all(s["finish_reason"] == "stop" for s in row["steps"])
    assert all(set(s) == {"kind", "chars_out", "finish_reason"} for s in row["steps"])


def test_a_single_call_has_no_steps(captured, tmp_path):
    server.local_explain_code(code="def f():\n    return 1\n")
    (row,) = _rows(tmp_path, "local_explain_code")
    assert "steps" not in row


def test_the_dump_of_the_notes_is_off_by_default(captured, tmp_path):
    server.local_explain_code(code=_four_pieces())
    assert not list(tmp_path.rglob("local_explain_code-*.json"))


def test_the_dump_writes_each_step_with_its_text_to_a_local_file(monkeypatch, captured, tmp_path):
    """Mutant "no dump": the file assert fails."""
    folder = tmp_path / "notes"
    monkeypatch.setattr(config, "DUMP_CHUNK_NOTES_DIR", str(folder))
    server.local_explain_code(code=_four_pieces())
    (dump,) = folder.glob("local_explain_code-*.json")
    data = json.loads(dump.read_text(encoding="utf-8"))
    assert data["tool"] == "local_explain_code"
    assert [s["kind"] for s in data["steps"]] == ["map"] * 4 + ["reduce"]
    assert all(s["text"] == "- nota" for s in data["steps"])
    # The usage log still keeps no text.
    (row,) = _rows(tmp_path, "local_explain_code")
    assert "- nota" not in json.dumps(row)


# --- 4. The fidelity counter --------------------------------------------------------------------


def test_a_markdown_escaped_underscore_is_the_file_of_the_log():
    """Mutant "no unescaping in `model_text`": the first assert fails."""
    log = "scripts/build_corpus.py: error X\n"
    assert (
        fidelity.count_inventions(r"Falla `scripts/build\_corpus.py`.", log)["invented_files"] == []
    )
    # Control: an escaped file that is not in the log is still invented.
    assert fidelity.count_inventions(r"Falla `scripts/other\_corpus.py`.", log)[
        "invented_files"
    ] == ["scripts/other_corpus.py"]


def test_a_tsc_position_gives_two_figures():
    """Mutant "no `(N,M)` figures": the 52 counts as invented."""
    log = "src/login.page.ts(52,24): error TS2322: bad\n"
    assert (
        fidelity.count_inventions("Error en la línea 52, columna 24.", log)["invented_numbers"]
        == []
    )
    assert fidelity.count_inventions("Error en la línea 53.", log)["invented_numbers"] == ["53"]


def test_a_version_with_v_is_its_figure():
    """Mutant "no `v` versions": the 255 counts as invented."""
    log = "llama-swap: v255\n"
    assert fidelity.count_inventions("Versión 255.", log)["invented_numbers"] == []
    assert fidelity.count_inventions("Versión 256.", log)["invented_numbers"] == ["256"]


def test_a_number_word_does_not_lean_on_a_line_or_column():
    """Mutant "words use every figure": "nine" passes through the `:9:` column."""
    log = "a.py:3:9: T201 print found\n"
    assert fidelity.count_inventions("nine instances of T201.", log)["invented_numbers"] == ["nine"]
    # The digit is still a figure of the log (a column), and a total backs the word.
    assert fidelity.count_inventions("Column 9.", log)["invented_numbers"] == []
    total = log + "Found 9 errors.\n"
    assert fidelity.count_inventions("nine errors.", total)["invented_numbers"] == []
