"""`uninstall` undoes what `install --agents` wrote in the subagents, and nothing else.

REQ-011 (SDD claude-plugin-and-mods, F1-install). Until 0.39 `uninstall` left the tools and the
catalog block that `--agents` had added.
"""

from __future__ import annotations

from conftest import FakeClaude, make_home

from local_delegate import agents, claude_plugin, install, install_state

LD_BIN = "C:/uv/tools/local-delegate-mcp/Scripts/python.exe"

AGENT = (
    "---\n"
    "name: worker\n"
    f"tools: Read, Grep, {agents.ANCHOR}\n"
    "---\n"
    "\n"
    "# Worker\n"
    "\n"
    "## Delegación a modelos locales\n"
    "\n"
    "Usa las tools locales.\n"
    "\n"
    "## Otra sección\n"
    "\n"
    "Texto del usuario.\n"
)
FOREIGN_AGENT = "---\nname: other\ntools: Read\n---\n\nNo delega.\n"


def _opts(home, **kwargs):
    fake = FakeClaude(present=False)
    return install.Options(
        home=home,
        targets={"claude"},
        python_exe="python",
        use_cli=False,
        claude_runner=fake,
        claude_which=fake.which,
        claude_ld_bin=claude_plugin.LdBin(LD_BIN, None),
        **kwargs,
    )


def _run(actions) -> int:
    return install.apply(actions, dry_run=False, out=lambda _line: None)


def test_uninstall_undoes_agents_edit(tmp_path):
    home = make_home(tmp_path, codex=False, opencode=False, complete=False)
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    worker = agents_dir / "worker.md"
    other = agents_dir / "other.md"
    worker.write_bytes(AGENT.encode("utf-8"))
    other.write_bytes(FOREIGN_AGENT.encode("utf-8"))

    assert _run(install.plan_install(_opts(home, components={"agents"}))) == 0
    edited = worker.read_text(encoding="utf-8")
    assert edited != AGENT
    assert agents.CATALOG_BEGIN in edited
    assert install_state.piece(install_state.load(home), "agents") is not None

    assert _run(install.plan_uninstall(_opts(home, components={"agents"}))) == 0

    assert worker.read_text(encoding="utf-8") == AGENT
    assert other.read_text(encoding="utf-8") == FOREIGN_AGENT
    assert install_state.piece(install_state.load(home), "agents") is None


def test_user_edit_after_install_survives_uninstall(tmp_path):
    home = make_home(tmp_path, codex=False, opencode=False, complete=False)
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    worker = agents_dir / "worker.md"
    worker.write_bytes(AGENT.encode("utf-8"))
    assert _run(install.plan_install(_opts(home, components={"agents"}))) == 0
    worker.write_text(
        worker.read_text(encoding="utf-8") + "\nNota añadida después.\n", encoding="utf-8"
    )

    assert _run(install.plan_uninstall(_opts(home, components={"agents"}))) == 0

    assert worker.read_text(encoding="utf-8") == AGENT + "\nNota añadida después.\n"


def test_agents_not_in_state_are_not_touched(tmp_path):
    home = make_home(tmp_path, codex=False, opencode=False, complete=False)
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    worker = agents_dir / "worker.md"
    # Edited by an older version or by hand: there is no record that `install` wrote it.
    already = AGENT.replace(agents.ANCHOR, f"{agents.ANCHOR}, {agents.TOOL_PREFIX}local_extract")
    worker.write_bytes(already.encode("utf-8"))

    assert _run(install.plan_uninstall(_opts(home, components={"agents"}))) == 0

    assert worker.read_text(encoding="utf-8") == already
