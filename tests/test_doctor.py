"""Tests del subcomando `doctor` (doctor.py): parseo de versiones, detección desde el
config.yaml (sin pyyaml), comparación vs RECOMMENDED_VERSIONS, salida del registro de
comprobaciones y exit codes."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from conftest import make_home, snapshot

from local_delegate import checks, daemon, doctor


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


def _stub_environment(monkeypatch, *, swap="ok", backend=True, daemon_alive=True):
    """Dobla lo que sale del proceso: versiones, backend y daemon. Nada real se ejecuta."""
    version = doctor.RECOMMENDED_VERSIONS["llama-swap"] if swap == "ok" else swap
    monkeypatch.setattr(doctor, "detect_llamaswap_version", lambda: version)
    monkeypatch.setattr(
        doctor,
        "detect_llamaserver_version",
        lambda cfg: (doctor.RECOMMENDED_VERSIONS["llama-server"], None),
    )
    monkeypatch.setattr(doctor, "_backend_up", lambda: backend)
    monkeypatch.setattr(
        daemon,
        "query_daemon",
        lambda host, port, timeout=1.0: (
            {"version": "0.13.1", "pid": 42, "mcp_url": f"http://{host}:{port}/mcp"}
            if daemon_alive
            else None
        ),
    )
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: False)


def test_run_doctor_exit_0_when_everything_is_in_place(tmp_path, monkeypatch, capsys):
    _stub_environment(monkeypatch)
    home = make_home(tmp_path)
    args = argparse.Namespace(config=None, online=False, home=str(home))
    assert doctor.run_doctor(args) == 0
    # Solo las líneas de los checks: la leyenda de la cabecera nombra todos los estados.
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  [")]
    assert lines and all(line.startswith("  [ OK ]") for line in lines)


def test_run_doctor_exit_1_when_outdated(tmp_path, monkeypatch):
    _stub_environment(monkeypatch, swap="v100", backend=False)  # versión muy vieja
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    assert doctor.run_doctor(args) == 1


def test_run_doctor_on_empty_home_reports_missing_and_exits_1(tmp_path, monkeypatch, capsys):
    _stub_environment(monkeypatch)
    home = make_home(tmp_path, complete=False)
    args = argparse.Namespace(config=None, online=False, home=str(home))
    assert doctor.run_doctor(args) == 1
    out = capsys.readouterr().out
    assert "[FALT]" in out
    assert "arréglalo con: local-delegate install" in out


def test_run_doctor_reports_the_dead_daemon(tmp_path, monkeypatch, capsys):
    _stub_environment(monkeypatch, daemon_alive=False)
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    assert doctor.run_doctor(args) == 1
    out = capsys.readouterr().out
    assert "nadie escucha" in out
    assert "local-delegate serve" in out


def test_run_doctor_keeps_the_previous_output(tmp_path, monkeypatch, capsys):
    """REQ-010: lo que el doctor ya imprimía sigue estando, con el mismo texto."""
    _stub_environment(monkeypatch, backend=False)
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    doctor.run_doctor(args)
    out = capsys.readouterr().out
    assert "LLAMASWAP_EXE:" in out
    assert "LLAMASWAP_CONFIG:" in out
    assert "CAÍDO" in out
    assert "Versiones (instalada vs probada; usa --online para comparar con GitHub):" in out
    assert f"llama-swap: {doctor.RECOMMENDED_VERSIONS['llama-swap']} (= probada)" in out
    assert f"llama-server: {doctor.RECOMMENDED_VERSIONS['llama-server']} (= probada)" in out


def test_run_doctor_without_network_does_not_fail(tmp_path, monkeypatch, capsys):
    """Sin GitHub ni backend ni daemon, el diagnóstico se completa y no lanza."""
    _stub_environment(monkeypatch, backend=False, daemon_alive=False)
    monkeypatch.setattr(doctor, "latest_github_info", lambda component: None)
    monkeypatch.setattr(doctor, "recent_relevant_issues", lambda component: [])
    args = argparse.Namespace(config=None, online=True, home=str(make_home(tmp_path)))
    assert doctor.run_doctor(args) == 1
    out = capsys.readouterr().out
    assert "Issues abiertos con señales de riesgo" in out
    assert "ninguno detectado" in out


def test_run_doctor_writes_nothing_in_the_simulated_home(tmp_path, monkeypatch):
    """REQ-013: el árbol del HOME simulado queda idéntico, byte a byte."""
    _stub_environment(monkeypatch, daemon_alive=False)
    home = make_home(tmp_path)
    before = snapshot(home)
    doctor.run_doctor(argparse.Namespace(config=None, online=False, home=str(home)))
    assert snapshot(home) == before


def test_run_doctor_writes_nothing_in_an_empty_home(tmp_path, monkeypatch):
    """El caso peligroso: con todo por instalar, el doctor sigue sin escribir."""
    _stub_environment(monkeypatch, daemon_alive=False)
    home = make_home(tmp_path, complete=False)
    before = snapshot(home)
    doctor.run_doctor(argparse.Namespace(config=None, online=False, home=str(home)))
    assert snapshot(home) == before
