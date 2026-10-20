"""Reader of `LOCAL_DELEGATE_BACKEND_PARAMS` in `config` (SDD `backend-extra-params`, T4, REQ-008)."""

from __future__ import annotations

from local_delegate import backend_params, config

VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"


def test_variable_is_registered():
    assert VARIABLE in config.ENVIRONMENT_VARIABLES


def test_read_at_call_time(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    assert config.backend_params_override() == (None, None, None)

    # No reload: the reader looks at the environment when it is called.
    monkeypatch.setenv(VARIABLE, "code.top_k=20")
    assert config.backend_params_override() == ("code.top_k=20", None, "code.top_k=20")

    monkeypatch.setenv(VARIABLE, "code.top_k=30")
    assert config.backend_params_override().value == "code.top_k=30"

    monkeypatch.setenv(VARIABLE, "   ")
    assert config.backend_params_override().value is None
    assert config.backend_params_override().problem is None


def test_too_long_is_ignored_whole(monkeypatch):
    limit = config.BACKEND_PARAMS_OVERRIDE_MAX_CHARS
    assert limit == 2048 == backend_params.MAX_OVERRIDE_CHARS

    exact = "code.top_k=20;".ljust(limit, ";")
    monkeypatch.setenv(VARIABLE, exact)
    assert config.backend_params_override() == (exact, None, exact)

    too_long = exact + ";"
    monkeypatch.setenv(VARIABLE, too_long)
    value, problem, raw = config.backend_params_override()
    assert value is None
    assert problem == "override_too_long"
    assert raw == too_long
