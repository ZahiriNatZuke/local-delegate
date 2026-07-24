"""Tests de los hooks consultivos de Claude Code."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HOOKS = Path(__file__).parents[1] / "docs" / "recipes" / "hooks"
sys.path.insert(0, str(HOOKS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prompt = _load("suggest_delegate_prompt")


def test_prompt_hook_detects_mechanical_intent():
    assert prompt.classify("Resume este archivo en cinco viñetas") == "summarize"
    assert prompt.classify("Extrae nombre y fecha como JSON") == "extract"


def test_prompt_hook_keeps_architecture_and_research_in_host():
    assert prompt.classify("Investiga y diseña la arquitectura del sistema") is None
    assert prompt.classify("Resume el research multi-fuente y decide la migración") is None


def test_hook_telemetry_contains_no_prompt_command_or_path(tmp_path, monkeypatch):
    common = _load("hook_common")
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    common.record("PreToolUse", category="read", size_kb=40)
    text = log.read_text(encoding="utf-8")
    assert "category" in text
    assert "prompt" not in text
    assert "command" not in text
    assert "path" not in text


def test_disabled_hook_emits_nothing(tmp_path, monkeypatch, capsys):
    common = _load("hook_common")
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_ENABLED", "0")
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))

    common.emit("UserPromptSubmit", "context", category="summarize")

    assert capsys.readouterr().out == ""
    assert not log.exists()
