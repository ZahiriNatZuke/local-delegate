"""B2e probe (scratchpad, not part of the suite): do the losses when combining chunks exist on main?

Fake backend (`_run_chat` doubled), no network. Each test is written to PASS when the loss is
FIXED, so a failure today proves the loss still exists.
"""

from __future__ import annotations

import pytest

from local_delegate import config, i18n, server


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        result = server.ChatResult(text="- nota", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return calls


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


def test_lint_reduce_keeps_the_lint_format(monkeypatch, captured):
    """Loss 1: the reduce of the chunked lint asks for prose that does not enumerate."""
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 1200)
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "long", 1200)
    server.local_lint_summary(text=_ruff_log(12, 6))
    assert len(captured) > 2
    reduce_step = captured[-1]
    assert "Resume la siguiente salida" not in reduce_step["user"]
    print("\nREDUCE SYSTEM:", reduce_step["system"][:300])
    assert "agrupados por archivo" in reduce_step["system"]
    assert "sin repetir ni enumerar" not in reduce_step["system"]


def _cli_like(n_subcommands: int, filler_defs: int) -> str:
    filler = "".join(
        f"def helper_{i}(x):\n    '''Helper {i}.'''\n    return x + {i}  # " + "z" * 300 + "\n\n"
        for i in range(filler_defs)
    )
    subs = "".join(f'    sub.add_parser("cmd-zz{i}", help="h")\n' for i in range(n_subcommands))
    return filler + "def build_parser():\n    sub = make()\n" + subs + "    other.add_parser(sub)\n"


def test_explain_reduce_inventory_names_the_registered_subcommands(monkeypatch, captured):
    """Loss 2: the reduce inventory lists only top-level def/class, not what a def registers."""
    code = _cli_like(14, 220)
    assert len(code) > config.max_chars_for_role("code")
    server.local_explain_code(code=code)
    assert len(captured) > 2
    reduce_user = captured[-1]["user"]
    assert "build_parser" in reduce_user  # guard: the inventory is there
    print("\nREDUCE max_tokens:", captured[-1]["max_tokens"], "map:", captured[0]["max_tokens"])
    assert all(f"cmd-zz{i}" in reduce_user for i in range(14))
