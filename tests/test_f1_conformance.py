"""Tarea 31: los tres huecos de F1 que encontro la revision de conformidad.

- REQ-F1-9: las lecturas por tools de OTROS MCP se cuentan siempre, y nunca se bloquean.
- REQ-F1-10: con el modelo que haria el resumen en enfriamiento, el bloqueo se cae.
- REQ-F1-11: el bloqueo se apaga en caliente desde un fichero, no desde el entorno, y cada evento
  dice en que estado estaba.

Cada caso lleva su control positivo: el mismo escenario con la condicion quitada tiene que
bloquear, o el test pasaria con la guarda rota.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from local_delegate import config
from local_delegate import install as inst

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"
sys.path.insert(0, str(HOOKS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = _load("hook_common")
read_hook = _load("suggest_delegate_read")
shell_hook = _load("suggest_delegate_shell")


@pytest.fixture
def hook_env(tmp_path, monkeypatch):
    """Telemetria, interruptor y LOG_DIR en tmp; bloqueo encendido y backend vivo por defecto."""
    log = tmp_path / "telemetria.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    monkeypatch.setenv("LD_HOOK_READ_SWITCH_FILE", str(tmp_path / "bloqueo-apagado"))
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "logs"))
    for variable in ("LOCAL_DELEGATE_MODEL_LONG", "LOCAL_DELEGATE_MODEL_MECHANICAL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("LOCAL_DELEGATE_LONG_INPUT_CHARS", raising=False)
    monkeypatch.setattr(read_hook, "backend_available", lambda **k: True)
    monkeypatch.setattr(shell_hook, "backend_available", lambda **k: True)
    return tmp_path


def _events(tmp_path: Path) -> list[dict]:
    log = tmp_path / "telemetria.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _run(hook, monkeypatch, capsys, payload: dict) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    hook.main()
    return capsys.readouterr().out


def _prose(tmp_path: Path, kb: int = 40) -> Path:
    dest = tmp_path / "informe.md"
    dest.write_text("x" * kb * 1024, encoding="utf-8")
    return dest


def _cool_down(tmp_path: Path, model: str, remaining_s: float) -> None:
    directory = tmp_path / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "enfriamiento.json").write_text(
        json.dumps(
            {
                model: {
                    "fallos": 0,
                    "espera_s": 120.0,
                    "hasta": time.time() + remaining_s,
                    "reentradas": 1,
                }
            }
        ),
        encoding="utf-8",
    )


# --- REQ-F1-9: lecturas por otros MCP ------------------------------------------------------------


def test_a_read_through_another_mcp_is_counted_and_not_blocked(hook_env, monkeypatch, capsys):
    """Prosa grande, bloqueo encendido y backend vivo: por `Read` se bloquearia. Por un MCP ajeno
    solo se mide (P-6)."""
    dest = _prose(hook_env)
    output = _run(
        read_hook,
        monkeypatch,
        capsys,
        {"tool_name": "mcp__filesystem__read_text_file", "tool_input": {"path": str(dest)}},
    )
    assert output == "", "ni bloqueo ni sugerencia"
    (event,) = _events(hook_env)
    assert event["route"] == "mcp"
    assert event["category"] == "read", "tiene que entrar en el denominador de medir_adopcion"
    assert event["reason"] == "foreign_mcp"
    assert event["path_sha"] == common.path_digest(str(dest))
    assert str(dest) not in json.dumps(event), "la telemetria nunca guarda rutas"


def test_the_same_read_through_read_is_blocked(hook_env, monkeypatch, capsys):
    """Control positivo del anterior: lo que lo deja pasar es el camino, no el escenario."""
    dest = _prose(hook_env)
    output = _run(
        read_hook,
        monkeypatch,
        capsys,
        {"tool_name": "Read", "tool_input": {"file_path": str(dest)}},
    )
    assert json.loads(output)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_multiple_read_through_another_mcp_is_also_counted(hook_env, monkeypatch, capsys):
    dest = _prose(hook_env)
    output = _run(
        read_hook,
        monkeypatch,
        capsys,
        {
            "tool_name": "mcp__filesystem__read_multiple_files",
            "tool_input": {"paths": [str(dest), str(dest)]},
        },
    )
    assert output == ""
    (event,) = _events(hook_env)
    assert event["route"] == "mcp"


def test_the_installer_registers_the_hook_for_reads_from_other_mcps():
    pattern = inst._MCP_READ_HOOK[2]
    assert inst._MCP_READ_HOOK[0] == inst._READ_HOOK[0], "el mismo script decide los dos caminos"
    for read in (
        "mcp__filesystem__read_text_file",
        "mcp__filesystem__read_file",
        "mcp__filesystem__read_multiple_files",
        "mcp__github__get_file_contents",
        "mcp__obsidian__read_note",
    ):
        assert re.fullmatch(pattern, read), read
    for other in (
        "mcp__filesystem__write_file",
        "mcp__local-delegate__local_summarize",
        "mcp__filesystem__list_directory",
        "Read",
    ):
        assert not re.fullmatch(pattern, other), other


# --- REQ-F1-10: el modelo del resumen en enfriamiento ----------------------------------------------


def test_with_the_long_model_cooling_down_prose_is_not_blocked(hook_env, monkeypatch, capsys):
    dest = _prose(hook_env)  # 40 KB > 6000 chars: el resumen iria al modelo largo
    _cool_down(hook_env, "gemma4-26b-a4b", 100)
    output = _run(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(dest)}})
    assert "deny" not in output
    assert any(e.get("reason") == "model_cooled" for e in _events(hook_env))


def test_an_expired_cooldown_does_not_lift_the_block(hook_env, monkeypatch, capsys):
    dest = _prose(hook_env)
    _cool_down(hook_env, "gemma4-26b-a4b", -5)
    output = _run(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(dest)}})
    assert "deny" in output


def test_another_model_cooling_down_does_not_lift_the_block(hook_env, monkeypatch, capsys):
    dest = _prose(hook_env)
    _cool_down(hook_env, "qwen36-35b-a3b", 100)
    output = _run(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(dest)}})
    assert "deny" in output


def test_the_model_is_taken_from_the_variable_if_set(hook_env, monkeypatch, capsys):
    dest = _prose(hook_env)
    monkeypatch.setenv("LOCAL_DELEGATE_MODEL_LONG", "mi-largo")
    _cool_down(hook_env, "mi-largo", 100)
    output = _run(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(dest)}})
    assert "deny" not in output


def test_a_corrupt_cooldown_file_does_not_lift_the_block(hook_env, monkeypatch, capsys):
    dest = _prose(hook_env)
    (hook_env / "logs").mkdir()
    (hook_env / "logs" / "enfriamiento.json").write_text("{roto", encoding="utf-8")
    output = _run(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(dest)}})
    assert "deny" in output


def test_the_shell_dump_also_respects_the_cooldown(hook_env, monkeypatch, capsys):
    dest = _prose(hook_env)
    payload = {"tool_input": {"command": f"cat {dest}"}}
    assert "deny" in _run(shell_hook, monkeypatch, capsys, payload), "control: sin enfriar bloquea"
    _cool_down(hook_env, "gemma4-26b-a4b", 100)
    assert "deny" not in _run(shell_hook, monkeypatch, capsys, payload)
    assert _events(hook_env)[-1]["reason"] == "model_cooled"


def test_the_hook_defaults_are_the_config_ones():
    """El hook es stdlib y no puede importar `config`: lleva su copia, y esto la ata."""
    source = (Path(config.__file__)).read_text(encoding="utf-8")
    for role, variable in (("long", "LONG"), ("mechanical", "MECHANICAL")):
        default = re.search(rf'"LOCAL_DELEGATE_MODEL_{variable}",\s*"([^"]+)"', source)
        assert default, variable
        assert common.DEFAULT_MODELS[role] == default.group(1)
    threshold = re.search(r'"LOCAL_DELEGATE_LONG_INPUT_CHARS",\s*(\d+)', source)
    assert threshold and common.LONG_THRESHOLD_CHARS == int(threshold.group(1))


def test_the_hook_log_directory_is_the_config_one(monkeypatch):
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)
    assert common.log_dir() == config._default_log_dir()


# --- REQ-F1-11: apagado en caliente por fichero, y el estado en cada evento -----------------------


def test_the_switch_file_turns_off_the_block_even_if_the_variable_says_1(
    hook_env, monkeypatch, capsys
):
    dest = _prose(hook_env)
    payload = {"tool_input": {"file_path": str(dest)}}
    assert "deny" in _run(read_hook, monkeypatch, capsys, payload)
    (hook_env / "bloqueo-apagado").write_text("", encoding="utf-8")
    assert "deny" not in _run(read_hook, monkeypatch, capsys, payload)


def test_each_event_records_the_block_state(hook_env, monkeypatch, capsys):
    dest = _prose(hook_env)
    slice = {"tool_input": {"file_path": str(dest), "offset": 1, "limit": 10}}
    _run(read_hook, monkeypatch, capsys, slice)
    (hook_env / "bloqueo-apagado").write_text("", encoding="utf-8")
    _run(read_hook, monkeypatch, capsys, slice)
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "0")
    (hook_env / "bloqueo-apagado").unlink()
    _run(read_hook, monkeypatch, capsys, slice)
    _run(shell_hook, monkeypatch, capsys, {"tool_input": {"command": "git status"}})
    assert [e["block"] for e in _events(hook_env)] == [
        "on",
        "off_file",
        "off_variable",
        "off_variable",
    ]


class _Backend(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args) -> None:
        pass


def test_turning_off_needs_no_relaunch(tmp_path):
    """Dos invocaciones del hook como PROCESOS aparte, con el mismo entorno heredado: entre una y
    otra solo cambia el fichero. Es lo que hace el cliente real, que lanza un proceso por lectura;
    cambiar `os.environ` dentro del mismo proceso no lo demostraba."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        dest = _prose(tmp_path)
        switch = tmp_path / "bloqueo-apagado"
        env = {
            **os.environ,
            "LD_HOOK_READ_BLOCK": "1",
            "LD_HOOK_READ_SWITCH_FILE": str(switch),
            "LD_HOOK_ENABLED": "1",
            "LOCAL_DELEGATE_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1",
            "LOCAL_DELEGATE_LOG_DIR": str(tmp_path / "logs"),
        }
        entry = json.dumps({"tool_input": {"file_path": str(dest)}})

        def invoke() -> str:
            return subprocess.run(
                [sys.executable, str(HOOKS / "suggest_delegate_read.py"), "--enabled"],
                input=entry,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=True,
            ).stdout

        assert "deny" in invoke(), "control: encendido y con backend, bloquea"
        switch.write_text("", encoding="utf-8")
        assert "deny" not in invoke()
        switch.unlink()
        assert "deny" in invoke(), "y quitar el fichero lo vuelve a encender, sin relanzar"
    finally:
        server.shutdown()
