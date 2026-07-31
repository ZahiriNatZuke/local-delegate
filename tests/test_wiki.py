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

# `[texto](destino)`, quedándose con el destino.
ENLACE_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _paginas() -> list[Path]:
    return sorted(WIKI.glob("*.md"))


def _enlaces(texto: str) -> list[str]:
    return ENLACE_RE.findall(texto)


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
