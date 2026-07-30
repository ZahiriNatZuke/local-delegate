"""Aislamiento global de artefactos runtime durante la suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_delegate import config, install


@pytest.fixture(autouse=True)
def isolate_runtime_logs(tmp_path, monkeypatch):
    """Evita que mocks de tests contaminen los logs reales del usuario."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.delenv("LD_HOOK_TELEMETRY_LOG", raising=False)


# --- HOME simulado, compartido por test_checks.py y test_doctor.py ------------
def make_home(tmp_path: Path, *, claude=True, codex=True, complete=True) -> Path:
    """Arma un HOME de mentira. Con ``complete=False`` los clientes existen pero vacíos.

    Lo escribe con las funciones del propio ``install`` (no con literales) para que el HOME
    «completo» sea el que produce el instalador de verdad y no una idea de cómo debería ser.
    """
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    memory_block = "Regla de delegación de prueba."
    if claude:
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True)
        if complete:
            hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
            hooks_dir.mkdir(parents=True)
            for script, _event, _matcher in install._HOOK_EVENTS:
                (hooks_dir / script).write_text("# hook\n", encoding="utf-8")
            entries = [
                (event, matcher, install.hook_command(hooks_dir, script, "python"))
                for script, event, matcher in install._HOOK_EVENTS
            ]
            settings, _removed = install.merge_hook_settings({}, entries, hooks_dir)
            (claude_dir / "settings.json").write_text(
                json.dumps(settings, indent=2), encoding="utf-8"
            )
            skill_dir = claude_dir / "skills" / install.SKILL_NAME
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# skill\n", encoding="utf-8")
            (claude_dir / "CLAUDE.md").write_text(
                install.upsert_block("", memory_block, install.MD_BEGIN, install.MD_END),
                encoding="utf-8",
            )
            (home / ".claude.json").write_text(
                json.dumps({"mcpServers": {install.SERVER_NAME: {"type": "http", "url": "u"}}}),
                encoding="utf-8",
            )
    if codex:
        codex_dir = home / ".codex"
        codex_dir.mkdir(parents=True)
        if complete:
            (codex_dir / "AGENTS.md").write_text(
                install.upsert_block("", memory_block, install.MD_BEGIN, install.MD_END),
                encoding="utf-8",
            )
            block = install.codex_mcp_block({"type": "http", "url": "http://127.0.0.1:9393/mcp"})
            (codex_dir / "config.toml").write_text(
                install.upsert_codex_mcp("", block), encoding="utf-8"
            )
    return home


def snapshot(root: Path) -> dict[str, bytes | None]:
    """Árbol completo con el contenido de cada fichero: la prueba de que nadie escribió."""
    return {
        str(path.relative_to(root)): (path.read_bytes() if path.is_file() else None)
        for path in sorted(root.rglob("*"))
    }
