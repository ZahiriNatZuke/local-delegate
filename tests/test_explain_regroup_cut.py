"""#598: a regroup step cut by `max_tokens` that a split cannot halve, and the answer built on it.

`local_explain_code` on a ~177 000 character module had a regroup step cut after the split retry
of #455/#497 (the split could not halve its group, so the cut output was kept), and the answer
denied writes the file does make. Now that step is retried once with twice the cap while that
still shrinks the group and the backend takes the wider cap; a cut that stays is named as a
note-combining step in the notice, which says a statement that something does not happen may come
from the cut. The backend is faked (`_run_chat`): no network, log in tmp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import config, i18n, server


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """Every call recorded; `answer(call)` decides the response; log in tmp."""
    calls: list[dict] = []
    state = {"answer": lambda call: _ok("nota")}

    def run_chat(model, system, user, max_tokens, temperature, **_):
        call = {"system": system, "user": user, "max_tokens": max_tokens}
        calls.append(call)
        return state["answer"](call), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.delenv("LOCAL_DELEGATE_DUMP_CHUNK_NOTES", raising=False)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return calls, state


def _row(tmp_path: Path, tool: str) -> dict:
    rows = [
        json.loads(line)
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["tool"] == tool
    ]
    assert len(rows) == 1
    return rows[0]


def _lines(n: int, tag: str) -> str:
    return "".join(f"{tag} {i:04d} " + "x" * 60 + "\n" for i in range(n))


MAX_CHARS = 12_500  # budget 10 000
REGROUP_CAP = 264  # `_tokens(100)`: the regroup cap for `max_words=100`
CUT = 2_500  # a cut regroup output: 4 × 2 500 > 8 000, so a split cannot halve its group
NOTE = 4_200  # each map note: four of them do not fit one reduce, two groups of ~8 400


def _map_reduce(widen: bool = True) -> str:
    return server._chat_map_reduce(
        "m",
        "MAP",
        _lines(4 * 140, "line"),
        lambda piece: f"GRP:{piece}",
        max_chars=MAX_CHARS,
        tool="local_summarize",
        source="inline",
        max_words=100,
        user_for=lambda piece: f"MAP:{piece}",
        reduce_system="RED",
        build_reduce=lambda joined: f"RED:{joined}",
        widen_cut_regroup=widen,
    )


def _answer(widened_finish: str):
    """Map: one ~4 200 char note per chunk. Regroup: cut at its cap; with twice the cap, `widened_finish`."""

    def answer(call):
        user = call["user"]
        if user.startswith("MAP:"):
            return _ok(_lines(NOTE // 70, f"note{len(user)}"))
        if user.startswith("GRP:"):
            if call["max_tokens"] == REGROUP_CAP:
                return _ok("CUT " + _lines(CUT // 70, "cut"), "length")
            return _ok("WIDE " + _lines(10, "wide"), widened_finish)
        return _ok("final answer")

    return answer


def test_a_cut_regroup_that_cannot_split_is_retried_wider(backend, tmp_path):
    """Mutant `main` (no widened retry): the cut output reaches the reduce, the row says
    `truncated_out: true` and the notice is appended; the `truncated_out` assert fails first."""
    calls, state = backend
    state["answer"] = _answer("stop")
    out = _map_reduce()
    row = _row(tmp_path, "local_summarize")
    regroups = [s for s in row["steps"] if s["kind"] == "regroup"]
    assert regroups and regroups[0]["finish_reason"] == "length"  # guard: a regroup was cut
    assert not server._regroup_split_shrinks(NOTE * 2, CUT, 2)  # guard: the split cannot halve it
    assert not row.get("truncated_out")
    assert any(c["max_tokens"] == REGROUP_CAP * server.REGROUP_WIDEN_FACTOR for c in calls)
    assert all(s.get("retried") for s in regroups if s["finish_reason"] == "length")
    reduce_user = calls[-1]["user"]
    assert reduce_user.startswith("RED:") and "WIDE" in reduce_user and "CUT" not in reduce_user
    assert server.WARNING_MARKER not in out


def test_a_regroup_cut_again_is_named_as_a_combining_step(backend, tmp_path):
    """Mutant «notice of today»: the notice has no combining-step tail; its assert fails."""
    _calls, state = backend
    state["answer"] = _answer("length")
    out = _map_reduce()
    row = _row(tmp_path, "local_summarize")
    cut_left = [
        s
        for s in row["steps"]
        if s["finish_reason"] == "length" and not s.get("retried") and s["kind"] == "regroup"
    ]
    assert cut_left  # guard: a regroup is still cut after the widened retry
    assert row["truncated_out"] is True
    # Right after the main sentence, so «de ellas» reads as «of the cut calls».
    main = i18n.t("mcp.warning.output_truncated_calls", truncated=len(cut_left), calls=len(_calls))
    assert main + i18n.t("mcp.warning.combine_cut", count=len(cut_left)) in out
    assert i18n.t("mcp.warning.widened_calls", widened=len(cut_left)) in out
    # The notice adds up to the `length` steps of the log: left + split retries + widened.
    length_steps = sum(1 for s in row["steps"] if s["finish_reason"] == "length")
    assert length_steps == 2 * len(cut_left)


def test_a_widened_retry_that_overflows_keeps_the_cut_output(backend, tmp_path):
    """The wider cap does not fit the context: the operation does not fail, the cut stays."""
    _calls, state = backend
    base = _answer("stop")

    def answer(call):
        if call["user"].startswith("GRP:") and call["max_tokens"] > REGROUP_CAP:
            return server.ChatResult(
                text=server.ERROR_PREFIX + "context length exceeded",
                ok=False,
                error="http_400",
                finish_reason=None,
            )
        return base(call)

    state["answer"] = answer
    assert server._is_context_overflow(answer({"user": "GRP:x", "max_tokens": 999}))  # guard
    out = _map_reduce()
    # Guard: the widened retry was made (and overflowed); without it this test proves nothing.
    assert any(c["max_tokens"] > REGROUP_CAP for c in _calls if c["user"].startswith("GRP:"))
    row = _row(tmp_path, "local_summarize")
    assert row["ok"] is True
    assert row["truncated_out"] is True
    assert not out.startswith(server.ERROR_PREFIX)


def test_without_the_flag_the_cut_regroup_is_kept_as_before(backend, tmp_path):
    """The other tools (and `local_explain_code` without a question, frozen by #504) keep today's
    behaviour: no widened call, the cut stays and no note-combining tail."""
    calls, state = backend
    state["answer"] = _answer("stop")
    out = _map_reduce(widen=False)
    assert all(c["max_tokens"] == REGROUP_CAP for c in calls if c["user"].startswith("GRP:"))
    assert _row(tmp_path, "local_summarize")["truncated_out"] is True
    assert i18n.t("mcp.warning.combine_cut", count=1) not in out


# --- By the tool's own path: `local_explain_code` with a question --------------------------------

CHARS_PER_TOKEN = 4.08


def _verbose(call):
    """Notes at 70 % of their input, cut at the cap (the backend of `test_explain_code_question`)."""
    cap = int(call["max_tokens"] * CHARS_PER_TOKEN)
    need = int(len(call["user"]) * 0.7)
    size = min(need, cap)
    line = "nota " + "n" * 50 + "\n"
    return _ok((line * (size // len(line) + 1))[:size], "length" if need > cap else "stop")


def _module(tmp_path: Path) -> Path:
    body = "".join(f"    v{j} = compute_{j}(args)  # step {j}\n" for j in range(60))
    code = "".join(f"def func_{i}(args):\n{body}    return v0\n\n\n" for i in range(30))
    path = tmp_path / "module.py"
    path.write_text(code, encoding="utf-8")
    return path


def test_explain_with_a_question_widens_a_cut_regroup(backend, tmp_path):
    """Mutant «flag off for explain»: no call asks for twice the regroup cap; that assert fails."""
    calls, state = backend
    state["answer"] = _verbose
    server.local_explain_code(path=str(_module(tmp_path)), question="¿Qué escribe `func_3`?")
    row = _row(tmp_path, "local_explain_code")
    assert any(s["kind"] == "regroup" for s in row["steps"])  # guard: it regrouped
    regroup_cap = 350 * 2 + 64  # `_tokens(partial_max_words=350)`
    assert any(c["max_tokens"] == regroup_cap * server.REGROUP_WIDEN_FACTOR for c in calls)


# --- (m) the widened cap within what the backend accepts ---------------------------------------


def test_the_widened_cap_stays_within_the_chunk_cap_and_the_context(monkeypatch):
    monkeypatch.setattr(config, "CHUNK_MAX_TOKENS", 2048)
    monkeypatch.setattr(server.llamaswap_config, "model_context_size", lambda m: (8192, False))
    assert server._widened_cap("m", 764, 4_000) == 1528  # twice the cap
    assert server._widened_cap("m", 1_500, 4_000) == 2048  # the chunk cap
    # A prompt that leaves less room in the context than twice the cap.
    room = 8192 - server.math.ceil(
        28_000 * config.REASONING_CONTEXT_MARGIN / config.CHARS_PER_TOKEN
    )
    assert server._widened_cap("m", 764, 28_000) == min(1528, room)


def test_no_widened_retry_when_the_backend_would_not_take_a_wider_cap(backend, monkeypatch):
    """Mutant «2 × cap always»: the call with twice the cap is made; the assert fails."""
    calls, state = backend
    monkeypatch.setattr(config, "CHUNK_MAX_TOKENS", REGROUP_CAP)  # no room above the cap
    state["answer"] = _answer("stop")
    _map_reduce()
    regroup_caps = {c["max_tokens"] for c in calls if c["user"].startswith("GRP:")}
    assert regroup_caps == {REGROUP_CAP}
