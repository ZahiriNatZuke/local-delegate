"""#504: the chunked `local_explain_code` carries the question to every step.

With `path` and `question`, a ~72 KB file answered with an index of the file: the map asked for
one bullet per definition, the regroup reused the map prompt and the reduce was told to explain the
whole file, so the question only reached one clause of the reduce system. Each step now carries the
question; without one, every prompt and the result stay byte for byte. The backend is faked
(`_run_chat`): no network, log in tmp.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from local_delegate import config, i18n, server

CHARS_PER_TOKEN = 4.08
QUESTION = "¿con qué código de salida termina el comando check cuando hay avisos?"


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """Every call recorded; notes at 70 % of their input, cut at the cap; log in tmp."""
    calls: list[dict] = []

    def run_chat(model, system, user, max_tokens, temperature, **_):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        cap = int(max_tokens * CHARS_PER_TOKEN)
        need = int(len(user) * 0.7)
        size = min(need, cap)
        line = f"nota {len(calls):04d} " + "n" * 50 + "\n"
        text = (line * (size // len(line) + 1))[:size]
        result = _ok(text, "length" if need > cap else "stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.delenv("LOCAL_DELEGATE_DUMP_CHUNK_NOTES", raising=False)
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    i18n.reset()
    return calls


def _kinds(tmp_path: Path) -> list[str]:
    rows = [
        json.loads(line)
        for file in sorted(tmp_path.glob("*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["tool"] == "local_explain_code"
    ]
    assert len(rows) == 1
    return [step["kind"] for step in rows[0]["steps"]]


def _issue_file(tmp_path: Path) -> Path:
    """~72 KB of Python with a registered subcommand: six chunks for the `code` role."""
    parts = [
        'def build_parser(sub):\n    sub.add_parser("check")\n    return sub\n\n\n',
    ]
    i = 0
    while sum(map(len, parts)) < 72_000:
        body = "".join(f"    v{j} = helper_{i}_{j}(args, kwargs)  # step {j}\n" for j in range(12))
        parts.append(
            f'def func_{i}(args, kwargs):\n    """Do thing {i}."""\n{body}    return v0\n\n\n'
        )
        i += 1
    file = tmp_path / "big.py"
    file.write_bytes("".join(parts)[:72_000].encode("utf-8"))
    return file


def test_the_question_reaches_every_step(backend, tmp_path):
    """Mutant `main` before #504: the asserts on the map and regroup prompts fail."""
    calls = backend
    answer = server.local_explain_code(path=str(_issue_file(tmp_path)), question=QUESTION)
    kinds = _kinds(tmp_path)
    assert Counter(kinds)["map"] >= 6  # guard: it chunked
    assert Counter(kinds)["regroup"] >= 1  # guard: the regroup ran, so it was checked too
    assert kinds[-1] == "reduce"  # guard: the final step ran
    assert len(calls) == len(kinds)
    for kind, call in zip(kinds, calls, strict=True):
        assert QUESTION in call["user"], kind
        if kind in ("map", "regroup"):
            assert QUESTION in call["system"], kind
            assert "Nada relevante en este fragmento" in call["system"], kind
    reduce = calls[-1]
    assert "Responde a la pregunta" in reduce["user"]
    assert "Explica el fichero completo" not in reduce["user"]
    assert "Si no bastan para responderla, dilo claramente" in reduce["user"]
    # An answer is not an inventory: the registered names are not appended to it.
    assert "check" not in answer


def test_without_a_question_the_prompts_are_unchanged(backend, tmp_path):
    """The sequence of prompts and the result, hashed before #504 with the same fake backend.

    Mutant "always the question branch" (or any change to a prompt without a question): the hash
    changes and the assert fails.
    """
    calls = backend
    answer = server.local_explain_code(path=str(_issue_file(tmp_path)))
    kinds = _kinds(tmp_path)
    assert Counter(kinds)["regroup"] >= 1  # guard: every kind of step is in the hash
    assert kinds[-1] == "reduce"
    digest = hashlib.sha256()
    for call in calls:
        for part in (call["system"], call["user"], str(call["max_tokens"])):
            digest.update(part.encode("utf-8") + b"\0")
    digest.update(answer.encode("utf-8"))
    assert "check" in answer  # guard: the registered name is still appended without a question
    assert digest.hexdigest() == "37f11bd0286a316b8edc539bf6a82b6773e5aa17da1436c29920568b87a6f895"
