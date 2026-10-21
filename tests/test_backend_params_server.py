"""Per-role parameters in the request funnel of `server.py` (SDD `backend-extra-params`, T10).

REQ-009 (resolved on every operation), REQ-010 (the role's temperature), REQ-011 (reasoning and its
budget), REQ-012 (three layers, resolved once per operation and carried through fallback and
chunks), REQ-013 (`local_delegate` with an explicit model) and REQ-005/006/007 seen from the body.

Every test runs the real tool against a fake backend (`server._post_chat` replaced) that records
each body, with the fixed environment of `scripts/capture_request_bodies.py` (models per role,
fallback chains, a backend that is not on loopback).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from local_delegate import backend_params as bp
from local_delegate import config, failures, server

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
MECHANICAL, LONG, CODE = capture.MECHANICAL, capture.LONG, capture.CODE
VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"
EXTRACT_ANSWER = '{"name": "Ana", "city": "Holguín"}'
SENTINELS = ("SENTINEL-7Q", "SENTINEL-8R")


def _ok(text: str = EXTRACT_ANSWER) -> server.ChatResult:
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


class Backend:
    """The fake backend: records `(model, body)` of every real call, in order."""

    def __init__(self) -> None:
        self.models: list[str] = []
        self.bodies: list[dict] = []
        self.answer = lambda _model, _body: _ok()

    def __call__(self, model: str, payload: dict) -> server.ChatResult:
        # A deep copy, in order: `_call_model` may pop `response_format` afterwards.
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
    bp._forget()
    fake = Backend()
    monkeypatch.setattr(server, "_post_chat", fake)
    yield fake
    bp._forget()


def _write_roles(roles: dict) -> None:
    bp.path().write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")


def _codes(warnings) -> list[tuple[str, str, str]]:
    return [(w.role, w.key, w.code) for w in warnings]


# --- The tools ------------------------------------------------------------------------------------


def _classify(_tmp: Path):
    return server.local_classify(text="Ana vive en Holguín.", labels=["persona", "lugar"])


def _extract(_tmp: Path):
    return server.local_extract(fields=["name", "city"], text="Ana vive en Holguín.")


def _summarize(_tmp: Path):
    return server.local_summarize(text="Un texto corto para resumir.")


def _boilerplate(tmp: Path):
    target = tmp / "generated.py"
    target.unlink(missing_ok=True)
    return server.local_boilerplate(spec="una suma", language="python", target=str(target))


def _explain_short(_tmp: Path):
    return server.local_explain_code(code="def add(a, b):\n    return a + b\n")


#: (tool, action, its temperature today, its role).
TOOLS = {
    "local_classify": (_classify, 0.0, "mechanical"),
    "local_extract": (_extract, 0.0, "mechanical"),
    "local_summarize": (_summarize, 0.2, "mechanical"),
    "local_boilerplate": (_boilerplate, 0.1, "code"),
}


# --- REQ-010: the role's temperature ------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_role_temperature_overrides_tool(tool, backend, tmp_path):
    action, today, role = TOOLS[tool]
    action(tmp_path)
    assert [body["temperature"] for body in backend.bodies] == [today]

    backend.reset()
    _write_roles({"mechanical": {"temperature": 0.5}})
    action(tmp_path)
    expected = 0.5 if role == "mechanical" else today
    assert [body["temperature"] for body in backend.bodies] == [expected]


@pytest.mark.parametrize("action", [_boilerplate, _explain_short], ids=["boilerplate", "explain"])
def test_code_temperature_0_7(action, backend, tmp_path):
    _write_roles({"code": {"temperature": 0.7}})
    action(tmp_path)
    assert backend.models == [CODE]
    assert backend.bodies[0]["temperature"] == 0.7
    # Replaced in place: the key order of the body is today's.
    assert list(backend.bodies[0]) == ["model", "messages", "max_tokens", "temperature", "stream"]


# --- REQ-012: the contract keys -----------------------------------------------------------------


def test_contract_keys_always_from_product(backend, tmp_path):
    _extract(tmp_path)
    (today,) = backend.bodies

    backend.reset()
    _write_roles(
        {
            "mechanical": {
                "temperature": 0.9,
                "top_k": 20,
                "min_p": 0.1,
                "reasoning_effort": "high",
                "enable_thinking": True,
                "reasoning_budget_tokens": 64,
            }
        }
    )
    _extract(tmp_path)
    (body,) = backend.bodies
    for key in ("model", "messages", "stream", "response_format"):
        assert body[key] == today[key], key
    # Layers 1 and 3 keep their place; the role's keys go at the end, in catalog order.
    assert list(body)[: len(today)] == list(today)
    assert list(body)[len(today) :] == [
        "top_k",
        "min_p",
        "reasoning_budget_tokens",
        "reasoning_effort",
        "chat_template_kwargs",
    ]


# --- REQ-011: reasoning -------------------------------------------------------------------------


def test_thinking_on_classify_sums_budget(backend, tmp_path):
    _write_roles({"mechanical": {"enable_thinking": True, "reasoning_budget_tokens": 512}})
    _classify(tmp_path)
    (body,) = backend.bodies
    assert body["max_tokens"] == 16 + 512
    assert body["reasoning_budget_tokens"] == 512
    assert body["chat_template_kwargs"] == {"enable_thinking": True}


def test_thinking_off_sends_false_and_keeps_max_tokens(backend, tmp_path):
    _write_roles({"mechanical": {"enable_thinking": False, "reasoning_budget_tokens": 512}})
    _classify(tmp_path)
    (body,) = backend.bodies
    assert body["max_tokens"] == 16
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_budget_tokens" not in body


def _delegate_chunked(_tmp: Path):
    text = "\n\n".join(f"Párrafo {i}: " + "palabra " * 80 for i in range(40))
    assert len(text) > 2 * config.CHUNK_CHARS  # at least three chunks
    return server.local_delegate(
        task="Pasa el texto a mayúsculas.",
        input=text,
        output_format="El texto en mayúsculas.",
        chunk="on",
    )


def _summarize_long(_tmp: Path):
    return server.local_summarize(text=capture._long_text())


@pytest.mark.parametrize(
    ("action", "role"),
    [(_delegate_chunked, "mechanical"), (_summarize_long, "long")],
    ids=["chunked", "map_reduce"],
)
def test_every_chunk_sums_budget(action, role, backend, tmp_path):
    backend.answer = lambda _model, _body: _ok("resumen parcial")
    action(tmp_path)
    today = [body["max_tokens"] for body in backend.bodies]
    assert len(today) >= 3, "the operation must make several real calls"

    backend.reset()
    _write_roles({role: {"enable_thinking": True, "reasoning_budget_tokens": 300}})
    action(tmp_path)
    assert [body["max_tokens"] for body in backend.bodies] == [cap + 300 for cap in today]
    for body in backend.bodies:
        assert body["reasoning_budget_tokens"] == 300
        assert body["chat_template_kwargs"] == {"enable_thinking": True}


# --- REQ-012: once per operation, through fallback and later chunks -----------------------------


def _explain_long(_tmp: Path):
    code = "\n\n".join(
        f"def function_{i}(value):\n" + "".join(f"    value = value + {j}\n" for j in range(12))
        for i in range(30)
    )
    assert len(code) > config.max_chars_for_role("code")
    return server.local_explain_code(code=code)


def _code_fails(model: str, _body: dict) -> server.ChatResult:
    if model == CODE:
        return server.ChatResult(
            text="[local-delegate error] HTTP 500",
            ok=False,
            error="http_500",
            error_class=failures.FailureClass.MODEL,
        )
    return _ok("- function: notes")


def test_params_survive_fallback_and_later_chunks(reload_config, backend, tmp_path):
    reload_config(**capture.ENVIRONMENT, LOCAL_DELEGATE_MAX_CHARS_CODE="3000")
    backend.answer = _code_fails
    _write_roles(
        {
            "code": {
                "temperature": 0.7,
                "top_k": 33,
                "enable_thinking": True,
                "reasoning_budget_tokens": 100,
            },
            # The fallback model's own role must not leak into the operation of `code`.
            "long": {"top_k": 5},
        }
    )
    _explain_long(tmp_path)
    assert backend.models[:2] == [CODE, LONG], "the first model fails and its fallback answers"
    assert len(backend.models) >= 4, "several chunks after the hop"
    assert set(backend.models[1:]) == {LONG}
    for index, body in enumerate(backend.bodies):
        assert body.get("top_k") == 33, index
        assert body["temperature"] == 0.7, index
        assert body.get("reasoning_budget_tokens") == 100, index
        assert body.get("chat_template_kwargs") == {"enable_thinking": True}, index
    # The hop resends the same payload: the budget is added once, not once per attempt.
    assert backend.bodies[1]["max_tokens"] == backend.bodies[0]["max_tokens"]


def test_params_resolved_once_even_if_file_changes_mid_operation(reload_config, backend, tmp_path):
    """REQ-012: the file is read when the operation starts, not on every real call.

    The fake backend rewrites the parameters file while it answers the first chunk. Every chunk
    must still carry the values resolved at the start; a resolution per call would send the new
    ones from the second chunk on. The values differ in size on purpose, so the stat cache of
    `backend_params` cannot hide the rewrite.
    """
    reload_config(**capture.ENVIRONMENT, LOCAL_DELEGATE_MAX_CHARS_CODE="3000")
    _write_roles({"code": {"temperature": 0.7, "top_k": 33}})
    rewritten: list[int] = []

    def rewrite_on_first_chunk(_model: str, _body: dict) -> server.ChatResult:
        if not rewritten:
            _write_roles({"code": {"temperature": 0.25, "top_k": 444}})
            rewritten.append(len(backend.bodies))
        return _ok("- function: notes")

    backend.answer = rewrite_on_first_chunk
    _explain_long(tmp_path)
    assert rewritten == [1], "the file is rewritten while the first chunk is in flight"
    assert len(backend.bodies) >= 3, "several real calls after the rewrite"
    # Guard: the rewrite is visible to a fresh resolution, so the check below can discriminate.
    assert bp.effective("code").values.get("top_k") == 444
    sent = [(body.get("top_k"), body.get("temperature")) for body in backend.bodies]
    assert sent == [(33, 0.7)] * len(backend.bodies), "every chunk keeps the starting params"

    # The next operation reads the new file (REQ-009).
    backend.reset()
    _explain_long(tmp_path)
    assert {(body.get("top_k"), body.get("temperature")) for body in backend.bodies} == {
        (444, 0.25)
    }


# --- REQ-013: `local_delegate` ------------------------------------------------------------------


def _delegate(model: str | None):
    return server.local_delegate(
        task="Pasa el texto a mayúsculas.",
        input="hola",
        output_format="El texto en mayúsculas, sin nada más.",
        model=model,
    )


def test_explicit_model_carries_no_params(backend):
    _write_roles({role: {"top_k": 20, "temperature": 0.9} for role in bp.ROLES})
    backend.answer = lambda _model, _body: _ok("HOLA")
    _delegate(CODE)
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "request_bodies" / "delegate_explicit.json").read_text(
            encoding="utf-8"
        ),
        object_pairs_hook=list,
    )
    expected = next(value for key, value in fixture if key == "bodies")
    assert [capture.as_pairs(body) for body in backend.bodies] == expected


def test_local_delegate_without_model_uses_mechanical(backend):
    _write_roles({"mechanical": {"top_k": 20}, "code": {"top_k": 99}})
    _delegate(None)
    (body,) = backend.bodies
    assert body["model"] == MECHANICAL
    assert body["top_k"] == 20


def test_vision_role_params_reach_image_call(backend, tmp_path):
    image = capture._minimal_png(tmp_path / "dot.png")
    server.local_describe_image(path=str(image))
    (today,) = backend.bodies

    backend.reset()
    _write_roles({"vision": {"top_k": 7}, "mechanical": {"top_k": 99}})
    server.local_describe_image(path=str(image))
    (body,) = backend.bodies
    assert body["model"] == capture.VISION
    assert body["messages"] == today["messages"], "the content blocks are the product's"
    assert body["top_k"] == 7


# --- REQ-009: read on every operation -----------------------------------------------------------


def test_file_change_applies_next_operation(backend, tmp_path):
    assert bp.set_value("mechanical", "top_k", "20")[0]
    _classify(tmp_path)
    # Same size on purpose (`20` -> `30`): the cache must see it by `st_mtime_ns`/`st_ino`.
    assert bp.set_value("mechanical", "top_k", "30")[0]
    _classify(tmp_path)
    assert bp.unset("mechanical", "top_k")[0]
    _classify(tmp_path)
    assert [body.get("top_k") for body in backend.bodies] == [20, 30, None]


# --- REQ-011 by file and by variable: reasoning without budget ----------------------------------


@pytest.mark.parametrize("source", ["file", "env"])
def test_thinking_without_budget_body_has_no_template_kwargs(
    source, backend, tmp_path, monkeypatch
):
    if source == "file":
        _write_roles({"mechanical": {"enable_thinking": True, "top_k": 20}})
    else:
        monkeypatch.setenv(VARIABLE, "mechanical.enable_thinking=on;mechanical.top_k=20")
    _classify(tmp_path)
    (body,) = backend.bodies
    assert body["top_k"] == 20, "the rest of the role still applies"
    assert "chat_template_kwargs" not in body
    assert "reasoning_budget_tokens" not in body
    assert body["max_tokens"] == 16
    assert ("mechanical", "enable_thinking", "thinking_without_budget") in _codes(
        bp.effective("mechanical").warnings
    )


# --- REQ-005/006/007: what never reaches the body ------------------------------------------------


def _logged_text() -> str:
    """Everything the operation wrote in `LOG_DIR` but the parameters file itself."""
    return "".join(
        file.read_text(encoding="utf-8", errors="replace")
        for file in Path(config.LOG_DIR).rglob("*")
        if file.is_file() and file.name != bp.FILE_NAME and not file.name.endswith(".lock")
    )


@pytest.mark.parametrize("source", ["file", "env"])
@pytest.mark.parametrize("key", sorted(bp.RESERVED_KEYS))
def test_reserved_key_never_reaches_body(key, source, backend, tmp_path, monkeypatch):
    _extract(tmp_path)
    (today,) = backend.bodies

    backend.reset()
    if source == "file":
        _write_roles({"mechanical": {key: SENTINELS[0], "top_k": 20}})
    else:
        monkeypatch.setenv(VARIABLE, f"mechanical.{key}=7;mechanical.top_k=20")
    _extract(tmp_path)
    (body,) = backend.bodies
    assert body["top_k"] == 20, "the valid key of the role still applies"
    if key in today:
        assert body[key] == today[key]
    else:
        assert key not in body
    assert SENTINELS[0] not in json.dumps(body)
    assert ("mechanical", key, "reserved_key") in _codes(bp.effective("mechanical").warnings)


@pytest.mark.parametrize(
    ("source", "roles", "variable", "kept", "dropped"),
    [
        ("file", {"code": {"top_k": 20, "foo": SENTINELS[0]}}, "", {"top_k": 20}, ["foo"]),
        (
            "env",
            {},
            f"code.foo={SENTINELS[0]};code.top_k={SENTINELS[1]};code.min_p=0.1",
            {"min_p": 0.1},
            ["foo", "top_k"],
        ),
        ("range", {"code": {"top_p": 1.5, "min_p": 0.1}}, "", {"min_p": 0.1}, ["top_p"]),
    ],
)
def test_bad_keys_dropped_rest_applied(
    source, roles, variable, kept, dropped, backend, tmp_path, monkeypatch
):
    if roles:
        _write_roles(roles)
    if variable:
        monkeypatch.setenv(VARIABLE, variable)
    _boilerplate(tmp_path)
    (body,) = backend.bodies
    for key, value in kept.items():
        assert body[key] == value, key
    for key in dropped:
        assert key not in body, key
    warnings = bp.effective("code").warnings
    assert {w.key for w in warnings} >= set(dropped)
    shown = json.dumps(body) + _logged_text() + " ".join(map(bp.warning_text, warnings))
    for sentinel in SENTINELS:
        assert sentinel not in shown, source
