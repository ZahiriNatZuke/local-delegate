"""#692, #698: the JSON schema of `local_extract` typed field by field, its check and its cap.

#692: a field that asks for a list came back as `true`, because every field had the same
primitive schema. #698: a fixed 512-token cap cut the JSON of a long list. Backend faked
(`_run_chat` doubled), no network; the usage log goes to `tmp_path`.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import config, extract_schema, i18n, server


@pytest.mark.parametrize(
    ("name", "by_path", "kind"),
    [
        ("tres_reglas_desactivadas", False, "list"),
        ("tiene_tests", False, "boolean"),
        ("hay_errores", False, "boolean"),
        ("tiene_dos_tests", False, "boolean"),  # order: boolean before list
        ("¿funciona?", False, "boolean"),
        ("number_of_comments", False, "count"),
        ("commentCount", False, "count"),
        ("total_lines_added", False, "count"),
        ("licensed_user_limits", False, "list"),
        ("top_3", False, "list"),
        ("todos_los_autores", False, "list"),
        ("status", False, "scalar"),
        ("class", False, "scalar"),
        ("analysis", False, "scalar"),
        ("soporta_windows", False, "scalar"),
        ("title", False, "scalar"),
        ("funciones_con_lineas", True, "location"),
        ("funciones_con_lineas", False, "list"),
        ("heading_line", True, "location"),
        ("heading_line", False, "scalar"),
    ],
)
def test_field_kinds(name, by_path, kind):
    assert extract_schema.field_kind(name, by_path) == kind


def test_a_number_fits_a_list_and_a_boolean_does_not():
    assert not extract_schema.mismatch("list", 14)
    assert not extract_schema.mismatch("list", ["a", 2])
    assert extract_schema.mismatch("list", True)
    assert extract_schema.mismatch("list", {"a": 1})
    assert extract_schema.mismatch("count", False)
    assert not extract_schema.mismatch("scalar", True)
    assert extract_schema.mismatch("scalar", {"value": "x"})
    assert not extract_schema.mismatch("boolean", None)
    assert not extract_schema.mismatch("location", [{"name": "a", "anchor": "x"}])
    assert extract_schema.mismatch("location", "a: líneas 3-4")
    assert extract_schema.mismatch("location", [{"anchor": "x"}])


def test_the_location_schema_has_its_enum_and_its_cap():
    prop = extract_schema.property_schema("location", singular=True, names=["A.f", "g"])
    assert prop["maxItems"] == 1
    assert prop["items"]["properties"]["name"]["enum"] == ["A.f", "g"]
    assert prop["items"]["additionalProperties"] is False
    many = [f"n{i}" for i in range(extract_schema.MAX_ENUM_NAMES + 1)]
    prop = extract_schema.property_schema("location", names=many)
    assert "enum" not in prop["items"]["properties"]["name"]
    assert "maxItems" not in prop


def test_output_budget():
    assert extract_schema.output_budget({"a": "scalar"}) == 512
    assert extract_schema.output_budget({"f": "location"}, {"f": 60}) == 64 + 40 * 60 == 2464
    assert extract_schema.output_budget({"f": "location"}, {"f": 500}) == 4096
    many = {f"lista_{i}": "list" for i in range(5)}
    assert extract_schema.output_budget(many) == 64 + 5 * 384


def _ok(text: str, finish: str = "stop"):
    return server.ChatResult(text=text, ok=True, finish_reason=finish)


@pytest.fixture
def backend(monkeypatch, tmp_path):
    """A model that answers the queued replies in order; each call is recorded."""
    state: dict = {"replies": [], "calls": []}

    def run_chat(model, system, user, max_tokens, temperature, **kwargs):
        state["calls"].append({"system": system, "user": user, "max_tokens": max_tokens, **kwargs})
        reply = state["replies"].pop(0) if len(state["replies"]) > 1 else state["replies"][0]
        return _ok(reply), 0, None, [server.Attempt(model, True, None, None, 0)]

    monkeypatch.setattr(server, "_run_chat", run_chat)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    i18n.reset()
    state["log"] = tmp_path / "usage.jsonl"
    return state


def _rows(state) -> list[dict]:
    rows: list[dict] = []
    for file in sorted(state["log"].parent.glob("usage*.jsonl")):
        rows += [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if row.get("tool") == "local_extract"]


def test_a_boolean_in_a_list_field_is_retried_once(backend):
    backend["replies"] = ['{"tres_reglas": true}', '{"tres_reglas": ["a", "b", "c"]}']
    out = server.local_extract(fields=["tres_reglas"], text="Reglas: a, b y c.")
    assert out["tres_reglas"] == ["a", "b", "c"]
    assert len(backend["calls"]) == 2
    assert "tres_reglas" in backend["calls"][1]["user"]
    assert "boolean" in backend["calls"][1]["user"]
    assert "type_mismatch_keys" not in out.get("_local_delegate", {})
    [row] = _rows(backend)
    assert row["chunks"] == 2, "both backend calls are counted in the one row"


def test_a_mismatch_that_persists_is_null_and_said(backend):
    backend["replies"] = ['{"tres_reglas": true, "status": "ok"}']
    out = server.local_extract(fields=["tres_reglas", "status"], text="Reglas: a, b y c.")
    assert len(backend["calls"]) == 2
    assert out["tres_reglas"] is None
    assert out["status"] == "ok"
    meta = out["_local_delegate"]
    assert meta["type_mismatch_keys"] == {"tres_reglas": {"expected": "array", "got": "boolean"}}
    assert meta["warning"].endswith(
        i18n.t("mcp.warning.extract_type_mismatch", fields="tres_reglas")
    )


def test_free_mode_is_validated_too(backend, monkeypatch):
    monkeypatch.setattr(config, "JSON_SCHEMA_MODE", "off")
    backend["replies"] = ['{"tres_reglas": true}', '{"tres_reglas": ["a"]}']
    out = server.local_extract(fields=["tres_reglas"], text="Reglas: a.")
    assert backend["calls"][0].get("response_format") is None
    assert len(backend["calls"]) == 2
    assert out["tres_reglas"] == ["a"]


def test_a_number_in_a_list_field_is_accepted(backend):
    backend["replies"] = ['{"licensed_user_limits": 14}']
    out = server.local_extract(fields=["licensed_user_limits"], text="Límite: 14 usuarios.")
    assert len(backend["calls"]) == 1
    assert out["licensed_user_limits"] == 14


def test_a_boolean_in_a_scalar_field_is_accepted(backend):
    backend["replies"] = ['{"soporta_windows": true}']
    out = server.local_extract(fields=["soporta_windows"], text="Funciona en Windows.")
    assert len(backend["calls"]) == 1
    assert out["soporta_windows"] is True


def test_a_chunked_value_that_breaks_its_type_is_dropped_before_joining(backend, monkeypatch):
    monkeypatch.setattr(config, "max_chars_for_role", lambda role: 4_000)
    backend["replies"] = ['{"tres_reglas": true}']
    text = "".join(f"Línea {i}: relleno de un bloque que no dice nada.\n" for i in range(600))
    out = server.local_extract(fields=["tres_reglas"], text=text)
    assert len(backend["calls"]) > 2  # guard: it went through the map/reduce
    assert out["tres_reglas"] is None
    assert out["_local_delegate"]["type_mismatch_keys"]["tres_reglas"]["got"] == "boolean"


def test_the_single_call_asks_the_budget_of_its_fields(backend):
    backend["replies"] = ['{"tres_reglas": ["a"], "status": "ok"}']
    server.local_extract(fields=["tres_reglas", "status"], text="Reglas: a.")
    assert [c["max_tokens"] for c in backend["calls"]] == [64 + 384 + 192]
