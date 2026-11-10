"""#586: a small `local_extract` input that carries a table goes to the `long` role.

REQ-011 to REQ-019 and REQ-031 of the SDD change `extract-cross-fill-and-routing`. The mechanical
model answered with the value of another row in 8 of the 16 small inputs with a table of the
research, the long one in none (measured by the product, `verification.md`, «Puerta (T1)»).

Every test runs the real tool against a fake backend (`server._post_chat` replaced) that records
the model and body of each call, with the default configuration reloaded from the environment.
The inputs are the research's, copied in `tests/fixtures/extract_table_routing/`. Nothing calls a
real backend and every log row goes to the test's directory.
"""

from __future__ import annotations

import contextvars
import json
from pathlib import Path

import pytest

from local_delegate import backend_params as bp
from local_delegate import cancellation, config, failures, i18n, server

FIXTURES = Path(__file__).parent / "fixtures" / "extract_table_routing"
MECHANICAL = "gemma3-4b"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"


def _cases() -> dict[str, dict]:
    data = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    return {case["id"]: case for case in data["cases"]}


CASES = _cases()


def _case(prefix: str) -> dict:
    return next(case for name, case in CASES.items() if name.startswith(prefix))


def _path(case: dict) -> str:
    return str(FIXTURES / case["file"])


def _text(case: dict) -> str:
    return (FIXTURES / case["file"]).read_text(encoding="utf-8")


def _answer(fields: list[str]) -> str:
    """A full answer: every field with a value that is not a "no data" marker."""
    return json.dumps({name: f"value-{index}" for index, name in enumerate(fields)})


class Backend:
    """The fake backend: records `(model, body)` of every real call and answers per model."""

    def __init__(self) -> None:
        self.models: list[str] = []
        self.bodies: list[dict] = []
        self.answer = lambda _model, _body: server.ChatResult(
            text="{}", ok=True, finish_reason="stop"
        )

    def __call__(self, model: str, payload: dict) -> server.ChatResult:
        self.models.append(model)
        self.bodies.append(json.loads(json.dumps(payload)))
        return self.answer(model, payload)

    def answer_with(self, text: str) -> None:
        self.answer = lambda _model, _body: server.ChatResult(
            text=text, ok=True, finish_reason="stop"
        )


@pytest.fixture
def backend(reload_config, monkeypatch):
    reload_config()
    bp._forget()
    fake = Backend()
    monkeypatch.setattr(server, "_post_chat", fake)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    yield fake
    bp._forget()


@pytest.fixture
def chat_roles(monkeypatch):
    """The `role` each `_chat` call of the operation got, in order."""
    roles: list[str | None] = []
    original = server._chat

    def spy(*args, **kwargs):
        roles.append(kwargs.get("role"))
        return original(*args, **kwargs)

    monkeypatch.setattr(server, "_chat", spy)
    return roles


def _rows(tmp_path: Path, tool: str = "local_extract") -> list[dict]:
    rows: list[dict] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        rows += [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if row.get("tool") == tool]


def _expected_reason() -> dict:
    return {
        "role": "long",
        "reason": "table",
        "notice": i18n.t("mcp.warning.extract_role_reason_table"),
    }


# --- REQ-011: a small input with a table goes to `long`, by `text` and by `path` --------------


def test_a_small_table_goes_to_the_long_model_by_path(backend, chat_roles, tmp_path):
    case = _case("01-")
    backend.answer_with(_answer(case["fields"]))

    data = server.local_extract(fields=case["fields"], path=_path(case))

    assert backend.models == [LONG], "the small table goes to the long model"
    assert chat_roles == ["long"], "the call carries role='long'"
    assert data["_local_delegate"]["role_reason"] == _expected_reason()
    assert [row["model"] for row in _rows(tmp_path)] == [LONG]


def test_a_small_table_goes_to_the_long_model_by_text(backend, chat_roles, tmp_path):
    case = _case("06-")
    backend.answer_with(_answer(case["fields"]))

    data = server.local_extract(fields=case["fields"], text=_text(case))

    assert backend.models == [LONG], "the small table goes to the long model"
    assert chat_roles == ["long"], "the call carries role='long'"
    assert data["_local_delegate"]["role_reason"]["reason"] == "table"


@pytest.mark.parametrize(
    "case_id",
    sorted(name for name, case in CASES.items() if case["has_table"] and not case.get("large")),
)
def test_every_small_case_with_a_table_goes_to_long(case_id, backend, tmp_path):
    case = CASES[case_id]
    backend.answer_with(_answer(case["fields"]))

    data = server.local_extract(fields=case["fields"], path=_path(case))

    assert backend.models == [LONG]
    assert data["_local_delegate"]["role_reason"] == _expected_reason()
    assert [row.get("role_reason") for row in _rows(tmp_path)] == ["table"]


# --- REQ-012: without a table, today's routing (the negative control) -------------------------


@pytest.mark.parametrize(
    "case_id", sorted(name for name, case in CASES.items() if not case["has_table"])
)
def test_a_small_input_without_a_table_stays_on_the_mechanical_model(case_id, backend, tmp_path):
    case = CASES[case_id]
    backend.answer_with(_answer(case["fields"]))

    data = server.local_extract(fields=case["fields"], path=_path(case))

    assert backend.models == [MECHANICAL]
    assert "role_reason" not in data.get("_local_delegate", {})
    rows = _rows(tmp_path)
    assert len(rows) == 1 and "role_reason" not in rows[0], rows


def test_the_six_cases_without_a_table_are_the_ones_of_the_research():
    without = sorted(name[:2] for name, case in CASES.items() if not case["has_table"])
    assert without == ["03", "04", "05", "13", "14", "18"]


# --- REQ-013: no minimum of fields (D12) ------------------------------------------------------


def test_with_one_field_the_small_table_goes_to_the_long_model(backend, chat_roles, tmp_path):
    case = _case("01-")
    backend.answer_with('{"licensed_user_limits": null}')

    data = server.local_extract(fields=["licensed_user_limits"], path=_path(case))

    assert backend.models == [LONG], "with one field, the small table goes to the long model"
    assert chat_roles == ["long"]
    assert data["_local_delegate"]["role_reason"]["reason"] == "table"


def test_the_minimum_of_fields_is_one():
    assert server._TABLE_LONG_MIN_FIELDS == 1


# --- REQ-014: the switch ----------------------------------------------------------------------


def test_with_the_switch_off_a_small_table_stays_on_the_mechanical_model(
    backend, reload_config, tmp_path
):
    reload_config(LOCAL_DELEGATE_EXTRACT_TABLE_LONG="0")
    assert config.EXTRACT_TABLE_LONG is False
    case = _case("01-")
    backend.answer_with(_answer(case["fields"]))

    data = server.local_extract(fields=case["fields"], path=_path(case))

    assert backend.models == [MECHANICAL], "switched off, it goes to the mechanical model"
    assert "role_reason" not in data.get("_local_delegate", {})
    rows = _rows(tmp_path)
    assert len(rows) == 1 and "role_reason" not in rows[0], rows


def test_the_switch_is_on_by_default_and_registered(backend):
    assert config.EXTRACT_TABLE_LONG is True
    assert "LOCAL_DELEGATE_EXTRACT_TABLE_LONG" in config.ENVIRONMENT_VARIABLES


# --- REQ-015: only `local_extract` ------------------------------------------------------------


def test_the_other_three_tools_stay_on_the_mechanical_model(backend, tmp_path):
    case = _case("06-")
    backend.answer_with("- a summary line")

    server.local_summarize(text=_text(case))
    server.local_lint_summary(text=_text(case))
    server.local_translate(target_lang="en", text=_text(case))

    assert backend.models, "the three tools reached the backend"
    assert set(backend.models) == {MECHANICAL}, "the other three tools stay on mechanical"
    for tool in ("local_summarize", "local_lint_summary", "local_translate"):
        assert all("role_reason" not in row for row in _rows(tmp_path, tool)), tool


# --- REQ-016: `role_reason` in the answer, also an error one; never in `warning` --------------


def test_by_size_there_is_no_role_reason(backend, tmp_path):
    case = _case("15-")
    assert (FIXTURES / case["file"]).stat().st_size > config.LONG_INPUT_CHARS
    backend.answer_with(_answer(case["fields"]))

    data = server.local_extract(fields=case["fields"], path=_path(case))

    assert backend.models == [LONG]
    assert "role_reason" not in data.get("_local_delegate", {}), "by size there is no role_reason"
    assert all("role_reason" not in row for row in _rows(tmp_path))


def test_the_error_answer_carries_role_reason(backend, tmp_path):
    case = _case("01-")
    backend.answer_with("this is not JSON")

    data = server.local_extract(fields=case["fields"], path=_path(case))

    meta = data["_local_delegate"]
    assert "error" in meta and "raw" in meta, meta
    assert meta.get("role_reason") == _expected_reason(), "the error answer carries role_reason"
    assert [row.get("role_reason") for row in _rows(tmp_path)] == ["table"]


def test_a_json_that_is_not_an_object_carries_role_reason(backend):
    case = _case("01-")
    backend.answer_with("[1, 2]")

    data = server.local_extract(fields=case["fields"], path=_path(case))

    assert data["_local_delegate"].get("role_reason") == _expected_reason()


def test_role_reason_adds_nothing_to_warning(backend):
    case = _case("10-")
    backend.answer_with(_answer(case["fields"]))

    data = server.local_extract(fields=case["fields"], path=_path(case))

    meta = data["_local_delegate"]
    assert meta["role_reason"]["reason"] == "table"
    assert "warning" not in meta, "warning does not exist"
    assert all(data[name] is not None for name in case["fields"])


# --- REQ-017: the log rows, also the ones `_log_stopped` writes --------------------------------


def test_the_good_path_row_carries_role_reason(backend, tmp_path):
    case = _case("01-")
    backend.answer_with(_answer(case["fields"]))

    server.local_extract(fields=case["fields"], path=_path(case))

    rows = _rows(tmp_path)
    assert len(rows) == 1, rows
    assert rows[0]["role_reason"] == "table" and rows[0]["ok"] is True
    assert rows[0]["model"] == LONG


def _run_under_token(fn) -> tuple[cancellation.Token, BaseException | None]:
    """Runs `fn` as a `tools/call` does: with the call's token bound, in its own context."""
    token = cancellation.Token("local_extract")
    raised: list[BaseException] = []

    def call() -> None:
        cancellation._CURRENT.set(token)
        try:
            fn()
        except BaseException as exc:
            raised.append(exc)

    contextvars.copy_context().run(call)
    return token, (raised[0] if raised else None)


def test_the_deadline_row_of_log_stopped_carries_role_reason(backend, tmp_path):
    case = _case("01-")

    def deadline(_model, _payload):
        # The daemon's own deadline fires while the long model answers (or loads).
        cancellation.current().cancel(cancellation.REASON_DEADLINE)
        return server.ChatResult(text=_answer(case["fields"]), ok=True, finish_reason="stop")

    backend.answer = deadline
    token, raised = _run_under_token(
        lambda: server.local_extract(fields=case["fields"], path=_path(case))
    )
    assert isinstance(raised, cancellation.CallCancelled), raised
    assert _rows(tmp_path) == [], "the operation stopped before writing its own row"

    # What the middleware does on the event loop, outside the tool's context.
    server._log_cancelled(token)

    rows = _rows(tmp_path)
    assert len(rows) == 1, rows
    assert rows[0]["error"] == "cancelled" and rows[0]["cancel_reason"] == "deadline", rows[0]
    assert rows[0].get("role_reason") == "table", "the _log_stopped row carries role_reason"
    assert rows[0]["model"] == LONG


@pytest.mark.parametrize(
    ("failure", "error"),
    [(server.QueueSaturated("full"), "queue_saturated"), (RuntimeError("boom"), "exception")],
    ids=["queue_saturated", "exception"],
)
def test_the_aborted_rows_of_log_stopped_carry_role_reason(failure, error, backend, tmp_path):
    case = _case("01-")

    def fail(_model, _payload):
        raise failure

    backend.answer = fail
    token, raised = _run_under_token(
        lambda: server.local_extract(fields=case["fields"], path=_path(case))
    )
    assert raised is failure, raised
    assert token.failure is failure

    server._log_aborted(token)

    rows = _rows(tmp_path)
    assert len(rows) == 1, rows
    assert rows[0]["error"] == error, rows[0]
    assert rows[0].get("role_reason") == "table", "the _log_stopped row carries role_reason"


def test_a_stopped_call_without_a_table_has_no_role_reason(backend, tmp_path):
    case = _case("14-")

    def fail(_model, _payload):
        raise RuntimeError("boom")

    backend.answer = fail
    token, raised = _run_under_token(
        lambda: server.local_extract(fields=case["fields"], path=_path(case))
    )
    assert isinstance(raised, RuntimeError)
    server._log_aborted(token)

    rows = _rows(tmp_path)
    assert len(rows) == 1 and "role_reason" not in rows[0], rows


def test_the_reason_does_not_leak_to_the_next_operation(backend, tmp_path):
    table = _case("01-")
    backend.answer_with(_answer(table["fields"]))
    server.local_extract(fields=table["fields"], path=_path(table))
    backend.answer_with("- a summary line")

    server.local_summarize(text="A short text to summarize.")

    assert server._ROLE_REASON.get() is None
    rows = _rows(tmp_path, "local_summarize")
    assert len(rows) == 1 and "role_reason" not in rows[0], rows


# --- REQ-018: the prompt does not change; the role's parameters apply -------------------------


def test_system_and_user_message_are_identical_byte_for_byte(backend, reload_config):
    case = _case("01-")
    backend.answer_with(_answer(case["fields"]))
    server.local_extract(fields=case["fields"], path=_path(case))
    with_rule = backend.bodies[-1]

    reload_config(LOCAL_DELEGATE_EXTRACT_TABLE_LONG="0")
    server.local_extract(fields=case["fields"], path=_path(case))
    without_rule = backend.bodies[-1]

    assert backend.models == [LONG, MECHANICAL]
    assert with_rule["messages"] == without_rule["messages"], "system and message identical"
    assert with_rule.get("response_format") == without_rule.get("response_format")


def test_the_parameters_of_the_long_role_apply_to_the_call(backend):
    bp.path().write_text(
        json.dumps({"version": 1, "roles": {"long": {"temperature": 0.6}}}), encoding="utf-8"
    )
    bp._forget()
    case = _case("01-")
    backend.answer_with(_answer(case["fields"]))

    server.local_extract(fields=case["fields"], path=_path(case))
    assert [body["temperature"] for body in backend.bodies] == [0.6]

    server.local_extract(fields=_case("14-")["fields"], path=_path(_case("14-")))
    assert backend.bodies[-1]["temperature"] == 0.0, "the mechanical call keeps its own"


# --- REQ-019: the fallback is the one of `long`: the model of `code` --------------------------


def test_when_the_long_model_fails_the_code_model_answers(backend, tmp_path):
    case = _case("01-")
    answer = _answer(case["fields"])

    def long_fails(model, _payload):
        if model == LONG:
            return server.ChatResult(
                text="[local-delegate error] HTTP 500",
                ok=False,
                error="http_500",
                error_class=failures.FailureClass.MODEL,
            )
        return server.ChatResult(text=answer, ok=True, finish_reason="stop")

    backend.answer = long_fails

    data = server.local_extract(fields=case["fields"], path=_path(case))

    meta = data["_local_delegate"]
    assert backend.models == [LONG, CODE], "`loaded` is empty: the code model answers"
    assert meta["fallback"]["answered_by"] == config.MODEL_CODE
    assert meta["fallback"]["instead_of"] == LONG
    assert meta["role_reason"]["role"] == "long", "the role decided, next to who answered"
    rows = _rows(tmp_path)
    assert len(rows) == 1 and rows[0]["model"] == CODE and rows[0]["role_reason"] == "table"


# --- REQ-031 and REQ-010: the tool's description, and `server` calls the rule ------------------


def test_the_docstring_names_role_reason_and_its_switch():
    doc = server.local_extract.__doc__ or ""
    assert "role_reason" in doc
    assert "LOCAL_DELEGATE_EXTRACT_TABLE_LONG" in doc
    assert "table" in doc


def test_the_server_calls_the_rule_and_does_not_repeat_it():
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "table_detect.has_table(" in source
    assert '"<table"' not in source and "'<table'" not in source
