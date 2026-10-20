"""Lines of the per-role backend parameters in `local_status` (SDD backend-extra-params, T14).

REQ-016 (`local_status`), REQ-023 (context warnings) and REQ-017/REQ-006 (texts from the catalog,
no value of a dropped entry). `local_status` runs in the daemon, so its lines show the daemon's
own file and variable. Without parameters or warnings the report is the one of before.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import backend_params as bp
from local_delegate import llamaswap_config, server
from local_delegate.i18n import t

VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"
SENTINELS = ("SENTINEL-7Q", "SENTINEL-8R")


@pytest.fixture(autouse=True)
def offline(reload_config, monkeypatch):
    """`local_status` without backend, GPU or llama-swap, and no parameters to start with."""
    reload_config()
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (32768, False))
    monkeypatch.setattr(
        server,
        "probe_backend",
        lambda: server.BackendState(False, [], True, "refused", "no network in the tests", None),
    )
    for name in ("_vram_info", "_ram_info", "_llamaswap_groups"):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)
    bp._forget()
    yield
    bp._forget()


def _write_doc(roles: dict) -> None:
    bp.path().write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")


def _status_lines() -> list[str]:
    return server.local_status().splitlines()


def _param(key: str, value: str, source: str = "file") -> str:
    return f"{key}={value} " + t(f"mcp.status.backend_params.from_{source}")


def _role_line(role: str, *params: str) -> str:
    return t("mcp.status.backend_params.role", role=role, params=", ".join(params))


def _warning_line(role: str, code: str, key: str = "") -> str:
    return t(
        "mcp.status.backend_params.warning",
        detail=bp.warning_text(bp.Warning(role, key, code)),
    )


def test_status_with_file():
    _write_doc({"code": {"top_k": 20, "enable_thinking": True, "reasoning_budget_tokens": 512}})
    lines = _status_lines()
    header = t("mcp.status.backend_params.line", path=bp.path())
    # Right under the roles: the line after the `vision` one.
    vision = next(i for i, line in enumerate(lines) if line.startswith("  vision: "))
    assert lines[vision + 1] == header
    assert lines[vision + 2] == _role_line(
        "code",
        _param("top_k", "20"),
        _param("enable_thinking", "on"),
        _param("reasoning_budget_tokens", "512"),
    )
    # Only roles with parameters get a line.
    assert not any(line.startswith("  mechanical: top_k") for line in lines)


def test_status_with_env_shows_source(monkeypatch):
    _write_doc({"mechanical": {"top_k": 20}})
    monkeypatch.setenv(VARIABLE, "mechanical.min_p=0.1")
    bp._forget()
    lines = _status_lines()
    expected = _role_line("mechanical", _param("top_k", "20"), _param("min_p", "0.1", "env"))
    assert expected in lines


def test_status_without_params_unchanged(monkeypatch):
    """Without a file, with empty roles or an empty role: the report of before, line by line."""
    real = server._describe_backend_params
    for document in (None, {"version": 1, "roles": {}}, {"version": 1, "roles": {"code": {}}}):
        if document is not None:
            bp.path().write_text(json.dumps(document), encoding="utf-8")
        bp._forget()
        with monkeypatch.context() as mp:
            mp.setattr(server, "_describe_backend_params", list)
            before = server.local_status()
        assert real() == []
        assert server.local_status() == before, document
    # Control: the same comparison does see a role with parameters.
    _write_doc({"code": {"top_k": 20}})
    bp._forget()
    with monkeypatch.context() as mp:
        mp.setattr(server, "_describe_backend_params", list)
        before = server.local_status()
    assert server.local_status() != before


def test_status_context_estimated(monkeypatch):
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (8192, True))
    _write_doc({"code": {"enable_thinking": True, "reasoning_budget_tokens": 8000}})
    lines = _status_lines()
    assert _warning_line("code", "context_estimated") in lines
    assert _warning_line("code", "context_overflow") in lines
    # The warnings follow their role line.
    role = lines.index(
        _role_line(
            "code", _param("enable_thinking", "on"), _param("reasoning_budget_tokens", "8000")
        )
    )
    assert set(lines[role + 1 : role + 3]) == {
        _warning_line("code", "context_estimated"),
        _warning_line("code", "context_overflow"),
    }


@pytest.mark.parametrize("where", ["file", "env"])
def test_status_hides_sentinels(where, monkeypatch):
    if where == "file":
        _write_doc({"code": {"top_k": SENTINELS[1], "foo": SENTINELS[0], "min_p": 0.1}})
    else:
        monkeypatch.setenv(
            VARIABLE, f"code.foo={SENTINELS[0]};code.top_k={SENTINELS[1]};code.min_p=0.1"
        )
    bp._forget()
    text = server.local_status()
    # Guard: the dropped entries did reach `local_status` as warnings, and the valid key as a
    # value, so the absence of the sentinels means something.
    assert _warning_line("code", "unknown_key", "foo") in text.splitlines()
    assert _param("min_p", "0.1", "file" if where == "file" else "env") in text
    for sentinel in SENTINELS:
        assert sentinel not in text, sentinel
