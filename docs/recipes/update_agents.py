"""update_agents.py — propaga tools de local-delegate al frontmatter `tools:` de tus subagentes.

RECIPE (integración personal de Claude Code) — NO forma parte del paquete publicable.
Es un ejemplo de cómo mantener sincronizados tus subagentes de `~/.claude/agents` con las
tools que expone local-delegate. Adáptalo a tu setup.

Idempotente: solo modifica agentes que YA delegan (su línea `tools:` contiene
`mcp__local-delegate__local_delegate`) y a los que aún les falten tools de NEW_TOOLS. No toca
agentes sin delegación ni reordena; solo agrega las tools que falten tras `local_delegate`.

Uso:   python update_agents.py          (aplica)
       python update_agents.py --dry    (muestra qué cambiaría, sin escribir)
"""

from __future__ import annotations

import sys
from pathlib import Path

AGENTS_DIR = Path.home() / ".claude" / "agents"
ANCHOR = "mcp__local-delegate__local_delegate"
NEW_TOOLS = [
    "mcp__local-delegate__local_lint_summary",
    "mcp__local-delegate__local_commit_msg",
    "mcp__local-delegate__local_translate",
    "mcp__local-delegate__local_explain_code",
]


def process(text: str) -> tuple[str, list[str]]:
    """Devuelve (texto_nuevo, tools_agregadas). Solo edita la línea `tools:` del frontmatter."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines[:60]):  # el frontmatter está al inicio
        stripped = line.lstrip()
        if not stripped.startswith("tools:") or ANCHOR not in line:
            continue
        missing = [t for t in NEW_TOOLS if t not in line]
        if not missing:
            return text, []
        newline_char = "\n" if line.endswith("\n") else ""
        body = line[: len(line) - len(newline_char)] if newline_char else line
        body = body + ", " + ", ".join(missing)
        lines[i] = body + newline_char
        return "".join(lines), missing
    return text, []


def main() -> None:
    dry = "--dry" in sys.argv
    if not AGENTS_DIR.is_dir():
        print(f"No existe {AGENTS_DIR}")
        return
    changed = 0
    for md in sorted(AGENTS_DIR.glob("*.md")):
        original = md.read_text(encoding="utf-8")
        updated, added = process(original)
        if added:
            changed += 1
            print(f"{'[dry] ' if dry else ''}{md.name}: +{len(added)} tools")
            if not dry:
                md.write_text(updated, encoding="utf-8")
    print(f"\n{'Cambiarían' if dry else 'Actualizados'} {changed} agentes.")


if __name__ == "__main__":
    main()
