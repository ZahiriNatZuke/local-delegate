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
ANCLA = agents.ANCHOR

DELEGADOR = f"""---
name: probador
tools: Read, Write, {ANCLA}, mcp__local-delegate__local_summarize
---

# Probador

## Delegación a modelos locales

Delega lo mecánico.

## Otra sección

Texto que no se toca.
"""

AJENO = """---
name: ajeno
tools: Read, Write, Bash
---

# Ajeno

## Delegación a modelos locales

Este agente no declara nuestras tools, así que no es nuestro.
"""

SIN_SECCION = f"""---
name: sin-seccion
tools: {ANCLA}
---

# Sin sección reconocible

Nada que permita adivinar dónde va el bloque.
"""


def _agents_dir(tmp_path: Path, **ficheros: str) -> Path:
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True)
    for nombre, texto in ficheros.items():
        (d / f"{nombre}.md").write_text(texto, encoding="utf-8")
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
def test_el_catalogo_sale_de_la_tabla_de_la_skill():
    catalogo = agents.tool_catalog(SKILL_MD)
    assert len(catalogo) == 11
    nombres = [n for n, _ in catalogo]
    assert "local_describe_image" in nombres, "la tool que la receta vieja se dejaba fuera"
    assert all(what.strip() for _n, what in catalogo), "toda tool necesita su descripción"


def test_el_bloque_dice_cuantas_tools_hay_de_verdad():
    bloque = agents.catalog_block(agents.tool_catalog(SKILL_MD))
    assert "11 tools" in bloque
    assert bloque.startswith(agents.CATALOG_BEGIN)
    assert bloque.rstrip().endswith(agents.CATALOG_END)


def test_el_bloque_no_se_come_los_acronimos():
    """Un `.lower()` entero convertía «lint/tests/CI» en «lint/tests/ci». Se vio ejecutándolo."""
    assert "lint/tests/CI" in agents.catalog_block(agents.tool_catalog(SKILL_MD))


def test_el_detalle_de_la_accion_cabe_en_la_consola_de_windows(tmp_path):
    """El bloque va a un fichero UTF-8, pero el detalle se IMPRIME.

    La descripción de `local_delegate` lleva una flecha `→`, que no existe en cp1252 y mataría
    el `install` en la consola de Windows — que es el bug que ya se pagó una vez en el `doctor`.
    Por eso el detalle lleva nombres de fichero y no el catálogo.
    """
    _agents_dir(tmp_path, delegador=DELEGADOR)
    for action in inst.plan_install(_opts(tmp_path)):
        action.describe().encode("cp1252")


def test_sin_catalogo_no_se_toca_nada(tmp_path, monkeypatch):
    """Degradación segura: si la tabla no se puede leer, no se escribe.

    Se apunta a una ruta inexistente en vez de doblar la función que lee: así se ejercita el
    `except OSError` de verdad, no un doble que devuelve la lista vacía por su cuenta.
    """
    assert agents.tool_catalog(tmp_path / "no-existe.md") == []

    monkeypatch.setattr(inst, "resources_dir", lambda: tmp_path / "sin-recursos")
    d = _agents_dir(tmp_path, delegador=DELEGADOR)
    antes = snapshot(d)
    assert [a for a in inst.plan_install(_opts(tmp_path)) if a.kind == "agents"] == []
    assert snapshot(d) == antes


# --- Qué se toca y qué no ------------------------------------------------------
def test_un_agente_que_delega_se_actualiza(tmp_path):
    d = _agents_dir(tmp_path, delegador=DELEGADOR)
    assert _install(tmp_path) == 0

    texto = (d / "delegador.md").read_text(encoding="utf-8")
    assert "mcp__local-delegate__local_describe_image" in texto, "faltaba y debía añadirse"
    assert agents.CATALOG_BEGIN in texto and "11 tools" in texto
    assert "Texto que no se toca." in texto
    assert (d / "delegador.md.bak").is_file(), "toda escritura deja copia"


def test_un_agente_ajeno_queda_byte_a_byte_igual(tmp_path):
    """El que no declara nuestras tools no es nuestro, y no se toca ni para añadirle nada."""
    d = _agents_dir(tmp_path, ajeno=AJENO)
    antes = snapshot(d)
    assert _install(tmp_path) == 0
    assert snapshot(d) == antes
    assert not (d / "ajeno.md.bak").exists(), "ni siquiera se hizo copia: no se abrió para escribir"


def test_sin_seccion_reconocible_no_se_inventa_donde_va_el_bloque(tmp_path):
    d = _agents_dir(tmp_path, raro=SIN_SECCION)
    _install(tmp_path)
    texto = (d / "raro.md").read_text(encoding="utf-8")
    assert agents.CATALOG_BEGIN not in texto, "no debe insertar donde no sabe"
    assert "mcp__local-delegate__local_summarize" in texto, "pero el `tools:` sí se completa"


def test_un_marcador_de_apertura_huerfano_no_arrasa_el_fichero(tmp_path):
    roto = DELEGADOR.replace("## Otra sección", f"{agents.CATALOG_BEGIN}\nviejo\n\n## Otra sección")
    d = _agents_dir(tmp_path, roto=roto)
    _install(tmp_path)
    texto = (d / "roto.md").read_text(encoding="utf-8")
    assert "Texto que no se toca." in texto, "sin marcador de cierre no se reemplaza hasta el final"


# --- Opt-in, dry-run e idempotencia -------------------------------------------
def test_sin_el_flag_no_se_toca_ningun_agente(tmp_path):
    d = _agents_dir(tmp_path, delegador=DELEGADOR)
    antes = snapshot(d)
    inst.apply(
        inst.plan_install(_opts(tmp_path, components={"hooks", "skill", "memory", "mcp"})),
        dry_run=False,
        out=lambda *_a: None,
    )
    assert snapshot(d) == antes


def test_dry_run_no_escribe(tmp_path):
    d = _agents_dir(tmp_path, delegador=DELEGADOR)
    antes = snapshot(d)
    inst.apply(inst.plan_install(_opts(tmp_path)), dry_run=True, out=lambda *_a: None)
    assert snapshot(d) == antes


def test_segunda_pasada_no_planifica_nada(tmp_path):
    _agents_dir(tmp_path, delegador=DELEGADOR)
    _install(tmp_path)
    assert [a for a in inst.plan_install(_opts(tmp_path)) if a.kind == "agents"] == []


def test_sin_directorio_de_agentes_no_hay_accion(tmp_path):
    (tmp_path / ".claude").mkdir(parents=True)
    assert [a for a in inst.plan_install(_opts(tmp_path)) if a.kind == "agents"] == []


def test_el_bloque_se_reemplaza_y_no_se_duplica(tmp_path):
    d = _agents_dir(tmp_path, delegador=DELEGADOR)
    _install(tmp_path)
    primera = (d / "delegador.md").read_text(encoding="utf-8")
    # Se ensucia el contenido del bloque para forzar un segundo reemplazo.
    (d / "delegador.md").write_text(primera.replace("11 tools", "3 tools"), encoding="utf-8")
    _install(tmp_path)
    texto = (d / "delegador.md").read_text(encoding="utf-8")
    assert texto.count(agents.CATALOG_BEGIN) == 1
    assert "11 tools" in texto
