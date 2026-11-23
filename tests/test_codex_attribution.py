"""Issue #669, second part: each delegation of Codex attributed to its Codex session.

The chain: the `codex-mcp-call` hook (`PreToolUse` on our MCP tools) leaves a note
`codex-<call id>.json`; the middleware reads `_meta.callId` and `_meta.sessionId` only from
`codex-mcp-client`; the log line carries the call id, the session's one-way key and, with the note,
the thread, the agent type and the Codex model. Those rows stay out of the backfill and the cost,
and have their own column (`codex`) in the panel and in the summary per session.

The payloads of ``tests/fixtures/codex_hooks/pre_tool_use_*.json`` meet the official input schema
of Codex CLI 0.169.0 (copied there); see its README.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import jsonschema
import pytest
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import Implementation

# The subprocess harness of the core tests: the hook launched with `-I` as Codex launches it.
from test_codex_hooks import PYTHON, _hook, _sandbox

from local_delegate import (
    attribution,
    clients,
    codex_hooks,
    codex_plugin,
    config,
    cost,
    i18n,
    server,
    transcripts,
    valuation,
)
from local_delegate.resources.hooks import hook_common
from local_delegate.web import metrics

FIXTURES = Path(__file__).parent / "fixtures" / "codex_hooks"
ROOT = Path(__file__).parents[1]
CODEX = "codex-mcp-client"
SESSION = "019a6e3b-5c1d-7a2e-9f40-3b8d2c6e1a55"
OTHER_SESSION = "019a6e3b-0000-7000-8000-000000000000"
MODEL = "gpt-5.5-codex"

OURS = ("pre_tool_use_mcp", "pre_tool_use_mcp_subagent", "pre_tool_use_code_mode")
NOT_OURS = ("pre_tool_use_bash", "pre_tool_use_apply_patch", "pre_tool_use_other_mcp")


def _key(session_id: str) -> str:
    """The contract, written out so a test fails on its assert and not on a missing name."""
    return hashlib.sha256(f"local-delegate-session:{session_id}".encode()).hexdigest()[:32]


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _notes_of(env: dict[str, str]) -> Path:
    return Path(env["TMP"]) / hook_common.FILE_NAMES["call_notes_dir"][1]


# --- REQ-001: the entry -------------------------------------------------------------------------
def test_the_mcp_hook_is_the_last_entry_and_the_first_two_do_not_change():
    assert [(s.name, s.event, s.matcher) for s in codex_hooks.SPECS[:2]] == [
        ("codex-prompt", "UserPromptSubmit", None),
        ("codex-subagent-start", "SubagentStart", None),
    ]
    mine = next(s for s in codex_hooks.SPECS if s.name == "codex-mcp-call")
    assert (mine.event, mine.matcher) == ("PreToolUse", r"^mcp__local[-_]delegate__")
    # `codex-tool-guard` (#670) is also a `PreToolUse` group: pick ours by name, the last one.
    pre_tool_use = codex_hooks.entries(PYTHON, "win32")["PreToolUse"]
    group = pre_tool_use[-1]
    assert codex_hooks.our_name(group) == "codex-mcp-call"
    assert group["matcher"] == mine.matcher
    [only] = group["hooks"]
    assert set(only) == {"type", "command", "timeout"} and only["timeout"] == 30
    assert codex_hooks.our_name(group) == "codex-mcp-call"
    assert codex_plugin.check_hooks_file({"hooks": codex_hooks.entries(PYTHON, "win32")}) == []


def test_merge_puts_the_new_hook_behind_a_users_pre_tool_use_group(tmp_path):
    """A user's `PreToolUse/Bash` group keeps index 0 (and its approval key); ours go behind it
    (`codex-tool-guard` of #670 at 1, this one at 2), and `doctor` counts its approval under the
    key of that index."""
    users = {"matcher": "Bash", "hooks": [{"type": "command", "command": "audit.sh"}]}
    data, changed = codex_hooks.merge({"hooks": {"PreToolUse": [users]}}, PYTHON, "win32")
    assert data["hooks"]["PreToolUse"][0] == users
    assert codex_hooks.our_name(data["hooks"]["PreToolUse"][2]) == "codex-mcp-call"
    assert "codex-mcp-call" in changed
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    path = codex_dir / codex_hooks.HOOKS_FILE_NAME
    path.write_text(json.dumps(data), encoding="utf-8")
    [found] = [
        f for f in codex_hooks.inspect(codex_dir, tmp_path).found if f.name == "codex-mcp-call"
    ]
    key = codex_hooks.hook_key(path, found.event, found.group_index)
    assert key.endswith(":pre_tool_use:2:0")
    (codex_dir / "config.toml").write_text(
        f'[hooks.state."{key}"]\ntrusted_hash = "sha256:aa"\n'.replace("\\", "\\\\"), "utf-8"
    )
    assert codex_hooks.inspect(codex_dir, tmp_path).trusted == {"codex-mcp-call"}


# --- REQ-002: the matcher -----------------------------------------------------------------------
@pytest.mark.parametrize(
    "tool", ["mcp__local_delegate__local_summarize", "mcp__local-delegate__local_extract"]
)
def test_our_matcher_catches_our_tools_under_both_namespaces(tool):
    assert codex_hooks.matcher_matches(codex_hooks.MCP_MATCHER, (tool,))


@pytest.mark.parametrize(
    "names",
    [
        ("Bash",),
        ("apply_patch", "Write", "Edit"),
        ("mcp__memory__create_entities",),
        ("mcp__local_delegatex__t",),
        ("xmcp__local_delegate__t",),
    ],
)
def test_our_matcher_leaves_other_tools_alone(names):
    assert not codex_hooks.matcher_matches(codex_hooks.MCP_MATCHER, names)


def test_the_matcher_controls_discriminate():
    """Without `^` it would catch a foreign tool; as a literal it is an exact match on nothing."""
    assert codex_hooks.matcher_matches(r"mcp__local[-_]delegate__", ("xmcp__local_delegate__t",))
    assert not codex_hooks.matcher_matches(
        "mcp__local_delegate__", ("mcp__local_delegate__local_summarize",)
    )


@pytest.mark.parametrize(
    ("matcher", "names", "expected"),
    [
        (None, ("Bash",), True),
        ("", ("Bash",), True),
        ("*", ("anything",), True),
        ("Bash|Write", ("apply_patch", "Write"), True),
        ("Bash|Write", ("Bashful",), False),
        ("Ba.h", ("Bash",), True),
    ],
)
def test_the_matcher_follows_the_rules_of_codex(matcher, names, expected):
    assert codex_hooks.matcher_matches(matcher, names) is expected


# --- REQ-003: the payloads and the note ---------------------------------------------------------
@pytest.mark.parametrize("fixture", OURS + NOT_OURS)
def test_the_pre_tool_use_fixtures_meet_the_official_schema(fixture):
    schema = _fixture("pre-tool-use.command.input.schema")
    jsonschema.validate(_fixture(fixture), schema)


def test_the_code_mode_fixture_has_the_id_shape_of_code_mode():
    call_id = _fixture("pre_tool_use_code_mode")["tool_use_id"]
    prefix, _, rest = call_id.partition("-")
    assert prefix == "exec"
    import uuid

    assert uuid.UUID(rest).version == 4


@pytest.mark.parametrize("fixture", OURS)
def test_the_hook_notes_our_calls_with_only_the_allowed_fields(tmp_path, fixture):
    env = _sandbox(tmp_path)
    payload = _fixture(fixture)
    result = _hook("codex-mcp-call", json.dumps(payload).encode(), env)
    assert result.returncode == 0
    assert result.stdout == b""
    note_path = _notes_of(env) / f"codex-{payload['tool_use_id']}.json"
    note = json.loads(note_path.read_text(encoding="utf-8"))
    assert set(note) == {
        "tool_use_id",
        "ts",
        "client",
        "model",
        "agent_id",
        "agent_type",
        "session_key",
    }
    assert note["client"] == "codex" and note["model"] == MODEL
    assert note["session_key"] == _key(payload["session_id"])
    assert note["agent_id"] == payload.get("agent_id")
    raw = note_path.read_text(encoding="utf-8")
    for secret in (payload["session_id"], payload["cwd"], json.dumps(payload["tool_input"])):
        assert secret not in raw


@pytest.mark.parametrize("fixture", NOT_OURS)
def test_the_hook_leaves_no_note_for_other_tools(tmp_path, fixture):
    """Codex would not dispatch it (matcher); if a hand-widened matcher did, still no note."""
    env = _sandbox(tmp_path)
    result = _hook("codex-mcp-call", json.dumps(_fixture(fixture)).encode(), env)
    assert result.returncode == 0 and result.stdout == b""
    notes = _notes_of(env)
    assert not notes.exists() or not any(notes.iterdir())


@pytest.mark.parametrize("call_id", [None, "", "../escape", "a/b", "x" * 129, "id\n"], ids=repr)
def test_a_bad_call_id_leaves_no_note(tmp_path, call_id):
    payload = _fixture("pre_tool_use_mcp")
    if call_id is None:
        del payload["tool_use_id"]
    else:
        payload["tool_use_id"] = call_id
    assert hook_common.record_codex_call(payload, tmp_path / "notes") is False
    assert not (tmp_path / "notes").exists()
    assert not (tmp_path / "escape.json").exists()


def test_the_longest_valid_call_id_is_noted(tmp_path):
    """Control of the case above: 128 characters pass, so the 129 one fails for its length."""
    payload = {**_fixture("pre_tool_use_mcp"), "tool_use_id": "x" * 128}
    assert hook_common.record_codex_call(payload, tmp_path / "notes") is True


def test_a_model_of_a_strange_shape_is_dropped(tmp_path):
    payload = {**_fixture("pre_tool_use_mcp"), "model": "gpt 5\n<script>"}
    assert hook_common.record_codex_call(payload, tmp_path)
    note = json.loads((tmp_path / "codex-call_mcp_0001.json").read_text(encoding="utf-8"))
    assert note["model"] is None


@pytest.mark.parametrize(
    ("field", "value"), [("agent_type", "x" * 65), ("agent_type", "a\nb"), ("agent_id", "../a")]
)
def test_an_agent_field_of_a_strange_shape_is_dropped(tmp_path, field, value):
    payload = {**_fixture("pre_tool_use_mcp_subagent"), field: value}
    assert hook_common.record_codex_call(payload, tmp_path)
    note = json.loads((tmp_path / "codex-call_mcp_0002.json").read_text(encoding="utf-8"))
    assert note[field] is None


def test_the_agent_fields_of_the_fixture_are_kept(tmp_path):
    """Control of the case above: the real shapes pass."""
    payload = _fixture("pre_tool_use_mcp_subagent")
    assert hook_common.record_codex_call(payload, tmp_path)
    note = json.loads((tmp_path / "codex-call_mcp_0002.json").read_text(encoding="utf-8"))
    assert (note["agent_id"], note["agent_type"]) == (payload["agent_id"], payload["agent_type"])


@pytest.mark.parametrize("stdin", [b"", b"not json", b"[1, 2]", b"\xff\xfe"])
def test_broken_input_exits_zero_without_a_note(tmp_path, stdin):
    env = _sandbox(tmp_path)
    result = _hook("codex-mcp-call", stdin, env)
    assert result.returncode == 0 and result.stdout == b""
    notes = _notes_of(env)
    assert not notes.exists() or not any(notes.iterdir())


def test_the_hook_notes_even_with_the_switch_off_and_the_backend_down(tmp_path):
    """Observation, like `record_call.py`: the advice switches do not apply."""
    env = {**_sandbox(tmp_path), "LD_HOOK_ENABLED": "0"}
    payload = _fixture("pre_tool_use_mcp")
    assert _hook("codex-mcp-call", json.dumps(payload).encode(), env).returncode == 0
    assert (_notes_of(env) / "codex-call_mcp_0001.json").is_file()


# --- REQ-004: the middleware --------------------------------------------------------------------
async def _call_as(client_name: str, metas: list[dict], in_tool) -> list:
    """A server with the middleware and one call per `_meta`, from a client of that name."""
    mcp_server = MCPServer("prueba", version="0.0.0", middleware=[clients.observe_client])
    seen: list = []

    @mcp_server.tool()
    def delegates() -> str:
        """A SYNC tool, like the real ones."""
        seen.append(in_tool())
        return "ok"

    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = mcp_server._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            info = Implementation(name=client_name, version="0.169.0")
            async with ClientSession(cr, cw, client_info=info) as client:
                await client.initialize()
                for meta in metas:
                    await client.call_tool("delegates", {}, meta=meta)
            tg.cancel_scope.cancel()
    return seen


def _ids() -> tuple:
    return clients.current_tool_use_id(), clients.current_codex_session_key()


BOTH_META = {"callId": "call_mcp_0001", "sessionId": SESSION, clients.TOOL_USE_ID_KEY: "toolu_z"}


def test_codex_gives_its_call_id_and_its_session_key():
    seen = anyio.run(_call_as, CODEX, [BOTH_META], _ids)
    assert seen == [("call_mcp_0001", _key(SESSION))]


def test_claude_code_never_gives_the_codex_keys():
    """Control: the same `_meta` from Claude Code gives only its own id, as before."""
    seen = anyio.run(_call_as, "claude-code", [BOTH_META], _ids)
    assert seen == [("toolu_z", None)]


def test_codex_with_a_bad_call_id_or_no_meta_gives_none():
    metas = [{"callId": "../x", "sessionId": SESSION}, {}, {clients.TOOL_USE_ID_KEY: "toolu_z"}]
    seen = anyio.run(_call_as, CODEX, metas, _ids)
    # The last: Codex never falls back to the Claude key.
    assert seen == [(None, _key(SESSION)), (None, None), (None, None)]


# --- REQ-005: the log line ----------------------------------------------------------------------
@pytest.fixture
def log_and_notes(tmp_path, monkeypatch):
    log = tmp_path / "usage.jsonl"
    notes = tmp_path / "notes"
    monkeypatch.setenv("LOCAL_DELEGATE_LOG", str(log))
    monkeypatch.setattr(server, "_current_log_path", lambda: log)
    monkeypatch.setattr(hook_common, "call_notes_dir", lambda: notes)
    monkeypatch.setattr(attribution, "_projects_root", lambda: tmp_path / "projects")
    return log, notes


def _lines(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


def _log_one() -> None:
    server._log_event(
        tool="local_summarize",
        model="m",
        source="inline",
        chars_in=10,
        chars_out=5,
        latency_ms=1,
        ok=True,
    )


def _line_of(log: Path, client: str, meta: dict) -> dict:
    anyio.run(_call_as, client, [meta], _log_one)
    [line] = _lines(log)
    return line


def test_a_codex_line_with_the_note_of_a_subagent(log_and_notes):
    log, notes = log_and_notes
    payload = _fixture("pre_tool_use_mcp_subagent")
    assert hook_common.record_codex_call(payload, notes)
    line = _line_of(log, CODEX, {"callId": payload["tool_use_id"], "sessionId": SESSION})
    assert line["client"] == CODEX
    assert line["tool_use_id"] == "call_mcp_0002"
    assert line["caller_kind"] == "subagent"
    assert line["caller_agent_type"] == "explorer"
    assert line["caller_model"] == MODEL
    assert line["caller_src"] == "codex-hook"
    assert line["caller_session_key"] == _key(SESSION)
    for absent in ("caller_effort", "caller_project", "caller_project_kind"):
        assert absent not in line
    assert SESSION not in json.dumps(line)


def test_a_codex_line_of_the_main_thread_has_no_agent_type(log_and_notes):
    log, notes = log_and_notes
    payload = _fixture("pre_tool_use_code_mode")
    assert hook_common.record_codex_call(payload, notes)
    line = _line_of(log, CODEX, {"callId": payload["tool_use_id"], "sessionId": SESSION})
    assert line["caller_kind"] == "main" and "caller_agent_type" not in line
    assert line["tool_use_id"].startswith("exec-")


def test_a_codex_line_without_the_hook_keeps_its_session(log_and_notes):
    """The hook not approved: only the id and the session, no thread made up."""
    log, _notes = log_and_notes
    line = _line_of(log, CODEX, {"callId": "call_x", "sessionId": SESSION})
    assert line["tool_use_id"] == "call_x"
    assert {k for k in line if k.startswith("caller_")} == {"caller_session_key"}


def test_a_codex_line_with_only_the_session(log_and_notes):
    """Control of the `_log_event` change: without a call id the Claude path wrote no `caller_*`."""
    log, _notes = log_and_notes
    line = _line_of(log, CODEX, {"sessionId": SESSION})
    assert "tool_use_id" not in line
    assert line["caller_session_key"] == _key(SESSION)


def test_a_stale_note_or_a_claude_note_does_not_count(log_and_notes):
    _log, notes = log_and_notes
    payload = _fixture("pre_tool_use_mcp")
    assert hook_common.record_codex_call(payload, notes)
    note_path = notes / "codex-call_mcp_0001.json"
    note = json.loads(note_path.read_text(encoding="utf-8"))
    note["ts"] = time.time() - hook_common.NOTE_TTL_S - 5
    note_path.write_text(json.dumps(note), encoding="utf-8")
    assert attribution.resolve_codex_call("call_mcp_0001", None, notes=notes) == {}
    # A note of Claude Code under the same id is never read for Codex.
    (notes / "call_mcp_0002.json").write_text(
        json.dumps({"tool_use_id": "call_mcp_0002", "ts": time.time(), "agent_id": None}),
        encoding="utf-8",
    )
    assert attribution.resolve_codex_call("call_mcp_0002", None, notes=notes) == {}
    # A Codex note under the name of one id that carries another id does not count either.
    (notes / "codex-call_mcp_0003.json").write_text(
        json.dumps({**note, "tool_use_id": "call_mcp_0004", "ts": time.time()}), encoding="utf-8"
    )
    assert attribution.resolve_codex_call("call_mcp_0003", None, notes=notes) == {}
    # A `codex-<id>.json` without `client: codex` (not written by our hook) does not count.
    (notes / "codex-call_mcp_0005.json").write_text(
        json.dumps({**note, "tool_use_id": "call_mcp_0005", "ts": time.time(), "client": None}),
        encoding="utf-8",
    )
    assert attribution.resolve_codex_call("call_mcp_0005", None, notes=notes) == {}
    # Without the meta session, the note's key is used.
    fresh = {**note, "ts": time.time()}
    note_path.write_text(json.dumps(fresh), encoding="utf-8")
    assert attribution.resolve_codex_call("call_mcp_0001", None, notes=notes)[
        "caller_session_key"
    ] == _key(payload["session_id"])


def test_claude_lines_do_not_change(log_and_notes):
    """Control: a Claude Code call without an id still writes no `caller_*`."""
    log, _notes = log_and_notes
    line = _line_of(log, "claude-code", {"callId": "call_x", "sessionId": SESSION})
    assert "tool_use_id" not in line
    assert not [k for k in line if k.startswith("caller_")]


def test_the_inflight_entry_of_codex_carries_its_session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(hook_common, "call_notes_dir", lambda: tmp_path / "notes")

    def start_and_ask():
        entry_id = server._inflight_start(
            tool="local_summarize", model="m", source="inline", chars_in=10
        )
        try:
            mine = TestClient(metrics.app).get(f"/api/inflight?session={SESSION}").json()
            other = TestClient(metrics.app).get(f"/api/inflight?session={OTHER_SESSION}").json()
            raw = (tmp_path / "inflight.json").read_text(encoding="utf-8")
        finally:
            server._inflight_end(entry_id)
        return mine["mine_count"], other["mine_count"], SESSION in raw

    [seen] = anyio.run(_call_as, CODEX, [{"callId": "call_x", "sessionId": SESSION}], start_and_ask)
    assert seen == (1, 0, False)


# --- REQ-006: out of the backfill ---------------------------------------------------------------
def _index_with_a_claude_call(ts: datetime) -> transcripts.Index:
    index = transcripts.Index()
    index.delegations["toolu_claude"] = transcripts.Delegation(
        tool="local_summarize",
        ts_use=ts,
        thread="t",
        kind="main",
        model="claude-opus-5-5",
        effort=None,
        path=None,
        bench=False,
        mid=None,
        ts_res=ts + timedelta(seconds=1),
    )
    index.threads["t"] = transcripts.Thread(kind="main")
    return index


@pytest.mark.parametrize(("client", "crossed"), [(CODEX, False), ("claude-code", True)])
def test_a_codex_row_is_never_crossed_with_a_claude_transcript(client, crossed):
    ts = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    index = _index_with_a_claude_call(ts)
    row = {"ts": ts.isoformat(), "tool": "local_summarize", "client": client}
    entries = transcripts.match_lines([("k", row)], index, since=ts - timedelta(days=1))
    if crossed:
        assert entries["k"]["match"] == "window", "control: the same row of Claude is crossed"
    else:
        assert entries == {}


def test_merge_row_takes_no_backfill_entry_for_codex():
    entry = {"caller_model": "claude-opus-5-5", "caller_kind": "main", "match": "window"}
    codex_row = {"ts": "2026-11-16T12:00:00+00:00", "tool": "local_summarize", "client": CODEX}
    claude_row = {**codex_row, "client": "claude-code"}
    assert cost.merge_row(codex_row, entry)["caller_origin"] != "backfill"
    assert "match" not in cost.merge_row(codex_row, entry)
    assert cost.merge_row(claude_row, entry)["caller_origin"] == "backfill", "control"


def test_the_receipt_of_a_codex_call_does_not_take_its_model(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    monkeypatch.setattr(hook_common, "call_notes_dir", lambda: notes)
    assert hook_common.record_codex_call(_fixture("pre_tool_use_mcp"), notes)

    def receipt():
        return cost.in_flight_row(tool="local_summarize", source="inline")

    [codex] = anyio.run(
        _call_as, CODEX, [{"callId": "call_mcp_0001", "sessionId": SESSION}], receipt
    )
    [plain] = anyio.run(_call_as, CODEX, [{}], receipt)
    assert codex == plain
    assert codex["caller_model"] != MODEL


# --- REQ-007: out of the cost -------------------------------------------------------------------
def test_a_fully_attributed_codex_row_is_excluded_from_the_cost():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    row = {
        "ts": now.isoformat(),
        "tool": "local_summarize",
        "source": "path",
        "chars_in": 4000,
        "chars_out": 100,
        "ok": True,
        "client": CODEX,
        "tool_use_id": "call_mcp_0001",
        "caller_kind": "main",
        "caller_model": MODEL,
        "caller_src": "codex-hook",
        "caller_session_key": _key(SESSION),
    }
    merged = cost.merge_row(row)
    assert cost.segment(merged, now=now, cleanup_days=30) == "excluded"
    block = valuation.cost_block([merged], None, now=now, language="es")
    assert block["bar"]["excluded_by_reason"] == {"not_claude": 1}


# --- REQ-008 and REQ-009: the panel and the summary per session ---------------------------------
def test_caller_column_gives_codex_before_the_mod():
    assert (
        attribution.caller_column(
            {"client": CODEX, "caller_kind": "main", "caller_src": "codex-hook"}
        )
        == "codex"
    )
    assert attribution.caller_column({"client": CODEX, "tool_use_id": "toolu_plugin_x"}) == "codex"
    assert attribution.caller_column({"client": CODEX}) == "codex"
    claude = {"client": "claude-code", "caller_kind": "main", "caller_src": "hook"}
    assert attribution.caller_column(claude) == "main", "control"


@pytest.fixture
def usage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    base = {"tool": "local_summarize", "model": "m", "source": "path", "chars_out": 10, "ok": True}
    rows = [
        {
            **base,
            "ts": "2026-07-20T10:00:00+00:00",
            "chars_in": 4000,
            "client": "claude-code",
            "caller_kind": "main",
            "caller_src": "hook",
            "caller_session_key": _key("claude-s"),
        },
        {
            **base,
            "ts": "2026-07-20T11:00:00+00:00",
            "chars_in": 3000,
            "client": CODEX,
            "tool_use_id": "call_a",
            "caller_kind": "subagent",
            "caller_src": "codex-hook",
            "caller_model": MODEL,
            "caller_session_key": _key(SESSION),
        },
        {
            **base,
            "ts": "2026-07-20T12:00:00+00:00",
            "chars_in": 2000,
            "client": CODEX,
            "tool_use_id": "call_b",
            "caller_session_key": _key(SESSION),
        },
        {**base, "ts": "2026-07-20T13:00:00+00:00", "chars_in": 1000, "client": CODEX},
    ]
    (tmp_path / "usage-202607.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    metrics._FILE_CACHE.clear()
    return tmp_path


def _stats(query: str = "") -> dict:
    response = TestClient(metrics.app).get(
        "/api/stats?from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00" + query
    )
    assert response.status_code == 200, response.text
    return response.json()


COLUMNS = ("main_calls", "subagent_calls", "mod_calls", "codex_calls", "unknown_caller_calls")


def test_stats_have_a_codex_column_that_adds_up(usage_dir):
    data = _stats()
    total = data["total"]
    assert total["codex_calls"] == 3 and total["main_calls"] == 1
    assert total["subagent_calls"] == 0, "the Codex subagent is not a Claude subagent"
    assert sum(total[c] for c in COLUMNS) == total["calls"] == 4
    by_client = {c["client"]: c for c in data["by_client"]}
    assert by_client[CODEX]["codex_calls"] == 3
    assert by_client["claude-code"]["codex_calls"] == 0
    for row in data["by_client"]:
        assert sum(row[c] for c in COLUMNS) == row["calls"]


def test_the_summary_of_a_codex_session(usage_dir):
    mine = _stats(f"&session={SESSION}")["total"]
    assert mine["calls"] == mine["codex_calls"] == 2
    assert _stats(f"&session={OTHER_SESSION}")["total"]["calls"] == 0


def test_the_card_shows_the_codex_column_only_when_there_is_one():
    source = Path(metrics.__file__).read_text(encoding="utf-8")
    assert "const showCodex = rows.some(c => (c.codex_calls||0) > 0);" in source
    assert "showCodex ? '<th>' + T('clients.col.codex')" in source
    assert "showCodex ? callerCell(c.codex_calls||0)" in source
    for lang in ("es", "en"):
        catalog = json.loads(
            (Path(i18n.__file__).parent / "resources" / "i18n" / lang / "panel.json").read_text(
                encoding="utf-8"
            )
        )
        assert catalog["panel.clients.col.codex"] == "Codex"


# --- REQ-010: the adoption meter ----------------------------------------------------------------
def test_measure_adoption_counts_codex_in_its_own_column():
    spec = importlib.util.spec_from_file_location(
        "measure_adoption_codex", ROOT / "scripts" / "measure_adoption.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_adoption_codex"] = module
    spec.loader.exec_module(module)
    assert "codex" in module.CALLER_COLUMNS
    for lang in ("es", "en"):
        text = i18n.t_lang(
            lang,
            "cli.script.measure_adoption.by_thread",
            main=1,
            subagent=2,
            mod=3,
            codex=4,
            unknown=5,
        )
        assert "Codex 4" in text
