"""La landing de GitHub Pages: que la versión se inyecte y que nadie la escriba a mano.

El riesgo real de esta pieza no es que se rompa el CSS: es que el número de versión se quede
clavado en la página mientras el paquete avanza, que es exactamente lo que pasó dentro del
prototipo (estaba escrito dos veces y con la primera release ya mentía en una). Por eso los
tests miran el contrato de la inyección, no el diseño.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "site" / "index.html"
SITE_FAVICON = ROOT / "site" / "favicon.svg"
PACKAGE_FAVICON = ROOT / "src" / "local_delegate" / "resources" / "brand" / "favicon.svg"
OG_IMAGE = ROOT / "site" / "og-image.png"
BASE = "https://zahirinatzuke.github.io/local-delegate/"


def _load_build_site():
    """Carga scripts/build_site.py como módulo (el patrón de tests/test_bump_version.py)."""
    path = ROOT / "scripts" / "build_site.py"
    spec = importlib.util.spec_from_file_location("build_site", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_site():
    return _load_build_site()


def test_the_page_carries_the_marker_and_no_literal_version():
    """Si alguien escribe la versión a mano en la página, este test lo caza."""
    text = INDEX.read_text(encoding="utf-8")
    assert "__LD_VERSION__" in text

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    # Una versión X.Y.Z escrita a pelo en el fuente es el defecto que esto previene.
    assert version not in text, f"la versión {version} está escrita a mano en {INDEX.name}"

    # Y cualquier OTRA versión literal, no solo la de hoy: si alguien pone la 0.15.0, esto la
    # caza igual. Los `lookaround` excluyen los cuartetos punteados — `127.0.0.1` es una IP
    # legítima de la página (el puerto del panel), no un número de versión.
    literals = re.findall(r"(?<![\d.])v?\d+\.\d+\.\d+(?![\d.])", text)
    assert literals == [], f"números de versión escritos a mano: {literals}"


def test_the_build_replaces_the_marker_with_the_pyproject_version(build_site, tmp_path):
    dest = tmp_path / "_site"
    written = build_site.build(dest, "9.9.9")

    assert written, "el build no tocó ningún fichero"
    output = (dest / "index.html").read_text(encoding="utf-8")
    assert 'var VERSION = "9.9.9"' in output
    assert "__LD_VERSION__" not in output
    assert build_site.check(dest) == []


def test_the_check_fails_if_a_marker_remains(build_site, tmp_path):
    """Verificado al revés: con un marcador vivo, `comprobar` tiene que denunciarlo."""
    dest = tmp_path / "_site"
    build_site.build(dest, "9.9.9")
    (dest / "colado.html").write_text("<p>__LD_VERSION__</p>", encoding="utf-8")

    pending = build_site.check(dest)
    assert [r.name for r in pending] == ["colado.html"]


def test_the_declared_version_comes_from_the_pyproject(build_site):
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert build_site.declared_version() == expected


def test_the_page_is_a_complete_document_and_does_not_depend_on_the_network():
    """GitHub Pages sirve el fichero tal cual: tiene que bastarse solo.

    Nada de CDNs — ni fuentes, ni scripts, ni hojas de estilo externas. Es la misma razón por
    la que el dashboard lleva Chart.js vendorizado: una dependencia remota es una pieza que un
    día no responde, y aquí además dejaría la tipografía en un fallback silencioso.
    """
    text = INDEX.read_text(encoding="utf-8")
    assert text.lstrip().startswith("<!doctype html>")
    assert "<html lang=" in text and "<title>" in text

    external = re.findall(r'(?:src|href)\s*=\s*"(https?://[^"]+)"', text)
    # La URL del propio sitio entra por `rel="canonical"`: es un metadato que apunta a este
    # mismo documento, no un recurso que el navegador tenga que ir a buscar. Lo que este test
    # protege —que la página no se quede coja si un tercero no responde— sigue igual de vigilado.
    allowed = ("https://github.com/", "https://pypi.org/", BASE)
    intruders = [u for u in external if not u.startswith(allowed)]
    assert intruders == [], f"recursos externos en la página: {intruders}"


def test_both_languages_have_the_same_keys():
    """Una clave sin traducir sale como hueco vacío en la página, sin avisar de nada."""
    text = INDEX.read_text(encoding="utf-8")
    used = set(re.findall(r'data-t="([^"]+)"', text))
    assert used, "la página no declara ninguna ranura de traducción"

    for lang in ("es", "en"):
        block = re.search(rf"^    {lang}: \{{(.*?)^    \}}", text, re.DOTALL | re.MULTILINE)
        assert block, f"no se encontró el diccionario '{lang}'"
        defined = set(re.findall(r"(\w+):\s*[\"']", block.group(1)))
        missing = used - defined
        assert not missing, f"claves sin traducir en '{lang}': {sorted(missing)}"


# --- Marca: un solo icono para la landing y el dashboard ---------------------


def test_the_landing_favicon_is_the_same_as_the_dashboards():
    """La marca vive en el paquete y la landing sirve una copia: tienen que ser idénticas.

    Un icono que se edita en un sitio y no en el otro es la misma clase de verdad duplicada que
    ya costó caro aquí con el número de versión. Si esto falla, copia el canónico:
        cp src/local_delegate/resources/brand/favicon.svg site/favicon.svg
    """
    assert PACKAGE_FAVICON.is_file(), "falta el favicon canónico del paquete"
    assert SITE_FAVICON.is_file(), "falta site/favicon.svg"
    assert SITE_FAVICON.read_bytes() == PACKAGE_FAVICON.read_bytes()


def test_the_dashboard_serves_that_same_favicon():
    """El dashboard no puede tener su propio SVG escrito a mano: lo lee del recurso."""
    from local_delegate.web import metrics

    assert metrics.FAVICON.strip() == PACKAGE_FAVICON.read_text(encoding="utf-8").strip()


def test_the_dashboard_header_carries_the_canonical_mark():
    """El icono del header **es** el favicon, no una copia parecida.

    Hasta la 0.17.0 ahí había un SVG dibujado a mano: al unificar la marca se actualizó el
    favicon y el header se quedó con el icono anterior, así que el panel enseñaba una marca y
    su propia pestaña otra. Ahora se inyecta el mismo fichero y no pueden separarse.
    """
    from local_delegate.web import metrics

    page = metrics.render_index()
    canonical = PACKAGE_FAVICON.read_text(encoding="utf-8").strip()

    assert canonical in page, "el header no lleva el favicon canónico"
    assert "__BRAND_MARK__" not in page, "quedó el marcador sin sustituir"
    # Un solo <svg> dentro del contenedor de marca: si alguien vuelve a escribir uno a mano al
    # lado del inyectado, esto lo caza.
    mark = page.split('<span class="mark"', 1)[1].split("</span>", 1)[0]
    assert mark.count("<svg") == 1


def test_the_page_points_to_the_favicon_as_a_file_not_inline():
    text = INDEX.read_text(encoding="utf-8")
    assert 'href="favicon.svg"' in text
    assert "data:image/svg+xml" not in text, "el icono volvió a estar incrustado en el HTML"


def test_the_headline_does_not_highlight_the_cloud_with_the_local_path_yellow():
    """El amarillo de esta paleta significa una cosa sola: la vía que se toma, tu máquina.

    El titular dice «lo mecánico no tiene por qué ir a la nube»; pintar «la nube» con ese
    amarillo —y encima subrayarla— la señalaba como el camino bueno, justo lo contrario de lo
    que dice la frase. La tarjeta social ya lo tenía resuelto en gris y la landing no.
    """
    text = INDEX.read_text(encoding="utf-8")

    rule = re.search(r"\.hero h1 \.hl\s*\{([^}]*)\}", text)
    assert rule, "no se encontró la regla del resalte del titular"
    assert "--local" not in rule.group(1), (
        "el resalte del titular volvió al amarillo de la vía local: " + rule.group(1).strip()
    )

    for lang, expected in (("es", "la nube"), ("en", "the cloud")):
        block = re.search(rf"^    {lang}: \{{(.*?)^    \}}", text, re.DOTALL | re.MULTILINE)
        assert block, f"no se encontró el diccionario '{lang}'"
        highlighted = re.search(r'hero_h1:.*?<span class="hl">(.*?)</span>', block.group(1))
        assert highlighted, f"el titular de '{lang}' no resalta nada"
        real = highlighted.group(1)
        assert real == expected, f"el titular de '{lang}' resalta «{real}» y no «{expected}»"


def test_the_active_language_is_not_marked_with_the_local_path_yellow():
    """Elegir idioma no es tomar una ruta, y el amarillo de esta paleta significa exactamente eso.

    Es la misma mezcla del titular, en otra superficie: un token semántico usado como color de
    estado de una UI. Se marca invirtiendo (`--ink` de fondo, `--paper` de texto), que además
    se resuelve solo en los dos temas.
    """
    text = INDEX.read_text(encoding="utf-8")

    rule = re.search(r'\.lang button\[aria-pressed="true"\]\s*\{([^}]*)\}', text)
    assert rule, "no se encontró la regla del idioma activo"
    body = rule.group(1)

    assert "--local" not in body, (
        "el idioma activo volvió al amarillo de la vía local: " + body.strip()
    )

    # El `color` iba declarado dos veces, y la segunda no era residuo: `--ink` es casi blanco en
    # tema oscuro, así que hacía falta un literal para que el texto no desapareciera sobre el
    # amarillo. Al invertir deja de hacer falta — pero si alguien reintroduce el duplicado, es
    # señal de que el fondo volvió a ser un color que no acompaña a `--ink`.
    assert body.count("color:") == body.count("-color:") + 1, (
        "la regla del idioma activo declara `color` más de una vez: " + body.strip()
    )


# --- Metadatos sociales -------------------------------------------------------


def test_the_page_declares_complete_open_graph_and_twitter():
    """Sin estas etiquetas el enlace compartido sale sin imagen y con título de relleno."""
    text = INDEX.read_text(encoding="utf-8")
    required = [
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
    missing = [label for label in required if label not in text]
    assert not missing, f"faltan metadatos sociales: {missing}"


def test_the_social_descriptions_fit_what_the_platforms_show():
    """Una descripción larga no se muestra entera: se trunca, y casi siempre a media frase.

    El corte ronda los 160 caracteres en la mayoría de plataformas. La que había en `og:description`
    medía 213 y se perdía justo el final, que es donde estaba el argumento.
    """
    text = INDEX.read_text(encoding="utf-8")
    long_ones = {
        key: len(value)
        for key, value in re.findall(
            r'(?:name|property)="((?:og:|twitter:)?description)"\s+content="([^"]*)"', text
        )
    }
    assert {"description", "og:description", "twitter:description"} <= set(long_ones), long_ones

    for key in ("og:description", "twitter:description"):
        assert 110 <= long_ones[key] <= 160, f"{key} mide {long_ones[key]} caracteres"

    # Las dos sociales dicen lo mismo: que sean el mismo texto es lo que evita que se separen.
    social = set(re.findall(r'(?:og|twitter):description"\s+content="([^"]*)"', text))
    assert len(social) == 1, f"og:description y twitter:description divergieron: {social}"


def test_the_page_declares_the_x_account():
    """Sin `twitter:site` la tarjeta no atribuye el contenido a nadie."""
    text = INDEX.read_text(encoding="utf-8")
    accounts = set(re.findall(r'name="twitter:(?:site|creator)" content="([^"]+)"', text))
    assert accounts == {"@ZahiriNatZuke"}, accounts


def test_the_card_is_large_image():
    """Con `summary` a secas el PNG se recorta a un cuadrado diminuto y se pierde el diseño."""
    text = INDEX.read_text(encoding="utf-8")
    assert 'name="twitter:card" content="summary_large_image"' in text


def test_every_absolute_metadata_url_points_to_the_same_site():
    """La URL está escrita en varios metadatos; si una diverge, el crawler la sigue igual."""
    text = INDEX.read_text(encoding="utf-8")
    urls = re.findall(r'(?:content|href)="(https://zahirinatzuke\.github\.io[^"]*)"', text)
    assert len(urls) >= 4, f"se esperaban las URLs de canonical, og:url y las dos imágenes: {urls}"
    intruders = [u for u in urls if not u.startswith(BASE)]
    assert not intruders, f"URLs que no cuelgan de {BASE}: {intruders}"


def test_the_social_image_exists_and_is_1200x630():
    """Las medidas van declaradas en el HTML: si el PNG no coincide, el metadato miente.

    Se leen del propio PNG (cabecera IHDR, stdlib pura) en vez de fiarse del fichero fuente.
    """
    assert OG_IMAGE.is_file(), "falta site/og-image.png"
    header = OG_IMAGE.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", "site/og-image.png no es un PNG"
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    assert (width, height) == (1200, 630)

    text = INDEX.read_text(encoding="utf-8")
    assert f'property="og:image:width" content="{width}"' in text
    assert f'property="og:image:height" content="{height}"' in text


def test_the_social_image_source_is_versioned():
    """El PNG no se puede revisar en un diff; lo que se revisa es el HTML que lo genera."""
    source = ROOT / "site" / "og-image.src.html"
    assert source.is_file(), "falta site/og-image.src.html, la fuente revisable del PNG"
    assert "1200px" in source.read_text(encoding="utf-8")


def test_the_sources_are_not_published_but_their_artifacts_are(build_site, tmp_path):
    """Son la fuente de un artefacto, no páginas: no tienen por qué tener URL pública.

    Mismo criterio por el que se publica `site/` y no `docs/`: nada llega a una URL pública sin
    que alguien lo haya decidido.
    """
    dest = tmp_path / "_site"
    build_site.build(dest, "9.9.9")
    published = {p.name for p in dest.rglob("*") if p.is_file()}
    assert not [p for p in published if p.endswith(".src.html")]
    assert {
        "index.html",
        "favicon.svg",
        "og-image.png",
        "favicon-32x32.png",
        "apple-touch-icon.png",
        "site.webmanifest",
    } <= published


# --- Iconos rasterizados, manifest y datos estructurados ----------------------


def _png_header(path: Path) -> tuple[int, int]:
    """Ancho y alto leídos del IHDR. Stdlib pura: el PNG es la verdad, no el fichero fuente."""
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} no es un PNG"
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def test_the_png_icons_exist_and_measure_what_the_page_declares():
    """Un `sizes` que no coincide con el PNG es un metadato que miente, igual que og:image.

    iOS no usa el SVG para la pantalla de inicio: sin estos PNG hace una captura de la página.
    """
    text = INDEX.read_text(encoding="utf-8")
    declared = re.findall(r'<link[^>]*sizes="(\d+)x(\d+)"[^>]*href="([^"]+\.png)"', text)
    assert len(declared) == 2, f"se esperaban el favicon PNG y el apple-touch-icon: {declared}"

    for width, height, href in declared:
        file = ROOT / "site" / href
        assert file.is_file(), f"la página declara {href} y no está en site/"
        measured = _png_header(file)
        expected = (int(width), int(height))
        assert measured == expected, f"{href} mide {measured} y el <link> declara {expected}"


# --- Los PNG atados al icono del que salieron ---------------------------------
#
# Lo de arriba comprueba que los PNG existen, que son PNG y que miden lo declarado. Nada miraba si
# su CONTENIDO sigue correspondiéndose con `favicon.svg`, así que tocar el icono y no regenerarlos
# dejaba la marca desincronizada en silencio — el propio repo lo llamaba «riesgo aceptado».
#
# No se resuelve rasterizando en el CI (dependencia pesada por un riesgo pequeño) sino **por
# procedencia**: `site/icons.json` registra el sha256 del SVG con el que se generaron, y aquí se
# compara con el del SVG actual. Mismo patrón que el manifiesto de la captura del README.

ICONS_JSON = ROOT / "site" / "icons.json"


def _icon_manifest() -> dict:
    return json.loads(ICONS_JSON.read_text(encoding="utf-8"))


def test_the_pngs_were_generated_from_the_current_favicon_svg():
    """Si el icono cambia y nadie regenera los PNG, esto falla — que es todo el objetivo.

    El manifiesto lo escribe `scripts/dev/capture_icons.py` al capturar y **nunca se toca a
    mano**: uno actualizado a mano cumpliría el check sin que nadie regenerara nada.
    """
    svg = ROOT / "site" / "favicon.svg"
    # Normalizado a LF, igual que lo escribe el script. Con los bytes crudos, el mismo commit daba
    # un hash en Linux y otro en el runner de Windows: git entrega el texto con los finales de
    # línea de cada máquina. Lo cazó el CI a la primera, y es lo que justifica la matriz de tres
    # sistemas. Los PNG no lo necesitan: son binarios y git no los toca.
    current = hashlib.sha256(svg.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    recorded = _icon_manifest()["source_sha256"]

    assert current == recorded, (
        "site/favicon.svg cambió y los PNG de la marca siguen siendo los de antes. "
        "Regenéralos con: uv run python scripts/dev/capture_icons.py"
    )


def test_the_icon_manifest_describes_the_pngs_on_disk():
    """Un manifiesto que no corresponde con los ficheros no ata nada.

    Cubre el caso de regenerar los PNG a mano —siguiendo el procedimiento de `icon.src.html`— sin
    pasar por el script: el sha del SVG cuadraría y los PNG serían otros.
    """
    for icon in _icon_manifest()["icons"]:
        png = ROOT / "site" / icon["file"]
        assert png.is_file(), f"el manifiesto declara {icon['file']} y no está en site/"

        blob = png.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == icon["sha256"], (
            f"{icon['file']} no es el que registra site/icons.json. "
            "Regenéralo con: uv run python scripts/dev/capture_icons.py"
        )
        assert len(blob) == icon["bytes"]
        assert _png_header(png) == (icon["size"], icon["size"])


def test_the_icon_manifest_covers_every_brand_png():
    """Por conjuntos iguales: añadir un icono y olvidarlo aquí lo dejaría sin atar."""
    declared = {i["file"] for i in _icon_manifest()["icons"]}
    on_disk = {p.name for p in (ROOT / "site").glob("*.png")} - {"og-image.png"}
    assert declared == on_disk, (
        f"el manifiesto de iconos y los PNG de site/ no coinciden: {declared} vs {on_disk}"
    )


def test_no_page_path_is_absolute():
    """Esto es un GitHub Pages *de proyecto*, y ahí una ruta absoluta se sale del repo.

    `/favicon.ico` apunta a la raíz de zahirinatzuke.github.io, que pertenece a otro sitio (da
    404). Es el error que traen los snippets de todos los analizadores de metadatos, así que este
    test existe para que no entre por copiar uno.
    """
    text = INDEX.read_text(encoding="utf-8")
    absolute_ones = re.findall(r'(?:href|src)="(/[^/"][^"]*)"', text)
    assert absolute_ones == [], f"rutas absolutas en la página: {absolute_ones}"


def test_the_manifest_is_valid_json_and_its_icons_exist():
    """Un manifest que apunta a un icono que no está es peor que no tenerlo."""
    manifest = ROOT / "site" / "site.webmanifest"
    assert manifest.is_file(), "falta site/site.webmanifest"
    assert 'rel="manifest" href="site.webmanifest"' in INDEX.read_text(encoding="utf-8")

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["icons"], "el manifest no declara ningún icono"
    for icon in data["icons"]:
        assert (ROOT / "site" / icon["src"]).is_file(), f"el manifest apunta a {icon['src']}"

    # La landing no es una PWA y el manifest no puede fingir que lo es: sin service worker,
    # `standalone` solo consigue que Android ofrezca instalar algo que no funciona sin red.
    assert data["display"] == "browser"
    assert data["theme_color"] == "#0D1A1D", "el manifest y el theme-color del HTML se separaron"


def test_the_structured_data_describes_the_program_and_parses():
    """JSON-LD roto es JSON-LD que el buscador descarta entero, y sin avisar de nada."""
    text = INDEX.read_text(encoding="utf-8")
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.DOTALL)
    assert block, "la página no declara datos estructurados"

    data = json.loads(block.group(1))
    assert data["@context"] == "https://schema.org"
    # `SoftwareApplication` y no la `WebPage` genérica: esto es un programa, y ese es el
    # vocabulario que un buscador puede aprovechar para algo.
    assert data["@type"] == "SoftwareApplication"
    assert data["url"] == BASE
    assert data["softwareVersion"] == "__LD_VERSION__", "la versión se escribió a mano"
