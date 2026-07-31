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


def test_el_header_del_dashboard_lleva_la_marca_canonica():
    """El icono del header **es** el favicon, no una copia parecida.

    Hasta la 0.17.0 ahí había un SVG dibujado a mano: al unificar la marca se actualizó el
    favicon y el header se quedó con el icono anterior, así que el panel enseñaba una marca y
    su propia pestaña otra. Ahora se inyecta el mismo fichero y no pueden separarse.
    """
    from local_delegate.web import metrics

    pagina = metrics.render_index()
    canonico = FAVICON_PAQUETE.read_text(encoding="utf-8").strip()

    assert canonico in pagina, "el header no lleva el favicon canónico"
    assert "__BRAND_MARK__" not in pagina, "quedó el marcador sin sustituir"
    # Un solo <svg> dentro del contenedor de marca: si alguien vuelve a escribir uno a mano al
    # lado del inyectado, esto lo caza.
    marca = pagina.split('<span class="mark"', 1)[1].split("</span>", 1)[0]
    assert marca.count("<svg") == 1


def test_la_pagina_apunta_al_favicon_como_fichero_y_no_inline():
    texto = INDEX.read_text(encoding="utf-8")
    assert 'href="favicon.svg"' in texto
    assert "data:image/svg+xml" not in texto, "el icono volvió a estar incrustado en el HTML"


def test_el_titular_no_resalta_la_nube_con_el_amarillo_de_la_via_local():
    """El amarillo de esta paleta significa una cosa sola: la vía que se toma, tu máquina.

    El titular dice «lo mecánico no tiene por qué ir a la nube»; pintar «la nube» con ese
    amarillo —y encima subrayarla— la señalaba como el camino bueno, justo lo contrario de lo
    que dice la frase. La tarjeta social ya lo tenía resuelto en gris y la landing no.
    """
    texto = INDEX.read_text(encoding="utf-8")

    regla = re.search(r"\.hero h1 \.hl\s*\{([^}]*)\}", texto)
    assert regla, "no se encontró la regla del resalte del titular"
    assert "--local" not in regla.group(1), (
        "el resalte del titular volvió al amarillo de la vía local: " + regla.group(1).strip()
    )

    for lang, esperado in (("es", "la nube"), ("en", "the cloud")):
        bloque = re.search(rf"^    {lang}: \{{(.*?)^    \}}", texto, re.DOTALL | re.MULTILINE)
        assert bloque, f"no se encontró el diccionario '{lang}'"
        resaltado = re.search(r'hero_h1:.*?<span class="hl">(.*?)</span>', bloque.group(1))
        assert resaltado, f"el titular de '{lang}' no resalta nada"
        real = resaltado.group(1)
        assert real == esperado, f"el titular de '{lang}' resalta «{real}» y no «{esperado}»"


def test_el_idioma_activo_no_se_marca_con_el_amarillo_de_la_via_local():
    """Elegir idioma no es tomar una ruta, y el amarillo de esta paleta significa exactamente eso.

    Es la misma mezcla del titular, en otra superficie: un token semántico usado como color de
    estado de una UI. Se marca invirtiendo (`--ink` de fondo, `--paper` de texto), que además
    se resuelve solo en los dos temas.
    """
    texto = INDEX.read_text(encoding="utf-8")

    regla = re.search(r'\.lang button\[aria-pressed="true"\]\s*\{([^}]*)\}', texto)
    assert regla, "no se encontró la regla del idioma activo"
    cuerpo = regla.group(1)

    assert "--local" not in cuerpo, (
        "el idioma activo volvió al amarillo de la vía local: " + cuerpo.strip()
    )

    # El `color` iba declarado dos veces, y la segunda no era residuo: `--ink` es casi blanco en
    # tema oscuro, así que hacía falta un literal para que el texto no desapareciera sobre el
    # amarillo. Al invertir deja de hacer falta — pero si alguien reintroduce el duplicado, es
    # señal de que el fondo volvió a ser un color que no acompaña a `--ink`.
    assert cuerpo.count("color:") == cuerpo.count("-color:") + 1, (
        "la regla del idioma activo declara `color` más de una vez: " + cuerpo.strip()
    )


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


def test_las_descripciones_sociales_caben_en_lo_que_muestran_las_plataformas():
    """Una descripción larga no se muestra entera: se trunca, y casi siempre a media frase.

    El corte ronda los 160 caracteres en la mayoría de plataformas. La que había en `og:description`
    medía 213 y se perdía justo el final, que es donde estaba el argumento.
    """
    texto = INDEX.read_text(encoding="utf-8")
    largos = {
        clave: len(valor)
        for clave, valor in re.findall(
            r'(?:name|property)="((?:og:|twitter:)?description)"\s+content="([^"]*)"', texto
        )
    }
    assert {"description", "og:description", "twitter:description"} <= set(largos), largos

    for clave in ("og:description", "twitter:description"):
        assert 110 <= largos[clave] <= 160, f"{clave} mide {largos[clave]} caracteres"

    # Las dos sociales dicen lo mismo: que sean el mismo texto es lo que evita que se separen.
    sociales = set(re.findall(r'(?:og|twitter):description"\s+content="([^"]*)"', texto))
    assert len(sociales) == 1, f"og:description y twitter:description divergieron: {sociales}"


def test_la_pagina_declara_la_cuenta_de_x():
    """Sin `twitter:site` la tarjeta no atribuye el contenido a nadie."""
    texto = INDEX.read_text(encoding="utf-8")
    cuentas = set(re.findall(r'name="twitter:(?:site|creator)" content="([^"]+)"', texto))
    assert cuentas == {"@ZahiriNatZuke"}, cuentas


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


def test_las_fuentes_no_se_publican_pero_sus_artefactos_si(build_site, tmp_path):
    """Son la fuente de un artefacto, no páginas: no tienen por qué tener URL pública.

    Mismo criterio por el que se publica `site/` y no `docs/`: nada llega a una URL pública sin
    que alguien lo haya decidido.
    """
    destino = tmp_path / "_site"
    build_site.construir(destino, "9.9.9")
    publicados = {p.name for p in destino.rglob("*") if p.is_file()}
    assert not [p for p in publicados if p.endswith(".src.html")]
    assert {
        "index.html",
        "favicon.svg",
        "og-image.png",
        "favicon-32x32.png",
        "apple-touch-icon.png",
        "site.webmanifest",
    } <= publicados


# --- Iconos rasterizados, manifest y datos estructurados ----------------------


def _cabecera_png(ruta: Path) -> tuple[int, int]:
    """Ancho y alto leídos del IHDR. Stdlib pura: el PNG es la verdad, no el fichero fuente."""
    cabecera = ruta.read_bytes()[:24]
    assert cabecera[:8] == b"\x89PNG\r\n\x1a\n", f"{ruta.name} no es un PNG"
    return int.from_bytes(cabecera[16:20], "big"), int.from_bytes(cabecera[20:24], "big")


def test_los_iconos_png_existen_y_miden_lo_que_declara_la_pagina():
    """Un `sizes` que no coincide con el PNG es un metadato que miente, igual que og:image.

    iOS no usa el SVG para la pantalla de inicio: sin estos PNG hace una captura de la página.
    """
    texto = INDEX.read_text(encoding="utf-8")
    declarados = re.findall(r'<link[^>]*sizes="(\d+)x(\d+)"[^>]*href="([^"]+\.png)"', texto)
    assert len(declarados) == 2, f"se esperaban el favicon PNG y el apple-touch-icon: {declarados}"

    for ancho, alto, href in declarados:
        fichero = RAIZ / "site" / href
        assert fichero.is_file(), f"la página declara {href} y no está en site/"
        medido = _cabecera_png(fichero)
        esperado = (int(ancho), int(alto))
        assert medido == esperado, f"{href} mide {medido} y el <link> declara {esperado}"


# --- Los PNG atados al icono del que salieron ---------------------------------
#
# Lo de arriba comprueba que los PNG existen, que son PNG y que miden lo declarado. Nada miraba si
# su CONTENIDO sigue correspondiéndose con `favicon.svg`, así que tocar el icono y no regenerarlos
# dejaba la marca desincronizada en silencio — el propio repo lo llamaba «riesgo aceptado».
#
# No se resuelve rasterizando en el CI (dependencia pesada por un riesgo pequeño) sino **por
# procedencia**: `site/icons.json` registra el sha256 del SVG con el que se generaron, y aquí se
# compara con el del SVG actual. Mismo patrón que el manifiesto de la captura del README.

ICONS_JSON = RAIZ / "site" / "icons.json"


def _manifiesto_iconos() -> dict:
    return json.loads(ICONS_JSON.read_text(encoding="utf-8"))


def test_los_png_se_generaron_con_el_favicon_svg_actual():
    """Si el icono cambia y nadie regenera los PNG, esto falla — que es todo el objetivo.

    El manifiesto lo escribe `scripts/dev/capture_icons.py` al capturar y **nunca se toca a
    mano**: uno actualizado a mano cumpliría el check sin que nadie regenerara nada.
    """
    svg = RAIZ / "site" / "favicon.svg"
    actual = hashlib.sha256(svg.read_bytes()).hexdigest()
    registrado = _manifiesto_iconos()["source_sha256"]

    assert actual == registrado, (
        "site/favicon.svg cambió y los PNG de la marca siguen siendo los de antes. "
        "Regenéralos con: uv run python scripts/dev/capture_icons.py"
    )


def test_el_manifiesto_describe_los_png_que_hay_en_disco():
    """Un manifiesto que no corresponde con los ficheros no ata nada.

    Cubre el caso de regenerar los PNG a mano —siguiendo el procedimiento de `icon.src.html`— sin
    pasar por el script: el sha del SVG cuadraría y los PNG serían otros.
    """
    for icono in _manifiesto_iconos()["icons"]:
        png = RAIZ / "site" / icono["file"]
        assert png.is_file(), f"el manifiesto declara {icono['file']} y no está en site/"

        blob = png.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == icono["sha256"], (
            f"{icono['file']} no es el que registra site/icons.json. "
            "Regenéralo con: uv run python scripts/dev/capture_icons.py"
        )
        assert len(blob) == icono["bytes"]
        assert _cabecera_png(png) == (icono["size"], icono["size"])


def test_el_manifiesto_cubre_todos_los_png_de_la_marca():
    """Por conjuntos iguales: añadir un icono y olvidarlo aquí lo dejaría sin atar."""
    declarados = {i["file"] for i in _manifiesto_iconos()["icons"]}
    en_disco = {p.name for p in (RAIZ / "site").glob("*.png")} - {"og-image.png"}
    assert declarados == en_disco, (
        f"el manifiesto de iconos y los PNG de site/ no coinciden: {declarados} vs {en_disco}"
    )


def test_ninguna_ruta_de_la_pagina_es_absoluta():
    """Esto es un GitHub Pages *de proyecto*, y ahí una ruta absoluta se sale del repo.

    `/favicon.ico` apunta a la raíz de zahirinatzuke.github.io, que pertenece a otro sitio (da
    404). Es el error que traen los snippets de todos los analizadores de metadatos, así que este
    test existe para que no entre por copiar uno.
    """
    texto = INDEX.read_text(encoding="utf-8")
    absolutas = re.findall(r'(?:href|src)="(/[^/"][^"]*)"', texto)
    assert absolutas == [], f"rutas absolutas en la página: {absolutas}"


def test_el_manifest_es_json_valido_y_sus_iconos_existen():
    """Un manifest que apunta a un icono que no está es peor que no tenerlo."""
    manifest = RAIZ / "site" / "site.webmanifest"
    assert manifest.is_file(), "falta site/site.webmanifest"
    assert 'rel="manifest" href="site.webmanifest"' in INDEX.read_text(encoding="utf-8")

    datos = json.loads(manifest.read_text(encoding="utf-8"))
    assert datos["icons"], "el manifest no declara ningún icono"
    for icono in datos["icons"]:
        assert (RAIZ / "site" / icono["src"]).is_file(), f"el manifest apunta a {icono['src']}"

    # La landing no es una PWA y el manifest no puede fingir que lo es: sin service worker,
    # `standalone` solo consigue que Android ofrezca instalar algo que no funciona sin red.
    assert datos["display"] == "browser"
    assert datos["theme_color"] == "#0D1A1D", "el manifest y el theme-color del HTML se separaron"


def test_los_datos_estructurados_describen_el_programa_y_parsean():
    """JSON-LD roto es JSON-LD que el buscador descarta entero, y sin avisar de nada."""
    texto = INDEX.read_text(encoding="utf-8")
    bloque = re.search(r'<script type="application/ld\+json">(.*?)</script>', texto, re.DOTALL)
    assert bloque, "la página no declara datos estructurados"

    datos = json.loads(bloque.group(1))
    assert datos["@context"] == "https://schema.org"
    # `SoftwareApplication` y no la `WebPage` genérica: esto es un programa, y ese es el
    # vocabulario que un buscador puede aprovechar para algo.
    assert datos["@type"] == "SoftwareApplication"
    assert datos["url"] == BASE
    assert datos["softwareVersion"] == "__LD_VERSION__", "la versión se escribió a mano"
