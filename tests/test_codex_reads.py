"""Issue #670: the read summary and the write guard of Codex (`codex_reads`, hook `codex-tool-guard`).

The payloads of ``tests/fixtures/codex_hooks/pre_tool_use_*.json`` carry every field the input schema
of ``PreToolUse`` (Codex CLI 0.169.0) marks as required, and what the hook prints is checked against
the output schema of the same tag. The summary comes from an injected function, or from a fake
``/mcp`` in this process: these tests never reach the real daemon, the backend or a token.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import ClassVar

import jsonschema
import perf
import pytest

from local_delegate import (
    attribution,
    codex_hooks,
    codex_plugin,
    codex_reads,
    config,
    hook_classify,
    hook_entry,
)

FIXTURES = Path(__file__).parent / "fixtures" / "codex_hooks"
SRC = Path(config.__file__).resolve().parents[1]
PYTHON = "C:/Users/someone/AppData/Roaming/uv/tools/local-delegate-mcp/Scripts/python.exe"
SESSION = "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
AGENT = "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a61"
SENTINEL = "ZEBRA-SENTINEL-4417"
COMMON = hook_entry._load_hook_module("hook_common")


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _schema(name: str) -> dict:
    return _fixture(f"{name}.schema")


@pytest.fixture
def world(tmp_path):
    """A project folder, a data folder and the client environment of the read layer, turned on."""
    work = tmp_path / "work"
    work.mkdir()
    data = tmp_path / "data"
    env = {
        "LD_HOOK_READ_ENABLED": "1",
        "LD_HOOK_READ_BLOCK": "1",
        "LOCAL_DELEGATE_LOG_DIR": str(data),
        "LOCAL_DELEGATE_LANG": "es",
        "USERPROFILE": str(tmp_path),
        "HOME": str(tmp_path),
    }
    return {"work": work, "data": data, "env": env, "calls": []}


def _prose(path: Path, lines: int = 800, width: int = 60) -> Path:
    text = "".join(
        f"Linea {i} de prosa {'x' * width}{' ' + SENTINEL if i == lines // 2 else ''}\n"
        for i in range(1, lines + 1)
    )
    path.write_text(text, encoding="utf-8")
    return path


def _payload(world, tool: str, tool_input: dict, agent: str | None = None, **extra) -> dict:
    name = {"Bash": "pre_tool_use_bash", "apply_patch": "pre_tool_use_apply_patch"}.get(
        tool, "pre_tool_use_mcp_read"
    )
    payload = {
        **_fixture(name),
        "tool_name": tool,
        "tool_input": tool_input,
        "cwd": str(world["work"]),
    }
    if agent:
        payload.update({"agent_id": agent, "agent_type": "worker"})
    payload.update(extra)
    return payload


def _decide(world, payload, summary="Resumen local del fichero."):
    def summarize(path):
        world["calls"].append(path)
        if isinstance(summary, Exception):
            raise summary
        return summary

    return codex_reads.decide(
        payload, COMMON, environ=world["env"], log_dir=world["data"], summarize=summarize
    )


def _bash(world, command, agent=None, summary="Resumen local del fichero."):
    return _decide(world, _payload(world, "Bash", {"command": command}, agent), summary)


def _patch(world, body: str, agent=None):
    patch = f"*** Begin Patch\n{body}\n*** End Patch\n"
    return _decide(world, _payload(world, "apply_patch", {"command": patch}, agent), None)


def _denied(out) -> str:
    assert out is not None, "expected a denial"
    jsonschema.validate(out, _schema("pre-tool-use.command.output"))
    spec = out["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    return spec["permissionDecisionReason"]


def _note(out) -> str:
    assert out is not None, "expected a note"
    jsonschema.validate(out, _schema("pre-tool-use.command.output"))
    spec = out["hookSpecificOutput"]
    assert "permissionDecision" not in spec
    return spec["additionalContext"]


# --- The fixtures are what they say ------------------------------------------------------------
@pytest.mark.parametrize(
    "fixture", ["pre_tool_use_bash", "pre_tool_use_apply_patch", "pre_tool_use_mcp_read"]
)
def test_the_pre_tool_use_fixtures_meet_the_official_input_schema(fixture):
    jsonschema.validate(_fixture(fixture), _schema("pre-tool-use.command.input"))


def test_the_pre_tool_use_schema_check_can_fail():
    broken = _fixture("pre_tool_use_bash")
    del broken["tool_use_id"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, _schema("pre-tool-use.command.input"))


# --- REQ-001: the entry and its matcher ----------------------------------------------------------
def test_the_guard_entry_goes_after_the_two_hooks_of_669():
    names = [spec.name for spec in codex_hooks.SPECS]
    assert names[:2] == ["codex-prompt", "codex-subagent-start"]
    assert codex_reads.NAME in names
    entries = codex_hooks.entries(PYTHON, "win32")
    # `codex-mcp-call` (#669) is also a `PreToolUse` group: pick ours by name.
    [group] = [g for g in entries["PreToolUse"] if codex_hooks.our_name(g) == codex_reads.NAME]
    assert group["matcher"] == codex_reads.MATCHER
    [only] = group["hooks"]
    assert only["timeout"] == codex_reads.HOOK_TIMEOUT_S == 180
    assert codex_hooks.our_name(group) == codex_reads.NAME
    for event in ("UserPromptSubmit", "SubagentStart"):
        [consultive] = entries[event]
        assert "matcher" not in consultive and consultive["hooks"][0]["timeout"] == 30
    assert codex_plugin.check_hooks_file({"hooks": entries}) == []
    assert codex_hooks.EVENT_LABELS["PreToolUse"] == "pre_tool_use"


MATCHING = [
    "Bash",
    "apply_patch",
    "mcp__filesystem__read_text_file",
    "mcp__filesystem__read_file",
    "mcp__obsidian__read_note",
    "mcp__markitdown__convert_to_markdown",
    "mcp__github__get_file_contents",
]
NOT_MATCHING = [
    "Read",
    "shell",
    "Bashful",
    "mcp__local-delegate__local_summarize",
    "mcp__local_delegate__local_extract",
    "mcp__local-delegate__local_describe_image",
    "mcp__filesystem__list_directory",
    "mcp__filesystem__write_file",
    "spawn_agent",
]


def _codex_matches(pattern: str, name: str) -> bool:
    """`matcher.rs`: a pattern with characters besides ``[A-Za-z0-9_|]`` is an unanchored regex."""
    assert re.fullmatch(r"[A-Za-z0-9_|]+", pattern) is None
    assert (
        "(?=" not in pattern and "(?!" not in pattern and "(?<" not in pattern
    )  # Rust: no lookaround
    return re.search(pattern, name) is not None


@pytest.mark.parametrize("name", MATCHING)
def test_the_matcher_takes_the_shell_the_patch_and_mcp_reads(name):
    assert _codex_matches(codex_reads.MATCHER, name)


@pytest.mark.parametrize("name", NOT_MATCHING)
def test_the_matcher_leaves_out_our_tools_and_what_does_not_read(name):
    assert not _codex_matches(codex_reads.MATCHER, name)


def test_the_matcher_reads_the_same_words_as_the_classifier():
    """The MCP names that match are exactly those the classifier counts as reads (`_MCP_READ`)."""
    from local_delegate.resources.hooks import read_classifier

    for name in [n for n in MATCHING + NOT_MATCHING if n.startswith("mcp__")]:
        found = read_classifier.classify_tool(name, {"path": "x.md"})
        assert _codex_matches(codex_reads.MATCHER, name) == (found is not None), name


# --- REQ-002: a whole prose read becomes its summary ---------------------------------------------
@pytest.mark.parametrize("agent", [None, AGENT])
def test_a_whole_prose_read_is_denied_with_the_summary_as_its_result(world, agent):
    notes = _prose(world["work"] / "notes.md")
    reason = _denied(_bash(world, "cat notes.md", agent))
    assert reason.startswith("Resumen de `")
    assert "la lectura no se ejecuto" in reason and "Resumen local del fichero." in reason
    assert "hasta 639 de sus 800 lineas" in reason and "sed -n '1,120p'" in reason
    assert SENTINEL not in reason
    assert world["calls"] == [str(notes)]
    assert Path(world["calls"][0]).is_absolute()
    # guarded for this agent
    _denied(_patch(world, "*** Update File: notes.md\n@@\n-a\n+b", agent))


@pytest.mark.parametrize(
    "command",
    [
        "Get-Content notes.md",
        "Get-Content -Raw notes.md",
        "type notes.md",
        "cd sub && cat ../notes.md",
    ],
)
def test_other_whole_reads_are_summarized_too(world, command):
    if command.startswith("type") and sys.platform != "win32":
        pytest.skip("PowerShell verbs count only where Codex's shell is PowerShell")
    (world["work"] / "sub").mkdir()
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, command))


@pytest.mark.parametrize(
    "command", ["cat notes.md; rm other.txt", "cat notes.md && git status", "echo $(cat notes.md)"]
)
def test_a_compound_command_with_other_commands_is_never_denied_for_a_read(world, command):
    _prose(world["work"] / "notes.md")
    out = _bash(world, command)
    assert out is None or "permissionDecision" not in out["hookSpecificOutput"]
    assert world["calls"] == []


def test_a_compound_command_gets_the_large_read_note(world):
    _prose(world["work"] / "notes.md")
    assert "puede meter mucho texto" in _note(_bash(world, "cat notes.md; rm other.txt"))


# --- REQ-003: fail open ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "summary",
    [
        None,
        "",
        "   \n",
        "[local-delegate error] backend unavailable",
        'MCP tool "local_summarize" was moved to the background as task 7',
        'MCP tool "local_summarize" is still running after 120s. It was moved to the background as task 9',
        "Texto.\n[local-delegate warning: output truncated by max_tokens]",
        "Texto.\n[local-delegate warning: salida cortada por max_tokens]",
        RuntimeError("boom"),
    ],
)
def test_an_invalid_summary_lets_the_read_through_and_guards_nothing(world, summary):
    _prose(world["work"] / "notes.md")
    if isinstance(summary, str) and "cortada" in summary:
        es = json.loads((SRC / "local_delegate/resources/i18n/es/mcp.json").read_text("utf-8"))
        summary = f"Texto.\n[local-delegate warning: {es['mcp.warning.output_truncated']}]"
    assert _bash(world, "cat notes.md", summary=summary) is None
    assert world["calls"], "the summary was never asked: the case proves nothing"
    assert _patch(world, "*** Update File: notes.md\n@@\n-a\n+b") is None


def test_the_valid_summary_control(world):
    """Control of the list above: the same file with a good summary is denied."""
    assert codex_reads.valid_summary("Un resumen correcto.")
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))


@pytest.mark.parametrize(
    "change",
    [{"LD_HOOK_READ_ENABLED": "0"}, {"LD_HOOK_READ_BLOCK": "0"}],
)
def test_the_read_switch_off_lets_it_through(world, change):
    _prose(world["work"] / "notes.md")
    world["env"].update(change)
    assert _bash(world, "cat notes.md") is None
    assert world["calls"] == []


def _cut_the_backend(world) -> None:
    world["data"].mkdir(exist_ok=True)
    breaker = world["data"] / COMMON.BACKEND_BREAKER_FILE
    breaker.write_text(json.dumps({"127.0.0.1:1": {"until": time.time() + 600}}), "utf-8")
    assert COMMON.backend_down(world["env"]), "the cut did not open: the test proves nothing"


def test_backend_down_lets_it_through_and_the_literal_read_lifts_the_guard(world):
    """Issue #707: the whole file entered the context literally, so the guard goes (it used to stay,
    and `apply_patch` was refused in a loop for as long as the backend was down)."""
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    _denied(_patch(world, "*** Update File: notes.md\n@@\n-a\n+b"))  # control: guarded
    _cut_the_backend(world)
    world["calls"].clear()
    assert _bash(world, "cat notes.md") is None and world["calls"] == []
    assert _patch(world, "*** Update File: notes.md\n@@\n-a\n+b") is None


@pytest.mark.parametrize("session", [None, "", "../x", "a" * 129, "con espacio"])
def test_a_session_id_that_cannot_name_a_file_keeps_nothing(world, session):
    _prose(world["work"] / "notes.md")
    payload = _payload(world, "Bash", {"command": "cat notes.md"}, session_id=session)
    assert _decide(world, payload) is None
    assert not (world["data"] / codex_reads.STATE_DIR).exists()


# --- REQ-004: what passes literally ---------------------------------------------------------------
def test_large_code_and_small_prose_pass(world):
    (world["work"] / "big.py").write_text("x = 1\n" * 4000, encoding="utf-8")
    (world["work"] / "small.md").write_text("Poco texto.\n", encoding="utf-8")
    assert _bash(world, "cat big.py") is None
    assert _bash(world, "cat small.md") is None
    assert world["calls"] == []


def test_a_subagent_reading_large_code_whole_gets_the_locate_note(world):
    (world["work"] / "big.py").write_text("x = 1\n" * 4000, encoding="utf-8")
    assert "Subagente:" in _note(_bash(world, "cat big.py", AGENT))
    assert _bash(world, "cat big.py") is None


def test_a_range_of_a_short_file_passes_even_past_the_share(world):
    _prose(world["work"] / "short.md", lines=150, width=60)  # >8 KB, <32 KB, <=200 lines
    assert _bash(world, "sed -n '1,149p' short.md") is None
    assert world["calls"] == []


# --- REQ-005: ranges add up -----------------------------------------------------------------------
def test_ranges_pass_until_the_one_that_reaches_80_percent(world):
    _prose(world["work"] / "notes.md", lines=400, width=100)
    assert _bash(world, "sed -n '1,200p' notes.md") is None
    assert _bash(world, "head -n 250 notes.md") is None
    assert _bash(world, "sed -n '251,316p' notes.md") is None  # 316 of 400: 79 %
    reason = _denied(_bash(world, "sed -n '317,320p' notes.md"))  # 320 of 400: 80 %
    assert "llegaria al 80 % de sus 400 lineas" in reason
    assert "Llevas 316 lineas leidas literales; te quedan 3 (el maximo es 319)" in reason
    assert "Las lineas 317-320 que pediste no llegaron literales" in reason


def test_a_range_past_the_end_passes(world):
    _prose(world["work"] / "notes.md", lines=400, width=100)
    assert _bash(world, "sed -n '1,300p' notes.md") is None
    assert _bash(world, "sed -n '500,900p' notes.md") is None


def test_after_a_literal_whole_read_ranges_pass(world):
    _prose(world["work"] / "notes.md", lines=400, width=100)
    assert _bash(world, "cat notes.md", summary=None) is None  # failed summary: read for real
    assert _bash(world, "sed -n '1,400p' notes.md") is None


def test_subagent_ranges_pass_and_do_not_count_for_the_main_thread(world):
    _prose(world["work"] / "notes.md", lines=400, width=100)
    assert _bash(world, "sed -n '1,399p' notes.md", AGENT) is None
    assert _bash(world, "sed -n '1,300p' notes.md") is None  # 75 % for the main thread
    _denied(_bash(world, "sed -n '301,330p' notes.md"))  # 82 %


# --- REQ-006: the write guard ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "body",
    [
        "*** Update File: notes.md\n@@\n-a\n+b",
        "*** Delete File: notes.md",
        "*** Update File: other.md\n*** Move to: notes.md\n@@\n-a\n+b",
        "*** Add File: ./notes.md\n+nuevo",
    ],
)
def test_a_patch_on_a_summarized_file_is_refused(world, body):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    reason = _denied(_patch(world, body))
    assert "solo se ha leido resumido" in reason and "sed -n '1,120p'" in reason


def test_the_patch_path_is_resolved_like_the_read(world):
    notes = _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    _denied(_patch(world, f"*** Update File: {notes}\n@@\n-a\n+b"))
    if sys.platform == "win32":
        _denied(_patch(world, f"*** Update File: {str(notes).upper()}\n@@\n-a\n+b"))
        drive, rest = str(notes).replace("\\", "/").split(":/", 1)
        _denied(_patch(world, f"*** Update File: /{drive.lower()}/{rest}\n@@\n-a\n+b"))


def test_a_patch_on_another_file_passes(world):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    assert _patch(world, "*** Update File: other.md\n@@\n-a\n+b") is None


@pytest.mark.parametrize(
    "command",
    [
        "sed -i 's/a/b/' notes.md",
        "echo x > notes.md",
        "cp other.md notes.md",
        "apply_patch <<'EOF'\n*** Begin Patch\n*** Update File: notes.md\n@@\n-a\n+b\n*** End Patch\nEOF",
    ],
)
def test_a_shell_write_on_a_summarized_file_is_refused(world, command):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    _denied(_bash(world, command))


def test_a_literal_range_lifts_the_guard(world):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    assert _bash(world, "sed -n '10,40p' notes.md") is None
    assert _patch(world, "*** Update File: notes.md\n@@\n-a\n+b") is None


def test_the_guard_is_per_agent_both_ways(world):
    _prose(world["work"] / "notes.md")
    _prose(world["work"] / "other.md")
    _denied(_bash(world, "cat notes.md"))  # main
    assert _patch(world, "*** Update File: notes.md\n@@\n-a\n+b", AGENT) is None
    _denied(_bash(world, "cat other.md", AGENT))  # subagent
    assert _patch(world, "*** Update File: other.md\n@@\n-a\n+b") is None
    _denied(_patch(world, "*** Update File: other.md\n@@\n-a\n+b", AGENT))
    # and a subagent's literal read does not lift the main thread's guard
    assert _bash(world, "sed -n '1,10p' notes.md", AGENT) is None
    _denied(_patch(world, "*** Update File: notes.md\n@@\n-a\n+b"))


def test_the_guard_survives_another_hook_process(world, tmp_path):
    """Resuming: the state is on disk, so a new process of the real hook still refuses."""
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    payload = _payload(world, "apply_patch", _fixture("pre_tool_use_apply_patch")["tool_input"])
    env = _sandbox(tmp_path, world)
    result = _hook(json.dumps(payload).encode("utf-8"), env)
    assert result.returncode == 0, result.stderr
    assert "solo se ha leido resumido" in _denied(json.loads(result.stdout))


def test_the_hook_process_lets_an_unguarded_patch_through(world, tmp_path):
    """Control of the test above: the same process with no summary before prints nothing."""
    payload = _payload(world, "apply_patch", _fixture("pre_tool_use_apply_patch")["tool_input"])
    result = _hook(json.dumps(payload).encode("utf-8"), _sandbox(tmp_path, world))
    assert result.returncode == 0 and result.stdout == b""


# --- REQ-007: MCP reads ---------------------------------------------------------------------------
def test_a_large_mcp_read_gets_a_note_and_is_never_denied(world):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))  # even guarded
    payload = _payload(world, "mcp__filesystem__read_text_file", {"path": "notes.md"})
    assert "local_summarize" in _note(_decide(world, payload))
    assert world["calls"] == [str(world["work"] / "notes.md")]


def test_our_own_mcp_tools_are_left_alone(world):
    _prose(world["work"] / "notes.md")
    payload = _payload(world, "mcp__local-delegate__local_summarize", {"path": "notes.md"})
    assert _decide(world, payload) is None


# --- REQ-009: the state ---------------------------------------------------------------------------
def test_the_state_holds_paths_and_ranges_never_content(world):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md", summary=f"Resumen que cita {SENTINEL}"))
    assert _bash(world, "sed -n '1,10p' notes.md") is None
    [log] = list((world["data"] / codex_reads.STATE_DIR).iterdir())
    assert log.name == f"{SESSION}.jsonl"
    text = log.read_text("utf-8")
    assert SENTINEL not in text and "Linea" not in text
    ops = [json.loads(line)["op"] for line in text.splitlines()]
    assert ops == ["guard", "range"]


def test_the_prefilter_skips_the_classifier_without_prose_or_state(world, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("classifier loaded")

    monkeypatch.setattr(hook_classify, "classify_text", boom)
    assert _bash(world, "ls -la") is None
    assert _bash(world, "cat big.py") is None
    with pytest.raises(AssertionError, match="classifier loaded"):
        _bash(world, "cat notes.md")  # control: a prose name does reach it


# --- REQ-008: the daemon's /mcp -------------------------------------------------------------------
class _FakeMcp(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    mode = "sse"
    delay = 0.0
    step = 0.0  # before every request: each one in time, all of them together not

    def log_message(self, *_args):
        pass

    def _answer(self, message: dict, status: int = 200) -> None:
        if self.mode == "sse":
            body = f"event: message\ndata: {json.dumps(message)}\n\n".encode()
            kind = "text/event-stream"
        else:
            body = json.dumps(message).encode()
            kind = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Mcp-Session-Id", "sess-1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        time.sleep(self.step)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(("POST", body, dict(self.headers)))
        if self.mode == "401":
            self.send_response(401)
            self.end_headers()
            return
        method = body.get("method")
        if method == "initialize":
            self._answer(
                {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18"}}
            )
        elif method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
        else:
            time.sleep(self.delay)
            error = self.mode == "error"
            result = {
                "content": [{"type": "text", "text": "Resumen del daemon."}],
                "isError": error,
            }
            self._answer({"jsonrpc": "2.0", "id": body["id"], "result": result})

    def do_DELETE(self):
        time.sleep(self.step)
        type(self).seen.append(("DELETE", None, dict(self.headers)))
        self.send_response(200)
        self.end_headers()


@pytest.fixture
def fake_mcp():
    _FakeMcp.seen = []
    _FakeMcp.mode = "sse"
    _FakeMcp.delay = 0.0
    _FakeMcp.step = 0.0
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeMcp)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}/mcp"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("mode", ["sse", "json"])
def test_the_summary_comes_from_one_tool_call_to_the_daemon(fake_mcp, mode):
    _server, url = fake_mcp
    _FakeMcp.mode = mode
    text = codex_reads.daemon_summarize("C:/work/notes.md", url=url, token="test-token")
    assert text == "Resumen del daemon."
    methods = [(verb, body and body.get("method")) for verb, body, _ in _FakeMcp.seen]
    assert methods == [
        ("POST", "initialize"),
        ("POST", "notifications/initialized"),
        ("POST", "tools/call"),
        ("DELETE", None),
    ]
    init = _FakeMcp.seen[0][1]
    assert init["params"]["clientInfo"]["name"] == codex_reads.CLIENT_NAME
    call = _FakeMcp.seen[2][1]["params"]
    assert call == {"name": "local_summarize", "arguments": {"path": "C:/work/notes.md"}}
    headers = {k.lower(): v for k, v in _FakeMcp.seen[2][2].items()}
    assert headers["authorization"] == "Bearer test-token"
    assert headers["mcp-session-id"] == "sess-1"


@pytest.mark.parametrize("mode", ["401", "error"])
def test_a_refused_or_failed_call_gives_none(fake_mcp, mode):
    _server, url = fake_mcp
    _FakeMcp.mode = mode
    assert codex_reads.daemon_summarize("C:/work/notes.md", url=url, token="t") is None


@pytest.mark.real_io
def test_a_daemon_that_does_not_answer_in_time_gives_none(fake_mcp):
    _server, url = fake_mcp
    _FakeMcp.delay = 3.0
    start = time.monotonic()
    assert codex_reads.daemon_summarize("C:/w/n.md", url=url, token="t", timeout=0.5) is None
    assert time.monotonic() - start < 2.5
    assert codex_reads.SUMMARY_TIMEOUT_S < codex_reads.HOOK_TIMEOUT_S


def test_no_daemon_gives_none():
    assert (
        codex_reads.daemon_summarize("C:/w/n.md", url="http://127.0.0.1:9/mcp", token="t") is None
    )


def test_the_hook_client_is_out_of_the_claude_cost():
    assert attribution.exclusion_reason({"client": codex_reads.CLIENT_NAME}) == "not_claude"
    assert attribution.exclusion_reason({"client": "claude-code"}) is None


# --- The real hook process --------------------------------------------------------------------------
_BOOT = (
    "import sys, runpy; sys.path.insert(0, {src!r}); "
    "runpy.run_module('local_delegate.hook', run_name='__main__', alter_sys=True)"
)


def _sandbox(base: Path, world) -> dict[str, str]:
    tmp = base / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in config.ENVIRONMENT_VARIABLES
        and name not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH"}
        and not name.startswith("LD_HOOK_")
    }
    env.update(world["env"])
    env.update(
        {
            "TMP": str(tmp),
            "TEMP": str(tmp),
            "TMPDIR": str(tmp),
            "LD_HOOK_TELEMETRY_LOG": str(base / "telemetry.jsonl"),
        }
    )
    return env


def _hook(stdin: bytes, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", "-c", _BOOT.format(src=str(SRC)), codex_reads.NAME],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=60,
        cwd=env["TMP"],
    )


def test_the_experiment_switch_off_silences_the_guard_too(world, tmp_path):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    payload = _payload(world, "apply_patch", _fixture("pre_tool_use_apply_patch")["tool_input"])
    env = {**_sandbox(tmp_path, world), "LD_HOOK_ENABLED": "0"}
    result = _hook(json.dumps(payload).encode("utf-8"), env)
    assert result.returncode == 0 and result.stdout == b""


# --- codex-guard-fixes (issues #706 and #707) -----------------------------------------------------
_PATCH_ON_NOTES = "*** Update File: notes.md\n@@\n-a\n+b"


@pytest.mark.perf
def test_the_patch_paths_come_out_in_linear_time():
    """REQ-001 (#706): `(.+?)\\s*$` backtracked over every blank, quadratic (40 000: about 5 s)."""

    def header(blanks: int) -> str:
        return "*** Begin Patch\n*** Update File: a" + " " * blanks + "b\n*** End Patch\n"

    small, big = header(4_000), header(40_000)
    found = [m.group(1).strip() for m in codex_reads._PATCH_PATH.finditer(big)]
    assert found == ["a" + " " * 40_000 + "b"]
    perf.assert_linear(
        lambda: list(codex_reads._PATCH_PATH.finditer(small)),
        lambda: list(codex_reads._PATCH_PATH.finditer(big)),
        size_ratio=10,
    )


def test_a_patch_path_loses_its_trailing_blanks_and_the_cr(world):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    patch = "*** Begin Patch\r\n*** Update File: notes.md   \r\n@@\r\n-a\r\n+b\r\n*** End Patch\r\n"
    _denied(_decide(world, _payload(world, "apply_patch", {"command": patch}), None))
    empty = "*** Begin Patch\n*** Delete File:    \n*** End Patch\n"
    assert codex_reads.write_targets("apply_patch", {"command": empty}, None, world["env"]) == []


def _switch_off(world, how: str) -> None:
    if how == "variable":
        world["env"]["LD_HOOK_READ_BLOCK"] = "0"
    elif how == "disabled":
        world["env"]["LD_HOOK_READ_ENABLED"] = "0"
    elif how == "file":
        switch = Path(world["env"]["USERPROFILE" if os.name == "nt" else "HOME"]) / ".claude"
        switch.mkdir(parents=True, exist_ok=True)
        (switch / COMMON.SWITCH_FILE_NAME).write_text("", "utf-8")
        assert COMMON.block_state(world["env"]) == "off_file", (
            "the file is not seen: proves nothing"
        )
    else:
        _cut_the_backend(world)


@pytest.mark.parametrize("how", ["variable", "disabled", "file", "backend"])
@pytest.mark.parametrize("command", ["sed -n '1,40p' notes.md", "cat notes.md"])
def test_a_literal_read_lifts_the_guard_with_the_switch_off(world, how, command):
    """REQ-002 (#707, F1): `decide` went out before `note_real_read`, so the patch was refused in a
    loop for as long as the switch stayed off."""
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    _denied(_patch(world, _PATCH_ON_NOTES))  # control: guarded
    _switch_off(world, how)
    world["calls"].clear()
    assert _bash(world, command) is None and world["calls"] == []
    assert _patch(world, _PATCH_ON_NOTES) is None


def test_ranges_read_with_the_switch_off_still_count(world):
    _prose(world["work"] / "notes.md", lines=400, width=100)
    world["env"]["LD_HOOK_READ_BLOCK"] = "0"
    assert _bash(world, "sed -n '1,300p' notes.md") is None
    world["env"]["LD_HOOK_READ_BLOCK"] = "1"
    _denied(_bash(world, "sed -n '301,330p' notes.md"))  # 330 of 400 counted: 82 %


def test_the_switch_off_does_not_lift_another_agents_guard(world):
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    world["env"]["LD_HOOK_READ_BLOCK"] = "0"
    assert _bash(world, "sed -n '1,40p' notes.md", AGENT) is None
    _denied(_patch(world, _PATCH_ON_NOTES))


@pytest.mark.parametrize(
    "command",
    [
        "cat notes.md other.py",
        "cat notes.md | cat",
        "cat notes.md | grep Linea",
        "Get-Content notes.md | Out-String",
    ],
)
def test_a_read_with_more_files_or_a_pipe_passes_with_the_note(world, command):
    """REQ-003 (#707, F2): denying would drop the other file or the filter's output too."""
    _prose(world["work"] / "notes.md")
    (world["work"] / "other.py").write_text("x = 1\n", encoding="utf-8")
    assert "puede meter mucho texto" in _note(_bash(world, command))
    assert world["calls"] == []


def test_a_pipe_into_a_range_filter_is_still_the_read(world):
    """Control of the test above: `| head -n` and `| Select-Object -First` choose lines, so the
    command is still only the read and the range check applies."""
    _prose(world["work"] / "notes.md")  # 800 lines
    _denied(_bash(world, "cat notes.md | head -n 700"))
    _denied(_bash(world, "Get-Content notes.md | Select-Object -First 700"))
    assert world["calls"] == [str(world["work"] / "notes.md")] * 2


def test_select_object_skip_counts_its_own_lines(world):
    """REQ-004 (#707, F3): `-Skip 200 -First 100` is 201..300, not 1..100."""
    _prose(world["work"] / "notes.md", lines=400, width=100)
    assert _bash(world, "Get-Content notes.md | Select-Object -Skip 200 -First 100") is None
    assert _bash(world, "sed -n '1,200p' notes.md") is None  # 1..300: 75 %
    _denied(_bash(world, "sed -n '301,330p' notes.md"))  # 82 %


@pytest.mark.parametrize("joiner", ["; ", " && ", "\n"])
def test_the_ranges_of_one_compound_command_add_up(world, joiner):
    """REQ-005 (#707, F4): two ranges in one command were one range, under the 80 %."""
    _prose(world["work"] / "notes.md", lines=500, width=100)
    command = f"sed -n '1,300p' notes.md{joiner}sed -n '301,400p' notes.md"
    reason = _denied(_bash(world, command))
    assert "llegaria al 80 % de sus 500 lineas" in reason


def test_ranges_of_one_command_under_the_share_pass(world):
    """Control of the test above: 399 of 500 lines (79 %) passes, and both ranges count."""
    _prose(world["work"] / "notes.md", lines=500, width=100)
    assert _bash(world, "sed -n '1,300p' notes.md; sed -n '301,399p' notes.md") is None
    _denied(_bash(world, "sed -n '400,400p' notes.md"))


def test_ranges_in_a_mixed_compound_command_count_for_the_next_read(world):
    _prose(world["work"] / "notes.md", lines=500, width=100)
    command = "sed -n '1,200p' notes.md; echo ---; sed -n '201,390p' notes.md"
    assert "puede meter mucho texto" in _note(_bash(world, command))
    assert world["calls"] == []
    _denied(_bash(world, "sed -n '391,400p' notes.md"))  # 400 of 500: 80 %


def test_reads_of_two_files_in_one_command_are_not_only_the_read(world):
    _prose(world["work"] / "notes.md", lines=500, width=100)
    _prose(world["work"] / "other.md", lines=500, width=100)
    command = "sed -n '1,450p' notes.md; sed -n '1,10p' other.md"
    assert "puede meter mucho texto" in _note(_bash(world, command))
    assert world["calls"] == []


def test_get_content_total_count_is_a_range_that_counts(world):
    _prose(world["work"] / "notes.md", lines=400, width=100)
    assert _bash(world, "Get-Content notes.md -TotalCount 300") is None
    _denied(_bash(world, "sed -n '301,330p' notes.md"))


@pytest.mark.parametrize(
    "command",
    [
        "Set-Content notes.md 'nuevo'",
        "Set-Content -Path notes.md -Value nuevo",
        "'nuevo' | Out-File notes.md",
        "Out-File -FilePath notes.md -InputObject nuevo",
        "mv other.md notes.md",
        "Move-Item other.md notes.md",
    ],
)
def test_more_shell_writes_on_a_summarized_file_are_refused(world, command):
    """REQ-009 (#707, F10): the PowerShell writes and `mv`, with their control (unguarded: pass)."""
    _prose(world["work"] / "notes.md")
    assert _bash(world, command) is None
    _denied(_bash(world, "cat notes.md"))
    _denied(_bash(world, command))


def test_a_mcp_read_never_lifts_the_guard(world):
    """REQ-007 (#707, F7): the hook cannot see which part of the file an MCP read returns."""
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    payload = _payload(world, "mcp__filesystem__read_text_file", {"path": "notes.md"})
    _note(_decide(world, payload))
    _denied(_patch(world, _PATCH_ON_NOTES))


def test_old_session_logs_are_pruned_when_a_session_starts(world):
    """REQ-008 (#707, F9): 31 days old goes, 29 stays, and only `*.jsonl`."""
    folder = world["data"] / codex_reads.STATE_DIR
    folder.mkdir(parents=True)
    old, recent, other = folder / "old.jsonl", folder / "recent.jsonl", folder / "keep.txt"
    for item, days in ((old, 31), (recent, 29), (other, 31)):
        item.write_text("{}\n", encoding="utf-8")
        past = time.time() - days * 86400
        os.utime(item, (past, past))
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    assert (folder / f"{SESSION}.jsonl").exists()
    assert not old.exists()
    assert recent.exists() and other.exists()


@pytest.mark.real_io
def test_the_summary_deadline_is_for_the_whole_call(fake_mcp):
    """REQ-006 (#707, F5): four requests of 0.4 s each are all in time for a socket, not in total."""
    _server, url = fake_mcp
    _FakeMcp.step = 0.4
    start = time.monotonic()
    assert codex_reads.daemon_summarize("C:/w/n.md", url=url, token="t", timeout=1.0) is None
    assert time.monotonic() - start < 1.5


def test_the_same_slow_daemon_answers_within_a_longer_deadline(fake_mcp):
    """Control of the test above: with room for the four requests the summary comes back."""
    _server, url = fake_mcp
    _FakeMcp.step = 0.4
    assert codex_reads.daemon_summarize("C:/w/n.md", url=url, token="t", timeout=5.0) == (
        "Resumen del daemon."
    )


def test_a_write_in_the_same_command_does_not_hide_the_read(world):
    """A write wins as the call's primary access: the read beside it still lifts the guard."""
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    assert _bash(world, "sed -n '1,40p' notes.md; echo x > out.txt") is None
    assert _patch(world, _PATCH_ON_NOTES) is None


def test_a_search_does_not_lift_the_guard(world):
    """Control of the lifts: `grep` shows loose lines, not a known part of the file."""
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    _bash(world, "grep Linea notes.md")
    _denied(_patch(world, _PATCH_ON_NOTES))


def test_a_prune_that_cannot_delete_leaves_the_read_alone(world, monkeypatch):
    folder = world["data"] / codex_reads.STATE_DIR
    folder.mkdir(parents=True)
    old = folder / "old.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    past = time.time() - 31 * 86400
    os.utime(old, (past, past))

    def refuse(self, *_args, **_kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", refuse)
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    assert old.exists()
    _denied(_patch(world, _PATCH_ON_NOTES))


def test_a_patch_header_with_blanks_before_it_is_still_guarded(world):
    """Security review: a parser that trims the line applies `  *** Update File:` too."""
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    _denied(_patch(world, "  *** Update File: notes.md\n@@\n-a\n+b"))
    _denied(_patch(world, "\t*** Delete File: notes.md"))
    command = "*** Begin Patch\n" + " " * 40_000 + "x\n*** End Patch\n"
    assert list(codex_reads._PATCH_PATH.finditer(command)) == []


@pytest.mark.perf
def test_blanks_before_a_patch_header_cost_linearly():
    """The cost half of the test above, measured as growth (SDD ci-root-cause)."""

    def command(blanks: int) -> str:
        return "*** Begin Patch\n" + " " * blanks + "x\n*** End Patch\n"

    small, big = command(4_000), command(40_000)
    perf.assert_linear(
        lambda: list(codex_reads._PATCH_PATH.finditer(small)),
        lambda: list(codex_reads._PATCH_PATH.finditer(big)),
        size_ratio=10,
    )


@pytest.mark.parametrize(
    "command",
    [
        "cat notes.md | head -n 5 > out.txt",
        "Get-Content notes.md | Select-Object -First 1 | Out-File out.txt",
    ],
)
def test_a_read_that_goes_to_a_file_does_not_lift_the_guard(world, command):
    """Security review: the output went to a file, so nothing entered the context."""
    _prose(world["work"] / "notes.md")
    _denied(_bash(world, "cat notes.md"))
    assert _bash(world, command) is None
    _denied(_patch(world, _PATCH_ON_NOTES))
    assert _bash(world, "sed -n '1,5p' notes.md") is None  # control: a real range does lift it
    assert _patch(world, _PATCH_ON_NOTES) is None
