"""Los hooks de lectura y de shell no mandan a tools `local_*` que la sesion no tiene (issue #595).

La entrada de un hook no dice que servidores MCP hay; el transcript si, con los adjuntos
`deferred_tools_delta` que escribe Claude Code (formato medido en transcripts reales, el mismo que lee
`scripts/_claude_bench.py`). Solo con prueba de ausencia el hook calla y registra `mcp_absent`; ante
cualquier duda avisa o bloquea como antes. Cada caso con el MCP presente es el control positivo del
caso ausente: misma lectura, mismo entorno, solo cambia el transcript.

Los hooks se lanzan como proceso, `python <script>` (la entrega por settings, y el mismo fichero que
carga `local_delegate.hook`), con el log de hooks en un temporal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "src" / "local_delegate" / "resources" / "hooks"
TIMEOUT_S = 60

LD = "mcp__local-delegate__local_describe_image"
OTHER = "mcp__other-server__web_search"


def _delta(added=(), removed=(), pending=()) -> dict:
    return {
        "type": "attachment",
        "attachment": {
            "type": "deferred_tools_delta",
            "addedNames": list(added),
            "removedNames": list(removed),
            "pendingMcpServers": list(pending),
        },
    }


def _write_transcript(path: Path, events: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "message": {"content": "hola"}})]
    lines += [json.dumps(e, separators=(",", ":")) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


#: The plugin's command for each script (`hook_entry`), launched as Claude Code does.
ENTRY_NAMES = {"suggest_delegate_read.py": "read", "suggest_delegate_shell.py": "shell"}


@pytest.fixture(params=["settings", "plugin"])
def world(tmp_path, request):
    """Un HOME, un LOG_DIR y un temporal propios; el bloqueo encendido y el backend «vivo»."""
    data = tmp_path / "data"
    temp = tmp_path / "tmp"
    data.mkdir()
    temp.mkdir()
    # La marca de salud que `backend_available` lee: fresca y en verde, sin sondear la red.
    import time

    health = {"ok": True, "at": time.time()}
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("LD_", "LOCAL_DELEGATE_", "CLAUDE_PLUGIN_"))
        and key not in {"PYTHONPATH"}
    }
    env.update(
        {
            "HOME": str(tmp_path),
            "USERPROFILE": str(tmp_path),
            "TMP": str(temp),
            "TEMP": str(temp),
            "TMPDIR": str(temp),
            "LOCAL_DELEGATE_LOG_DIR": str(data),
            "LOCAL_DELEGATE_LANG": "es",
            "LD_HOOK_TELEMETRY_LOG": str(tmp_path / "telemetry.jsonl"),
            "LD_HOOK_READ_SWITCH_FILE": str(tmp_path / "no-switch"),
            "LD_HOOK_READ_ENABLED": "1",
            "LD_HOOK_READ_BLOCK": "1",
            "PYTHONUTF8": "1",
        }
    )
    return {"tmp": tmp_path, "env": env, "health": health, "delivery": request.param}


def _mark_backend_alive(world) -> None:
    """`backend_available` lee una marca cacheada; se escribe por su propia funcion de ruta."""
    code = (
        "import sys, json, time; sys.path.insert(0, sys.argv[1]); import hook_common as h;"
        "p = h._health_path(); p.parent.mkdir(parents=True, exist_ok=True);"
        "print(p)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(HOOKS)],
        capture_output=True,
        text=True,
        env=world["env"],
        timeout=TIMEOUT_S,
        check=True,
    )
    marker = Path(out.stdout.strip())
    marker.write_text(json.dumps({"ts": world["health"]["at"], "ok": True}), "utf-8")


def _run(world, script: str, payload: dict) -> tuple[str, list[dict]]:
    if world["delivery"] == "plugin":
        # The plugin's entry: the tool's interpreter, isolated, by module (`hooks.json`).
        command = [sys.executable, "-I", "-m", "local_delegate.hook", ENTRY_NAMES[script]]
    else:
        command = [sys.executable, str(HOOKS / script)]
    done = subprocess.run(
        command,
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=world["env"],
        timeout=TIMEOUT_S,
        cwd=world["tmp"],
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    log = world["tmp"] / "telemetry.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done.stdout.decode("utf-8"), [json.loads(line) for line in lines if line]


def _read_payload(file: Path, transcript: Path | None, **extra) -> dict:
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-595",
        "tool_name": "Read",
        "tool_input": {"file_path": str(file)},
        "cwd": str(file.parent),
        **extra,
    }
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    return payload


def _prose(world) -> Path:
    doc = world["tmp"] / "notes.md"
    doc.write_text("prosa larga para el hook\n" * 1200, encoding="utf-8")  # ~29 KB
    return doc


def _decision(out: str) -> str | None:
    if not out.strip():
        return None
    data = json.loads(out)["hookSpecificOutput"]
    return data.get("permissionDecision") or ("context" if data.get("additionalContext") else None)


ABSENT = [_delta(added=[OTHER, "Monitor"])]
PRESENT = [_delta(added=[OTHER, LD])]


@pytest.mark.parametrize("events", [ABSENT, PRESENT], ids=["absent", "present"])
def test_read_of_large_prose(world, events):
    _mark_backend_alive(world)
    doc = _prose(world)
    transcript = _write_transcript(world["tmp"] / "proj" / "sess-595.jsonl", events)
    out, log = _run(world, "suggest_delegate_read.py", _read_payload(doc, transcript))
    if events is ABSENT:
        assert _decision(out) is None
        assert log[-1]["reason"] == "mcp_absent"
        assert log[-1]["suggested"] is False
    else:
        assert _decision(out) == "deny"
        assert log[-1]["reason"] == "large_prose"


@pytest.mark.parametrize("events", [ABSENT, PRESENT], ids=["absent", "present"])
def test_read_of_large_image(world, events):
    image = world["tmp"] / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 40 * 1024)
    transcript = _write_transcript(world["tmp"] / "proj" / "sess-595.jsonl", events)
    out, log = _run(world, "suggest_delegate_read.py", _read_payload(image, transcript))
    if events is ABSENT:
        assert _decision(out) is None
        assert log[-1]["reason"] == "mcp_absent"
    else:
        assert "local_describe_image" in out


@pytest.mark.parametrize("events", [ABSENT, PRESENT], ids=["absent", "present"])
def test_shell_dump_of_large_prose(world, events):
    _mark_backend_alive(world)
    doc = _prose(world)
    transcript = _write_transcript(world["tmp"] / "proj" / "sess-595.jsonl", events)
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-595",
        "tool_name": "Bash",
        "tool_input": {"command": f"cat {doc.as_posix()}"},
        "cwd": str(world["tmp"]),
        "transcript_path": str(transcript),
    }
    out, log = _run(world, "suggest_delegate_shell.py", payload)
    if events is ABSENT:
        assert _decision(out) is None
        assert log[-1]["reason"] == "mcp_absent"
    else:
        assert _decision(out) == "deny"


def test_subagent_looks_at_its_own_transcript(world):
    """La entrada de un subagente trae el transcript del principal; se mira el suyo."""
    _mark_backend_alive(world)
    code = world["tmp"] / "big.py"
    code.write_text("x = 1\n" * 5000, encoding="utf-8")
    main = _write_transcript(world["tmp"] / "proj" / "sess-595.jsonl", PRESENT)
    _write_transcript(
        world["tmp"] / "proj" / "sess-595" / "subagents" / "agent-abc123.jsonl", ABSENT
    )
    out, log = _run(world, "suggest_delegate_read.py", _read_payload(code, main, agent_id="abc123"))
    assert _decision(out) is None
    assert log[-1]["reason"] == "mcp_absent"
    # Control: el subagente sin transcript propio se guia por el principal (que las tiene).
    out, log = _run(world, "suggest_delegate_read.py", _read_payload(code, main, agent_id="zzz999"))
    assert _decision(out) == "context"
    assert "local_extract" in out


# --- La funcion, caso a caso (REQ-002: ante la duda, como hoy) -----------------------------------


@pytest.fixture
def hook_common(monkeypatch):
    monkeypatch.syspath_prepend(str(HOOKS))
    import hook_common as module

    return module


def _absent(hook_common, tmp_path, events, **payload) -> bool:
    transcript = _write_transcript(tmp_path / "t.jsonl", events)
    return hook_common.local_tools_absent({"transcript_path": str(transcript), **payload})


def test_absent_only_with_a_delta_and_no_local_tool(hook_common, tmp_path):
    assert _absent(hook_common, tmp_path, ABSENT) is True
    assert _absent(hook_common, tmp_path, PRESENT) is False
    # Sin ningun delta: formato desconocido, como hoy.
    assert _absent(hook_common, tmp_path, [{"type": "assistant"}]) is False
    # Anadida y luego quitada: ausente. Quitada y luego anadida: presente.
    assert _absent(hook_common, tmp_path, [*PRESENT, _delta(removed=[LD])]) is True
    assert _absent(hook_common, tmp_path, [*ABSENT, _delta(added=[LD])]) is False
    # El servidor aun conecta: como hoy.
    assert (
        _absent(hook_common, tmp_path, [_delta(added=[OTHER], pending=["local-delegate"])]) is False
    )
    # Con prefijo de plugin tambien cuenta.
    plugin = "mcp__plugin_local-delegate_local-delegate__local_status"
    assert _absent(hook_common, tmp_path, [_delta(added=[plugin])]) is False


def test_a_local_tool_use_means_present(hook_common, tmp_path):
    """Las tools fijadas por el mod no salen como diferidas: un `tool_use` de una basta."""
    use = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "mcp__local-delegate__local_summarize",
                }
            ]
        },
    }
    assert _absent(hook_common, tmp_path, [*ABSENT, use]) is False
    # El texto de un aviso que nombra la tool (dentro de un string) no es un uso.
    hint = {
        "type": "attachment",
        "attachment": {
            "type": "hook_success",
            "content": 'ToolSearch("select:mcp__local-delegate__local_extract")',
        },
    }
    assert _absent(hook_common, tmp_path, [*ABSENT, hint]) is True


def test_doubt_means_suggest(hook_common, tmp_path, monkeypatch):
    assert hook_common.local_tools_absent({}) is False
    assert hook_common.local_tools_absent(None) is False
    assert (
        hook_common.local_tools_absent({"transcript_path": str(tmp_path / "missing.jsonl")})
        is False
    )
    transcript = _write_transcript(tmp_path / "t.jsonl", ABSENT)
    # Un `agent_id` con forma de ruta no construye ninguna.
    assert (
        hook_common.local_tools_absent({"transcript_path": str(transcript), "agent_id": "../../x"})
        is False
    )
    # Por encima del tope no se lee.
    monkeypatch.setattr(hook_common, "TRANSCRIPT_MAX_BYTES", 10)
    assert hook_common.local_tools_absent({"transcript_path": str(transcript)}) is False
