"""Tests del subcomando `doctor` (doctor.py): parseo de versiones, detección desde el
config.yaml (sin pyyaml), comparación vs RECOMMENDED_VERSIONS y exit codes."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

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


def test_release_age_days():
    now = datetime(2026, 7, 23, 12, tzinfo=UTC)
    assert doctor._release_age_days("2026-07-20T10:00:00Z", now) == 3
    assert doctor._release_age_days("", now) is None
    assert doctor._release_age_days("no-es-fecha", now) is None


def test_online_new_release_is_held_before_soak(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "latest_github_info",
        lambda component: {
            "tag": "v999",
            "published_at": datetime.now(UTC).isoformat(),
            "url": "https://example.invalid/release",
        },
    )
    line, warn = doctor._compare_line("llama-swap", doctor.RECOMMENDED_VERSIONS["llama-swap"], True)
    assert warn is False
    assert "HOLD" in line
    assert "canary" not in line


def test_select_relevant_issues_excludes_prs_and_noise():
    items = [
        {"number": 1, "title": "Docs typo", "body": "small fix", "html_url": "u1"},
        {
            "number": 2,
            "title": "CUDA crash on unload",
            "body": "",
            "html_url": "u2",
        },
        {
            "number": 3,
            "title": "Windows crash",
            "body": "",
            "html_url": "u3",
            "pull_request": {},
        },
    ]
    assert doctor._select_relevant_issues(items) == [
        {"number": 2, "title": "CUDA crash on unload", "url": "u2"}
    ]


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
