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

RAIZ = Path(__file__).parents[1]

# `scripts/` no se empaqueta ni está en el path de import: se carga por ruta, igual que hacen los
# demás tests de scripts de este repo.
_spec = importlib.util.spec_from_file_location("sync_wiki", RAIZ / "scripts" / "sync_wiki.py")
sync_wiki = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_wiki)
WIKI = RAIZ / "docs" / "wiki"
WORKFLOW = RAIZ / ".github" / "workflows" / "wiki.yml"

# La tabla del doctor de `Integration-install.md` se compara contra el registro real de
# comprobaciones, así que este módulo importa `checks`. Los grupos son la primera columna.
from local_delegate import checks

_GRUPOS_DE_LA_TABLA = {"Entorno", "Andamiaje", "Servicios", "Backend"}
_NUMERO_DE_TOOLS = {10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce"}

_NUMERO_DE_CHECKS = {
    15: "quince",
    16: "dieciséis",
    17: "diecisiete",
    18: "dieciocho",
    19: "diecinueve",
    20: "veinte",
}

# `[texto](destino)`, quedándose con el destino.
ENLACE_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _paginas() -> list[Path]:
    return sorted(WIKI.glob("*.md"))


def _enlaces(texto: str) -> list[str]:
    return ENLACE_RE.findall(texto)


def test_un_script_con_shebang_esta_marcado_ejecutable_en_git():
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

    salida = subprocess.run(
        ["git", "ls-files", "-s", "--", "scripts/*.py", "src/local_delegate/resources/hooks/*.py"],
        cwd=RAIZ,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if salida.returncode != 0:
        import pytest

        pytest.skip("no hay git disponible para leer los modos")

    descuadrados = []
    for linea in salida.stdout.splitlines():
        modo, _resto = linea.split(" ", 1)
        ruta = RAIZ / linea.split("\t", 1)[1]
        if not ruta.exists():
            continue
        tiene_shebang = ruta.read_bytes().startswith(b"#!")
        marcado = modo == "100755"
        if tiene_shebang != marcado:
            que = "lleva shebang y no está marcado" if tiene_shebang else "está marcado sin shebang"
            descuadrados.append(f"{ruta.name} ({que})")

    assert not descuadrados, (
        "scripts con shebang y bit de ejecución descuadrados; ruff lo marcaría como EXE001 "
        f"en el CI (Linux) pero no en Windows: {descuadrados}"
    )


def test_hay_paginas_que_sincronizar():
    """Guarda del resto: sin esto, los tests de abajo pasarían sobre una lista vacía."""
    assert len(_paginas()) >= 5


def test_el_workflow_se_dispara_con_los_cambios_de_la_wiki():
    """Si el `paths` no cubre `docs/wiki/`, la sincronización no corre y nadie lo nota.

    El síntoma sería idéntico al de hoy —la wiki congelada mientras el repo avanza— con el
    agravante de que existiría un workflow dando a entender que está resuelto.
    """
    texto = WORKFLOW.read_text(encoding="utf-8")
    assert "docs/wiki/**" in texto
    assert "branches: [main]" in texto


def test_ninguna_pagina_queda_huerfana_del_indice():
    """La wiki de GitHub no genera índice: lo que no esté en `Home.md` no se alcanza navegando."""
    home = (WIKI / "Home.md").read_text(encoding="utf-8")
    enlazadas = {Path(e.split("#")[0]).name for e in _enlaces(home)}

    huerfanas = [p.name for p in _paginas() if p.name != "Home.md" and p.name not in enlazadas]
    assert not huerfanas, f"páginas que no se alcanzan desde Home.md: {huerfanas}"


def test_lo_que_sale_del_directorio_se_convierte_en_url_absoluta():
    """`../algo` funciona leyendo el repo y es un **404** en la wiki publicada.

    Eran 18 enlaces en 6 páginas cuando se midió, y ninguno se veía roto en GitHub: el fuente se
    renderiza perfecto navegando el repo. Por eso la conversión la hace el sync y no el autor —
    `docs/wiki/` existe sobre todo para leerse dentro del repo, donde lo relativo es lo correcto.
    """
    for pagina in _paginas():
        convertido, _ = sync_wiki.convertir(pagina.read_text(encoding="utf-8"))
        fuera = [e for e in _enlaces(convertido) if e.startswith("..")]
        assert not fuera, f"{pagina.name}: enlaces que seguirían rotos en la wiki: {fuera}"


def test_los_enlaces_entre_paginas_NO_se_convierten():
    """Una página hermana se enlaza en relativo, que es lo que la wiki espera.

    Convertirla a URL absoluta funcionaría, pero **sacaría al lector de la wiki en cada clic**:
    la navegación interna dejaría de existir. Es el error simétrico al de arriba y sale gratis
    cometerlo si la regla se escribe como «convierte todos los enlaces».
    """
    hermanas = {p.name for p in _paginas()}
    comprobados = 0

    for pagina in _paginas():
        # Se pregunta por los enlaces del ORIGINAL, no por los del resultado: mirando el resultado,
        # una conversión indebida ya trae `/` en la URL y se escapa del filtro. Es el error que
        # dejó pasar este mismo mutante en la primera versión del test.
        for destino in _enlaces(pagina.read_text(encoding="utf-8")):
            if destino.split("#")[0] in hermanas:
                comprobados += 1
                assert sync_wiki.convertir_destino(destino) is None, (
                    f"{pagina.name}: '{destino}' es una página hermana y se convirtió a URL "
                    "absoluta; eso rompe la navegación interna de la wiki"
                )

    assert comprobados >= 5, "no se comprobó ningún enlace entre páginas: el test no prueba nada"


def test_la_conversion_conserva_el_ancla():
    """Perder el `#seccion` manda al lector al principio de un documento largo, sin avisar."""
    convertido = sync_wiki.convertir_destino("../recipes/llama-swap-blackwell.md#descarga-de-vram")
    assert convertido is not None
    assert convertido.endswith("/docs/recipes/llama-swap-blackwell.md#descarga-de-vram")


def test_no_se_tocan_las_urls_externas_ni_las_anclas():
    for destino in ("https://pypi.org/", "http://127.0.0.1:9393/", "#seccion", "mailto:a@b.c"):
        assert sync_wiki.convertir_destino(destino) is None


def test_un_enlace_que_sale_del_repo_se_deja_como_esta():
    """Ya está roto en el fuente; convertirlo lo disfrazaría de URL válida.

    Una URL de GitHub bien formada apuntando a nada es **peor** que un enlace relativo roto: la
    primera parece correcta en una revisión y la segunda salta a la vista.
    """
    assert sync_wiki.convertir_destino("../../../fuera-del-repo.md") is None


def test_los_enlaces_entre_paginas_apuntan_a_paginas_que_existen():
    """Un enlace a una página inexistente es un 404 silencioso en la wiki."""
    existentes = {p.name for p in _paginas()}
    rotos = []
    for pagina in _paginas():
        for enlace in _enlaces(pagina.read_text(encoding="utf-8")):
            destino = enlace.split("#")[0]
            if not destino.endswith(".md") or "/" in destino or destino.startswith(".."):
                continue  # externo, ancla pura o fuera del directorio (lo cubre el test de arriba)
            if destino not in existentes:
                rotos.append(f"{pagina.name} -> {destino}")

    assert not rotos, f"enlaces a páginas que no existen: {rotos}"


def _filas_de_la_tabla_de_checks() -> list[tuple[str, str]]:
    """`(grupo, comprobación)` de la tabla del doctor en `Integration-install.md`."""
    texto = (WIKI / "Integration-install.md").read_text(encoding="utf-8")
    filas = []
    for linea in texto.splitlines():
        if not linea.startswith("|"):
            continue
        celdas = [c.strip() for c in linea.strip("|").split("|")]
        if len(celdas) >= 2 and celdas[0] in _GRUPOS_DE_LA_TABLA:
            filas.append((celdas[0], celdas[1]))
    return filas


def test_la_tabla_del_doctor_lista_todas_las_comprobaciones():
    """La wiki es la única superficie del doctor que no tenía guardián, y se desfasó.

    `checks.py` sí lo tiene —`test_el_docstring_dice_cuantos_checks_hay_de_verdad`— y por eso sus
    frases de tamaño estaban al día. La wiki no, así que el check `service.daemon_auth` de la
    0.26.0 nunca llegó a la tabla y el texto siguió diciendo «dieciséis» con dieciocho checks en
    el registro. Medido el 2026-09-08: la tabla tenía diecisiete filas.

    Este test compara la tabla contra el registro **real**, que es la única fuente: añadir un
    check y no documentarlo pone la wiki en rojo en el mismo PR que lo introduce.
    """
    titulos_wiki = [titulo for _grupo, titulo in _filas_de_la_tabla_de_checks()]
    titulos_codigo = [c.title for c in checks.CHECKS]

    faltan = [t for t in titulos_codigo if t not in titulos_wiki]
    sobran = [t for t in titulos_wiki if t not in titulos_codigo]
    assert not faltan, f"comprobaciones sin fila en la wiki: {faltan}"
    assert not sobran, f"filas de la wiki que ya no existen en checks.py: {sobran}"


def test_la_wiki_dice_cuantas_comprobaciones_hay_de_verdad():
    """El número escrito con letra envejece solo; que lo cuente el programa."""
    cuantas = _NUMERO_DE_CHECKS[len(checks.CHECKS)]
    texto = (WIKI / "Integration-install.md").read_text(encoding="utf-8")
    frase = f"las {cuantas} piezas"
    assert frase in texto, f"la wiki no dice «{frase}»; hay {len(checks.CHECKS)} comprobaciones"


def _tools_del_servidor() -> list[str]:
    """Los nombres que el servidor MCP expone de verdad, no los que creemos que expone."""
    import asyncio

    from local_delegate import server

    return sorted(t.name for t in asyncio.run(server.mcp.list_tools()))


def _tools_documentadas() -> list[str]:
    """Las que `Tools.md` documenta con su propia sección `## \\`local_x\\``."""
    texto = (WIKI / "Tools.md").read_text(encoding="utf-8")
    return sorted(re.findall(r"^## `(local_\w+)`", texto, re.MULTILINE))


def test_el_catalogo_documenta_todas_las_tools_y_ninguna_de_mas():
    """La página de tools envejece con cada tool nueva, así que no puede depender de acordarse.

    Es la misma medicina que la tabla del doctor: la wiki se comparó contra el registro real y
    resultó llevar cuatro versiones desfasada. Aquí la fuente es `server.mcp.list_tools()`, o sea
    lo que el cliente MCP ve de verdad — añadir una tool sin documentarla pone el CI en rojo en el
    mismo PR que la introduce, y quitar una deja la sección huérfana a la vista.
    """
    del_servidor = _tools_del_servidor()
    documentadas = _tools_documentadas()

    faltan = [t for t in del_servidor if t not in documentadas]
    sobran = [t for t in documentadas if t not in del_servidor]
    assert not faltan, f"tools sin sección en Tools.md: {faltan}"
    assert not sobran, f"secciones de Tools.md sin tool detrás: {sobran}"


def test_el_catalogo_dice_cuantas_tools_hay_de_verdad():
    """El número escrito con letra en la entradilla y en el índice de la wiki."""
    cuantas = _NUMERO_DE_TOOLS[len(_tools_del_servidor())]
    assert f"Las **{cuantas}** tools" in (WIKI / "Tools.md").read_text(encoding="utf-8")
    assert f"las {cuantas} tools" in (WIKI / "Home.md").read_text(encoding="utf-8")


def test_la_tabla_de_un_vistazo_lista_todas_las_tools():
    """La tabla índice y las secciones son dos listas del mismo conjunto: se desincronizan solas."""
    texto = (WIKI / "Tools.md").read_text(encoding="utf-8")
    tabla = re.findall(r"^\| \[`(local_\w+)`\]", texto, re.MULTILINE)
    assert sorted(tabla) == _tools_del_servidor(), (
        f"la tabla «De un vistazo» no cuadra con el servidor: {sorted(tabla)}"
    )
