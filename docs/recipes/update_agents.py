"""update_agents.py — propaga tools de local-delegate al frontmatter `tools:` y mantiene
un bloque de catálogo en prosa en tus subagentes de `~/.claude/agents`.

RECIPE (integración personal de Claude Code) — NO forma parte del paquete publicable.
Es un ejemplo de cómo mantener sincronizados tus subagentes con las tools que expone
local-delegate. Adáptalo a tu setup.

Idempotente, y solo toca agentes que YA delegan (su línea `tools:` del frontmatter
contiene `mcp__local-delegate__local_delegate`):

- `tools:` — agrega las tools de NEW_TOOLS que falten. No reordena ni toca lo demás.
- Bloque de catálogo delimitado por `<!-- local-delegate:catalog:begin -->` …
  `<!-- local-delegate:catalog:end -->`: si los marcadores ya existen, reemplaza su
  contenido; si no, los inserta justo antes del siguiente encabezado `##`/`###` que
  sigue a la sección de delegación existente (heurística: la primera línea que matchea
  "Delegación a modelos locales"), o al final del archivo si no hay encabezado
  posterior. Si no se reconoce una sección de delegación, no inserta nada (no adivina).

Uso:   python update_agents.py          (aplica)
       python update_agents.py --dry    (muestra qué cambiaría, sin escribir)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AGENTS_DIR = Path.home() / ".claude" / "agents"
ANCHOR = "mcp__local-delegate__local_delegate"
NEW_TOOLS = [
    "mcp__local-delegate__local_lint_summary",
    "mcp__local-delegate__local_commit_msg",
    "mcp__local-delegate__local_translate",
    "mcp__local-delegate__local_explain_code",
    "mcp__local-delegate__local_status",
]

CATALOG_BEGIN = "<!-- local-delegate:catalog:begin -->"
CATALOG_END = "<!-- local-delegate:catalog:end -->"
CATALOG_BODY = """**Catálogo de tools `local_*` (MCP `local-delegate`, 10 tools):** `local_summarize`
(resumir), `local_classify` (etiquetar), `local_extract` (JSON), `local_boilerplate`
(código), `local_delegate` (genérica), `local_lint_summary` (resumir lint/tests/CI),
`local_commit_msg` (mensaje de commit desde un diff), `local_translate` (traducir),
`local_explain_code` (explicar código), `local_status` (diagnóstico del backend).

Regla de oro: si el paso cabe en una frase con formato de salida explícito, delégalo; si
necesita criterio, arquitectura o razonamiento, hazlo tú. Detalle en la skill
`delegacion-local`."""
CATALOG_BLOCK = f"{CATALOG_BEGIN}\n{CATALOG_BODY}\n{CATALOG_END}\n"

_DELEGACION_HEADING_RE = re.compile(r"^#{1,3}\s*Delegaci[oó]n a modelos locales", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,3}\s")
_CATALOG_BLOCK_RE = re.compile(
    re.escape(CATALOG_BEGIN) + r".*?" + re.escape(CATALOG_END), re.DOTALL
)


def _is_delegator(text: str) -> bool:
    for line in text.splitlines()[:60]:  # el frontmatter está al inicio
        if line.lstrip().startswith("tools:") and ANCHOR in line:
            return True
    return False


def _update_tools_line(text: str) -> tuple[str, list[str]]:
    """Devuelve (texto_nuevo, tools_agregadas). Solo edita la línea `tools:` del frontmatter."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines[:60]):
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


def _update_catalog_block(text: str) -> tuple[str, str | None]:
    """Devuelve (texto_nuevo, accion) con accion en {"replaced", "inserted", None}."""
    if CATALOG_BEGIN in text:
        new_text = _CATALOG_BLOCK_RE.sub(CATALOG_BLOCK.rstrip("\n"), text, count=1)
        return (new_text, "replaced") if new_text != text else (text, None)

    lines = text.splitlines(keepends=True)
    insert_at = None
    seen_delegacion = False
    for i, line in enumerate(lines):
        if _DELEGACION_HEADING_RE.match(line):
            seen_delegacion = True
            continue
        if seen_delegacion and _HEADING_RE.match(line):
            insert_at = i
            break
    if not seen_delegacion:
        return text, None  # sin sección de delegación reconocible: no adivinamos dónde insertar

    before = lines if insert_at is None else lines[:insert_at]
    after = [] if insert_at is None else lines[insert_at:]
    # colapsa blancos al final de `before` a como mucho una línea, para no acumular saltos
    while len(before) >= 2 and before[-1].strip() == "" and before[-2].strip() == "":
        before.pop()
    if before and before[-1].strip() != "":
        before.append("\n")
    block_lines = CATALOG_BLOCK.splitlines(keepends=True) + (["\n"] if after else [])
    return "".join(before + block_lines + after), "inserted"


def process(text: str) -> tuple[str, list[str], str | None]:
    if not _is_delegator(text):
        return text, [], None
    text, added = _update_tools_line(text)
    text, catalog_action = _update_catalog_block(text)
    return text, added, catalog_action


def main() -> None:
    dry = "--dry" in sys.argv
    if not AGENTS_DIR.is_dir():
        print(f"No existe {AGENTS_DIR}")
        return
    changed = 0
    for md in sorted(AGENTS_DIR.glob("*.md")):
        original = md.read_text(encoding="utf-8")
        updated, added, catalog_action = process(original)
        if added or catalog_action:
            changed += 1
            bits = []
            if added:
                bits.append(f"+{len(added)} tools")
            if catalog_action:
                bits.append(f"catálogo {catalog_action}")
            print(f"{'[dry] ' if dry else ''}{md.name}: {', '.join(bits)}")
            if not dry:
                md.write_text(updated, encoding="utf-8")
    print(f"\n{'Cambiarían' if dry else 'Actualizados'} {changed} agentes.")


if __name__ == "__main__":
    main()
