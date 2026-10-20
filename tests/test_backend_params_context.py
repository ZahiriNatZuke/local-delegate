"""Reasoning that does not fit in the context (SDD `backend-extra-params`, T12, REQ-023).

Before every real call with reasoning on, `_call_model` estimates
`ceil((len(system) + len(user)) × REASONING_CONTEXT_MARGIN / CHARS_PER_TOKEN)` and, if that plus
the tool's cap plus the budget is over the `n_ctx` of the real target, THAT call goes without
reasoning. The context comes from a test llama-swap config (`LLAMASWAP_CONFIG`); every test runs
the real tool against a fake backend with the fixed environment of `capture_request_bodies.py`.
The `reasoning_skipped` field of the event is lot D's (T13); here it is read from `_RoleParams`.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

from local_delegate import backend_params as bp
from local_delegate import config, failures, llamaswap_config, server

pytest.importorskip("yaml")

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
MECHANICAL, LONG, VISION = capture.MECHANICAL, capture.LONG, capture.VISION
VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"
BUDGET = 512
N_CTX = 8192
THINKING = {"enable_thinking": True, "reasoning_budget_tokens": BUDGET}


def _ok(text: str = "RESULTADO") -> server.ChatResult:
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


class Backend:
    """The fake backend: records `(model, body)` of every real call, in order."""

    def __init__(self) -> None:
        self.models: list[str] = []
        self.bodies: list[dict] = []
        self.answer = lambda _model, _body: _ok()

    def __call__(self, model: str, payload: dict) -> server.ChatResult:
        self.models.append(model)
        self.bodies.append(json.loads(json.dumps(payload)))
        return self.answer(model, payload)

    def reset(self) -> None:
        self.models.clear()
        self.bodies.clear()


@pytest.fixture
def backend(reload_config, monkeypatch):
    reload_config(**capture.ENVIRONMENT)
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    bp._forget()
    llamaswap_config._forget_context_sizes()
    fake = Backend()
    monkeypatch.setattr(server, "_post_chat", fake)
    yield fake
    bp._forget()
    llamaswap_config._forget_context_sizes()


@pytest.fixture
def operations(monkeypatch):
    """The `_RoleParams` of every operation, in order."""
    made: list = []
    real = server._role_params_for

    def spy(role, explicit):
        params = real(role, explicit)
        made.append(params)
        return params

    monkeypatch.setattr(server, "_role_params_for", spy)
    return made


def _context_config(tmp_path: Path, monkeypatch, sizes: dict[str, int]) -> None:
    """A llama-swap config (JSON is YAML) whose models carry `--ctx-size N`."""
    models = {
        name: {"cmd": f"llama-server --port ${{PORT}} --ctx-size {n}"} for name, n in sizes.items()
    }
    path = tmp_path / "llama-swap.yaml"
    path.write_text(json.dumps({"models": models}), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))
    llamaswap_config._forget_context_sizes()


def _write_roles(roles: dict) -> None:
    bp.path().write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")


def _delegate(text: str):
    return server.local_delegate(
        task="Resume el texto en una línea.",
        input=text,
        output_format="Una línea.",
        chunk="off",
    )


def _chars(body: dict) -> int:
    return sum(len(message["content"]) for message in body["messages"])


def _with_reasoning(body: dict) -> bool:
    return body.get("chat_template_kwargs") == {"enable_thinking": True}


def _skips(body: dict, cap: int) -> bool:
    """Without reasoning: `enable_thinking: false`, no budget and the tool's cap."""
    return (
        body.get("chat_template_kwargs") == {"enable_thinking": False}
        and "reasoning_budget_tokens" not in body
        and body["max_tokens"] == cap
    )


def _measure(backend: Backend) -> tuple[int, int]:
    """`(extra, cap)` of `local_delegate`: the chars around the input and the tool's cap.

    Measured with two inputs and no parameters: the prompt must grow exactly with the input, or
    the boundary computed from it would be wrong.
    """
    extras = []
    for size in (10, 37):
        backend.reset()
        _delegate("a" * size)
        (body,) = backend.bodies
        extras.append(_chars(body) - size)
        cap = body["max_tokens"]
    assert extras[0] == extras[1], "the prompt does not grow 1:1 with the input"
    backend.reset()
    return extras[0], cap


def _room(cap: int, n_ctx: int = N_CTX) -> int:
    """The largest estimate (in tokens) that still fits with the reasoning on."""
    return n_ctx - cap - BUDGET


# --- The check, call by call --------------------------------------------------------------------


def test_long_input_skips_reasoning(backend, operations, tmp_path, monkeypatch):
    _context_config(tmp_path, monkeypatch, {MECHANICAL: N_CTX})
    _extra, cap = _measure(backend)
    _write_roles({"mechanical": {**THINKING, "top_k": 20}})
    text = ("Una frase de prueba en español. " * 700)[:20000]
    assert len(text) == 20000
    _delegate(text)
    assert backend.bodies, "the tool must call the backend"
    for body in backend.bodies:
        assert _skips(body, cap), body.get("chat_template_kwargs")
        assert body["top_k"] == 20, "the rest of the role still applies"
        assert text in body["messages"][-1]["content"], "the input is never cut"
    assert operations[-1].reasoning_skipped == "context"


def test_short_input_keeps_reasoning(backend, operations, tmp_path, monkeypatch):
    _context_config(tmp_path, monkeypatch, {MECHANICAL: N_CTX})
    _extra, cap = _measure(backend)
    _write_roles({"mechanical": THINKING})
    _delegate("Un texto corto.")
    (body,) = backend.bodies
    assert _with_reasoning(body)
    assert body["max_tokens"] == cap + BUDGET
    assert body["reasoning_budget_tokens"] == BUDGET
    assert operations[-1].reasoning_skipped is None


def test_boundary_exact_fits_one_more_char_skips(backend, tmp_path, monkeypatch):
    _context_config(tmp_path, monkeypatch, {MECHANICAL: N_CTX})
    extra, cap = _measure(backend)
    room = _room(cap)
    # ceil(chars × 2 / 4) == room exactly with chars = 2 × room; one char more makes room + 1.
    chars = room * config.CHARS_PER_TOKEN // config.REASONING_CONTEXT_MARGIN
    assert math.ceil(chars * config.REASONING_CONTEXT_MARGIN / config.CHARS_PER_TOKEN) == room
    _write_roles({"mechanical": THINKING})

    _delegate("b" * (chars - extra))
    _delegate("b" * (chars - extra + 1))
    exact, over = backend.bodies
    assert (_chars(exact), _chars(over)) == (chars, chars + 1)
    assert _with_reasoning(exact), "estimate + cap + budget == n_ctx fits"
    assert _skips(over, cap), "one token more does not"


def test_dense_input_uses_margin(backend, tmp_path, monkeypatch):
    """Code that fits at 4 chars per token but not at 2: the margin is applied."""
    _context_config(tmp_path, monkeypatch, {MECHANICAL: N_CTX})
    extra, cap = _measure(backend)
    room = _room(cap)
    chars = room * 2 + 2  # one token over at 2 chars per token, far under at 4
    assert math.ceil(chars / 4) <= room < math.ceil(chars / 2)
    code = "".join(f"x{i} = f(x{i - 1}, {i})\n" for i in range(1, 5000))
    text = code[: chars - extra]
    _write_roles({"mechanical": THINKING})
    _delegate(text)
    (body,) = backend.bodies
    assert _chars(body) == chars
    assert _skips(body, cap)


def test_vision_never_skips(backend, operations, tmp_path, monkeypatch):
    # A context too small even for the cap and the budget: only the exclusion of `vision` saves it.
    _context_config(tmp_path, monkeypatch, {VISION: 64})
    image = capture._minimal_png(tmp_path / "dot.png")
    server.local_describe_image(path=str(image))
    (today,) = backend.bodies

    backend.reset()
    _write_roles({"vision": THINKING})
    server.local_describe_image(path=str(image))
    (body,) = backend.bodies
    assert _with_reasoning(body)
    assert body["max_tokens"] == today["max_tokens"] + BUDGET
    assert operations[-1].reasoning_skipped is None


def test_unknown_context_uses_8192(backend, tmp_path, monkeypatch):
    extra, cap = _measure(backend)
    text = "c" * (_room(cap) * 2 + 2 - extra)  # one token over 8192, far under 32768
    _write_roles({"mechanical": THINKING})

    _delegate(text)  # no llama-swap config: the estimate, 8192
    _context_config(tmp_path, monkeypatch, {LONG: 32768})
    _delegate(text)  # a config without the model: the estimate again
    _context_config(tmp_path, monkeypatch, {MECHANICAL: 32768})
    _delegate(text)  # control: the model's own context, where it fits
    no_config, no_model, known = backend.bodies
    assert _skips(no_config, cap)
    assert _skips(no_model, cap)
    assert _with_reasoning(known)


def _mechanical_fails(model: str, _body: dict) -> server.ChatResult:
    if model == MECHANICAL:
        return server.ChatResult(
            text="[local-delegate error] HTTP 500",
            ok=False,
            error="http_500",
            error_class=failures.FailureClass.MODEL,
        )
    return _ok()


def test_fallback_checks_its_own_context(reload_config, backend, tmp_path, monkeypatch):
    """The check uses the real target: the fallback model with a smaller context skips."""
    reload_config(**{**capture.ENVIRONMENT, "LOCAL_DELEGATE_MAX_CHARS_LONG": "48000"})
    extra, cap = _measure(backend)
    _context_config(tmp_path, monkeypatch, {MECHANICAL: 32768, LONG: N_CTX})
    backend.answer = _mechanical_fails
    _write_roles({"mechanical": THINKING})
    _delegate("d" * (_room(cap) * 2 + 2 - extra))
    assert backend.models == [MECHANICAL, LONG]
    first, fallback = backend.bodies
    assert _with_reasoning(first)
    assert _skips(fallback, cap)
