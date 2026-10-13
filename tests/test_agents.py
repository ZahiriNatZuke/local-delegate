"""Tests de `install --agents` (agents.py).

Lo que más se vigila aquí no es que un agente se actualice, sino **que no se toque el que no
debe**: estos ficheros los escribió el usuario, no el instalador. De ahí que el test del agente
ajeno compare byte a byte y exija que no quede ni un `.bak`.
"""

from __future__ import annotations

from pathlib import Path

from conftest import snapshot

from local_delegate import agents
from local_delegate import install as inst

SKILL_MD = inst.resources_dir() / "skills" / inst.SKILL_NAME / "SKILL.md"
ANCHOR = agents.ANCHOR

DELEGATOR = f"""---
name: probador
tools: Read, Write, {ANCHOR}, mcp__local-delegate__local_summarize
---

# Probador

## Delegación a modelos locales

Delega lo mecánico.

## Otra sección

Texto que no se toca.
"""

FOREIGN = """---
name: ajeno
tools: Read, Write, Bash
---

# Ajeno

## Delegación a modelos locales

Este agente no declara nuestras tools, así que no es nuestro.
"""

NO_SECTION = f"""---
name: sin-seccion
tools: {ANCHOR}
---

# Sin sección reconocible

Nada que permita adivinar dónde va el bloque.
"""


def _agents_dir(tmp_path: Path, **files: str) -> Path:
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True)
    for name, text in files.items():
        (d / f"{name}.md").write_text(text, encoding="utf-8")
    return d


def _opts(home: Path, **kw) -> inst.Options:
    base = dict(  # noqa: C408
        home=home,
        components={"agents"},
        targets={"claude"},
        python_exe="python3",
        use_cli=False,
    )
    base.update(kw)
    return inst.Options(**base)


def _install(home: Path, **kw) -> int:
    return inst.apply(inst.plan_install(_opts(home, **kw)), dry_run=False, out=lambda *_a: None)


# --- El catálogo sale de la skill, no de una constante -------------------------
def test_the_catalog_comes_from_the_skill_table():
    catalog = agents.tool_catalog(SKILL_MD)
    assert len(catalog) == 11
    names = [n for n, _ in catalog]
    assert "local_describe_image" in names, "la tool que la receta vieja se dejaba fuera"
    assert all(what.strip() for _n, what in catalog), "toda tool necesita su descripción"


def test_the_block_states_how_many_tools_there_really_are():
    block = agents.catalog_block(agents.tool_catalog(SKILL_MD))
    assert "11 tools" in block
    assert block.startswith(agents.CATALOG_BEGIN)
    assert block.rstrip().endswith(agents.CATALOG_END)


def test_the_block_does_not_swallow_acronyms():
    """Un `.lower()` entero convertía «lint/tests/CI» en «lint/tests/ci». Se vio ejecutándolo."""
    assert "lint/tests/CI" in agents.catalog_block(agents.tool_catalog(SKILL_MD))


def test_the_action_detail_fits_the_windows_console(tmp_path):
    """El bloque va a un fichero UTF-8, pero el detalle se IMPRIME.

    La descripción de `local_delegate` lleva una flecha `→`, que no existe en cp1252 y mataría
    el `install` en la consola de Windows — que es el bug que ya se pagó una vez en el `doctor`.
    Por eso el detalle lleva nombres de fichero y no el catálogo.
    """
    _agents_dir(tmp_path, delegador=DELEGATOR)
    for action in inst.plan_install(_opts(tmp_path)):
        action.describe().encode("cp1252")


def test_without_catalog_nothing_is_touched(tmp_path, monkeypatch):
    """Degradación segura: si la tabla no se puede leer, no se escribe.

    Se apunta a una ruta inexistente en vez de doblar la función que lee: así se ejercita el
    `except OSError` de verdad, no un doble que devuelve la lista vacía por su cuenta.
    """
    assert agents.tool_catalog(tmp_path / "no-existe.md") == []

    monkeypatch.setattr(inst, "resources_dir", lambda: tmp_path / "sin-recursos")
    d = _agents_dir(tmp_path, delegador=DELEGATOR)
    before = snapshot(d)
    assert [a for a in inst.plan_install(_opts(tmp_path)) if a.kind == "agents"] == []
    assert snapshot(d) == before


# --- Qué se toca y qué no ------------------------------------------------------
def test_an_agent_that_delegates_is_updated(tmp_path):
    d = _agents_dir(tmp_path, delegador=DELEGATOR)
    assert _install(tmp_path) == 0

    text = (d / "delegador.md").read_text(encoding="utf-8")
    assert "mcp__local-delegate__local_describe_image" in text, "faltaba y debía añadirse"
    assert agents.CATALOG_BEGIN in text and "11 tools" in text
    assert "Texto que no se toca." in text
    assert (d / "delegador.md.bak").is_file(), "toda escritura deja copia"


def test_a_foreign_agent_stays_byte_for_byte_identical(tmp_path):
    """El que no declara nuestras tools no es nuestro, y no se toca ni para añadirle nada."""
    d = _agents_dir(tmp_path, ajeno=FOREIGN)
    before = snapshot(d)
    assert _install(tmp_path) == 0
    assert snapshot(d) == before
    assert not (d / "ajeno.md.bak").exists(), "ni siquiera se hizo copia: no se abrió para escribir"


def test_without_a_recognizable_section_the_block_location_is_not_made_up(tmp_path):
    d = _agents_dir(tmp_path, raro=NO_SECTION)
    _install(tmp_path)
    text = (d / "raro.md").read_text(encoding="utf-8")
    assert agents.CATALOG_BEGIN not in text, "no debe insertar donde no sabe"
    assert "mcp__local-delegate__local_summarize" in text, "pero el `tools:` sí se completa"


def test_an_orphan_opening_marker_does_not_wipe_the_file(tmp_path):
    broken = DELEGATOR.replace(
        "## Otra sección", f"{agents.CATALOG_BEGIN}\nviejo\n\n## Otra sección"
    )
    d = _agents_dir(tmp_path, roto=broken)
    _install(tmp_path)
    text = (d / "roto.md").read_text(encoding="utf-8")
    assert "Texto que no se toca." in text, "sin marcador de cierre no se reemplaza hasta el final"


# --- Opt-in, dry-run e idempotencia -------------------------------------------
def test_without_the_flag_no_agent_is_touched(tmp_path):
    d = _agents_dir(tmp_path, delegador=DELEGATOR)
    before = snapshot(d)
    inst.apply(
        inst.plan_install(_opts(tmp_path, components={"hooks", "skill", "memory", "mcp"})),
        dry_run=False,
        out=lambda *_a: None,
    )
    assert snapshot(d) == before


def test_dry_run_does_not_write(tmp_path):
    d = _agents_dir(tmp_path, delegador=DELEGATOR)
    before = snapshot(d)
    inst.apply(inst.plan_install(_opts(tmp_path)), dry_run=True, out=lambda *_a: None)
    assert snapshot(d) == before


def test_second_pass_plans_nothing(tmp_path):
    _agents_dir(tmp_path, delegador=DELEGATOR)
    _install(tmp_path)
    assert [a for a in inst.plan_install(_opts(tmp_path)) if a.kind == "agents"] == []


def test_without_agents_directory_there_is_no_action(tmp_path):
    (tmp_path / ".claude").mkdir(parents=True)
    assert [a for a in inst.plan_install(_opts(tmp_path)) if a.kind == "agents"] == []


def test_the_block_is_replaced_and_not_duplicated(tmp_path):
    d = _agents_dir(tmp_path, delegador=DELEGATOR)
    _install(tmp_path)
    first = (d / "delegador.md").read_text(encoding="utf-8")
    # Se ensucia el contenido del bloque para forzar un segundo reemplazo.
    (d / "delegador.md").write_text(first.replace("11 tools", "3 tools"), encoding="utf-8")
    _install(tmp_path)
    text = (d / "delegador.md").read_text(encoding="utf-8")
    assert text.count(agents.CATALOG_BEGIN) == 1
    assert "11 tools" in text


# --- D12: `update` regenera el bloque de catálogo ya marcado ------------------------------------
def _packaged_block() -> str:
    skill_md = inst.resources_dir() / "skills" / inst.SKILL_NAME / "SKILL.md"
    return agents.catalog_block(agents.tool_catalog(skill_md))


def test_refresh_replaces_an_outdated_marked_block_and_leaves_tools_alone():
    block = _packaged_block()
    old = block.replace(inst.SKILL_NAME, "delegacion-local")
    text = f"---\nname: x\ntools: Read, Grep\n---\n\nAntes.\n\n{old}\nDespués.\n"

    updated = agents.refresh_catalog_block(text, block, (block,))

    assert updated is not None
    assert "delegacion-local" not in updated and inst.SKILL_NAME in updated
    assert updated.startswith("---\nname: x\ntools: Read, Grep\n---\n\nAntes.\n\n")
    assert updated.endswith("\nDespués.\n")


def test_refresh_leaves_unmarked_and_current_blocks_alone():
    block = _packaged_block()
    assert agents.refresh_catalog_block("sin marcadores\n", block, (block,)) is None
    crlf = f"x\r\n{block.replace(chr(10), chr(13) + chr(10))}y\r\n"
    assert agents.refresh_catalog_block(crlf, block, (block,)) is None
    orphan = f"{agents.CATALOG_BEGIN}\nsin cierre\n"
    assert agents.refresh_catalog_block(orphan, block, (block,)) is None
