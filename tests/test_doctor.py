"""Tests del subcomando `doctor` (doctor.py): parseo de versiones, detección desde el
config.yaml (sin pyyaml), comparación vs RECOMMENDED_VERSIONS y exit codes."""

from __future__ import annotations

import argparse

from local_delegate import doctor


def test_vnum_extracts_number():
    assert doctor._vnum("v238") == 238
    assert doctor._vnum("b9925") == 9925
    assert doctor._vnum(None) is None
    assert doctor._vnum("sin-numero") is None


def test_llamaserver_exe_from_config_windows_path(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "models:\n"
        "  gemma3-4b:\n"
        "    cmd: 'D:\\Projects\\llms\\llamacpp\\llama-server.exe --port ${PORT} --host 127.0.0.1'\n",
        encoding="utf-8",
    )
    exe = doctor._llamaserver_exe_from_config(cfg)
    assert exe == "D:\\Projects\\llms\\llamacpp\\llama-server.exe"


def test_llamaserver_exe_from_config_posix_path(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "models:\n  m:\n    cmd: '/usr/local/bin/llama-server --port 1'\n", encoding="utf-8"
    )
    assert doctor._llamaserver_exe_from_config(cfg) == "/usr/local/bin/llama-server"


def test_detect_llamaserver_version_parses_build(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("models:\n  m:\n    cmd: '/usr/bin/llama-server --port 1'\n", encoding="utf-8")
    monkeypatch.setattr(
        doctor, "_run_version", lambda exe: "version: 9925 (ed8c26150)\nbuilt with Clang"
    )
    version, reason = doctor.detect_llamaserver_version(cfg)
    assert version == "b9925"
    assert reason is None


def test_detect_llamaserver_version_reports_reason_without_config():
    version, reason = doctor.detect_llamaserver_version(None)
    assert version is None
    assert reason and "config" in reason.lower()


def test_compare_line_warns_when_installed_older():
    line, warn = doctor._compare_line("llama-swap", "v100", online=False)
    assert warn is True
    assert "considera actualizar" in line
    assert "WARN" in line


def test_compare_line_ok_when_equal_to_recommended():
    recommended = doctor.RECOMMENDED_VERSIONS["llama-swap"]
    line, warn = doctor._compare_line("llama-swap", recommended, online=False)
    assert warn is False
    assert "OK" in line


def test_compare_line_not_detected():
    line, warn = doctor._compare_line("llama-server", None, online=False)
    assert warn is False  # 'no detectado' no cuenta como warning de actualización
    assert "no detectado" in line


def test_run_doctor_exit_0_when_up_to_date(monkeypatch):
    monkeypatch.setattr(
        doctor, "detect_llamaswap_version", lambda: doctor.RECOMMENDED_VERSIONS["llama-swap"]
    )
    monkeypatch.setattr(
        doctor,
        "detect_llamaserver_version",
        lambda cfg: (doctor.RECOMMENDED_VERSIONS["llama-server"], None),
    )
    monkeypatch.setattr(doctor, "_backend_up", lambda: True)
    args = argparse.Namespace(config=None, online=False)
    assert doctor.run_doctor(args) == 0


def test_run_doctor_exit_1_when_outdated(monkeypatch):
    monkeypatch.setattr(doctor, "detect_llamaswap_version", lambda: "v100")  # muy vieja
    monkeypatch.setattr(
        doctor,
        "detect_llamaserver_version",
        lambda cfg: (doctor.RECOMMENDED_VERSIONS["llama-server"], None),
    )
    monkeypatch.setattr(doctor, "_backend_up", lambda: False)
    args = argparse.Namespace(config=None, online=False)
    assert doctor.run_doctor(args) == 1
