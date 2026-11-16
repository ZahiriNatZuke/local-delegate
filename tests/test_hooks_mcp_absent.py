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
        and key not in {"PYTHONPATH", "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR"}
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
    # Only built-ins deferred: the MCP tools may be loaded up front (tool search off), no proof.
    assert _absent(hook_common, tmp_path, [_delta(added=["Monitor", "CronList"])]) is False


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
    # A folder (or a FIFO) is not read.
    assert hook_common.local_tools_absent({"transcript_path": str(tmp_path)}) is False
    transcript = _write_transcript(tmp_path / "t.jsonl", ABSENT)
    # Un `agent_id` con forma de ruta no construye ninguna.
    assert (
        hook_common.local_tools_absent({"transcript_path": str(transcript), "agent_id": "../../x"})
        is False
    )
    # Por encima del tope no se lee.
    monkeypatch.setattr(hook_common, "TRANSCRIPT_MAX_BYTES", 10)
    assert hook_common.local_tools_absent({"transcript_path": str(transcript)}) is False


# --- Subagente con lista cerrada de tools (issue #664) -------------------------------------------
#
# Medido en los transcripts de subagentes de una PC real: un agente con `tools:` cerrado y sin
# ninguna MCP (`tools: Read, Grep, Glob`) no tiene NINGUN `deferred_tools_delta` en su transcript
# (85 de 85), y uno que hereda las tools lo tiene antes de su primer `tool_use`. Pero un agente con
# `tools:` cerrado que SI nombra las `local_*` tampoco tiene delta (se cargan de entrada), asi que la
# falta de delta no basta: la prueba es la definicion del agente, que se busca por `agent_type`.

CLOSED = "---\nname: closed-reviewer\ndescription: x\ntools: Read, Grep, Glob\n---\n\nCuerpo.\n"
NAMED = (
    "---\nname: named-helper\ndescription: x\n"
    "tools: Read, Bash, mcp__local-delegate__local_extract\n---\n"
)
YAML_LIST = "---\nname: list-reviewer\ntools:\n  - Read\n  - Grep\n---\n"
OPEN = "---\nname: open-helper\ndescription: x\ndisallowedTools: Write, Edit\n---\n"
STAR = "---\nname: star-helper\ntools: '*'\n---\n"


def _name_of(definition: str) -> str:
    return definition.split("name: ", 1)[1].split("\n", 1)[0]


def _agent(base: Path, text: str, where: str = "user") -> None:
    root = base / ".claude" if where == "user" else base / "repo" / ".claude"
    folder = root / "agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{_name_of(text)}.md").write_text(text, encoding="utf-8")


def _subagent_payload(world, file: Path, agent_type: str, cwd: Path | None = None) -> dict:
    main = _write_transcript(world["tmp"] / "proj" / "sess-595.jsonl", PRESENT)
    _write_transcript(
        world["tmp"] / "proj" / "sess-595" / "subagents" / "agent-abc664.jsonl",
        [{"type": "assistant"}],
    )
    payload = _read_payload(file, main, agent_id="abc664", agent_type=agent_type)
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


@pytest.mark.parametrize(
    ("definition", "absent"),
    [(CLOSED, True), (YAML_LIST, True), (NAMED, False), (OPEN, False), (STAR, False)],
    ids=["closed", "yaml-list", "names-local", "inherits", "star"],
)
def test_closed_subagent_is_not_sent_to_local_tools(world, definition, absent):
    """El bloqueo de la prosa grande: solo calla si la lista cerrada no nombra las `local_*`."""
    _mark_backend_alive(world)
    doc = _prose(world)
    _agent(world["tmp"], definition)
    payload = _subagent_payload(world, doc, _name_of(definition))
    out, log = _run(world, "suggest_delegate_read.py", payload)
    if absent:
        assert _decision(out) is None
        assert log[-1]["reason"] == "mcp_absent"
    else:
        assert _decision(out) == "deny"
        assert log[-1]["reason"] == "large_prose"


def test_closed_subagent_reading_code_gets_no_hint(world):
    _mark_backend_alive(world)
    code = world["tmp"] / "big.py"
    code.write_text("x = 1\n" * 5000, encoding="utf-8")
    _agent(world["tmp"], CLOSED)
    payload = _subagent_payload(world, code, "closed-reviewer")
    out, log = _run(world, "suggest_delegate_read.py", payload)
    assert _decision(out) is None
    assert log[-1]["reason"] == "mcp_absent"
    # Control positivo: el mismo subagente, de un tipo sin definicion conocida, recibe la pista.
    out, _ = _run(world, "suggest_delegate_read.py", _subagent_payload(world, code, "unknown-type"))
    assert "local_extract" in out


def test_closed_subagent_shell_dump_is_not_blocked(world):
    _mark_backend_alive(world)
    doc = _prose(world)
    _agent(world["tmp"], CLOSED)
    payload = _subagent_payload(world, doc, "closed-reviewer")
    payload.update({"tool_name": "Bash", "tool_input": {"command": f"cat {doc.as_posix()}"}})
    out, log = _run(world, "suggest_delegate_shell.py", payload)
    assert _decision(out) is None
    assert log[-1]["reason"] == "mcp_absent"


def test_project_agent_definition_is_found_from_cwd(world):
    _mark_backend_alive(world)
    doc = _prose(world)
    _agent(world["tmp"], CLOSED, where="project")
    nested = world["tmp"] / "repo" / "src" / "deep"
    nested.mkdir(parents=True)
    payload = _subagent_payload(world, doc, "closed-reviewer", cwd=nested)
    out, log = _run(world, "suggest_delegate_read.py", payload)
    assert _decision(out) is None
    assert log[-1]["reason"] == "mcp_absent"


def test_a_local_tool_use_beats_the_definition(hook_common, tmp_path, monkeypatch):
    """Si el transcript del subagente ya usa una `local_*`, la definicion no manda."""
    monkeypatch.setenv("USERPROFILE" if os.name == "nt" else "HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    _agent(tmp_path, CLOSED)
    use = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "mcp__local-delegate__local_extract"}]
        },
    }
    transcript = _write_transcript(tmp_path / "t.jsonl", [use])
    payload = {"transcript_path": str(transcript), "agent_type": "closed-reviewer"}
    assert hook_common.local_tools_absent(payload) is False
    # Sin ese uso, la definicion cerrada basta (aunque no haya ningun delta).
    transcript = _write_transcript(tmp_path / "t.jsonl", [{"type": "assistant"}])
    assert hook_common.local_tools_absent(payload) is True
    # Y tambien sin transcript: la definicion es la prueba.
    assert hook_common.local_tools_absent({"agent_type": "closed-reviewer"}) is True
    # Sin `agent_type` (hilo principal) no se mira ninguna definicion.
    assert hook_common.local_tools_absent({"transcript_path": str(transcript)}) is False
    # Un `agent_type` de plugin, con forma de ruta o vacio no se busca, aunque haya una definicion
    # que se llame asi (sin la regex del nombre, estas dos se encontrarian).
    for odd_name in ("plugin:closed-reviewer", "../closed-reviewer"):
        (tmp_path / ".claude" / "agents" / f"odd{len(odd_name)}.md").write_text(
            CLOSED.replace("name: closed-reviewer", f"name: {odd_name}"), encoding="utf-8"
        )
    for odd in ("plugin:closed-reviewer", "../closed-reviewer", "", None, 3):
        probe = {"transcript_path": str(transcript), "agent_type": odd}
        assert hook_common.local_tools_absent(probe) is False


def test_own_transcript_decides_and_main_does_not(hook_common, tmp_path, monkeypatch):
    """El transcript propio del subagente puede desmentir la definicion; el del principal, no."""
    monkeypatch.setenv("USERPROFILE" if os.name == "nt" else "HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    _agent(tmp_path, CLOSED)
    use = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "mcp__local-delegate__local_extract"}]
        },
    }
    main = _write_transcript(tmp_path / "proj" / "s.jsonl", [*PRESENT, use])
    payload = {"transcript_path": str(main), "agent_id": "a1", "agent_type": "closed-reviewer"}
    # Sin transcript propio: el uso del principal no cuenta, manda la definicion.
    assert hook_common.local_tools_absent(payload) is True
    own = tmp_path / "proj" / "s" / "subagents" / "agent-a1.jsonl"
    _write_transcript(own, [{"type": "assistant"}])
    assert hook_common.local_tools_absent(payload) is True
    # Un delta propio que anade las `local_*` prueba que estan (la definicion era otra).
    _write_transcript(own, PRESENT)
    assert hook_common.local_tools_absent(payload) is False
    # Un delta propio sin ellas no desmiente la definicion.
    _write_transcript(own, ABSENT)
    assert hook_common.local_tools_absent(payload) is True


@pytest.mark.parametrize(
    ("tools_yaml", "closed"),
    [
        ("tools: Read, Grep, Glob", True),
        ("tools: [Read, Grep]", True),
        ('tools: "Read, Grep"', True),
        ("tools:\n  - Read\n  - Grep", True),
        ("tools:\n- Read\n- Grep", True),
        ("tools:\n  - Read\n  # comentario\n  - Grep", True),
        ("tools: [Read, Grep,\n  mcp__local-delegate__local_extract]", False),
        ("tools: >-\n  Read, mcp__local-delegate__local_extract", False),
        ("tools: |\n  Read", False),
        ("tools:\n  - Read\n  - mcp__local-delegate__local_extract", False),
        ("tools:\n  - Read\n  raro: x\n  - mcp__local-delegate__local_extract", False),
        ("tools: Read  # mcp__local-delegate__local_extract", False),
        ("tools: *", False),
        ("tools:", False),
    ],
    ids=lambda value: value if isinstance(value, bool) else value.replace("\n", "/"),
)
def test_yaml_forms_never_give_a_false_closed(
    hook_common, tmp_path, monkeypatch, tools_yaml, closed
):
    """Lo que el parser no lee entero es duda (como hoy), nunca un «cerrado» que silencie."""
    monkeypatch.setenv("USERPROFILE" if os.name == "nt" else "HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    folder = tmp_path / ".claude" / "agents"
    folder.mkdir(parents=True)
    text = f"---\nname: shape\ndescription: x\n{tools_yaml}\nmodel: sonnet\n---\n"
    (folder / "shape.md").write_text(text, encoding="utf-8")
    assert hook_common.closed_agent_without_local_tools({"agent_type": "shape"}) is closed


def test_definition_found_by_name_field_and_with_bom(hook_common, tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE" if os.name == "nt" else "HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    folder = tmp_path / ".claude" / "agents"
    folder.mkdir(parents=True)
    # El fichero se llama distinto que el agente: manda `name:`. Con BOM y CRLF.
    text = "﻿" + CLOSED.replace("\n", "\r\n")
    (folder / "other-file.md").write_text(text, encoding="utf-8")
    assert hook_common.local_tools_absent({"agent_type": "closed-reviewer"}) is True
    # Control: un fichero `closed-reviewer.md` cuyo `name:` es otro no cuenta como ese agente.
    (folder / "other-file.md").unlink()
    (folder / "closed-reviewer.md").write_text(
        CLOSED.replace("name: closed-reviewer", "name: someone-else"), encoding="utf-8"
    )
    assert hook_common.local_tools_absent({"agent_type": "closed-reviewer"}) is False


def test_subagent_start_skips_the_reminder_for_a_closed_list(world):
    _agent(world["tmp"], CLOSED)
    _agent(world["tmp"], OPEN)
    base = {"hook_event_name": "SubagentStart", "agent_id": "abc664", "cwd": str(world["tmp"])}
    command = [sys.executable, str(HOOKS / "subagent_start.py")]

    def run(agent_type: str) -> str:
        done = subprocess.run(
            command,
            input=json.dumps({**base, "agent_type": agent_type}).encode("utf-8"),
            capture_output=True,
            env=world["env"],
            timeout=TIMEOUT_S,
            cwd=world["tmp"],
        )
        assert done.returncode == 0
        return done.stdout.decode("utf-8")

    assert run("closed-reviewer").strip() == ""
    # Control positivo: un agente que hereda las tools sigue recibiendo el recordatorio.
    assert "ToolSearch" in run("open-helper")


@pytest.mark.parametrize("lang", ["es", "en"])
def test_block_and_skill_say_what_to_do_without_tool_search(lang):
    """REQ-005: el bloque y la skill tienen la salida para el subagente sin `ToolSearch`."""
    from local_delegate import install

    for source in (install.memory_source(lang), install.skill_source(lang)):
        text = source.read_text(encoding="utf-8")
        paragraph = next(
            (
                part
                for part in text.split("\n\n")
                if "ToolSearch` ni" in part or "ToolSearch` or" in part
            ),
            None,
        )
        assert paragraph is not None, source
        for needle in ("`tools:`", "mcp__local-delegate__local_*", "`offset`/`limit`"):
            assert needle in paragraph, (source, needle)
