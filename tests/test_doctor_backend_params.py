"""Lines of the per-role backend parameters in `doctor` (SDD backend-extra-params, T9).

REQ-016 (`doctor`), REQ-023 (context warnings) and REQ-017 (no value of a dropped entry). They are
header lines, not a check: the 26 checks and the exit code do not change.
"""

from __future__ import annotations

import argparse
import json

import pytest
from conftest import make_home
from test_doctor import _stub_environment

from local_delegate import backend_params as bp
from local_delegate import doctor, llamaswap_config
from local_delegate.i18n import t

VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"
SENTINELS = ("SENTINEL-7Q", "SENTINEL-8R")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (32768, False))
    bp._forget()
    yield
    bp._forget()


def _write_doc(roles: dict) -> None:
    bp.path().write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")


def _warning_line(role: str, code: str, key: str = "") -> str:
    return t("doctor.backend_params.warning", detail=bp.warning_text(bp.Warning(role, key, code)))


def test_doctor_lines_from_file():
    _write_doc({"code": {"top_k": 20, "enable_thinking": True, "reasoning_budget_tokens": 512}})
    lines = doctor.backend_params_lines()
    params = ", ".join(
        f"{key}={value}"
        for key, value in (
            ("top_k", "20"),
            ("enable_thinking", "on"),
            ("reasoning_budget_tokens", "512"),
        )
    )
    assert lines == [
        t("doctor.backend_params.line", path=bp.path()),
        t("doctor.backend_params.role", role="code", params=params),
    ]


def test_doctor_lines_with_env_warns_about_daemon(monkeypatch):
    _write_doc({"code": {"top_k": 20}})
    monkeypatch.setenv(VARIABLE, "code.min_p=0.1")
    from_env = t("doctor.backend_params.from_env")
    assert doctor.backend_params_lines() == [
        t("doctor.backend_params.line", path=bp.path()),
        t("doctor.backend_params.env_in_shell"),
        t("doctor.backend_params.role", role="code", params=f"top_k=20, min_p=0.1 {from_env}"),
    ]


def test_doctor_lines_with_only_the_variable_and_nothing_valid(monkeypatch):
    # A variable whose only entry is dropped: the line about this shell and the warning, no values.
    monkeypatch.setenv(VARIABLE, "code.foo=1")
    assert doctor.backend_params_lines() == [
        t("doctor.backend_params.line", path=bp.path()),
        t("doctor.backend_params.env_in_shell"),
        _warning_line("code", "unknown_key", "foo"),
    ]


def test_doctor_no_lines_without_params(tmp_path, monkeypatch, capsys):
    assert doctor.backend_params_lines() == []
    monkeypatch.setenv(VARIABLE, "")  # set but empty is the same as unset
    assert doctor.backend_params_lines() == []
    monkeypatch.delenv(VARIABLE)
    _write_doc({})  # a file without roles is no parameters either
    assert doctor.backend_params_lines() == []

    # The whole output is the one of today: the same as with the new lines taken out by hand.
    _stub_environment(monkeypatch, backend=False, log_dir=tmp_path)  # keeps `LOG_DIR`
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    code = doctor.run_doctor(args)
    out = capsys.readouterr().out
    with monkeypatch.context() as patch:
        patch.setattr(doctor, "backend_params_lines", list)
        assert doctor.run_doctor(args) == code
    assert capsys.readouterr().out == out
    # And the seam of today around the call site: the language lines, one blank line, the legend.
    expected = "\n".join(doctor.language_lines()) + "\n\n" + doctor.status_legend() + "\n"
    assert expected in out
    # Control: with a parameter, the same `doctor` does show the header line.
    _write_doc({"code": {"top_k": 20}})
    bp._forget()
    assert doctor.run_doctor(args) == code  # a header line, not a check: same exit code
    assert t("doctor.backend_params.line", path=bp.path()) in capsys.readouterr().out


def test_doctor_context_estimated_warning(monkeypatch):
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (8192, True))
    _write_doc({"code": {"enable_thinking": True, "reasoning_budget_tokens": 512}})
    lines = doctor.backend_params_lines()
    assert _warning_line("code", "context_estimated") in lines
    assert _warning_line("code", "context_overflow") not in lines
    # With a budget that does not fit, the overflow warning too.
    _write_doc({"code": {"enable_thinking": True, "reasoning_budget_tokens": 8000}})
    bp._forget()
    lines = doctor.backend_params_lines()
    assert _warning_line("code", "context_estimated") in lines
    assert _warning_line("code", "context_overflow") in lines


@pytest.mark.parametrize("where", ["file", "env"])
def test_doctor_hides_sentinels(where, monkeypatch):
    if where == "file":
        _write_doc({"code": {"top_k": 20, "foo": "SENTINEL-7Q"}})
    else:
        monkeypatch.setenv(VARIABLE, "code.foo=SENTINEL-7Q;code.top_k=SENTINEL-8R;code.min_p=0.1")
    lines = doctor.backend_params_lines()
    # Guard: the dropped entry did reach `doctor` as a warning, so the check means something.
    assert _warning_line("code", "unknown_key", "foo") in lines
    for line in lines:
        for sentinel in SENTINELS:
            assert sentinel not in line
