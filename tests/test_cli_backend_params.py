"""`local-delegate backend-params {show,set,unset,reset}` (SDD backend-extra-params, T8).

REQ-003 (the command), REQ-011 (rules of `set`/`unset`), REQ-023 (context warning of `set`),
REQ-005/007 (rejections by `set`, file untouched) and REQ-017 (no value in any message).
`config.LOG_DIR` points to `tmp_path` (conftest): the real file of the machine is never touched.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import backend_params as bp
from local_delegate import cli, i18n, llamaswap_config
from local_delegate.i18n import t

VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"
SENTINELS = ("SENTINEL-7Q", "SENTINEL-8R")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    # The context check reads the llama-swap config; a known context keeps it deterministic.
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (32768, False))
    bp._forget()
    yield
    bp._forget()


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    bp._forget()
    code = cli.run(["backend-params", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _write_doc(roles: dict) -> None:
    bp.path().write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")


def _roles() -> dict:
    return json.loads(bp.path().read_text(encoding="utf-8"))["roles"]


# --- show -----------------------------------------------------------------------------------------


def test_show_empty(capsys):
    code, out, err = _run(capsys, "show")
    assert code == 0 and err == ""
    assert out.splitlines() == [
        t("cli.backend_params.file", path=bp.path()),
        t("cli.backend_params.none"),
    ]
    assert not bp.path().exists()  # `show` never creates the file


def test_show_prints_file_path(capsys, tmp_path):
    # The check of `LOG_DIR` in the live test (plan §4.4) reads this first line.
    _write_doc({"code": {"top_k": 20}})
    _, out, _ = _run(capsys, "show")
    first = out.splitlines()[0]
    assert first == t("cli.backend_params.file", path=bp.path())
    assert str(tmp_path / "backend-params.json") in first


def test_show_text_rows(capsys, monkeypatch):
    _write_doc({"code": {"top_k": 20}})
    monkeypatch.setenv(VARIABLE, "code.min_p=0.1")
    _, out, _ = _run(capsys, "show")
    assert out.splitlines()[1:] == [
        "code",
        t(
            "cli.backend_params.row",
            key="top_k",
            value="20",
            source=t("cli.backend_params.source.file"),
        ),
        t(
            "cli.backend_params.row",
            key="min_p",
            value="0.1",
            source=t("cli.backend_params.source.env"),
        ),
    ]


def test_show_json_shape(capsys, monkeypatch):
    _write_doc({"code": {"top_k": 20, "enable_thinking": False}})
    monkeypatch.setenv(VARIABLE, "long.min_p=0.1;code.foo=1;bar.top_k=3")
    code, out, _ = _run(capsys, "show", "--json")
    assert code == 0
    data = json.loads(out)
    assert set(data) == {"file", "roles"}
    assert data["file"] == str(bp.path())
    assert [row["role"] for row in data["roles"]] == [*bp.ROLES, ""]
    by_role = {row["role"]: row for row in data["roles"]}
    assert all(set(row) == {"role", "params", "warnings"} for row in data["roles"])
    assert by_role["code"]["params"] == [
        {"key": "top_k", "value": 20, "source": "file"},
        {"key": "enable_thinking", "value": False, "source": "file"},
    ]
    assert by_role["code"]["warnings"] == [{"code": "unknown_key", "key": "foo"}]
    assert by_role["long"]["params"] == [{"key": "min_p", "value": 0.1, "source": "env"}]
    assert by_role[""] == {
        "role": "",
        "params": [],
        "warnings": [{"code": "unknown_role", "key": "top_k"}],
    }


@pytest.mark.parametrize("where", ["file", "env"])
def test_show_hides_sentinels(where, capsys, monkeypatch):
    if where == "file":
        _write_doc({"code": {"top_k": 20, "foo": "SENTINEL-7Q"}})
    else:
        monkeypatch.setenv(VARIABLE, "code.foo=SENTINEL-7Q;code.top_k=SENTINEL-8R;code.min_p=0.1")
    text = _run(capsys, "show")
    as_json = _run(capsys, "show", "--json")
    # Guard: the dropped entries did reach `show` (a warning per entry), so the check means something.
    assert "foo" in text[1] and '"unknown_key"' in as_json[1]
    for output in (*text[1:], *as_json[1:]):
        for sentinel in SENTINELS:
            assert sentinel not in output


# --- set ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value", "stored"),
    [("top_k", "20", 20), ("presence_penalty", "-0.5", -0.5), ("reasoning_effort", "high", "high")],
)
def test_set_valid_writes(key, value, stored, capsys):
    code, out, err = _run(capsys, "set", "code", key, value)
    assert code == 0 and err == ""
    assert out.strip() == t("cli.backend_params.saved", role="code", key=key, path=bp.path())
    assert _roles() == {"code": {key: stored}}


@pytest.mark.parametrize(
    ("role", "key", "value", "text_key"),
    [
        ("foo", "top_k", "20", "cli.backend_params.refused.unknown_role"),
        ("code", "foo", "SENTINEL-7Q", "cli.backend_params.refused.unknown_key"),
        ("code", "model", "SENTINEL-7Q", "cli.backend_params.refused.reserved_key"),
        ("code", "top_k", "SENTINEL-8R", "cli.backend_params.refused.bad_type"),
        ("code", "top_p", "1.5", "cli.backend_params.refused.out_of_range"),
    ],
    ids=["role", "key", "reserved", "type", "range"],
)
def test_set_invalid_leaves_file_untouched(role, key, value, text_key, capsys):
    _write_doc({"code": {"min_p": 0.1}})
    before = bp.path().read_bytes()
    mtime = bp.path().stat().st_mtime_ns
    code, out, err = _run(capsys, "set", role, key, value)
    assert code != 0
    assert out == ""
    reason = t(text_key, role=role, key=key)
    assert err.strip() == t("cli.backend_params.refused", reason=reason)
    assert bp.path().read_bytes() == before
    assert bp.path().stat().st_mtime_ns == mtime


def test_set_thinking_without_budget_exit_nonzero(capsys):
    code, out, err = _run(capsys, "set", "code", "enable_thinking", "on")
    assert code != 0 and out == ""
    reason = t("cli.backend_params.refused.thinking_set", role="code")
    assert err.strip() == t("cli.backend_params.refused", reason=reason)
    assert not bp.path().exists()


def test_set_context_warning_exit_zero(capsys, monkeypatch):
    # A context that is an estimate and too small for the budget: two warnings, no refusal.
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (8192, True))
    assert _run(capsys, "set", "code", "reasoning_budget_tokens", "8000")[0] == 0
    code, out, err = _run(capsys, "set", "code", "enable_thinking", "on")
    assert code == 0
    assert out.strip() == t(
        "cli.backend_params.saved", role="code", key="enable_thinking", path=bp.path()
    )
    assert err.splitlines() == [
        t("cli.backend_params.warning", detail=bp.warning_text(bp.Warning("code", "", c)))
        for c in ("context_estimated", "context_overflow")
    ]
    assert _roles() == {"code": {"reasoning_budget_tokens": 8000, "enable_thinking": True}}


@pytest.mark.parametrize("lang", ["es", "en"])
def test_messages_never_echo_value(lang, capsys, monkeypatch):
    _set_language(monkeypatch, lang)
    attempts = [
        ("code", "top_k", "SENTINEL-8R"),
        ("code", "foo", "SENTINEL-7Q"),
        ("code", "temperature", "SENTINEL-7Q"),
        ("code", "reasoning_effort", "SENTINEL-8R"),
        ("SENTINEL-ROLE", "top_k", "SENTINEL-7Q"),
    ]
    for role, key, value in attempts:
        code, out, err = _run(capsys, "set", role, key, value)
        assert code != 0
        assert err.strip()  # guard: the refusal did print a reason
        for sentinel in SENTINELS:
            assert sentinel not in out + err


# --- unset / reset --------------------------------------------------------------------------------


def test_unset(capsys):
    assert _run(capsys, "set", "code", "top_k", "20")[0] == 0
    assert _run(capsys, "set", "code", "min_p", "0.1")[0] == 0
    code, out, _ = _run(capsys, "unset", "code", "top_k")
    assert code == 0
    assert out.strip() == t("cli.backend_params.removed", role="code", key="top_k", path=bp.path())
    assert _roles() == {"code": {"min_p": 0.1}}
    # The budget cannot go while reasoning stays on (REQ-011).
    _run(capsys, "set", "code", "reasoning_budget_tokens", "512")
    _run(capsys, "set", "code", "enable_thinking", "on")
    before = bp.path().read_bytes()
    code, out, err = _run(capsys, "unset", "code", "reasoning_budget_tokens")
    assert code != 0 and out == ""
    reason = t("cli.backend_params.refused.thinking_unset", role="code")
    assert err.strip() == t("cli.backend_params.refused", reason=reason)
    assert bp.path().read_bytes() == before


def test_reset_role(capsys):
    # User decision 12: reasoning on with its budget does not block `reset`.
    for key, value in (("reasoning_budget_tokens", "512"), ("enable_thinking", "on")):
        assert _run(capsys, "set", "code", key, value)[0] == 0
    assert _run(capsys, "set", "long", "top_k", "20")[0] == 0
    code, out, err = _run(capsys, "reset", "code")
    assert (code, err) == (0, "")
    assert out.strip() == t("cli.backend_params.reset_role", role="code", path=bp.path())
    assert _roles() == {"long": {"top_k": 20}}
    code, _, err = _run(capsys, "reset", "foo")
    assert code != 0
    reason = t("cli.backend_params.refused.unknown_role", role="foo", key="")
    assert err.strip() == t("cli.backend_params.refused", reason=reason)


def test_reset_all(capsys):
    for key, value in (("reasoning_budget_tokens", "512"), ("enable_thinking", "on")):
        assert _run(capsys, "set", "code", key, value)[0] == 0
    assert _run(capsys, "set", "long", "top_k", "20")[0] == 0
    code, out, err = _run(capsys, "reset")
    assert (code, err) == (0, "")
    assert out.strip() == t("cli.backend_params.reset_all", path=bp.path())
    assert _roles() == {}
