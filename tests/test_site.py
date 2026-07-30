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
    permitidos = ("https://github.com/", "https://pypi.org/")
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
