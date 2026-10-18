"""La skill en español y en inglés listan las mismas tools con los mismos identificadores (REQ-029).

El catálogo de los subagentes sale de la tabla de la skill del idioma vigente
(`agents.tool_catalog`), así que una fila que falte en `SKILL.en.md` dejaría a los subagentes
ingleses sin esa tool sin que nada más fallara. Se comparan, por idioma:

- el `name` del frontmatter (es el nombre de la skill, REQ-012, y no se traduce);
- las filas de la tabla, en orden, con su tool;
- los identificadores entre comillas invertidas de la columna de argumentos de cada fila;
- el conjunto de `local_*` que nombra el texto entero.

Y lo mismo para el bloque de memoria: misma skill y mismas tools nombradas.
"""

from __future__ import annotations

import re

import pytest

from local_delegate import agents, install

_TOOL = re.compile(r"`(local_\w+)")
_BACKTICKED = re.compile(r"`([^`]+)`")
_ROW = re.compile(r"^\|\s*`(local_\w+)`\s*\|[^|]*\|([^|]*)\|")
_NAME = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)


def _rows(text: str) -> list[tuple[str, list[str]]]:
    """(tool, identificadores de su columna de argumentos) de cada fila de la tabla."""
    return [
        (match.group(1), _BACKTICKED.findall(match.group(2)))
        for line in text.splitlines()
        if (match := _ROW.match(line))
    ]


def _problems(spanish: str, english: str) -> list[str]:
    problems = []
    if _NAME.findall(spanish) != _NAME.findall(english):
        problems.append(f"name: {_NAME.findall(spanish)} != {_NAME.findall(english)}")
    rows_es, rows_en = _rows(spanish), _rows(english)
    if [tool for tool, _ in rows_es] != [tool for tool, _ in rows_en]:
        problems.append(f"filas: {[t for t, _ in rows_es]} != {[t for t, _ in rows_en]}")
    for (tool, args_es), (_tool, args_en) in zip(rows_es, rows_en, strict=False):
        if args_es != args_en:
            problems.append(f"{tool}: {args_es} != {args_en}")
    if set(_TOOL.findall(spanish)) != set(_TOOL.findall(english)):
        problems.append(f"tools: {set(_TOOL.findall(spanish)) ^ set(_TOOL.findall(english))}")
    return problems


def _skill(lang: str) -> str:
    return install.skill_source(lang).read_text(encoding="utf-8")


def test_both_skills_exist_and_are_different_files():
    assert install.skill_source("es") != install.skill_source("en")
    assert install.skill_source("en").name == "SKILL.en.md"
    assert _skill("es") != _skill("en")


def test_the_skills_list_the_same_tools_with_the_same_identifiers():
    rows = _rows(_skill("es"))
    assert len(rows) >= 11, "el escáner no encontró la tabla: no comprobaría nada"
    assert _problems(_skill("es"), _skill("en")) == []


def test_the_catalog_of_each_language_has_the_same_tools():
    names = {
        lang: [name for name, _ in agents.tool_catalog(install.skill_source(lang))]
        for lang in ("es", "en")
    }
    assert names["es"] == names["en"] and len(names["es"]) >= 11


def test_the_memory_blocks_name_the_same_skill_and_tools():
    texts = {lang: install.memory_source(lang).read_text(encoding="utf-8") for lang in ("es", "en")}
    assert set(_TOOL.findall(texts["es"])) == set(_TOOL.findall(texts["en"]))
    for text in texts.values():
        assert f"`{install.SKILL_NAME}`" in text


@pytest.mark.parametrize(
    "mutate",
    [
        lambda text: "\n".join(
            line for line in text.splitlines() if not line.startswith("| `local_translate`")
        ),
        lambda text: text.replace("`target_lang`", "`language`", 1),
        lambda text: text.replace("name: local-delegation", "name: local-delegation-en", 1),
    ],
    ids=["a-missing-row", "a-changed-identifier", "a-changed-name"],
)
def test_the_guardian_catches_a_broken_english_skill(mutate):
    """Control positivo: cada mutación de `SKILL.en.md` da al menos un problema."""
    broken = mutate(_skill("en"))
    assert broken != _skill("en"), "la mutación no mutó nada"
    assert _problems(_skill("es"), broken)
