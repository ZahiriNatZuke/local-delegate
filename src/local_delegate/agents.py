"""agents.py — mantiene los subagentes de Claude Code al día con el catálogo de tools.

Un subagente de `~/.claude/agents/*.md` que delega en local-delegate declara nuestras tools en su
frontmatter `tools:` y suele llevar una sección explicando cuándo usarlas. Las dos cosas envejecen
cada vez que el MCP gana una tool, y actualizarlas a mano en veintitantos ficheros no se hace.

Esto vivía en `docs/recipes/update_agents.py`, con dos problemas. El primero, de sitio: una receta
en `docs/` no viaja en el paquete, así que no llegaba a ninguna máquina instalada — la misma regla
que retiró `update_to_latest.sh` («lo que ejecuta el usuario va al CLI»). El segundo, de fondo:
**su catálogo estaba escrito a mano y ya se había desincronizado** (decía «10 tools» habiendo
once).

Por eso aquí el catálogo **no se escribe: se deriva** de la tabla de la skill, que es un recurso
empaquetado y la que el usuario ya lee. Y para que esa fuente no pueda mentir a su vez, hay un
test que compara sus nombres con los que registra el servidor MCP.

Tres reglas gobiernan la escritura, y las tres existen porque estos ficheros **son del usuario**:

1. **Solo se tocan los agentes que ya declaran nuestras tools** (el ancla :data:`ANCHOR`). Un
   subagente ajeno no se lee para escribir.
2. **Si no se reconoce dónde va el bloque, no se inserta.** No se adivina.
3. **Fuera de los marcadores no se toca nada**, y cada fichero modificado deja su `.bak`.
"""

from __future__ import annotations

import re
from pathlib import Path

ANCHOR = "mcp__local-delegate__local_delegate"
TOOL_PREFIX = "mcp__local-delegate__"

CATALOG_BEGIN = "<!-- local-delegate:catalog:begin -->"
CATALOG_END = "<!-- local-delegate:catalog:end -->"

# Los mismos marcadores y el mismo ancla que usaba la receta, a propósito: los agentes que ya
# pasaron por ella se reconocen y se actualizan en vez de duplicar el bloque.
_CATALOG_BLOCK_RE = re.compile(
    re.escape(CATALOG_BEGIN) + r".*?" + re.escape(CATALOG_END), re.DOTALL
)
_DELEGATION_HEADING_RE = re.compile(r"^#{1,3}\s*Delegaci[oó]n a modelos locales", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,3}\s")
# Filas de la tabla de la skill: | `local_x` | cuándo | args | devuelve |
_CATALOG_ROW_RE = re.compile(r"^\|\s*`(local_\w+)`\s*\|\s*([^|]+?)\s*\|")

_RULE = (
    "Regla de oro: si el paso cabe en una frase con formato de salida explícito, delégalo; si "
    "necesita criterio, arquitectura o razonamiento, hazlo tú. Detalle en la skill "
    "`delegacion-local`."
)


def tool_catalog(skill_md: Path) -> list[tuple[str, str]]:
    """(nombre, para qué sirve) de cada tool, leído de la tabla de la skill empaquetada.

    La skill es la fuente porque ya existe, viaja en el wheel y es lo que el usuario lee. La
    alternativa —preguntarle al servidor— obligaría a importar ``server``, que arrastra el SDK
    MCP y uvicorn para responder algo que es texto.

    La ruta **se recibe** en vez de derivarse de ``install.resources_dir()``: importar ``install``
    aquí cerraba un ciclo —``install`` importa este módulo para planificar la acción— que CodeQL
    marcó en el PR. Recibirla deja este módulo sin una sola dependencia del paquete, que además
    es lo que lo hace trivial de probar.

    Si la tabla no se puede leer devuelve vacío, y con el catálogo vacío no se toca ningún
    agente: la degradación segura de una escritura es no escribir.
    """
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        (match.group(1), match.group(2))
        for line in text.splitlines()
        if (match := _CATALOG_ROW_RE.match(line))
    ]


def catalog_block(catalog: list[tuple[str, str]]) -> str:
    """El bloque que se inserta en los agentes, ya delimitado."""
    # Solo la inicial en minúscula: un `.lower()` entero convertiría «lint/tests/CI» en
    # «lint/tests/ci» y se comería los acrónimos de la tabla. Se vio en la primera ejecución real.
    listado = ", ".join(f"`{name}` ({what[:1].lower()}{what[1:]})" for name, what in catalog)
    body = (
        f"**Catálogo de tools `local_*` (MCP `local-delegate`, {len(catalog)} tools):** "
        f"{listado}.\n\n{_RULE}"
    )
    return f"{CATALOG_BEGIN}\n{body}\n{CATALOG_END}\n"


def is_delegator(text: str) -> bool:
    """True si el agente ya declara nuestras tools. El frontmatter está al principio."""
    return any(
        line.lstrip().startswith("tools:") and ANCHOR in line for line in text.splitlines()[:60]
    )


def _update_tools_line(text: str, catalog: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """Añade a `tools:` las que falten. No reordena ni toca el resto de la línea."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines[:60]):
        if not line.lstrip().startswith("tools:") or ANCHOR not in line:
            continue
        missing = [
            f"{TOOL_PREFIX}{name}" for name, _ in catalog if f"{TOOL_PREFIX}{name}" not in line
        ]
        if not missing:
            return text, []
        newline = "\n" if line.endswith("\n") else ""
        body = line[: len(line) - len(newline)] if newline else line
        lines[i] = body + ", " + ", ".join(missing) + newline
        return "".join(lines), missing
    return text, []


def _update_catalog_block(text: str, block: str) -> tuple[str, str | None]:
    """(texto nuevo, acción) con acción en {"replaced", "inserted", None}."""
    if CATALOG_BEGIN in text:
        if CATALOG_END not in text:
            # Marcador de apertura huérfano: reemplazar «hasta el final» arrasaría el fichero.
            return text, None
        new_text = _CATALOG_BLOCK_RE.sub(block.rstrip("\n"), text, count=1)
        return (new_text, "replaced") if new_text != text else (text, None)

    lines = text.splitlines(keepends=True)
    insert_at, seen = None, False
    for i, line in enumerate(lines):
        if _DELEGATION_HEADING_RE.match(line):
            seen = True
            continue
        if seen and _HEADING_RE.match(line):
            insert_at = i
            break
    if not seen:
        # Sin sección de delegación reconocible no se adivina dónde va: se deja el fichero.
        return text, None

    before = lines if insert_at is None else lines[:insert_at]
    after = [] if insert_at is None else lines[insert_at:]
    while len(before) >= 2 and before[-1].strip() == "" and before[-2].strip() == "":
        before.pop()
    if before and before[-1].strip() != "":
        before.append("\n")
    block_lines = block.splitlines(keepends=True) + (["\n"] if after else [])
    return "".join(before + block_lines + after), "inserted"


def process(text: str, catalog: list[tuple[str, str]]) -> tuple[str, list[str], str | None]:
    """(texto nuevo, tools añadidas, acción sobre el bloque). Sin catálogo no se toca nada."""
    if not catalog or not is_delegator(text):
        return text, [], None
    text, added = _update_tools_line(text, catalog)
    text, action = _update_catalog_block(text, catalog_block(catalog))
    return text, added, action


def pending(agents_dir: Path, skill_md: Path) -> list[tuple[Path, str, list[str], str | None]]:
    """Agentes que cambiarían: (ruta, texto nuevo, tools añadidas, acción del bloque).

    Solo lectura. Un fichero ilegible se salta en vez de tumbar el recorrido: el instalador es
    best-effort sobre ficheros que no escribió él.
    """
    catalog = tool_catalog(skill_md)
    if not catalog or not agents_dir.is_dir():
        return []
    out = []
    for path in sorted(agents_dir.glob("*.md")):
        try:
            original = path.read_text(encoding="utf-8")
        except OSError:
            continue
        updated, added, action = process(original, catalog)
        if updated != original:
            out.append((path, updated, added, action))
    return out
