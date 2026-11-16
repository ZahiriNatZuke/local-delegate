"""Issue #669: the Codex hooks of local-delegate, from the file Codex reads to what each one prints.

The payloads of ``tests/fixtures/codex_hooks`` carry every field the input schemas of Codex CLI
0.169.0 mark as required, and the output schemas are copied from the same tag (see the README
there): what a hook prints is checked against what Codex parses, with ``jsonschema``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import jsonschema
import pytest

import local_delegate
from local_delegate import codex_hooks, codex_plugin, config, hook_entry

FIXTURES = Path(__file__).parent / "fixtures" / "codex_hooks"
SRC = Path(local_delegate.__file__).resolve().parents[1]
TIMEOUT_S = 60
PYTHON = "C:/Users/someone/AppData/Roaming/uv/tools/local-delegate-mcp/Scripts/python.exe"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _schema(name: str) -> dict:
    return _fixture(f"{name}.schema")


def _sandbox(base: Path) -> dict[str, str]:
    """A hook environment with its own temp, data and telemetry, and no variable of the package."""
    tmp = base / "tmp"
    data = base / "data"
    tmp.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
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
            "LD_HOOK_TELEMETRY_LOG": str(base / "telemetry.jsonl"),
        }
    )
    return env


# `-I` like the command Codex runs, with this tree first on `sys.path`: in a worktree the isolated
# interpreter would otherwise import the package of another checkout.
_BOOT = (
    "import sys, runpy; sys.path.insert(0, {src!r}); "
    "runpy.run_module('local_delegate.hook', run_name='__main__', alter_sys=True)"
)


def _hook(name: str, stdin: bytes, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", "-c", _BOOT.format(src=str(SRC)), name],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
        cwd=env["TMP"],
    )


def _bytes(name: str) -> bytes:
    return json.dumps(_fixture(name), ensure_ascii=False).encode("utf-8")


# --- The fixtures are what they say ------------------------------------------------------------
@pytest.mark.parametrize(
    ("fixture", "schema"),
    [
        ("user_prompt_submit_mechanical", "user-prompt-submit.command.input"),
        ("user_prompt_submit_plain", "user-prompt-submit.command.input"),
        ("subagent_start", "subagent-start.command.input"),
    ],
)
def test_the_payload_fixtures_meet_the_official_input_schema(fixture, schema):
    jsonschema.validate(_fixture(fixture), _schema(schema))


def test_the_schema_check_can_fail():
    """Control: a payload without a required field is refused, so the test above means something."""
    broken = _fixture("subagent_start")
    del broken["agent_id"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, _schema("subagent-start.command.input"))


# --- REQ-001: the entries ------------------------------------------------------------------------
def test_entries_are_two_command_handlers_without_args():
    entries = codex_hooks.entries(PYTHON, "win32")
    assert set(entries) == {"UserPromptSubmit", "SubagentStart"}
    flat = [(event, g) for event, groups in entries.items() for g in groups]
    assert len(flat) == 2
    for event, g in flat:
        assert "matcher" not in g
        [only] = g["hooks"]
        assert set(only) == {"type", "command", "timeout"}
        assert only["type"] == "command" and only["timeout"] == 30
        assert codex_hooks.our_name(g) is not None
    names = {codex_hooks.our_name(g): event for event, g in flat}
    assert names == {"codex-prompt": "UserPromptSubmit", "codex-subagent-start": "SubagentStart"}


def test_the_hooks_file_passes_the_codex_parser_rules():
    assert codex_plugin.check_hooks_file({"hooks": codex_hooks.entries(PYTHON, "win32")}) == []


@pytest.mark.parametrize(
    ("platform", "python", "expected"),
    [
        (
            "win32",
            "C:\\Program Files\\uv tools\\python.exe",
            '"C:/Program Files/uv tools/python.exe" -I -m local_delegate.hook codex-prompt',
        ),
        (
            "linux",
            "/home/u/.local/share/uv/tools/local-delegate-mcp/bin/python",
            "/home/u/.local/share/uv/tools/local-delegate-mcp/bin/python -I -m local_delegate.hook codex-prompt",
        ),
        (
            "darwin",
            "/Users/a b/python",
            "'/Users/a b/python' -I -m local_delegate.hook codex-prompt",
        ),
    ],
)
def test_the_command_quotes_the_interpreter_for_the_shell_codex_uses(platform, python, expected):
    assert codex_hooks.command(python, "codex-prompt", platform) == expected


@pytest.mark.parametrize(
    "group",
    [
        {"hooks": [{"type": "command", "command": "echo hi"}]},
        # Ours, plus a handler of the user: the user's arrangement, left alone.
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f'"{PYTHON}" -I -m local_delegate.hook codex-prompt',
                },
                {"type": "command", "command": "echo hi"},
            ]
        },
        # `commandWindows` is what Codex runs on Windows: not our command.
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f'"{PYTHON}" -I -m local_delegate.hook codex-prompt',
                    "commandWindows": "echo other",
                }
            ]
        },
        # The other spelling Codex reads.
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f'"{PYTHON}" -I -m local_delegate.hook codex-prompt',
                    "command_windows": "echo other",
                }
            ]
        },
        {"hooks": [{"type": "prompt", "prompt": "-I -m local_delegate.hook codex-prompt"}]},
        {"hooks": []},
        # The Claude plugin delivery (`hook prompt`), not a Codex hook.
        {"hooks": [{"type": "command", "command": f'"{PYTHON}" -I -m local_delegate.hook prompt'}]},
        # A wrapper of the user's that ends like ours: something else runs in front.
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f'mywrap "{PYTHON}" -I -m local_delegate.hook codex-prompt',
                }
            ]
        },
    ],
)
def test_groups_that_are_not_ours(group):
    assert codex_hooks.our_name(group) is None


@pytest.mark.parametrize(
    ("platform", "python"),
    [
        ("win32", "C:\\Program Files\\uv tools\\python.exe"),
        ("linux", "/home/u/.local/bin/python"),
        ("darwin", "/Users/a b/python"),
    ],
)
def test_every_command_we_write_is_recognized_with_its_interpreter(platform, python):
    """Control for the list above: the same recognizer does accept what `command` writes."""
    for spec in codex_hooks.SPECS:
        written = codex_hooks.group(spec, python, platform)
        assert codex_hooks.our_name(written) == spec.name
        assert codex_hooks.python_of(written) == (
            python.replace("\\", "/") if platform == "win32" else python
        )


# --- REQ-002: what each hook prints, against the official output schema -------------------------
def test_prompt_hook_gives_codex_text_for_a_mechanical_prompt(tmp_path):
    result = _hook("codex-prompt", _bytes("user_prompt_submit_mechanical"), _sandbox(tmp_path))
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    jsonschema.validate(output, _schema("user-prompt-submit.command.output"))
    text = output["hookSpecificOutput"]["additionalContext"]
    assert "Claude" not in text and "summarize" in text


@pytest.mark.parametrize("fixture", ["user_prompt_submit_plain"])
def test_prompt_hook_is_silent_without_a_mechanical_intent(tmp_path, fixture):
    result = _hook("codex-prompt", _bytes(fixture), _sandbox(tmp_path))
    assert result.returncode == 0 and result.stdout == b""


def test_prompt_hook_is_silent_on_a_system_event(tmp_path):
    payload = {
        **_fixture("user_prompt_submit_mechanical"),
        "prompt": "<system-reminder>resume</system-reminder>",
    }
    result = _hook("codex-prompt", json.dumps(payload).encode(), _sandbox(tmp_path))
    assert result.returncode == 0 and result.stdout == b""


def test_subagent_hook_meets_the_output_schema_and_names_no_claude_tool(tmp_path):
    result = _hook("codex-subagent-start", _bytes("subagent_start"), _sandbox(tmp_path))
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    jsonschema.validate(output, _schema("subagent-start.command.output"))
    text = output["hookSpecificOutput"]["additionalContext"]
    assert "ToolSearch" not in text and "local_extract" in text


def test_the_claude_texts_would_fail_these_checks():
    """Control: the Claude texts name Claude or `ToolSearch`, so the asserts above discriminate."""
    common = hook_entry._load_hook_module("hook_common")
    for lang in ("es", "en"):
        assert "Claude" in common.hook_text("prompt.mechanical", lang=lang, category="summarize")
        assert "ToolSearch" in common.hook_text("subagent.start", lang=lang)
        assert "Claude" not in common.hook_text("codex.prompt.mechanical", lang=lang, category="x")
        assert "ToolSearch" not in common.hook_text("codex.subagent.start", lang=lang)


# --- REQ-003: fail open --------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(codex_hooks.NAMES))
@pytest.mark.parametrize("stdin", [b"", b"no json", b"[1, 2]", b"\xff\xfe"])
def test_broken_input_exits_zero_and_silent(tmp_path, name, stdin):
    result = _hook(name, stdin, _sandbox(tmp_path))
    assert result.returncode == 0 and result.stdout == b""


@pytest.mark.parametrize(
    ("name", "fixture"),
    [("codex-prompt", "user_prompt_submit_mechanical"), ("codex-subagent-start", "subagent_start")],
)
def test_experiment_switch_off_silences_them(tmp_path, name, fixture):
    env = {**_sandbox(tmp_path), "LD_HOOK_ENABLED": "0"}
    result = _hook(name, _bytes(fixture), env)
    assert result.returncode == 0 and result.stdout == b""


@pytest.mark.parametrize(
    ("name", "fixture"),
    [("codex-prompt", "user_prompt_submit_mechanical"), ("codex-subagent-start", "subagent_start")],
)
def test_backend_down_gives_no_advice(tmp_path, name, fixture):
    env = _sandbox(tmp_path)
    common = hook_entry._load_hook_module("hook_common")
    breaker = Path(env["LOCAL_DELEGATE_LOG_DIR"]) / common.BACKEND_BREAKER_FILE
    breaker.write_text(json.dumps({"127.0.0.1:1": {"until": time.time() + 600}}), "utf-8")
    assert common.backend_down(env), "the backend-down cut did not open: the test proves nothing"
    result = _hook(name, _bytes(fixture), env)
    assert result.returncode == 0 and result.stdout == b""


@pytest.mark.parametrize("failure", ["raise RuntimeError('boom')", "raise SystemExit(2)"])
def test_a_failing_codex_handler_exits_zero_and_logs_only_the_type(tmp_path, failure):
    env = _sandbox(tmp_path)
    boot = (
        f"import sys; sys.path.insert(0, {str(SRC)!r}); "
        "from local_delegate import codex_hooks\n"
        f"def broken(name):\n    {failure}\n"
        "codex_hooks.run = broken\n"
        "from local_delegate.hook import run_hook; run_hook(['codex-prompt'])"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", boot],
        input=_bytes("user_prompt_submit_mechanical"),
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
    )
    assert result.returncode == 0 and result.stdout == b""
    lines = (Path(env["LOCAL_DELEGATE_LOG_DIR"]) / hook_entry.FAILURE_LOG).read_text("utf-8")
    [line] = [json.loads(x) for x in lines.splitlines() if x]
    assert line["hook"] == "codex-prompt"
    assert set(line) == {"ts", "hook", "error"}
    assert line["error"] == ("RuntimeError" if "RuntimeError" in failure else "SystemExit")


def _isolated_imports_this_tree() -> bool:
    probe = subprocess.run(
        [sys.executable, "-I", "-c", "import local_delegate; print(local_delegate.__file__)"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
    )
    return probe.returncode == 0 and Path(probe.stdout.strip()).resolve().parents[1] == SRC


def _as_codex_runs_it(command_line: str, stdin: bytes, env: dict[str, str]):
    """`cmd.exe /C "<command>"` on Windows (`command_runner.rs`, `build_command`), `sh -lc` else."""
    if sys.platform == "win32":
        shell = env.get("COMSPEC") or "cmd.exe"
        line = f'"{shell}" /C "{command_line}"'
        return subprocess.run(line, input=stdin, capture_output=True, env=env, timeout=TIMEOUT_S)
    return subprocess.run(
        ["/bin/sh", "-lc", command_line],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
    )


def test_the_generated_command_runs_through_the_codex_shell(tmp_path):
    if not _isolated_imports_this_tree():
        # In CI the tree is installed, so this must run there: a skip would hide REQ-003.
        assert not os.environ.get("CI"), "in CI the isolated interpreter must import this tree"
        pytest.skip("the isolated interpreter imports another checkout of local_delegate")
    env = _sandbox(tmp_path)
    line = codex_hooks.command(sys.executable, "codex-subagent-start")
    result = _as_codex_runs_it(line, _bytes("subagent_start"), env)
    assert result.returncode == 0, result.stderr
    jsonschema.validate(json.loads(result.stdout), _schema("subagent-start.command.output"))


@pytest.mark.parametrize("folder_exists", [False, True], ids=["no-folder", "folder-no-exe"])
def test_a_missing_interpreter_fails_without_exit_code_2(tmp_path, folder_exists):
    """Code 2 would block every prompt in Codex; on Windows 2 is also «file not found»."""
    env = _sandbox(tmp_path)
    folder = tmp_path / "uv tools" / "Scripts"
    if folder_exists:
        folder.mkdir(parents=True)
    line = codex_hooks.command(str(folder / "python.exe"), "codex-prompt")
    result = _as_codex_runs_it(line, _bytes("user_prompt_submit_mechanical"), env)
    assert result.returncode not in (0, 2)


# --- REQ-004: no hook telemetry, only the dispatch marker ----------------------------------------
@pytest.mark.parametrize(
    ("name", "fixture"),
    [("codex-prompt", "user_prompt_submit_mechanical"), ("codex-subagent-start", "subagent_start")],
)
def test_no_telemetry_and_a_bare_dispatch_marker(tmp_path, name, fixture):
    env = _sandbox(tmp_path)
    assert _hook(name, _bytes(fixture), env).returncode == 0
    assert not (tmp_path / "telemetry.jsonl").exists()
    seen = json.loads(
        (Path(env["LOCAL_DELEGATE_LOG_DIR"]) / codex_hooks.SEEN_FILE_NAME).read_text()
    )
    assert set(seen) == {name}
    assert isinstance(seen[name], str) and seen[name].endswith("+00:00")


def test_the_claude_prompt_hook_does_write_telemetry(tmp_path):
    """Control: the same sandbox records the Claude hook, so the absence above is real."""
    env = _sandbox(tmp_path)
    payload = json.dumps({"session_id": "s", "prompt": "Resume este informe"}).encode()
    assert _hook("prompt", payload, env).returncode == 0
    assert (tmp_path / "telemetry.jsonl").exists()
