"""El hook de lectura se aparta cuando el mod de lectura hace su trabajo (REQ-023, decisión 10).

SDD claude-plugin-and-mods, lote F4-hooks-swap. Con el mod encendido actuaban los dos: el mod
resumía y el hook registraba (o bloqueaba) la misma lectura. El hook se aparta **solo** con las
cuatro condiciones a la vez, las mismas con las que actúa el mod:

- la opción `read_mod_enabled` del plugin (`CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED`) es verdadera;
- el latido de **su misma sesión** dice `read_mod_active` y `process_run`, con menos de 24 h;
- la capa *bloquea* está en `on`;
- la vía es clasificable (una lectura con fichero y alcance que el mod sabe tratar).

Si falta cualquiera, el hook actúa como en la 0.40. Cada test tiene su control: el mismo montaje
con la condición cumplida se aparta, así que el «actúa» viene de la condición y no del montaje.

Los hooks corren como los lanza el plugin (`python -I -m local_delegate.hook <nombre>`), con un
entorno propio: temporal, telemetría, `CLAUDE_PLUGIN_DATA` y fichero del bloqueo en `tmp_path`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from local_delegate import config

ROOT = Path(__file__).parents[1]
HOOKS = ROOT / "src" / "local_delegate" / "resources" / "hooks"
PLUGIN_DIR = ROOT / "src" / "local_delegate" / "resources" / "claude-plugin" / "local-delegate"
TIMEOUT_S = 60
SESSION = "sess-main"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = _load("_sa_hook_common", HOOKS / "hook_common.py")


# --- Montaje ---------------------------------------------------------------------------------------


def _env(base: Path, *, option: str | None = "true", block: str = "1") -> dict[str, str]:
    """El entorno de un hook del plugin con el mod de lectura encendido y la capa bloquea en `on`."""
    tmp = base / "tmp"
    data = base / "data"
    plugin_data = base / "plugin-data"
    for folder in (tmp, data, plugin_data):
        folder.mkdir(parents=True, exist_ok=True)
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in config.ENVIRONMENT_VARIABLES
        and name not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH"}
    }
    env.update(
        {
            "TMP": str(tmp),
            "TEMP": str(tmp),
            "TMPDIR": str(tmp),
            "LOCAL_DELEGATE_LOG_DIR": str(data),
            "LOCAL_DELEGATE_LANG": "es",
            "LD_HOOK_TELEMETRY_LOG": str(base / "blocks.jsonl"),
            "LD_HOOK_READ_SWITCH_FILE": str(base / "block-off"),
            "LD_HOOK_READ_ENABLED": "1",
            "LD_HOOK_READ_BLOCK": block,
            "CLAUDE_PLUGIN_DATA": str(plugin_data),
        }
    )
    if option is not None:
        env["CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED"] = option
    # La marca de salud fresca: el hook bloquearía sin sondear la red.
    marker = tmp / common._health_path().name
    marker.write_text(json.dumps({"ts": time.time(), "ok": True}), encoding="utf-8")
    return env


def _heartbeat(base: Path, session: str = SESSION, *, age: timedelta = timedelta(0), **fields):
    """El latido que escribe el mod al iniciar la sesión (`mod/common.js`, `heartbeat`)."""
    folder = base / "plugin-data" / "heartbeats"
    folder.mkdir(parents=True, exist_ok=True)
    beat = {
        "session_id": session,
        "version": "0.41.0",
        "entrypoint": "cli",
        "process_run": True,
        "dialog": False,
        "read_mod_enabled": True,
        "pieces": {"read": "on"},
        "read_mod_active": True,
        "at": (datetime.now(UTC) - age).isoformat().replace("+00:00", "Z"),
    }
    beat.update(fields)
    path = folder / f"{session}.json"
    path.write_text(json.dumps(beat), encoding="utf-8")
    return path


def _prose(base: Path, kb: int = 20) -> Path:
    target = base / "docs" / "report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Texto de prosa para resumir.\n" * (kb * 1024 // 29 + 1), encoding="utf-8")
    return target


def _hook(name: str, payload: dict, env: dict[str, str]) -> subprocess.CompletedProcess:
    stdin = json.dumps({"session_id": SESSION, **payload}).encode("utf-8")
    return subprocess.run(
        [sys.executable, "-I", "-m", "local_delegate.hook", name],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
        cwd=env["TMP"],
    )


def _read(base: Path, env: dict[str, str], **extra) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(_prose(base))}, **extra}
    return _hook("read", payload, env)


def _events(base: Path) -> list[dict]:
    path = base / "blocks.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _denied(done: subprocess.CompletedProcess) -> bool:
    # Only the hook's own output reaches an assertion message: the environment (`_env`) is the
    # caller's whole environment and must never be printed.
    assert done.returncode == 0, done.stderr
    out = done.stdout.decode("utf-8").strip()
    if not out:
        return False
    decision = json.loads(out)["hookSpecificOutput"].get("permissionDecision")
    return decision == "deny"


def _stepped_aside(base: Path) -> list[dict]:
    return [e for e in _events(base) if e.get("step_aside")]


# --- Las cuatro condiciones ------------------------------------------------------------------------


def test_read_hook_steps_aside_when_mod_active(tmp_path):
    env = _env(tmp_path)
    _heartbeat(tmp_path)
    done = _read(tmp_path, env)
    # Ni bloquea ni avisa: la lectura es del mod.
    assert not _denied(done)
    assert done.stdout.strip() == b""
    events = _events(tmp_path)
    assert len(events) == 1 and events[0]["step_aside"] == common.STEP_ASIDE_READ_MOD
    assert not any(e.get("blocked") for e in events)

    # Control positivo: el mismo montaje sin el latido bloquea, así que el montaje sí bloquearía.
    control = tmp_path / "control"
    env_control = _env(control)
    done = _read(control, env_control)
    assert _denied(done)

    # La vía de shell igual: `cat` de la misma prosa.
    shell = tmp_path / "shell"
    env_shell = _env(shell)
    _heartbeat(shell)
    payload = {"tool_name": "Bash", "tool_input": {"command": f"cat {_prose(shell).as_posix()}"}}
    done = _hook("shell", payload, env_shell)
    assert not _denied(done)
    assert [e["category"] for e in _stepped_aside(shell)] == ["shell"]


@pytest.mark.parametrize(
    "case",
    [
        "option_off",
        "option_missing_by_settings",
        "stale",
        "no_process_run",
        "not_active",
        "no_heartbeat",
    ],
)
def test_read_hook_acts_when_mod_off_or_stale(tmp_path, case):
    option = {"option_off": "false", "option_missing_by_settings": None}.get(case, "true")
    env = _env(tmp_path, option=option)
    if case == "option_missing_by_settings":
        # Delivered by settings.json: no plugin option and no plugin data folder.
        env.pop("CLAUDE_PLUGIN_DATA")
    fields = {
        "stale": {"age": timedelta(hours=25)},
        "no_process_run": {"process_run": False},
        "not_active": {"read_mod_active": False},
    }.get(case, {})
    if case != "no_heartbeat":
        _heartbeat(tmp_path, **fields)
    done = _read(tmp_path, env)
    # Como en la 0.40: bloquea la lectura entera de la prosa grande, y no se aparta.
    assert _denied(done), case
    assert _stepped_aside(tmp_path) == []
    assert any(e.get("blocked") for e in _events(tmp_path))

    # Control: un latido fresco y completo, con la opción encendida, se aparta.
    control = tmp_path / "control"
    _heartbeat(control, age=timedelta(hours=23))
    env_control = _env(control)
    done = _read(control, env_control)
    assert not _denied(done)


def test_step_aside_logged_in_blocks_jsonl(tmp_path):
    env = _env(tmp_path)
    _heartbeat(tmp_path)
    _read(tmp_path, env)
    (event,) = _events(tmp_path)
    # Que se apartó, por qué, de qué sesión, por qué vía y sobre qué fichero (su huella, nunca la ruta).
    assert event["step_aside"] == common.STEP_ASIDE_READ_MOD
    assert event["reason"] == "step_aside"
    assert event["suggested"] is False
    assert event["session_id"] == SESSION
    assert event["category"] == "read"
    assert event["via"] == "read_whole" and event["scope"] == "whole"
    assert event["block"] == "on"
    assert event["path_sha"] == common.path_digest(str(_prose(tmp_path)))
    assert str(tmp_path) not in json.dumps(event)


def test_read_hook_does_not_step_aside_for_another_session(tmp_path):
    env = _env(tmp_path)
    # Un latido fresco y completo, pero de OTRA sesión: esta no sabe si su mod cargó.
    _heartbeat(tmp_path, "sess-other")
    done = _read(tmp_path, env)
    assert _denied(done)
    assert _stepped_aside(tmp_path) == []
    # Un fichero de esta sesión que dice ser de otra tampoco vale.
    _heartbeat(tmp_path, SESSION, session_id="sess-other")
    done = _read(tmp_path, env)
    assert _denied(done)
    assert _stepped_aside(tmp_path) == []
    # Control: el latido de esta sesión sí la aparta.
    _heartbeat(tmp_path, SESSION)
    done = _read(tmp_path, env)
    assert not _denied(done)
    assert len(_stepped_aside(tmp_path)) == 1


def test_no_gap_when_active_but_not_blocking(tmp_path):
    # Modo «solo registrar»: capa activo encendida y bloqueo apagado. El mod no actúa
    # (`read_switch` no es `on`), así que el hook tiene que registrar: si se apartara, la lectura
    # no quedaría en ningún sitio.
    env = _env(tmp_path, block="0")
    _heartbeat(tmp_path)
    done = _read(tmp_path, env)
    assert _stepped_aside(tmp_path) == []
    events = _events(tmp_path)
    assert len(events) == 1 and events[0]["block"] == "off_variable"
    assert events[0]["suggested"] is True  # el aviso de la 0.40, sin bloqueo
    assert not _denied(done)
    # El fichero que apaga el bloqueo, igual.
    (tmp_path / "block-off").write_text("", encoding="utf-8")
    env_on = {**env, "LD_HOOK_READ_BLOCK": "1"}
    _read(tmp_path, env_on)
    assert _stepped_aside(tmp_path) == []
    # Control: con el bloqueo encendido y sin el fichero, se aparta.
    (tmp_path / "block-off").unlink()
    _read(tmp_path, env_on)
    assert len(_stepped_aside(tmp_path)) == 1


def test_read_hook_acts_on_a_path_the_mod_does_not_take(tmp_path):
    """La cuarta condición: una vía que el mod no trata la sigue registrando el hook."""
    env = _env(tmp_path)
    _heartbeat(tmp_path)
    # `git show HEAD:x` lee, pero sin un fichero en disco que resumir (`unclassifiable`): el mod lo
    # deja pasar sin registrarlo.
    harmless = {"tool_name": "Bash", "tool_input": {"command": "git show HEAD:README.md"}}
    _hook("shell", harmless, env)
    # Una tool de otro MCP: el mod no la intercepta.
    foreign = {
        "tool_name": "mcp__filesystem__read_text_file",
        "tool_input": {"path": str(_prose(tmp_path))},
    }
    _hook("mcp-read", foreign, env)
    events = _events(tmp_path)
    assert len(events) == 2
    assert _stepped_aside(tmp_path) == []
    # Control: un `cat` de la misma prosa en la misma sesión sí se aparta.
    dump = {"tool_name": "Bash", "tool_input": {"command": f"cat {_prose(tmp_path).as_posix()}"}}
    _hook("shell", dump, env)
    assert len(_stepped_aside(tmp_path)) == 1


# --- El latido dice `read_mod_active` desde el inicio de la sesión ---------------------------------

NODE_DRIVER = """
import { pathToFileURL } from 'node:url'
const { register } = await import(pathToFileURL(process.argv[2]).href)
const hooks = []
const on = (event, matcher, hook) => {
  hooks.push({ event, hook: typeof matcher === 'function' ? matcher : hook })
}
register(on, { ld_bin: 'python', read_mod_enabled: process.argv[3] === 'on' })
const writes = []
const $ = {
  env: { get: async name => (name === 'CLAUDE_CONFIG_DIR' ? '/cfg' : undefined) },
  session: { id: async () => 'sess-9', cwd: async () => '/' },
  fs: {
    write: async (path, text) => { writes.push({ path, text }) },
    read: async () => { throw new Error('no file') },
  },
  process: { run: async () => ({ exitCode: 0, stdout: '["Read"]', stderr: '' }) },
}
const start = hooks.find(h => h.event === 'session.start')
await start.hook($, { cwd: '/', isInteractive: false }, async () => ({ cwd: '/' }))
const beats = writes.filter(w => w.path.includes('/heartbeats/')).map(w => JSON.parse(w.text))
console.log(JSON.stringify(beats))
"""


def _load_build_mod():
    return _load("_sa_build_mod", ROOT / "scripts" / "build_mod.py")


@pytest.mark.parametrize("switch", ["on", "off"])
def test_session_heartbeat_says_read_mod_active_from_start(tmp_path, switch):
    """Antes, `register.js` escribía el latido de `session.start` DESPUÉS de la pieza de lectura y
    se lo pisaba: `read_mod_active` solo aparecía tras la primera lectura clasificada, así que el
    hook nunca se apartaba en la primera lectura de la sesión."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en PATH")
    plugin = tmp_path / "plugin"
    shutil.copytree(
        PLUGIN_DIR, plugin, ignore=shutil.ignore_patterns("register.js", "*.test.ts", "types")
    )
    text = _load_build_mod().build(plugin)
    output = plugin / "register.mjs"
    output.write_text(text, encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(NODE_DRIVER, encoding="utf-8")
    done = subprocess.run(
        [node, str(driver), str(output), switch],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    beats = json.loads(done.stdout)
    # Un solo latido al iniciar la sesión, el último que queda escrito.
    assert len(beats) == 1, beats
    beat = beats[-1]
    assert beat["session_id"] == "sess-9"
    assert beat["process_run"] is True
    if switch == "on":
        assert beat["pieces"]["read"] == "on"
        assert beat.get("read_mod_active") is True, beat
    else:
        # Control: con la pieza apagada el latido no dice que el mod de lectura actúe.
        assert beat["pieces"]["read"] == "off"
        assert "read_mod_active" not in beat


def test_read_hook_steps_aside_with_option_unset(tmp_path):
    """F4-live: the read mod ships on (`"default": true`). A plugin hook whose option was never
    saved gets no `CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED`; with the mod's heartbeat in its session
    it steps aside as with the option on."""
    env = _env(tmp_path, option=None)
    _heartbeat(tmp_path)
    done = _read(tmp_path, env)
    assert not _denied(done)
    assert [e["step_aside"] for e in _stepped_aside(tmp_path)] == [common.STEP_ASIDE_READ_MOD]
    # Control: the same set-up with the option saved as false acts, so the step aside came from
    # the unset option being read as on.
    control = tmp_path / "control"
    env_control = _env(control, option="false")
    _heartbeat(control)
    assert _denied(_read(control, env_control))
    assert _stepped_aside(control) == []
