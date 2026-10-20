"""The usage-log fields of the per-role parameters (SDD `backend-extra-params`, T13, REQ-018).

The event of every operation gains, each one omitted when it does not apply:

- `backend_params`: `{"role", "values", "source"}` (`source` only lists keys from the variable);
- `reasoning_chars`: the reasoning of every real call of the operation, failed ones included
  (`reasoning_content` plus the `<think>` blocks of `content`), only when > 0;
- `backend_params_rejected: true` (REQ-015) and `reasoning_skipped: "context"` (REQ-023).

The tests read the real `usage-*.jsonl` that `_log_event` writes in `config.LOG_DIR`. Those that
count reasoning go through the real `_post_chat` against `backend_mock`; the others replace
`_post_chat` with a fake backend, with the fixed environment of `capture_request_bodies.py`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import backend_params as bp
from local_delegate import config, failures, llamaswap_config, server

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "capture_request_bodies.py"
FIXTURES = ROOT / "tests" / "fixtures" / "request_bodies"

# Same rule as `test_request_body_compat.py`: `scripts/` does not travel in the sdist.
if not SCRIPT.is_file():
    pytest.skip(
        "scripts/ is not in the tree (sdist): these tests need the repository",
        allow_module_level=True,
    )


def _load_script():
    spec = importlib.util.spec_from_file_location("capture_request_bodies", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = _load_script()
MECHANICAL, LONG = capture.MECHANICAL, capture.LONG
VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"
URL = "http://test-backend/v1/chat/completions"
NEW_FIELDS = ("backend_params", "reasoning_chars", "backend_params_rejected", "reasoning_skipped")
SENTINELS = ("SENTINEL-7Q", "SENTINEL-8R")
#: Text the fake model "thinks": none of it may ever reach the log.
REASONING_TEXT = "REASONING-FRAGMENT-K3 the user wants one line"
TAGGED = "TAGGED-FRAGMENT-M9 maybe two"


@pytest.fixture
def env(reload_config, monkeypatch):
    """The fixed environment of the captures, no parameters and the logs in `tmp_path`."""
    reload_config(**capture.ENVIRONMENT)
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    bp._forget()
    llamaswap_config._forget_context_sizes()
    yield
    bp._forget()
    llamaswap_config._forget_context_sizes()


def _ok(text: str = "hecho") -> server.ChatResult:
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


def _bad_request() -> server.ChatResult:
    return server.ChatResult(
        text="[local-delegate error] HTTP 400",
        ok=False,
        error="http_400",
        error_class=failures.FailureClass.REQUEST,
    )


@pytest.fixture
def fake(env, monkeypatch):
    """A fake `_post_chat`: `fake.answer(model, body)` decides; every body is kept."""

    class Fake:
        def __init__(self) -> None:
            self.bodies: list[dict] = []
            self.answer = lambda _model, _body: _ok()

        def __call__(self, model: str, payload: dict) -> server.ChatResult:
            self.bodies.append(json.loads(json.dumps(payload)))
            return self.answer(model, payload)

    backend = Fake()
    monkeypatch.setattr(server, "_post_chat", backend)
    return backend


def _write_roles(roles: dict) -> None:
    bp.path().write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")


def _log_text() -> str:
    return "".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path(config.LOG_DIR).glob("usage*.jsonl"))
    )


def _events() -> list[dict]:
    return [json.loads(line) for line in _log_text().splitlines() if line.strip()]


def _last_event() -> dict:
    events = _events()
    assert events, "no usage event was written"
    return events[-1]


def _summarize() -> str:
    return server.local_summarize(text="Un texto corto para resumir.")


def _classify() -> str:
    return server.local_classify(text="Ana vive en Holguín.", labels=["persona", "lugar"])


def _reply(
    content: str | None, *, reasoning: str | None = None, finish: str = "stop"
) -> httpx2.Response:
    message: dict = {"content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return httpx2.Response(200, json={"choices": [{"message": message, "finish_reason": finish}]})


# --- Omitted when they do not apply ------------------------------------------------------------


def test_fields_omitted_when_not_applicable(env, tmp_path):
    """No parameters and no reasoning: the event has exactly the keys of the L0 fixture."""
    fixture = json.loads((FIXTURES / "simple.json").read_text(encoding="utf-8"))
    result = capture.capture("simple", tmp_path)
    assert result["event_keys"] == sorted(fixture["event_keys"])
    event = _last_event()
    for name in NEW_FIELDS:
        assert name not in event, name

    # With parameters (and still no reasoning) only `backend_params` is added.
    _write_roles({"mechanical": {"top_k": 20}})
    result = capture.capture("simple", tmp_path)
    assert result["event_keys"] == sorted([*fixture["event_keys"], "backend_params"])
    assert _last_event()["backend_params"] == {"role": "mechanical", "values": {"top_k": 20}}


# --- reasoning_chars ---------------------------------------------------------------------------


@backend_mock.mock
def test_reasoning_chars_sums_failed_attempt(env):
    """The mechanical model reasons and fails (no content); its fallback reasons and answers."""
    backend_mock.post(URL).mock(
        side_effect=[
            _reply(None, reasoning="r" * 40),
            _reply("resumen del respaldo", reasoning="x" * 25),
        ]
    )
    _summarize()
    event = _last_event()
    assert event["ok"] is True and event.get("chunks") == 2
    assert event["model"] != event["model_requested"]
    assert event["reasoning_chars"] == 40 + 25


@backend_mock.mock
def test_think_tags_count_without_reasoning_content(env):
    block = f"<think>{TAGGED}</think>"
    backend_mock.post(URL).mock(return_value=_reply(f"{block}\n\nUn resumen."))
    out = _summarize()
    assert "Un resumen." in out and TAGGED not in out
    assert _last_event()["reasoning_chars"] == len(block)


@backend_mock.mock
def test_unclosed_think_counts_to_the_end(env):
    """Cut by `max_tokens` mid-reasoning: `_strip_think` removes it all, and all of it counts."""
    content = f"<think>{TAGGED} and then"
    backend_mock.post(URL).mock(return_value=_reply(content, reasoning="ab"))
    _summarize()
    assert _last_event()["reasoning_chars"] == len(content) + 2


@backend_mock.mock
def test_reasoning_text_never_logged(env):
    backend_mock.post(URL).mock(
        return_value=_reply(f"<think>{TAGGED}</think>Un resumen.", reasoning=REASONING_TEXT)
    )
    _summarize()
    text = _log_text()
    assert _last_event()["reasoning_chars"] == len(REASONING_TEXT) + len(f"<think>{TAGGED}</think>")
    for fragment in (REASONING_TEXT, TAGGED, "REASONING-FRAGMENT", "TAGGED-FRAGMENT"):
        assert fragment not in text, fragment


def test_reasoning_chars_of_every_post_in_one_attempt(fake):
    """Contract of `_call_model`: the reasoning of every POST of one call goes to its `Attempt`,
    also when a POST that reasoned is not the result returned."""
    _write_roles({"mechanical": {"top_k": 20}})
    first = _bad_request()
    first.reasoning_chars = 7
    second = _ok("persona")
    second.reasoning_chars = 5
    fake.answer = lambda _model, body: first if "top_k" in body else second
    assert "persona" in _classify()
    assert len(fake.bodies) == 2
    event = _last_event()
    assert event.get("chunks") is None, "both POST belong to ONE attempt"
    assert event["reasoning_chars"] == 12


# --- backend_params, rejection and skipped reasoning ------------------------------------------


def test_rejected_event_keeps_tried_values(fake):
    _write_roles({"mechanical": {"top_k": 20, "min_p": 0.1}})
    fake.answer = lambda _model, body: _bad_request() if "top_k" in body else _ok("persona")
    assert "persona" in _classify()
    event = _last_event()
    assert event["ok"] is True
    assert event["backend_params_rejected"] is True
    # The values that were tried, in catalog order, and no `source`: they all come from the file.
    assert event["backend_params"] == {"role": "mechanical", "values": {"top_k": 20, "min_p": 0.1}}
    assert "reasoning_skipped" not in event


def test_not_rejected_event_has_no_mark(fake):
    _write_roles({"mechanical": {"top_k": 20}})
    _classify()
    event = _last_event()
    assert event["backend_params"] == {"role": "mechanical", "values": {"top_k": 20}}
    assert "backend_params_rejected" not in event


def test_reasoning_skipped_in_event(fake, tmp_path, monkeypatch):
    """A context of 256 cannot take the budget: the call goes without reasoning, and says so."""
    config_path = tmp_path / "llama-swap.yaml"
    models = {MECHANICAL: {"cmd": "llama-server --port ${PORT} --ctx-size 256"}}
    config_path.write_text(json.dumps({"models": models}), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(config_path))
    llamaswap_config._forget_context_sizes()
    _write_roles({"mechanical": {"enable_thinking": True, "reasoning_budget_tokens": 512}})
    _classify()
    event = _last_event()
    assert event["reasoning_skipped"] == "context"
    # The values resolved for the operation are still the ones it was configured with.
    assert event["backend_params"]["values"] == {
        "enable_thinking": True,
        "reasoning_budget_tokens": 512,
    }
    (body,) = fake.bodies
    assert body["max_tokens"] == 16, "without reasoning the budget is not added to the cap"


@pytest.mark.parametrize("path", ["map_reduce", "chunked"])
def test_chunked_operation_event_carries_params(fake, path):
    """The event of an operation of several calls (map/reduce and plain chunks) has the fields."""
    if path == "map_reduce":
        _write_roles({"long": {"top_k": 20}})
        fake.answer = lambda _model, body: _bad_request() if "top_k" in body else _ok("parcial")
        server.local_summarize(text=capture._long_text())
        role = "long"
    else:
        _write_roles({"mechanical": {"top_k": 20}})
        fake.answer = lambda _model, body: _bad_request() if "top_k" in body else _ok("TEXTO")
        text = "\n\n".join(f"Párrafo {i}: " + "palabra " * 300 for i in range(3))
        server.local_delegate(
            task="Pasa el texto a mayúsculas.",
            input=text,
            output_format="El texto en mayúsculas.",
            chunk="on",
        )
        role = "mechanical"
    event = _last_event()
    assert event["chunks"] > 2, "the operation must make several calls"
    assert event["backend_params"] == {"role": role, "values": {"top_k": 20}}
    assert event["backend_params_rejected"] is True


def test_source_lists_only_variable_keys(fake, monkeypatch):
    _write_roles({"mechanical": {"top_k": 20}})
    monkeypatch.setenv(VARIABLE, "mechanical.min_p=0.1")
    bp._forget()
    _classify()
    assert _last_event()["backend_params"] == {
        "role": "mechanical",
        "values": {"top_k": 20, "min_p": 0.1},
        "source": {"min_p": "env"},
    }


@pytest.mark.parametrize("where", ["file", "env"])
def test_sentinels_never_in_log(fake, monkeypatch, where):
    """REQ-006: a dropped key or value never reaches the event, by file or by variable."""
    if where == "file":
        _write_roles({"mechanical": {"top_k": SENTINELS[0], "foo": SENTINELS[1], "min_p": 0.1}})
    else:
        monkeypatch.setenv(
            VARIABLE,
            f"mechanical.foo={SENTINELS[0]};mechanical.top_k={SENTINELS[1]};mechanical.min_p=0.1",
        )
        bp._forget()
    _classify()
    event = _last_event()
    assert event["backend_params"]["values"] == {"min_p": 0.1}, "the valid key must get through"
    text = _log_text()
    for sentinel in SENTINELS:
        assert sentinel not in text, sentinel
    assert "foo" not in json.dumps(event["backend_params"])


def test_explicit_model_event_has_no_backend_params(fake):
    """REQ-013: `local_delegate` with a model chosen by the caller carries no parameters."""
    _write_roles({"mechanical": {"top_k": 20}})

    def delegate(**model) -> str:
        return server.local_delegate(
            task="Pasa el texto a mayúsculas.",
            input="hola",
            output_format="El texto en mayúsculas, sin nada más.",
            **model,
        )

    delegate(model=MECHANICAL)
    assert "backend_params" not in _last_event()
    assert "top_k" not in fake.bodies[-1]
    # Control: the same call without `model` goes by the role and does carry them.
    delegate()
    assert _last_event()["backend_params"] == {"role": "mechanical", "values": {"top_k": 20}}
