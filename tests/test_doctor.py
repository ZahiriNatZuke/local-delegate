"""Tests del subcomando `doctor` (doctor.py): parseo de versiones, detección desde el
config.yaml (sin pyyaml), comparación vs RECOMMENDED_VERSIONS, salida del registro de
comprobaciones y exit codes."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from conftest import make_home, snapshot

from local_delegate import checks, daemon, doctor, update


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


def _stub_environment(
    monkeypatch,
    *,
    swap="ok",
    backend=True,
    daemon_alive=True,
    log_dir=None,
    backend_via_daemon=None,
    needs_key=False,
):
    """Dobla lo que sale del proceso: versiones, backend y daemon. Nada real se ejecuta.

    ``log_dir`` importa aunque casi ningún test lo pase: sin doblarlo, el check de clientes
    observados leería el ``clients.jsonl`` REAL de la máquina donde corra la suite —verde en CI,
    donde no existe, y otra cosa en la máquina de quien desarrolla—. Por defecto apunta a una ruta
    inexistente, que es el caso «todavía no ha hablado nadie».

    Se dobla ``config.LOG_DIR`` y **no** ``checks._default_clients_seen``: el dataclass capturó la
    referencia a esa función al definirse, así que monkeypatchearla no cambiaría el default del
    ``Context``. Mismo motivo que se explica más abajo para ``latest_version``.
    """
    monkeypatch.setattr(
        checks.config, "LOG_DIR", Path(log_dir) if log_dir else Path(__file__).parent / "_sin_logs"
    )
    # Por defecto, «no hay daemon a quien preguntar por el backend», que es lo que deja mandar al
    # `backend_probe` doblado justo debajo. Sin esto la suite **sale a la red de verdad**: verde en
    # CI, donde no hay daemon, y otra cosa en la máquina de quien desarrolla, donde sí lo hay.
    monkeypatch.setattr(daemon, "query_backend", lambda host, port, timeout=1.0: backend_via_daemon)
    version = doctor.RECOMMENDED_VERSIONS["llama-swap"] if swap == "ok" else swap
    monkeypatch.setattr(doctor, "detect_llamaswap_version", lambda: version)
    monkeypatch.setattr(
        doctor,
        "detect_llamaserver_version",
        lambda cfg: (doctor.RECOMMENDED_VERSIONS["llama-server"], None),
    )
    monkeypatch.setattr(
        doctor,
        "backend_probe",
        lambda: (True, "") if backend else (False, "no responde (ConnectError)"),
    )
    # Mismo caso que `query_backend`: sin doblarlo, `service.credential` pediría `/models` al
    # backend REAL de la máquina, verde en CI y otra cosa aquí. Por defecto «no exige credencial»,
    # que es el escenario donde el modo de la entrada MCP no cambia nada.
    monkeypatch.setattr(doctor, "backend_requires_key", lambda: (needs_key, ""))
    monkeypatch.setattr(
        daemon,
        "query_daemon",
        lambda host, port, timeout=1.0: (
            {
                # La instalada, no una fija: si no, el check de daemon desincronizado la marcaría
                # `warn` y estos tests dependerían de la versión que lleve el repo ese día.
                "version": checks._installed_version(),
                "pid": 42,
                "mcp_url": f"http://{host}:{port}/mcp",
            }
            if daemon_alive
            else None
        ),
    )
    monkeypatch.setattr(checks, "_port_taken", lambda host, port: False)
    monkeypatch.setattr(checks.shutil, "which", lambda name: "/usr/local/bin/local-delegate")
    # `run_doctor` arma el `Context` por dentro, así que aquí no hay kwarg que doblar. Y doblar
    # `checks._default_latest_release` tampoco serviría: el dataclass capturó la referencia a esa
    # función al definirse, igual que con `_default_daemon_status`. Lo que se dobla es el módulo
    # al que llama por dentro, que es lo mismo que hacen las tres líneas de arriba.
    #
    # No es cosmético: sin esto la suite consultaría PyPI de verdad y
    # `test_run_doctor_exit_0_when_everything_is_in_place` pasaría a depender de él — publicar
    # una versión rompería el CI sin que nadie tocara el código. Se devuelve **la instalada** por
    # el mismo motivo que el daemon: si no, el resultado dependería de la versión del repo.
    monkeypatch.setattr(
        update, "latest_version", lambda timeout=0: (checks._installed_version(), None)
    )


def test_run_doctor_exit_0_when_everything_is_in_place(tmp_path, monkeypatch, capsys):
    # El registro de clientes se siembra porque **no vive en el HOME**: está en `LOG_DIR`, así que
    # un HOME completo no basta para que ese check salga `[ OK ]`. Se le da un cliente real en vez
    # de excluirlo, para que este test también le exija estar bien.
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "clients.jsonl").write_text(
        '{"ts": "2026-07-31T17:15:52+00:00", "client": "claude-code", "version": "2.1.220",'
        ' "protocol": "2025-11-25", "caps": ["elicitation", "roots"]}\n',
        encoding="utf-8",
    )
    _stub_environment(monkeypatch, log_dir=logs)
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


def test_el_daemon_responde_por_el_backend_y_se_acabo_el_401(tmp_path, monkeypatch, capsys):
    """El caso que motivó el cambio, encontrado en uso real.

    La clave del backend se lee del entorno del proceso: el daemon la recibe de su lanzador, pero
    un `doctor` escrito en una consola cualquiera no la tiene. Antes se llevaba un 401 y se
    quedaba en `[ -- ]` sobre una máquina donde el daemon veía el backend sin problema.
    """
    _stub_environment(monkeypatch, backend=False, backend_via_daemon={"available": True})
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    doctor.run_doctor(args)
    out = capsys.readouterr().out
    assert "arriba" in out
    assert "rechaza la credencial" not in out
    assert "CAÍDO" not in out


def test_si_el_daemon_dice_que_el_backend_esta_caido_eso_no_es_una_duda(tmp_path, monkeypatch):
    """El daemon SÍ tiene credencial, así que su «no disponible» es diagnóstico, no incertidumbre."""
    _stub_environment(monkeypatch, backend=True, backend_via_daemon={"available": False})
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    assert doctor.run_doctor(args) == 1  # cuenta como aviso, no como `[ -- ]`


def test_sin_daemon_el_backend_se_prueba_directo_como_siempre(tmp_path, monkeypatch, capsys):
    """Cuando nadie puede mirar por nosotros, el camino viejo sigue siendo el correcto."""
    _stub_environment(monkeypatch, backend=False, daemon_alive=False, backend_via_daemon=None)
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    doctor.run_doctor(args)
    assert "CAÍDO" in capsys.readouterr().out


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
