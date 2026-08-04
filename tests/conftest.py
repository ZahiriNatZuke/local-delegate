"""Aislamiento global de artefactos runtime durante la suite."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from local_delegate import config, install


@pytest.fixture(scope="session", autouse=True)
def entorno_sin_variables_del_paquete():
    """Corre la suite como si NINGUNA variable del paquete estuviera definida.

    La suite tiene que dar el mismo resultado en la máquina de quien la escribe, en la de quien
    tiene el daemon instalado y en CI. Antes no lo daba: con `LOCAL_DELEGATE_WEB_TOKEN` puesta
    —lo normal en cualquier máquina con el daemon andando— cuatro tests del daemon esperaban 200
    y recibían 401, y el fallo parecía del cambio que estuvieras haciendo. En CI nunca se veía,
    porque allí esa variable no existe.

    Se recarga el módulo en vez de reasignar constantes una por una a propósito: los defaults
    viven en `config.py` y copiarlos aquí crearía una segunda fuente que se desactualiza sola.
    La lista de nombres tampoco se escribe a mano — `config.VARIABLES_DE_ENTORNO` se alimenta de
    las lecturas reales del módulo, así que una opción nueva queda cubierta sin tocar esto.
    """
    with pytest.MonkeyPatch.context() as mp:
        for nombre in config.VARIABLES_DE_ENTORNO:
            mp.delenv(nombre, raising=False)
        importlib.reload(config)
        yield
    importlib.reload(config)  # deja el proceso como estaba para lo que venga después


@pytest.fixture(autouse=True)
def isolate_runtime_logs(tmp_path, monkeypatch):
    """Evita que mocks de tests contaminen los logs reales del usuario."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")


# --- HOME simulado, compartido por test_checks.py y test_doctor.py ------------
def make_home(tmp_path: Path, *, claude=True, codex=True, opencode=True, complete=True) -> Path:
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
    if opencode:
        # `opencode_dir` y no `home / ".config" / "opencode"`: la ruta la decide `install`, y un
        # HOME de prueba que la calculara por su cuenta dejaría de probar lo que hace el paquete.
        oc_dir = install.opencode_dir(home)
        oc_dir.mkdir(parents=True)
        if complete:
            (oc_dir / "AGENTS.md").write_text(
                install.upsert_block("", memory_block, install.MD_BEGIN, install.MD_END),
                encoding="utf-8",
            )
            oc_skill = oc_dir / install.OPENCODE_SKILL_SUBDIR / install.SKILL_NAME
            oc_skill.mkdir(parents=True)
            (oc_skill / "SKILL.md").write_text("# skill\n", encoding="utf-8")
            entry = install.opencode_mcp_entry("http", None, False, None)
            (oc_dir / "opencode.json").write_text(
                json.dumps(
                    {"$schema": install.OPENCODE_SCHEMA, "mcp": {install.SERVER_NAME: entry}}
                ),
                encoding="utf-8",
            )
    return home


def snapshot(root: Path) -> dict[str, bytes | None]:
    """Árbol completo con el contenido de cada fichero: la prueba de que nadie escribió."""
    return {
        str(path.relative_to(root)): (path.read_bytes() if path.is_file() else None)
        for path in sorted(root.rglob("*"))
    }
