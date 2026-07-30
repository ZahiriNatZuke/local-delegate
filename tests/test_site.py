"""La landing de GitHub Pages: que la versión se inyecte y que nadie la escriba a mano.

El riesgo real de esta pieza no es que se rompa el CSS: es que el número de versión se quede
clavado en la página mientras el paquete avanza, que es exactamente lo que pasó dentro del
prototipo (estaba escrito dos veces y con la primera release ya mentía en una). Por eso los
tests miran el contrato de la inyección, no el diseño.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
INDEX = RAIZ / "site" / "index.html"
FAVICON_SITIO = RAIZ / "site" / "favicon.svg"
FAVICON_PAQUETE = RAIZ / "src" / "local_delegate" / "resources" / "brand" / "favicon.svg"
OG_IMAGE = RAIZ / "site" / "og-image.png"
BASE = "https://zahirinatzuke.github.io/local-delegate/"


def _cargar_build_site():
    """Carga scripts/build_site.py como módulo (el patrón de tests/test_bump_version.py)."""
    ruta = RAIZ / "scripts" / "build_site.py"
    spec = importlib.util.spec_from_file_location("build_site", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def build_site():
    return _cargar_build_site()


def test_la_pagina_trae_el_marcador_y_ninguna_version_literal():
    """Si alguien escribe la versión a mano en la página, este test lo caza."""
    texto = INDEX.read_text(encoding="utf-8")
    assert "__LD_VERSION__" in texto

    version = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    # Una versión X.Y.Z escrita a pelo en el fuente es el defecto que esto previene.
    assert version not in texto, f"la versión {version} está escrita a mano en {INDEX.name}"

    # Y cualquier OTRA versión literal, no solo la de hoy: si alguien pone la 0.15.0, esto la
    # caza igual. Los `lookaround` excluyen los cuartetos punteados — `127.0.0.1` es una IP
    # legítima de la página (el puerto del panel), no un número de versión.
    literales = re.findall(r"(?<![\d.])v?\d+\.\d+\.\d+(?![\d.])", texto)
    assert literales == [], f"números de versión escritos a mano: {literales}"


def test_el_build_sustituye_el_marcador_por_la_version_del_pyproject(build_site, tmp_path):
    destino = tmp_path / "_site"
    escritos = build_site.construir(destino, "9.9.9")

    assert escritos, "el build no tocó ningún fichero"
    salida = (destino / "index.html").read_text(encoding="utf-8")
    assert 'var VERSION = "9.9.9"' in salida
    assert "__LD_VERSION__" not in salida
    assert build_site.comprobar(destino) == []


def test_el_check_falla_si_queda_un_marcador(build_site, tmp_path):
    """Verificado al revés: con un marcador vivo, `comprobar` tiene que denunciarlo."""
    destino = tmp_path / "_site"
    build_site.construir(destino, "9.9.9")
    (destino / "colado.html").write_text("<p>__LD_VERSION__</p>", encoding="utf-8")

    pendientes = build_site.comprobar(destino)
    assert [r.name for r in pendientes] == ["colado.html"]


def test_la_version_declarada_sale_del_pyproject(build_site):
    esperada = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert build_site.version_declarada() == esperada


def test_la_pagina_es_un_documento_completo_y_no_depende_de_la_red():
    """GitHub Pages sirve el fichero tal cual: tiene que bastarse solo.

    Nada de CDNs — ni fuentes, ni scripts, ni hojas de estilo externas. Es la misma razón por
    la que el dashboard lleva Chart.js vendorizado: una dependencia remota es una pieza que un
    día no responde, y aquí además dejaría la tipografía en un fallback silencioso.
    """
    texto = INDEX.read_text(encoding="utf-8")
    assert texto.lstrip().startswith("<!doctype html>")
    assert "<html lang=" in texto and "<title>" in texto

    externos = re.findall(r'(?:src|href)\s*=\s*"(https?://[^"]+)"', texto)
    # La URL del propio sitio entra por `rel="canonical"`: es un metadato que apunta a este
    # mismo documento, no un recurso que el navegador tenga que ir a buscar. Lo que este test
    # protege —que la página no se quede coja si un tercero no responde— sigue igual de vigilado.
    permitidos = ("https://github.com/", "https://pypi.org/", BASE)
    intrusos = [u for u in externos if not u.startswith(permitidos)]
    assert intrusos == [], f"recursos externos en la página: {intrusos}"


def test_los_dos_idiomas_tienen_las_mismas_claves():
    """Una clave sin traducir sale como hueco vacío en la página, sin avisar de nada."""
    texto = INDEX.read_text(encoding="utf-8")
    usadas = set(re.findall(r'data-t="([^"]+)"', texto))
    assert usadas, "la página no declara ninguna ranura de traducción"

    for lang in ("es", "en"):
        bloque = re.search(rf"^    {lang}: \{{(.*?)^    \}}", texto, re.DOTALL | re.MULTILINE)
        assert bloque, f"no se encontró el diccionario '{lang}'"
        definidas = set(re.findall(r"(\w+):\s*[\"']", bloque.group(1)))
        faltan = usadas - definidas
        assert not faltan, f"claves sin traducir en '{lang}': {sorted(faltan)}"


# --- Marca: un solo icono para la landing y el dashboard ---------------------


def test_el_favicon_de_la_landing_es_el_mismo_del_dashboard():
    """La marca vive en el paquete y la landing sirve una copia: tienen que ser idénticas.

    Un icono que se edita en un sitio y no en el otro es la misma clase de verdad duplicada que
    ya costó caro aquí con el número de versión. Si esto falla, copia el canónico:
        cp src/local_delegate/resources/brand/favicon.svg site/favicon.svg
    """
    assert FAVICON_PAQUETE.is_file(), "falta el favicon canónico del paquete"
    assert FAVICON_SITIO.is_file(), "falta site/favicon.svg"
    assert FAVICON_SITIO.read_bytes() == FAVICON_PAQUETE.read_bytes()


def test_el_dashboard_sirve_ese_mismo_favicon():
    """El dashboard no puede tener su propio SVG escrito a mano: lo lee del recurso."""
    from local_delegate.web import metrics

    assert metrics.FAVICON.strip() == FAVICON_PAQUETE.read_text(encoding="utf-8").strip()


def test_la_pagina_apunta_al_favicon_como_fichero_y_no_inline():
    texto = INDEX.read_text(encoding="utf-8")
    assert 'href="favicon.svg"' in texto
    assert "data:image/svg+xml" not in texto, "el icono volvió a estar incrustado en el HTML"


# --- Metadatos sociales -------------------------------------------------------


def test_la_pagina_declara_open_graph_y_twitter_completos():
    """Sin estas etiquetas el enlace compartido sale sin imagen y con título de relleno."""
    texto = INDEX.read_text(encoding="utf-8")
    obligatorias = [
        'property="og:type"',
        'property="og:site_name"',
        'property="og:locale"',
        'property="og:url"',
        'property="og:title"',
        'property="og:description"',
        'property="og:image"',
        'property="og:image:width"',
        'property="og:image:height"',
        'property="og:image:alt"',
        'name="twitter:card"',
        'name="twitter:title"',
        'name="twitter:description"',
        'name="twitter:image"',
        'name="twitter:image:alt"',
    ]
    faltan = [etiqueta for etiqueta in obligatorias if etiqueta not in texto]
    assert not faltan, f"faltan metadatos sociales: {faltan}"


def test_la_tarjeta_es_de_imagen_grande():
    """Con `summary` a secas el PNG se recorta a un cuadrado diminuto y se pierde el diseño."""
    texto = INDEX.read_text(encoding="utf-8")
    assert 'name="twitter:card" content="summary_large_image"' in texto


def test_todas_las_urls_absolutas_de_los_metadatos_apuntan_al_mismo_sitio():
    """La URL está escrita en varios metadatos; si una diverge, el crawler la sigue igual."""
    texto = INDEX.read_text(encoding="utf-8")
    urls = re.findall(r'(?:content|href)="(https://zahirinatzuke\.github\.io[^"]*)"', texto)
    assert len(urls) >= 4, f"se esperaban las URLs de canonical, og:url y las dos imágenes: {urls}"
    intrusas = [u for u in urls if not u.startswith(BASE)]
    assert not intrusas, f"URLs que no cuelgan de {BASE}: {intrusas}"


def test_la_imagen_social_existe_y_mide_1200x630():
    """Las medidas van declaradas en el HTML: si el PNG no coincide, el metadato miente.

    Se leen del propio PNG (cabecera IHDR, stdlib pura) en vez de fiarse del fichero fuente.
    """
    assert OG_IMAGE.is_file(), "falta site/og-image.png"
    cabecera = OG_IMAGE.read_bytes()[:24]
    assert cabecera[:8] == b"\x89PNG\r\n\x1a\n", "site/og-image.png no es un PNG"
    ancho = int.from_bytes(cabecera[16:20], "big")
    alto = int.from_bytes(cabecera[20:24], "big")
    assert (ancho, alto) == (1200, 630)

    texto = INDEX.read_text(encoding="utf-8")
    assert f'property="og:image:width" content="{ancho}"' in texto
    assert f'property="og:image:height" content="{alto}"' in texto


def test_la_fuente_de_la_imagen_social_se_versiona():
    """El PNG no se puede revisar en un diff; lo que se revisa es el HTML que lo genera."""
    fuente = RAIZ / "site" / "og-image.src.html"
    assert fuente.is_file(), "falta site/og-image.src.html, la fuente revisable del PNG"
    assert "1200px" in fuente.read_text(encoding="utf-8")


def test_la_fuente_del_png_no_se_publica_pero_el_png_si(build_site, tmp_path):
    """Es la fuente de un artefacto, no una página: no tiene por qué tener URL pública.

    Mismo criterio por el que se publica `site/` y no `docs/`: nada llega a una URL pública sin
    que alguien lo haya decidido.
    """
    destino = tmp_path / "_site"
    build_site.construir(destino, "9.9.9")
    publicados = {p.name for p in destino.rglob("*") if p.is_file()}
    assert "og-image.src.html" not in publicados
    assert {"index.html", "favicon.svg", "og-image.png"} <= publicados
