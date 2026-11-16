"""codex_reads.py — the read summary and the write guard of Codex (#670).

One ``PreToolUse`` hook (``codex-tool-guard``, an entry of `codex_hooks.SPECS`) ports what the
Claude Code read mod (``mod/read.js``, ``readOnToolCall``) does, through the only door Codex CLI
0.169.0 opens for it. In ``openai/codex`` at ``rust-v0.169.0`` (paths under ``codex-rs/``):

- a ``PreToolUse`` handler that prints ``permissionDecision: "deny"`` stops the tool before it
  runs (``core/src/tools/registry.rs``, ``apply_pre_tool_use``) and the model gets
  ``"Command blocked by PreToolUse hook: {reason}. Command: {command}"``
  (``core/src/hook_runtime.rs``). So a large prose read by shell is answered with its summary as
  the reason: the file is never read and its text never enters the context;
- ``PostToolUse`` cannot stand in for a shell result (``updatedMCPToolOutput`` is unsupported and
  fails open, ``hooks/src/events/post_tool_use.rs``), and by then the read has already run;
- ``additionalContext`` without a decision is kept: that is the note for a large MCP read.

What this hook does, in the mod's order: a write (``apply_patch``, a shell write) on a file this
agent only read summarized is denied; a whole read of large prose is summarized; ranges add up and
the one that takes the reads of a file to 80 % of its lines is summarized; code, config, data,
small files and short files pass literally, and a literal read lifts the guard. Anything that fails
(no backend, an empty, cut or backgrounded summary, a bug) lets the call through.

The state is per session and per agent (the main thread, or each subagent's ``agent_id``), an
append-only log of paths and line ranges in ``LOG_DIR/codex-read/<session_id>.jsonl``: no content.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

NAME = "codex-tool-guard"
EVENT = "PreToolUse"

#: What Codex matches the hook against (``hooks/src/engine/matcher.rs``: a regex, not anchored,
#: since it has characters besides ``[A-Za-z0-9_|]``): the shell, ``apply_patch`` and the MCP tools
#: whose name reads a file (the words of ``read_classifier._MCP_READ``).
MATCHER = (
    r"^(Bash|apply_patch)$"
    r"|^mcp__.+__(?i:(.*_)?(read|get_file|file_contents|get_note|convert_to_markdown|get_page"
    r"|fetch_file|cat))"
)

#: The handler's ``timeout`` in ``hooks.json``: above the summary's own plazo, so the summary is cut
#: by us (and the read passes) before Codex marks the hook as failed (which also lets it pass).
HOOK_TIMEOUT_S = 180
SUMMARY_TIMEOUT_S = 150

#: The mod's constants (``read.js``): ranges that reach this share count as reading it whole.
WHOLE_SHARE = 0.8
SHORT_LINES = 200
SHORT_BYTES = 32 * 1024

#: How the hook introduces itself to the daemon: rows of the usage log with this client are
#: Codex's, out of the Claude cost (`attribution.NON_CLAUDE_CLIENTS`).
CLIENT_NAME = "local-delegate-codex-read"
SUMMARY_TOOL = "local_summarize"
MCP_PROTOCOL_VERSION = "2025-06-18"

STATE_DIR = "codex-read"
MAIN_SCOPE = "main"
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

#: What makes a summary not one (``read.js``, ``readSummarize``, issue #631).
ERROR_PREFIX = "[local-delegate error]"
BACKGROUNDED = re.compile(
    r'^MCP tool "[^"\n]*" (?:is still running after \d+s\. It )?was moved to the background as task '
)
#: The server's warnings of a cut output or of an input not read whole (`mcp.json`, es and en).
TRUNCATION_KEYS = (
    "mcp.warning.output_truncated",
    "mcp.warning.output_trimmed",
    "mcp.warning.output_truncated_calls",
    "mcp.warning.time_budget",
    "mcp.warning.time_budget_retries",
)

_PATCH_PATH = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+?)\s*$", re.MULTILINE)
_PATCH_BEGIN = "*** Begin Patch"

Summarize = Callable[[str], "str | None"]


# --- The state ------------------------------------------------------------------------------------
@dataclass
class FileReads:
    whole: bool = False
    ranges: list[tuple[int, int | None]] = field(default_factory=list)


@dataclass
class ScopeState:
    guard: set[str] = field(default_factory=set)
    files: dict[str, FileReads] = field(default_factory=dict)

    def file(self, key: str) -> FileReads:
        return self.files.setdefault(key, FileReads())


def state_path(session_id: object, log_dir: Path) -> Path | None:
    """The session's log, or ``None`` for an id that cannot name a file (then nothing is kept)."""
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        return None
    return Path(log_dir) / STATE_DIR / f"{session_id}.jsonl"


def load_scope(path: Path, scope: str) -> ScopeState:
    """What ``scope`` did in the session, folded from the log. Unreadable lines are skipped."""
    state = ScopeState()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return state
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("scope") != scope:
            continue
        key, op = event.get("path"), event.get("op")
        if not isinstance(key, str):
            continue
        if op == "guard":
            state.guard.add(key)
            continue
        state.guard.discard(key)
        if op == "whole":
            state.file(key).whole = True
        elif op == "range":
            span = _span(event.get("range"))
            if span is not None:
                state.file(key).ranges.append(span)
    return state


def _record(common: ModuleType, path: Path, scope: str, op: str, key: str, span=None) -> None:
    """One event, appended under the file lock (several subagents may write at once)."""
    event: dict = {"scope": scope, "op": op, "path": key}
    if span is not None:
        event["range"] = list(span)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        common.append_line(path, json.dumps(event, ensure_ascii=False))
    except OSError:
        pass  # the guard is lost for this file, the read itself is not affected


def file_key(path: str) -> str:
    """A path as the state keeps it: forward slashes, and case-folded on Windows (``readNormalize``)."""
    key = path.replace("\\", "/")
    return key.lower() if sys.platform == "win32" else key


# --- Lines and coverage (``read.js``: ``readCoverage``, ``readLiteralBudget``, ``readShortFile``) --
def _span(value: object) -> tuple[int, int | None] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    start, end = value
    if isinstance(start, bool) or not isinstance(start, int):
        return None
    if end is not None and (isinstance(end, bool) or not isinstance(end, int)):
        return None
    return start, end


def coverage(ranges: Sequence[tuple[int, int | None]], total: int) -> float:
    """The share of the ``total`` lines that ``ranges`` (1-based, end ``None`` = to the end) cover."""
    if total <= 0:
        return 0.0
    spans = sorted(
        (max(1, a), min(total, total if b is None else b))
        for a, b in ranges
        if min(total, total if b is None else b) >= max(1, a)
    )
    covered = reach = 0
    for a, b in spans:
        start = max(a, reach + 1)
        if b >= start:
            covered += b - start + 1
            reach = b
    return covered / total


def literal_budget(total: int) -> int:
    """The most lines of a file that can be read literally in a session (one short of the share)."""
    if total <= 0:
        return 0
    return max(0, math.ceil(total * WHOLE_SHARE - 1e-9) - 1)


def short_file(total: int | None, size: int | None) -> bool:
    return bool(total) and total <= SHORT_LINES and isinstance(size, int) and size < SHORT_BYTES


def count_lines(path: str) -> int | None:
    """The file's line count now (its text is never shown), or ``None`` when it cannot be read."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    lines = data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)
    return max(lines, 1)


# --- Summaries ------------------------------------------------------------------------------------
def _truncation_marks() -> tuple[str, ...]:
    """The fixed start of each warning of `TRUNCATION_KEYS`, in every language of the catalog."""
    marks: list[str] = []
    folder = Path(__file__).resolve().parent / "resources" / "i18n"
    for catalog in sorted(folder.glob("*/mcp.json")):
        try:
            texts = json.loads(catalog.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in TRUNCATION_KEYS:
            text = texts.get(key) if isinstance(texts, dict) else None
            if isinstance(text, str):
                head = text.split("{", 1)[0].strip()
                if len(head) >= 12:
                    marks.append(head)
    return tuple(marks)


def valid_summary(text: object) -> bool:
    """A summary that can stand in for the file: not empty, not an error, not the notice of a call
    moved to the background, and not cut (a cut summary would hide the rest of the file)."""
    if not isinstance(text, str) or not text.strip():
        return False
    stripped = text.lstrip()
    if stripped.startswith(ERROR_PREFIX) or BACKGROUNDED.match(stripped):
        return False
    return not any(mark in text for mark in _truncation_marks())


class _McpError(Exception):
    pass


class DaemonClient:
    """A minimal MCP client of the daemon's ``/mcp`` (streamable HTTP), only for one tool call."""

    def __init__(self, url: str, token: str, timeout: float) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session: str | None = None
        self.protocol = MCP_PROTOCOL_VERSION
        # No proxy: the daemon is local, and a `HTTP_PROXY` of the session must not see the token.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        return headers

    def _send(self, body: dict, method: str = "POST") -> dict | None:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=data, method=method, headers=self._headers()
        )
        with self._opener.open(request, timeout=self.timeout) as response:
            session = response.headers.get("Mcp-Session-Id")
            if session:
                self.session = session
            if body is None or "id" not in body:
                return None
            kind = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            raw = response.read().decode("utf-8", "replace")
        return _reply(raw, kind, body["id"])

    def call(self, tool: str, arguments: dict) -> dict:
        init = self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": CLIENT_NAME, "version": _version()},
                },
            }
        )
        version = (init or {}).get("result", {}).get("protocolVersion")
        if isinstance(version, str) and version:
            self.protocol = version
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        try:
            answer = self._send(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                }
            )
        finally:
            self.close()
        if not isinstance(answer, dict) or not isinstance(answer.get("result"), dict):
            raise _McpError
        return answer["result"]

    def close(self) -> None:
        if not self.session:
            return
        try:
            self._send(None, method="DELETE")
        except (OSError, urllib.error.URLError, ValueError):
            # Closing the session is a courtesy to the daemon, which also expires it on its own:
            # the answer is already in hand, so a failed DELETE must not turn it into a failure.
            return


def _version() -> str:
    try:
        from .version import __version__

        return str(__version__)
    except Exception:
        return "0"


def _reply(raw: str, kind: str, wanted: object) -> dict | None:
    """The JSON-RPC message that answers ``wanted``, from a JSON body or an SSE stream."""
    messages: list[object] = []
    if kind == "text/event-stream":
        data: list[str] = []
        for line in [*raw.splitlines(), ""]:
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line.strip() and data:
                try:
                    messages.append(json.loads("\n".join(data)))
                except ValueError:
                    pass
                data = []
    else:
        try:
            messages.append(json.loads(raw))
        except ValueError:
            return None
    for message in messages:
        candidates = message if isinstance(message, list) else [message]
        for item in candidates:
            if isinstance(item, dict) and item.get("id") == wanted:
                return item
    return None


def result_text(result: dict) -> str | None:
    """The text of a ``tools/call`` result, or ``None`` for an error result."""
    if result.get("isError"):
        return None
    content = result.get("content")
    if not isinstance(content, list):
        return None
    texts = [
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ]
    return "\n".join(texts) if texts else None


def daemon_summarize(
    path: str,
    *,
    url: str | None = None,
    token: str | None = None,
    timeout: float = SUMMARY_TIMEOUT_S,
) -> str | None:
    """``local_summarize`` of ``path`` through the daemon, or ``None`` on any failure."""
    try:
        if url is None:
            from .desktop_bridge import daemon_url

            url = daemon_url()
        if token is None:
            from . import token_source

            token = token_source.web_token()
        result = DaemonClient(url, token, timeout).call(SUMMARY_TOOL, {"path": path})
        return result_text(result)
    except Exception:
        return None


# --- The decision ---------------------------------------------------------------------------------
def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": EVENT,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _note(text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": EVENT, "additionalContext": text}}


def _shell_tool() -> str:
    """The tool name the classifier gets for Codex's shell: empty on Windows, where Codex's shell
    is PowerShell, so its own verbs (``type``, ``gc``) count too; ``Bash`` elsewhere."""
    return "" if sys.platform == "win32" else "Bash"


_CD_VERBS = frozenset({"cd", "set-location", "pushd", "sl"})


def only_read(command: str) -> bool:
    """Whether denying ``command`` drops nothing but the read: one segment (a leading ``cd`` aside),
    with or without a pipe, no redirection, heredoc or substitution. A compound command passes."""
    from .resources.hooks import read_classifier

    if "$(" in command or "`" in command:
        return False
    stripped, _ = read_classifier.strip_heredocs(command)
    parts = read_classifier.segments(read_classifier.tokenize(stripped))
    real = [
        part
        for part in parts
        if not (part.stages and read_classifier._verb(part.stages[0])[0] in _CD_VERBS)
    ]
    return len(real) == 1 and not real[0].targets and not real[0].heredoc and not real[0].redirected


def write_targets(tool: str, tool_input: dict, cwd: str | None, environ: Mapping) -> list[str]:
    """The files a call writes, absolute: the patch's paths, or the shell's writes."""
    from .resources.hooks import read_classifier

    command = tool_input.get("command")
    if not isinstance(command, str):
        return []
    raw: list[str] = []
    if tool == "apply_patch" or _PATCH_BEGIN in command:
        raw += [m.group(1).strip() for m in _PATCH_PATH.finditer(command)]
    if tool != "apply_patch":
        raw += [
            access.path
            for access in read_classifier.accesses(_shell_tool(), tool_input)
            if access.kind == "write" and access.path
        ]
    found: list[str] = []
    for item in raw:
        resolved = read_classifier.resolve(item, cwd, environ)
        if resolved and resolved not in found:
            found.append(resolved)
    return found


@dataclass
class _Call:
    common: ModuleType
    state_file: Path
    scope: str
    state: ScopeState
    subagent: bool
    classified: dict
    key: str

    def note_real_read(self, count_range: bool = True) -> None:
        """A literal read lifts the guard and adds to the coverage (``readNoteRealRead``)."""
        span = _span(self.classified.get("range"))
        if self.classified.get("scope") == "whole":
            self.state.file(self.key).whole = True
            _record(self.common, self.state_file, self.scope, "whole", self.key)
        elif span is not None and count_range:
            self.state.file(self.key).ranges.append(span)
            _record(self.common, self.state_file, self.scope, "range", self.key, span)
        elif self.key in self.state.guard:
            _record(self.common, self.state_file, self.scope, "lift", self.key)
        self.state.guard.discard(self.key)


def decide(
    payload: dict,
    common: ModuleType,
    *,
    environ: Mapping,
    log_dir: Path,
    summarize: Summarize,
) -> dict | None:
    """What the hook prints for ``payload`` (a ``PreToolUse`` input of Codex), or ``None``."""
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    state_file = state_path(payload.get("session_id"), log_dir)
    if state_file is None:
        return None
    from .resources.hooks import read_classifier

    command = tool_input.get("command")
    agent = payload.get("agent_id")
    subagent = isinstance(agent, str) and bool(agent)
    if tool == "Bash":
        if not isinstance(command, str) or not command.strip():
            return None
        lowered = command.lower()
        if (
            not subagent
            and not state_file.exists()
            and not any(e in lowered for e in read_classifier.PROSE_EXTENSIONS)
        ):
            # The prefilter (the mod's, in JS): in the main thread, no prose named and nothing
            # guarded or counted yet in this session, so nothing to decide and the classifier is
            # not even loaded. A subagent goes on: a large code file gets the note to locate first.
            return None
    scope = f"agent:{agent}" if subagent else MAIN_SCOPE
    state = load_scope(state_file, scope)

    for target in write_targets(tool, tool_input, cwd, environ):
        if file_key(target) in state.guard:
            return _deny(common.hook_text("codex.guard.refused", path=target))
    if tool == "apply_patch":
        return None

    from . import hook_classify

    name = _shell_tool() if tool == "Bash" else tool
    request = {"tool_name": name, "tool_input": tool_input, "cwd": cwd}
    classified = json.loads(hook_classify.classify_text(request, environ))
    path = classified.get("path")
    if classified.get("kind") != "read" or classified.get("read_switch") != "on" or not path:
        return None
    size = classified.get("bytes")
    min_bytes = read_classifier.prefilter_config(environ)["min_bytes"]
    big = isinstance(size, int) and size >= min_bytes
    kb = round(size / 1024) if isinstance(size, int) else 0
    call = _Call(common, state_file, scope, state, subagent, classified, file_key(path))

    if classified.get("scope") == "unclassifiable" or tool != "Bash":
        # Not sure what enters the context, or a tool whose result this hook cannot stand in for
        # (an MCP read): a note, never a block, and the guard stays.
        if not big:
            return None
        return _note(
            common.hook_text(
                "codex.read.warn.subagent" if subagent else "codex.read.warn.large",
                path=path,
                kb=kb,
            )
        )
    if not big:
        call.note_real_read()
        return None
    if not classified.get("summarizable"):
        # Code, config, data: the literal text is what the reader needs. A subagent that reads it
        # whole gets the note to locate first (issue #443).
        call.note_real_read()
        if subagent and classified.get("scope") == "whole":
            return _note(common.hook_text("codex.read.warn.subagent", path=path, kb=kb))
        return None
    if not only_read(command):
        # Denying would drop the rest of the command too: the read passes, with the note.
        call.note_real_read()
        return _note(
            common.hook_text(
                "codex.read.warn.subagent" if subagent else "codex.read.warn.large",
                path=path,
                kb=kb,
            )
        )
    if classified.get("scope") == "whole":
        return _steer(call, path, summarize, None, None)
    if subagent:
        # A subagent reads a range to quote or edit those very lines (issue #472): literal, and
        # outside the main thread's coverage (its scope is its own).
        call.note_real_read(count_range=False)
        return None
    span = _span(classified.get("range"))
    entry = state.file(call.key)
    total = count_lines(path) if span else None
    if span is None or not total or span[0] > total or short_file(total, size):
        call.note_real_read()
        return None
    covered = coverage([*entry.ranges, span], total)
    if not entry.whole and covered >= WHOLE_SHARE:
        return _steer(call, path, summarize, (covered, total, entry), span)
    call.note_real_read()
    return None


def _steer(call: _Call, path: str, summarize: Summarize, share, span) -> dict | None:
    """The summary as the denial's reason, or ``None`` (the read passes) when there is none."""
    try:
        summary = summarize(path)
    except Exception:
        summary = None
    if not valid_summary(summary):
        call.note_real_read()
        return None
    call.state.guard.add(call.key)
    _record(call.common, call.state_file, call.scope, "guard", call.key)
    return _deny(f"{_header(call.common, path, share, span)}\n\n{summary.strip()}")


def _header(common: ModuleType, path: str, share, span) -> str:
    if share is None:
        total = count_lines(path) or 0
        return common.hook_text(
            "codex.read.summary.header_budget", path=path, lines=literal_budget(total), total=total
        )
    covered, total, entry = share
    lines = literal_budget(total)
    read = round(coverage(entry.ranges, total) * total)
    left = max(0, lines - read)
    pct = int(covered * 100 + 1e-9)
    header = common.hook_text(
        "codex.read.summary.header_ranges",
        path=path,
        pct=pct,
        total=total,
        read=read,
        left=left,
        lines=lines,
    )
    first = min(span[0], total)
    last = total if span[1] is None else max(first, min(span[1], total))
    omitted = common.hook_text(
        "codex.read.summary.range_omitted" if left > 0 else "codex.read.summary.range_omitted_none",
        first=first,
        last=last,
        left=left,
    )
    return f"{header} {omitted}"


def run(payload: dict, common: ModuleType) -> None:
    """The hook: prints its decision, if any. Raises on a bug: `hook_entry` logs it and exits 0."""
    from .read_switch import log_dir

    out = decide(payload, common, environ=os.environ, log_dir=log_dir(), summarize=daemon_summarize)
    if out is not None:
        print(json.dumps(out, ensure_ascii=False))
