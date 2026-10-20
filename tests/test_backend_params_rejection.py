"""The backend rejects the role's parameters with a 400 (SDD `backend-extra-params`, T11, REQ-015).

Every test runs the real tool against a fake backend (`server._post_chat` replaced) that answers
`http_400` only when the body carries `top_k`, with the fixed environment of
`scripts/capture_request_bodies.py`. The POST are counted in the fake backend, never in `attempts`.
The log fields of the rejection (`backend_params_rejected`, `backend_params`) are lot D's (T13).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from local_delegate import backend_params as bp
from local_delegate import failures, server

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "capture_request_bodies.py"

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
MECHANICAL = capture.MECHANICAL
VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"
EXTRACT_ANSWER = '{"name": "Ana", "city": "Holguín"}'


def _ok(text: str = EXTRACT_ANSWER) -> server.ChatResult:
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


def _bad_request() -> server.ChatResult:
    return server.ChatResult(
        text="[local-delegate error] HTTP 400",
        ok=False,
        error="http_400",
        error_class=failures.FailureClass.REQUEST,
    )


def _rejects_top_k(_model: str, body: dict) -> server.ChatResult:
    """A backend whose build does not take `top_k`: 400 with it, an answer without it."""
    return _bad_request() if "top_k" in body else _ok()


def _rejects_schema(_model: str, body: dict) -> server.ChatResult:
    """A backend without JSON-schema support: 400 to `response_format`, with or without params."""
    return _bad_request() if "response_format" in body else _ok()


class Backend:
    """The fake backend: records every body, in order, as a deep copy."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.answer = _rejects_top_k

    def __call__(self, model: str, payload: dict) -> server.ChatResult:
        self.bodies.append(json.loads(json.dumps(payload)))
        return self.answer(model, payload)

    def reset(self) -> None:
        self.bodies.clear()


@pytest.fixture
def backend(reload_config, monkeypatch):
    reload_config(**capture.ENVIRONMENT)
    monkeypatch.delenv(VARIABLE, raising=False)
    bp._forget()
    fake = Backend()
    monkeypatch.setattr(server, "_post_chat", fake)
    yield fake
    bp._forget()


@pytest.fixture
def operations(monkeypatch):
    """The `_RoleParams` of every operation, in order (`None` for one without parameters)."""
    made: list = []
    real = server._role_params_for

    def spy(role, explicit):
        params = real(role, explicit)
        made.append(params)
        return params

    monkeypatch.setattr(server, "_role_params_for", spy)
    return made


def _write_roles(roles: dict) -> None:
    bp.path().write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")


@pytest.fixture
def events(monkeypatch):
    """The keyword arguments of every `_log_event` of the test, in order."""
    logged: list[dict] = []
    real = server._log_event

    def spy(**fields):
        logged.append(fields)
        return real(**fields)

    monkeypatch.setattr(server, "_log_event", spy)
    return logged


def _extract():
    return server.local_extract(fields=["name", "city"], text="Ana vive en Holguín.")


def _classify():
    return server.local_classify(text="Ana vive en Holguín.", labels=["persona", "lugar"])


def _delegate_three_chunks():
    # Three paragraphs, each one too big to share a chunk with another: exactly three chunks.
    text = "\n\n".join(f"Párrafo {i}: " + "palabra " * 300 for i in range(3))
    return server.local_delegate(
        task="Pasa el texto a mayúsculas.",
        input=text,
        output_format="El texto en mayúsculas.",
        chunk="on",
    )


# --- The rejection is detected, retried once and remembered -------------------------------------


def test_extract_schema_rejected_params_then_ok(backend, operations, events):
    _write_roles({"mechanical": {"top_k": 20}})
    result = _extract()
    assert result == json.loads(EXTRACT_ANSWER)
    first, second = backend.bodies
    assert first["top_k"] == 20
    assert "top_k" not in second
    # The retry without the parameters keeps the schema: it goes BEFORE the schema retry.
    assert second["response_format"] == first["response_format"]
    assert events[-1]["json_schema"] == "used"
    (params,) = operations
    assert params.probed and params.rejected


def test_three_chunks_make_four_requests(backend, operations):
    backend.answer = lambda _model, _body: _ok("RESULTADO")
    _delegate_three_chunks()
    today = list(backend.bodies)
    assert len(today) == 3, "the input must make exactly three chunks"

    backend.reset()
    backend.answer = lambda _model, body: _bad_request() if "top_k" in body else _ok("RESULTADO")
    _write_roles({"mechanical": {"top_k": 20}})
    _delegate_three_chunks()
    assert len(backend.bodies) == 4, "3 chunks + 1 retry, not 6"
    assert [("top_k" in body) for body in backend.bodies] == [True, False, False, False]
    # After the rejection the later chunks are the bodies of today, with the tool's cap.
    assert backend.bodies[1:] == today
    assert operations[-1].rejected


def test_retry_without_params_uses_tool_values(backend):
    _classify()
    (today,) = backend.bodies

    backend.reset()
    _write_roles(
        {
            "mechanical": {
                "temperature": 0.9,
                "top_k": 20,
                "enable_thinking": True,
                "reasoning_budget_tokens": 512,
            }
        }
    )
    _classify()
    tried, retry = backend.bodies
    assert (tried["temperature"], tried["max_tokens"]) == (0.9, 16 + 512)
    # The tool's temperature and cap, no budget, no role key: byte for byte today's body.
    assert retry == today
    assert list(retry) == list(today)


def test_400_with_and_without_params_does_not_mark(backend, operations, events):
    backend.answer = _rejects_schema
    _extract()
    today = len(backend.bodies)
    assert today == 2, "today: the call with schema and its retry without it"

    backend.reset()
    _write_roles({"mechanical": {"top_k": 20}})
    result = _extract()
    assert result == json.loads(EXTRACT_ANSWER)
    assert len(backend.bodies) == today + 1
    tried, probe, free = backend.bodies
    assert tried["top_k"] == 20 and "response_format" in tried
    assert "top_k" not in probe and "response_format" in probe
    # The cause was not the parameters: the schema retry still carries them.
    assert free["top_k"] == 20 and "response_format" not in free
    assert events[-1]["json_schema"] == "fallback"
    params = operations[-1]
    assert params.probed and not params.rejected


def test_probe_once_per_operation_even_if_it_fails(backend):
    """Two calls of ONE operation, every POST a 400: the probe without parameters goes once."""
    backend.answer = lambda _model, _body: _bad_request()
    _write_roles({"mechanical": {"top_k": 20}})
    params = server._role_params_for("mechanical", False)
    payload = {
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "max_tokens": 16,
        "temperature": 0.0,
        "stream": False,
    }
    for _call in range(2):
        result, schema, _ms = server._call_model(MECHANICAL, payload, False, params)
        assert result.error == "http_400" and schema is None
    assert [("top_k" in body) for body in backend.bodies] == [True, False, True]
    assert params.probed and not params.rejected


def test_no_params_400_still_fallback(backend, operations, events):
    backend.answer = _rejects_schema
    _extract()
    assert len(backend.bodies) == 2
    assert events[-1]["json_schema"] == "fallback"
    assert operations == [None]


def test_rejection_in_tool_without_schema(backend, operations, events):
    _write_roles({"mechanical": {"top_k": 20, "min_p": 0.1}})
    backend.answer = lambda _model, body: _bad_request() if "top_k" in body else _ok("persona")
    assert "persona" in _classify()
    tried, retry = backend.bodies
    assert "response_format" not in tried and "response_format" not in retry
    assert (tried["top_k"], tried["min_p"]) == (20, 0.1)
    assert "top_k" not in retry and "min_p" not in retry
    assert events[-1].get("json_schema") is None
    assert operations[-1].rejected
