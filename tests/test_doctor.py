"""Tests del subcomando `doctor` (doctor.py): parseo de versiones, detección desde el
config.yaml (sin pyyaml), comparación vs RECOMMENDED_VERSIONS, salida del registro de
comprobaciones y exit codes."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from conftest import desktop_mcp_remote_entry, make_home, snapshot, write_claude_desktop

from local_delegate import checks, daemon, doctor, install, probes, recompute, update
from local_delegate.failures import BackendView


def test_vnum_extracts_number():
    assert probes._vnum("v238") == 238
    assert probes._vnum("b9925") == 9925
    assert probes._vnum(None) is None
    assert probes._vnum("no-number") is None


def test_llamaserver_exe_from_config_windows_path(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "models:\n"
        "  gemma3-4b:\n"
        "    cmd: 'D:\\Projects\\llms\\llamacpp\\llama-server.exe --port ${PORT} --host 127.0.0.1'\n",
        encoding="utf-8",
    )
    exe = probes._llamaserver_exe_from_config(cfg)
    assert exe == "D:\\Projects\\llms\\llamacpp\\llama-server.exe"


def test_llamaserver_exe_from_config_posix_path(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "models:\n  m:\n    cmd: '/usr/local/bin/llama-server --port 1'\n", encoding="utf-8"
    )
    assert probes._llamaserver_exe_from_config(cfg) == "/usr/local/bin/llama-server"


def test_detect_llamaserver_version_parses_build(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("models:\n  m:\n    cmd: '/usr/bin/llama-server --port 1'\n", encoding="utf-8")
    monkeypatch.setattr(
        probes, "_run_version", lambda exe: "version: 9925 (ed8c26150)\nbuilt with Clang"
    )
    version, reason = probes.detect_llamaserver_version(cfg)
    assert version == "b9925"
    assert reason is None


def test_detect_llamaserver_version_parses_semver_build(tmp_path, monkeypatch):
    # Formato de b10909: la version es semver y el numero de build va entre parentesis. Leido con la
    # regex vieja daba "b0" sin avisar, y el doctor lo marcaba como desactualizado frente a b9925.
    cfg = tmp_path / "config.yaml"
    cfg.write_text("models:\n  m:\n    cmd: '/usr/bin/llama-server --port 1'\n", encoding="utf-8")
    monkeypatch.setattr(
        probes,
        "_run_version",
        lambda exe: "version: 0.4.0-dev (build 10909, commit a2878d30d)\nbuilt with Clang 20.1.8",
    )
    version, reason = probes.detect_llamaserver_version(cfg)
    assert version == "b10909"
    assert reason is None


def test_detect_llamaserver_version_semver_without_build_is_not_b0(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("models:\n  m:\n    cmd: '/usr/bin/llama-server --port 1'\n", encoding="utf-8")
    monkeypatch.setattr(probes, "_run_version", lambda exe: "version: 0.4.0-dev\nbuilt with Clang")
    version, reason = probes.detect_llamaserver_version(cfg)
    assert version is None
    assert reason and "inesperada" in reason


def test_detect_llamaserver_version_reports_reason_without_config():
    version, reason = probes.detect_llamaserver_version(None)
    assert version is None
    assert reason and "config" in reason.lower()


def test_compare_line_warns_when_installed_older():
    line, warn = probes._compare_line("llama-swap", "v100", online=False)
    assert warn is True
    assert "considera actualizar" in line
    assert "WARN" in line


def test_compare_line_ok_when_equal_to_recommended():
    recommended = probes.RECOMMENDED_VERSIONS["llama-swap"]
    line, warn = probes._compare_line("llama-swap", recommended, online=False)
    assert warn is False
    assert "OK" in line


def test_compare_line_not_detected():
    line, warn = probes._compare_line("llama-server", None, online=False)
    assert warn is False  # 'no detectado' no cuenta como warning de actualización
    assert "no detectado" in line


def test_release_age_days():
    now = datetime(2026, 7, 23, 12, tzinfo=UTC)
    assert probes._release_age_days("2026-07-20T10:00:00Z", now) == 3
    assert probes._release_age_days("", now) is None
    assert probes._release_age_days("not-a-date", now) is None


def test_online_new_release_is_held_before_soak(monkeypatch):
    monkeypatch.setattr(
        probes,
        "latest_github_info",
        lambda component: {
            "tag": "v999",
            "published_at": datetime.now(UTC).isoformat(),
            "url": "https://example.invalid/release",
        },
    )
    line, warn = probes._compare_line("llama-swap", probes.RECOMMENDED_VERSIONS["llama-swap"], True)
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
    assert probes._select_relevant_issues(items) == [
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
    daemon_needs_token=False,
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
    version = probes.RECOMMENDED_VERSIONS["llama-swap"] if swap == "ok" else swap
    monkeypatch.setattr(probes, "detect_llamaswap_version", lambda: version)
    monkeypatch.setattr(
        probes,
        "detect_llamaserver_version",
        lambda cfg: (probes.RECOMMENDED_VERSIONS["llama-server"], None),
    )
    monkeypatch.setattr(
        probes,
        "backend_probe",
        lambda: (
            BackendView(True, "", None, "direct")
            if backend
            else BackendView(False, "no responde (ConnectError)", None, "direct")
        ),
    )
    # Mismo caso que `query_backend`: sin doblarlo, `service.credential` pediría `/models` al
    # backend REAL de la máquina, verde en CI y otra cosa aquí. Por defecto «no exige credencial»,
    # que es el escenario donde el modo de la entrada MCP no cambia nada.
    monkeypatch.setattr(probes, "backend_requires_key", lambda: (needs_key, ""))
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
    # Tercer colaborador de red del check del daemon, y va aquí por el mismo motivo que los dos de
    # arriba: sin doblarlo, cualquier test que ponga `_port_taken` en True le preguntaría al puerto
    # REAL de la máquina si exige token.
    monkeypatch.setattr(
        daemon, "daemon_requires_token", lambda host, port, timeout=1.0: daemon_needs_token
    )
    # Y el que prueba el token de Claude Desktop: solo se llama si hay fichero de ese cliente en
    # el HOME, pero un colaborador de red sin doblar es cómo la suite acaba saliendo a la red.
    monkeypatch.setattr(daemon, "daemon_accepts_token", lambda host, port, token, timeout=1.0: True)
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
    # Igual con el cotejo de `config.cost`: vive en `LOG_DIR`, y sin él el check es `unknown`.
    recompute.write_aggregates(logs, {"version": 1, "check": {"verdict": "pass"}})
    _stub_environment(monkeypatch, log_dir=logs)
    home = make_home(tmp_path)
    # Claude Desktop no lo escribe `install`, así que el HOME completo no lo trae: se le pone aquí.
    write_claude_desktop(home, {install.SERVER_NAME: desktop_mcp_remote_entry()})
    # `backend.residency` y `backend.topology` (T13) leen la config de llama-swap de `--config`: la
    # de hoy (copia con claves falsas), sin residente y con turno. Sin ella serían `unknown`.
    today = Path(__file__).parent / "fixtures" / "residency" / "today.yaml"
    args = argparse.Namespace(config=str(today), online=False, home=str(home))
    assert doctor.run_doctor(args) == 0
    # Solo las líneas de los checks: la leyenda de la cabecera nombra todos los estados.
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith("  [")]
    assert lines and all(line.startswith("  [ OK ]") for line in lines)
    # A6 (REQ-011): no hay `doctor --json`, así que el contrato de los ids y grupos nuevos se mira
    # en la salida de texto: los 27 checks, una línea cada uno, bajo el encabezado de su grupo.
    assert len(lines) == len(checks.CHECKS) == 27
    headings = [*map(doctor.group_heading, doctor._GROUP_HEADINGS), doctor._versions_heading(False)]
    assert [h for h in headings if h in out] == headings
    for check in checks.CHECKS:
        if check.group in doctor._GROUP_HEADINGS:
            heading = doctor.group_heading(check.group)
        else:
            heading = doctor._versions_heading(False)
        section = out.split(heading, 1)[1].split("\n\n", 1)[0]
        assert f"] {check.title}:" in section, (check.id, check.group)


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
    assert f"llama-swap: {probes.RECOMMENDED_VERSIONS['llama-swap']} (= probada)" in out
    assert f"llama-server: {probes.RECOMMENDED_VERSIONS['llama-server']} (= probada)" in out


def test_the_daemon_answers_for_the_backend_and_the_401_is_gone(tmp_path, monkeypatch, capsys):
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


def test_if_the_daemon_says_the_backend_is_down_that_is_not_a_doubt(tmp_path, monkeypatch):
    """El daemon SÍ tiene credencial, así que su «no disponible» es diagnóstico, no incertidumbre."""
    _stub_environment(monkeypatch, backend=True, backend_via_daemon={"available": False})
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    assert doctor.run_doctor(args) == 1  # cuenta como aviso, no como `[ -- ]`


def test_without_daemon_the_backend_is_tested_directly_as_always(tmp_path, monkeypatch, capsys):
    """Cuando nadie puede mirar por nosotros, el camino viejo sigue siendo el correcto."""
    _stub_environment(monkeypatch, backend=False, daemon_alive=False, backend_via_daemon=None)
    args = argparse.Namespace(config=None, online=False, home=str(make_home(tmp_path)))
    doctor.run_doctor(args)
    assert "CAÍDO" in capsys.readouterr().out


def test_run_doctor_without_network_does_not_fail(tmp_path, monkeypatch, capsys):
    """Sin GitHub ni backend ni daemon, el diagnóstico se completa y no lanza."""
    _stub_environment(monkeypatch, backend=False, daemon_alive=False)
    monkeypatch.setattr(probes, "latest_github_info", lambda component: None)
    monkeypatch.setattr(probes, "recent_relevant_issues", lambda component: [])
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


# --- backend_probe: plazo de sondeo y causa (REQ-013, REQ-016) -----------------------------------


def test_backend_probe_uses_the_probe_timeout(monkeypatch):
    import httpx2

    from local_delegate import config

    timeouts = []

    class _Recorder:
        def __init__(self, *args, timeout=None, **kwargs):
            timeouts.append(timeout)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, **kwargs):
            raise httpx2.ConnectError("x", request=httpx2.Request("GET", url))

    monkeypatch.setattr(httpx2, "Client", _Recorder)

    probes.backend_probe()

    (t,) = timeouts
    connect_timeout = t.connect if isinstance(t, httpx2.Timeout) else t
    read_timeout = t.read if isinstance(t, httpx2.Timeout) else t
    assert connect_timeout == config.PROBE_CONNECT_TIMEOUT
    assert read_timeout == config.PROBE_READ_TIMEOUT


def test_backend_probe_without_daemon_says_dns(monkeypatch):
    """Red real: un nombre `.invalid` no resuelve nunca (RFC 6761)."""
    from local_delegate import config

    monkeypatch.setattr(config, "BASE_URL", "http://no-existe.invalid:9292/v1")

    view = probes.backend_probe()

    assert "no se resuelve" in view[1]
    assert view.cause == "dns"
    assert view.source == "direct"
    assert view.healthy is False
