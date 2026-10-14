"""La wiki nativa se publica desde `docs/wiki/`, y hay cosas que ahí no funcionan igual.

La wiki de GitHub sirve los `.md` **planos, en un repositorio aparte**: no hay subdirectorios que
recorrer ni un árbol relativo al que subir. Un enlace que funciona perfectamente leyendo el repo
—`../../README.md`— en la wiki publicada es un 404, y nadie se entera porque el fichero fuente se
ve bien en GitHub.

Estos tests cubren lo que la automatización **no** puede arreglar sola: que las páginas se puedan
alcanzar y que sus enlaces resuelvan una vez publicadas.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]

# `scripts/` no se empaqueta ni está en el path de import: se carga por ruta, igual que hacen los
# demás tests de scripts de este repo.
_spec = importlib.util.spec_from_file_location("sync_wiki", ROOT / "scripts" / "sync_wiki.py")
sync_wiki = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_wiki)
WIKI = ROOT / "docs" / "wiki"
WORKFLOW = ROOT / ".github" / "workflows" / "wiki.yml"

# La tabla del doctor de `Integration-install.md` se compara contra el registro real de
# comprobaciones, así que este módulo importa `checks`. Los grupos son la primera columna.
from local_delegate import checks

_TABLE_GROUPS = {"Entorno", "Andamiaje", "Servicios", "Backend"}
_TOOL_COUNT_WORDS = {10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce"}

_CHECK_COUNT_WORDS = {
    15: "quince",
    16: "dieciséis",
    17: "diecisiete",
    18: "dieciocho",
    19: "diecinueve",
    20: "veinte",
    # Femenino: la frase es «las N piezas».
    21: "veintiuna",
    22: "veintidós",
    23: "veintitrés",
    24: "veinticuatro",
    25: "veinticinco",
}

# `[texto](destino)`, quedándose con el destino.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _pages() -> list[Path]:
    return sorted(WIKI.glob("*.md"))


def _links(text: str) -> list[str]:
    return LINK_RE.findall(text)


def test_a_script_with_a_shebang_is_marked_executable_in_git():
    """`ruff` caza esto (EXE001), pero **solo en Linux**: en Windows no existe el bit de ejecución.

    O sea que el lint local pasa en verde y el CI falla, que es la peor forma de enterarse. Pasó
    con `sync_wiki.py` en este mismo change. El test lo comprueba leyendo el **modo que git tiene
    registrado**, que sí es el mismo dato en los tres sistemas.

    Mira `scripts/` **y los hooks**: el 2026-09-12 volvió a pasar por partida doble y este test
    solo vio uno de los dos, porque el otro estaba en `resources/hooks/`. Y hay una segunda mitad
    de la lección: un fichero **sin añadir a git todavía no aparece en `ls-files`**, así que la
    suite puede pasar en verde con el defecto ya escrito y delatarlo solo después del primer
    `git add`. Corre este test otra vez después de añadir ficheros nuevos.
    """
    import subprocess

    output = subprocess.run(
        ["git", "ls-files", "-s", "--", "scripts/*.py", "src/local_delegate/resources/hooks/*.py"],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if output.returncode != 0:
        import pytest

        pytest.skip("no hay git disponible para leer los modos")

    mismatched = []
    for line in output.stdout.splitlines():
        mode, _rest = line.split(" ", 1)
        path = ROOT / line.split("\t", 1)[1]
        if not path.exists():
            continue
        has_shebang = path.read_bytes().startswith(b"#!")
        marked = mode == "100755"
        if has_shebang != marked:
            what = "lleva shebang y no está marcado" if has_shebang else "está marcado sin shebang"
            mismatched.append(f"{path.name} ({what})")

    assert not mismatched, (
        "scripts con shebang y bit de ejecución descuadrados; ruff lo marcaría como EXE001 "
        f"en el CI (Linux) pero no en Windows: {mismatched}"
    )


def test_there_are_pages_to_sync():
    """Guarda del resto: sin esto, los tests de abajo pasarían sobre una lista vacía."""
    assert len(_pages()) >= 5


def test_the_workflow_triggers_on_wiki_changes():
    """Si el `paths` no cubre `docs/wiki/`, la sincronización no corre y nadie lo nota.

    El síntoma sería idéntico al de hoy —la wiki congelada mientras el repo avanza— con el
    agravante de que existiría un workflow dando a entender que está resuelto.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "docs/wiki/**" in text
    assert "branches: [main]" in text


def test_no_page_is_orphaned_from_the_index():
    """La wiki de GitHub no genera índice: lo que no esté en `Home.md` no se alcanza navegando."""
    home = (WIKI / "Home.md").read_text(encoding="utf-8")
    linked = {Path(e.split("#")[0]).name for e in _links(home)}

    orphans = [p.name for p in _pages() if p.name != "Home.md" and p.name not in linked]
    assert not orphans, f"páginas que no se alcanzan desde Home.md: {orphans}"


def test_what_leaves_the_directory_becomes_an_absolute_url():
    """`../algo` funciona leyendo el repo y es un **404** en la wiki publicada.

    Eran 18 enlaces en 6 páginas cuando se midió, y ninguno se veía roto en GitHub: el fuente se
    renderiza perfecto navegando el repo. Por eso la conversión la hace el sync y no el autor —
    `docs/wiki/` existe sobre todo para leerse dentro del repo, donde lo relativo es lo correcto.
    """
    for page in _pages():
        converted, _ = sync_wiki.convert(page.read_text(encoding="utf-8"))
        outside = [e for e in _links(converted) if e.startswith("..")]
        assert not outside, f"{page.name}: enlaces que seguirían rotos en la wiki: {outside}"


def test_links_between_pages_are_NOT_converted():
    """Una página hermana se enlaza en relativo, que es lo que la wiki espera.

    Convertirla a URL absoluta funcionaría, pero **sacaría al lector de la wiki en cada clic**:
    la navegación interna dejaría de existir. Es el error simétrico al de arriba y sale gratis
    cometerlo si la regla se escribe como «convierte todos los enlaces».
    """
    siblings = {p.name for p in _pages()}
    checked = 0

    for page in _pages():
        # Se pregunta por los enlaces del ORIGINAL, no por los del resultado: mirando el resultado,
        # una conversión indebida ya trae `/` en la URL y se escapa del filtro. Es el error que
        # dejó pasar este mismo mutante en la primera versión del test.
        for dest in _links(page.read_text(encoding="utf-8")):
            if dest.split("#")[0] in siblings:
                checked += 1
                assert sync_wiki.convert_destination(dest) is None, (
                    f"{page.name}: '{dest}' es una página hermana y se convirtió a URL "
                    "absoluta; eso rompe la navegación interna de la wiki"
                )

    assert checked >= 5, "no se comprobó ningún enlace entre páginas: el test no prueba nada"


def test_the_conversion_keeps_the_anchor():
    """Perder el `#seccion` manda al lector al principio de un documento largo, sin avisar."""
    converted = sync_wiki.convert_destination("../recipes/llama-swap-blackwell.md#descarga-de-vram")
    assert converted is not None
    assert converted.endswith("/docs/recipes/llama-swap-blackwell.md#descarga-de-vram")


def test_external_urls_and_anchors_are_not_touched():
    for dest in ("https://pypi.org/", "http://127.0.0.1:9393/", "#seccion", "mailto:a@b.c"):
        assert sync_wiki.convert_destination(dest) is None


def test_a_link_that_leaves_the_repo_is_left_as_is():
    """Ya está roto en el fuente; convertirlo lo disfrazaría de URL válida.

    Una URL de GitHub bien formada apuntando a nada es **peor** que un enlace relativo roto: la
    primera parece correcta en una revisión y la segunda salta a la vista.
    """
    assert sync_wiki.convert_destination("../../../fuera-del-repo.md") is None


def test_links_between_pages_point_to_pages_that_exist():
    """Un enlace a una página inexistente es un 404 silencioso en la wiki."""
    existing = {p.name for p in _pages()}
    broken = []
    for page in _pages():
        for link in _links(page.read_text(encoding="utf-8")):
            dest = link.split("#")[0]
            if not dest.endswith(".md") or "/" in dest or dest.startswith(".."):
                continue  # externo, ancla pura o fuera del directorio (lo cubre el test de arriba)
            if dest not in existing:
                broken.append(f"{page.name} -> {dest}")

    assert not broken, f"enlaces a páginas que no existen: {broken}"


def _check_table_rows() -> list[tuple[str, str]]:
    """`(grupo, comprobación)` de la tabla del doctor en `Integration-install.md`."""
    text = (WIKI / "Integration-install.md").read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] in _TABLE_GROUPS:
            rows.append((cells[0], cells[1]))
    return rows


def test_the_doctor_table_lists_every_check():
    """La wiki es la única superficie del doctor que no tenía guardián, y se desfasó.

    `checks.py` sí lo tiene —`test_the_docstring_states_how_many_checks_there_really_are`— y por eso sus
    frases de tamaño estaban al día. La wiki no, así que el check `service.daemon_auth` de la
    0.26.0 nunca llegó a la tabla y el texto siguió diciendo «dieciséis» con dieciocho checks en
    el registro. Medido el 2026-09-08: la tabla tenía diecisiete filas.

    Este test compara la tabla contra el registro **real**, que es la única fuente: añadir un
    check y no documentarlo pone la wiki en rojo en el mismo PR que lo introduce.
    """
    wiki_titles = [title for _group, title in _check_table_rows()]
    code_titles = [c.title for c in checks.CHECKS]

    missing = [t for t in code_titles if t not in wiki_titles]
    surplus = [t for t in wiki_titles if t not in code_titles]
    assert not missing, f"comprobaciones sin fila en la wiki: {missing}"
    assert not surplus, f"filas de la wiki que ya no existen en checks.py: {surplus}"


def test_the_wiki_says_how_many_checks_there_really_are():
    """El número escrito con letra envejece solo; que lo cuente el programa."""
    count_word = _CHECK_COUNT_WORDS[len(checks.CHECKS)]
    text = (WIKI / "Integration-install.md").read_text(encoding="utf-8")
    phrase = f"las {count_word} piezas"
    assert phrase in text, f"la wiki no dice «{phrase}»; hay {len(checks.CHECKS)} comprobaciones"


def _server_tools() -> list[str]:
    """Los nombres que el servidor MCP expone de verdad, no los que creemos que expone."""
    import asyncio

    from local_delegate import server

    return sorted(t.name for t in asyncio.run(server.mcp.list_tools()))


def _documented_tools() -> list[str]:
    """Las que `Tools.md` documenta con su propia sección `## \\`local_x\\``."""
    text = (WIKI / "Tools.md").read_text(encoding="utf-8")
    return sorted(re.findall(r"^## `(local_\w+)`", text, re.MULTILINE))


def test_the_catalog_documents_every_tool_and_none_extra():
    """La página de tools envejece con cada tool nueva, así que no puede depender de acordarse.

    Es la misma medicina que la tabla del doctor: la wiki se comparó contra el registro real y
    resultó llevar cuatro versiones desfasada. Aquí la fuente es `server.mcp.list_tools()`, o sea
    lo que el cliente MCP ve de verdad — añadir una tool sin documentarla pone el CI en rojo en el
    mismo PR que la introduce, y quitar una deja la sección huérfana a la vista.
    """
    from_server = _server_tools()
    documented = _documented_tools()

    missing = [t for t in from_server if t not in documented]
    surplus = [t for t in documented if t not in from_server]
    assert not missing, f"tools sin sección en Tools.md: {missing}"
    assert not surplus, f"secciones de Tools.md sin tool detrás: {surplus}"


def test_the_catalog_says_how_many_tools_there_really_are():
    """El número escrito con letra en la entradilla y en el índice de la wiki."""
    count_word = _TOOL_COUNT_WORDS[len(_server_tools())]
    assert f"Las **{count_word}** tools" in (WIKI / "Tools.md").read_text(encoding="utf-8")
    assert f"las {count_word} tools" in (WIKI / "Home.md").read_text(encoding="utf-8")


def test_the_at_a_glance_table_lists_every_tool():
    """La tabla índice y las secciones son dos listas del mismo conjunto: se desincronizan solas."""
    text = (WIKI / "Tools.md").read_text(encoding="utf-8")
    table = re.findall(r"^\| \[`(local_\w+)`\]", text, re.MULTILINE)
    assert sorted(table) == _server_tools(), (
        f"la tabla «De un vistazo» no cuadra con el servidor: {sorted(table)}"
    )
