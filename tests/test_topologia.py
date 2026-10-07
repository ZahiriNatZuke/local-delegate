"""Lector de topologia (T7): la regla de choques de llama-swap v255, TTL efectivo y relectura.

Los YAML sinteticos van escritos aqui mismo, al lado de lo que prueban. Los de
`tests/fixtures/topologia/` son copias saneadas de configs reales (claves y rutas sustituidas):
guardan que la regla dice sobre ficheros de verdad lo mismo que la tabla de casos.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from local_delegate import topologia
from local_delegate.topologia import Foto, SinTopologia

FIXTURES = Path(__file__).parent / "fixtures" / "topologia"


def _foto(tmp_path: Path, yaml_texto: str) -> Foto | SinTopologia:
    ruta = tmp_path / "config.yaml"
    ruta.write_text(textwrap.dedent(yaml_texto), encoding="utf-8")
    return topologia.leer(ruta)


def _modelos(*ids: str, ttl: int | None = 120) -> str:
    lineas = ["models:"]
    for mid in ids:
        lineas.append(f"  {mid}:")
        lineas.append(f"    cmd: llama-server --model /m/{mid}.gguf")
        if ttl is not None:
            lineas.append(f"    ttl: {ttl}")
    return "\n".join(lineas) + "\n"


@pytest.fixture(autouse=True)
def _cache_limpia():
    topologia._olvidar()
    yield
    topologia._olvidar()


# --- Tabla de casos contra EvictionFor -------------------------------------------------------


def test_mismo_grupo_con_swap_chocan_y_sin_swap_no(tmp_path):
    f = _foto(
        tmp_path,
        _modelos("a", "b", "c", "d")
        + """\
groups:
  con_swap:
    swap: true
    members: [a, b]
  sin_swap:
    swap: false
    exclusive: false
    members: [c, d]
""",
    )
    assert isinstance(f, Foto)
    assert f.choca("a", "b")
    assert f.choca("b", "a")
    assert not f.choca("c", "d")
    assert not f.choca("d", "c")


def test_grupo_sin_claves_desaloja_a_otro_grupo(tmp_path):
    # «g1» no dice nada: por defecto es exclusive. «g2» no es exclusive ni persistent.
    f = _foto(
        tmp_path,
        _modelos("a", "b")
        + """\
groups:
  g1:
    members: [a]
  g2:
    exclusive: false
    members: [b]
""",
    )
    assert f.choca("a", "b")
    assert f.grupos["g1"].exclusive is True


def test_exclusive_solo_en_b_choca_en_los_dos_sentidos(tmp_path):
    f = _foto(
        tmp_path,
        _modelos("a", "b")
        + """\
groups:
  ga:
    exclusive: false
    members: [a]
  gb:
    exclusive: true
    members: [b]
""",
    )
    # Cargar «a» no desaloja a «b» (ga no es exclusive); cargar «b» desaloja a «a».
    assert not f._desaloja("a", "b")
    assert f._desaloja("b", "a")
    assert f.choca("a", "b")
    assert f.choca("b", "a")


def test_exclusive_contra_persistent(tmp_path):
    f = _foto(
        tmp_path,
        _modelos("a", "b", "p")
        + """\
groups:
  ga:
    members: [a]
  fijo:
    persistent: true
    swap: false
    exclusive: false
    members: [b]
  fijo_exclusivo:
    persistent: true
    members: [p]
""",
    )
    # ga es exclusive pero «fijo» es persistent y no exclusive: nadie desaloja a nadie.
    assert not f.choca("a", "b")
    assert not f.choca("b", "a")
    # Un grupo persistent con exclusive por defecto SI desaloja a los demas al cargar.
    assert f.choca("p", "a")
    assert f.choca("a", "p")


def test_un_modelo_nunca_choca_consigo_mismo(tmp_path):
    f = _foto(tmp_path, _modelos("a", "b") + "groups:\n  g:\n    members: [a, b]\n")
    assert f.choca("a", "b")
    assert not f.choca("a", "a")


def test_modelo_que_no_esta_en_la_config_es_compatible_con_todos(tmp_path):
    f = _foto(tmp_path, _modelos("a", "b") + "groups:\n  g:\n    members: [a, b]\n")
    assert not f.choca("fantasma", "a")
    assert not f.choca("a", "fantasma")
    assert f.ttl_efectivo("fantasma") is None


# --- (default) -------------------------------------------------------------------------------


def test_modelos_sin_grupo_van_a_default_y_chocan_con_lo_no_persistente(tmp_path):
    f = _foto(
        tmp_path,
        _modelos("suelto", "gemma4-26b-a4b", "fijo")
        + """\
groups:
  swap:
    swap: true
    exclusive: false
    members: [gemma4-26b-a4b]
  resident:
    persistent: true
    swap: false
    exclusive: false
    members: [fijo]
""",
    )
    assert f.choca("suelto", "gemma4-26b-a4b")
    assert f.grupo("suelto") == "(default)"
    assert f.grupos["(default)"].miembros == ("suelto",)
    assert not f.choca("suelto", "fijo")


def test_sin_grupos_todos_van_a_default(tmp_path):
    f = _foto(tmp_path, _modelos("a", "b"))
    assert f.grupos["(default)"].miembros == ("a", "b")
    assert f.choca("a", "b")


# --- Las dos sintaxis y matrix ---------------------------------------------------------------

# Con estos grupos «a» (persistent, no exclusive) no choca con «b»; «b» y «c» comparten
# grupo con swap. Si se leyera mal la sintaxis, los tres irian a `(default)` y «a» chocaria
# con «b».
_GRUPOS = """\
    g1:
      persistent: true
      swap: false
      exclusive: false
      members: [a]
    g2:
      exclusive: false
      members: [b, c]
"""


def test_sintaxis_routing_router_settings_groups(tmp_path):
    f = _foto(
        tmp_path,
        _modelos("a", "b", "c")
        + "routing:\n  router:\n    use: group\n    settings:\n      groups:\n"
        + textwrap.indent(_GRUPOS, "    "),
    )
    assert isinstance(f, Foto)
    assert not f.choca("a", "b")
    assert f.choca("b", "c")
    assert f.grupo("a") == "g1"


def test_sintaxis_groups_arriba(tmp_path):
    f = _foto(
        tmp_path,
        _modelos("a", "b", "c") + "groups:\n" + textwrap.indent(textwrap.dedent(_GRUPOS), "  "),
    )
    assert not f.choca("a", "b")
    assert f.choca("b", "c")
    assert f.grupo("a") == "g1"


def test_las_dos_sintaxis_a_la_vez(tmp_path):
    f = _foto(
        tmp_path,
        _modelos("a", "b")
        + "groups:\n  g:\n    members: [a]\n"
        + "routing:\n  router:\n    settings:\n      groups:\n        h:\n          members: [b]\n",
    )
    assert f == SinTopologia("dos sintaxis")


def test_router_matrix(tmp_path):
    f = _foto(
        tmp_path,
        _modelos("a", "b")
        + "routing:\n  router:\n    use: matrix\n    settings:\n      matrix:\n        sets: {}\n",
    )
    assert f == SinTopologia("matrix")
    g = _foto(tmp_path, _modelos("a") + "matrix:\n  sets: {}\n")
    assert g == SinTopologia("matrix")


# --- Alias -----------------------------------------------------------------------------------


def test_alias_choca_igual_que_el_id_real(tmp_path):
    f = _foto(
        tmp_path,
        """\
models:
  gemma4-26b-a4b:
    cmd: llama-server --model /m/26b.gguf
    aliases: [alias-del-26b]
  qwen36-35b-a3b:
    cmd: llama-server --model /m/35b.gguf
  gemma3-4b:
    cmd: llama-server --model /m/4b.gguf
groups:
  swap:
    swap: true
    exclusive: false
    members: [gemma4-26b-a4b, qwen36-35b-a3b]
  resident:
    persistent: true
    swap: false
    exclusive: false
    members: [gemma3-4b]
""",
    )
    assert f.choca("alias-del-26b", "qwen36-35b-a3b")
    assert f.choca("gemma4-26b-a4b", "qwen36-35b-a3b")
    assert f.resolver("alias-del-26b") == "gemma4-26b-a4b"
    assert not f.choca("alias-del-26b", "gemma3-4b")


# --- TTL efectivo, residentes, mmproj y precarga ---------------------------------------------


def test_ttl_efectivo_y_residentes(tmp_path):
    f = _foto(
        tmp_path,
        """\
globalTTL: 120
models:
  menos_uno:
    cmd: x
    ttl: -1
  ausente:
    cmd: x
  cero:
    cmd: x
    ttl: 0
  treinta:
    cmd: x
    ttl: 30
""",
    )
    assert f.ttl_efectivo("menos_uno") == 120
    assert f.ttl_efectivo("ausente") == 120
    assert f.ttl_efectivo("cero") == 0
    assert f.ttl_efectivo("treinta") == 30
    assert f.residentes() == ("cero",)


def test_sin_global_ttl_la_ausencia_vale_cero_y_es_residente(tmp_path):
    # En v255 `globalTTL` vale 0 si falta: un modelo sin `ttl` no se descarga nunca.
    f = _foto(tmp_path, _modelos("a", ttl=None))
    assert f.ttl_efectivo("a") == 0
    assert f.residentes() == ("a",)


def test_mmproj_y_precargados(tmp_path):
    f = _foto(
        tmp_path,
        """\
models:
  vision:
    cmd: |
      D:\\llama\\llama-server.exe --port ${PORT}
        --model D:\\m\\v.gguf --mmproj D:\\m\\mmproj-F16.gguf
    aliases: [ojo]
    ttl: 30
  texto:
    cmd: llama-server --model /m/t.gguf
    ttl: 30
hooks:
  on_startup:
    preload: [" ojo ", "", "no-existe", texto]
""",
    )
    assert f.mmproj("vision") == "D:\\m\\mmproj-F16.gguf"
    assert f.mmproj("ojo") == "D:\\m\\mmproj-F16.gguf"
    assert f.mmproj("texto") is None
    assert f.precargados() == ("vision", "texto")


# --- Sin topologia ---------------------------------------------------------------------------


def test_sin_variable(monkeypatch):
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    assert topologia.foto() == SinTopologia("sin LLAMASWAP_CONFIG")


def test_sin_pyyaml(monkeypatch, tmp_path):
    ruta = tmp_path / "config.yaml"
    ruta.write_text(_modelos("a"), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    monkeypatch.setattr(topologia, "yaml", None)
    assert topologia.foto() == SinTopologia("sin PyYAML")
    assert topologia.leer(ruta) == SinTopologia("sin PyYAML")


def test_ilegible(monkeypatch, tmp_path):
    assert _foto(tmp_path, "models: [a\n") == SinTopologia("ilegible")
    assert topologia.leer(tmp_path / "no-existe.yaml") == SinTopologia("ilegible")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(tmp_path / "no-existe.yaml"))
    assert topologia.foto() == SinTopologia("ilegible")


def test_config_que_load_go_rechaza(tmp_path):
    f = _foto(tmp_path, _modelos("a") + "groups:\n  g:\n    members: [a]\n  h:\n    members: [a]\n")
    assert f == SinTopologia("no cumple load.go")
    assert "dos grupos" in f.detalle


# YAML valido con un tipo que el `Config` de v255 no puede deserializar. Antes lanzaban
# AttributeError/TypeError desde `leer`, que promete no lanzar nunca (REQ-002: van sin turno).
_FORMAS_RARAS = [
    ("routing_es_texto", "routing: hola\n", "`routing` no es un mapa"),
    ("router_es_texto", "routing:\n  router: hola\n", "`routing.router` no es un mapa"),
    ("settings_es_numero", "routing:\n  router:\n    settings: 5\n", "settings` no es un mapa"),
    ("use_es_lista", "routing:\n  router:\n    use: [group]\n", "use` no es un texto"),
    ("groups_es_lista", "groups: [a]\n", "`groups` no es un mapa"),
    ("grupo_es_lista", "groups:\n  g: [a]\n", "grupo g: no es un mapa"),
    (
        "grupo_es_lista_en_routing",
        "routing:\n  router:\n    settings:\n      groups:\n        g: [a]\n",
        "grupo g: no es un mapa",
    ),
    ("members_es_numero", "groups:\n  g:\n    members: 3\n", "`members` no es una lista"),
    ("members_es_texto", "groups:\n  g:\n    members: a\n", "`members` no es una lista"),
    ("miembro_es_mapa", "groups:\n  g:\n    members: [{x: 1}]\n", "un miembro no es un texto"),
    ("hooks_es_lista", "hooks: [1]\n", "`hooks` no es un mapa"),
    ("on_startup_es_lista", "hooks:\n  on_startup: [1]\n", "on_startup` no es un mapa"),
    ("preload_es_texto", "hooks:\n  on_startup:\n    preload: 7\n", "preload` no es una lista"),
]


@pytest.mark.parametrize(
    ("extra", "trozo"), [(e, t) for _, e, t in _FORMAS_RARAS], ids=[i for i, _, _ in _FORMAS_RARAS]
)
def test_yaml_valido_con_forma_rara_no_lanza_y_va_sin_turno(tmp_path, extra, trozo):
    try:
        f = _foto(tmp_path, _modelos("a") + extra)
    except Exception as e:
        f = f"excepcion {type(e).__name__}: {e}"
    assert f == SinTopologia("no cumple load.go"), f"leer no devolvio SinTopologia: {f}"
    assert trozo in f.detalle


@pytest.mark.parametrize(
    ("cfg_a", "trozo"),
    [
        ("    aliases: 7\n", "`aliases` no es una lista"),
        ("    aliases: [[x]]\n", "un alias no es un texto"),
        ("    cmd: [llama-server]\n", "`cmd` no es un texto"),
    ],
    ids=["aliases_es_numero", "alias_es_lista", "cmd_es_lista"],
)
def test_modelo_con_forma_rara_no_lanza(tmp_path, cfg_a, trozo):
    try:
        f = _foto(tmp_path, "models:\n  a:\n" + cfg_a)
    except Exception as e:
        f = f"excepcion {type(e).__name__}: {e}"
    assert f == SinTopologia("no cumple load.go"), f"leer no devolvio SinTopologia: {f}"
    assert trozo in f.detalle


def test_validar_como_load_go_tampoco_lanza_con_forma_rara():
    datos = {"models": {"a": {}}, "groups": {"g": ["a"]}, "hooks": [1]}
    try:
        errores = topologia.validar_como_load_go(datos)
    except Exception as e:
        errores = [f"excepcion {type(e).__name__}: {e}"]
    assert "grupo g: no es un mapa" in errores, errores
    assert "`hooks` no es un mapa" in errores, errores


def test_fallo_pasajero_al_abrir_no_se_cachea(monkeypatch, tmp_path):
    """Un OSError al abrir (violacion de comparticion en Windows, REQ-033) no se queda en la cache:
    la siguiente llamada, con la misma mtime y tamano, vuelve a leer y da la foto."""
    ruta = tmp_path / "config.yaml"
    ruta.write_text(_modelos("a"), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    abrir_de_verdad = Path.open

    def abrir_bloqueado(self, *args, **kwargs):
        if self == ruta:
            raise PermissionError(13, "El proceso no tiene acceso al archivo")
        return abrir_de_verdad(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", abrir_bloqueado)
    assert topologia.foto() == SinTopologia("ilegible")
    monkeypatch.setattr(Path, "open", abrir_de_verdad)
    st = ruta.stat()
    f = topologia.foto()
    assert ruta.stat().st_mtime_ns == st.st_mtime_ns  # misma clave: solo cambia el open
    assert isinstance(f, Foto), f"el fallo pasajero quedo cacheado: {f}"
    assert f.modelos == ("a",)


def test_yaml_roto_si_se_cachea(monkeypatch, tmp_path):
    """El contrapeso del anterior: un YAML mal escrito no es pasajero y no se relee sin cambios."""
    ruta = tmp_path / "config.yaml"
    ruta.write_text("models: [a\n", encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    assert topologia.foto() == SinTopologia("ilegible")
    leidas = topologia.lecturas()
    assert topologia.foto() == SinTopologia("ilegible")
    assert topologia.lecturas() == leidas


# --- validar_como_load_go --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("datos", "trozo"),
    [
        ({"models": {"a": {"ttl": "x"}}}, "entero"),
        ({"models": {"a": {"ttl": -2}}}, "TTL no valido"),
        ({"globalTTL": -1, "models": {}}, "globalTTL"),
        ({"models": {"a": {}}, "groups": {"g": {"members": ["a", "a"]}}}, "repetido"),
        ({"models": {"a": {}}, "groups": {"g": {"members": ["b"]}}}, "no es ningun modelo"),
        (
            {"models": {"a": {}}, "groups": {"g": {"members": ["a"]}, "h": {"members": ["a"]}}},
            "dos grupos",
        ),
        (
            {"models": {}, "groups": {"g": {}}, "routing": {"router": {"use": "group"}}},
            "a la vez",
        ),
        ({"models": {}, "routing": {"router": {"use": "otro"}}}, "desconocido"),
        (
            {"models": {"a": {"aliases": ["x"]}, "b": {"aliases": ["x"]}}},
            "alias repetido",
        ),
        ([1, 2], "raiz"),
    ],
)
def test_validar_como_load_go_rechaza(datos, trozo):
    errores = topologia.validar_como_load_go(datos)
    assert any(trozo in e for e in errores), errores


def test_validar_como_load_go_acepta_el_alias_como_miembro_y_el_menos_uno():
    datos = {
        "models": {"a": {"aliases": ["x"], "ttl": -1}, "b": {"ttl": 0}},
        "groups": {"g": {"members": ["x", "b"]}},
    }
    assert topologia.validar_como_load_go(datos) == []


# --- Relectura (REQ-009) ---------------------------------------------------------------------


def test_relectura_por_mtime_y_tamano(monkeypatch, tmp_path):
    ruta = tmp_path / "config.yaml"
    ruta.write_text(_modelos("a", "b"), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    f1 = topologia.foto()
    leidas = topologia.lecturas()
    assert topologia.foto() is f1
    assert topologia.lecturas() == leidas  # sin tocar el fichero no se relee

    ruta.write_text(_modelos("a", "b") + "groups:\n  g:\n    swap: false\n    members: [a, b]\n")
    st = ruta.stat()
    os.utime(ruta, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    f2 = topologia.foto()
    assert f2.version > f1.version
    assert topologia.lecturas() == leidas + 1
    assert f1.choca("a", "b") and not f2.choca("a", "b")


def test_relectura_solo_por_mtime_con_el_mismo_tamano(monkeypatch, tmp_path):
    ruta = tmp_path / "config.yaml"
    ruta.write_text(_modelos("a", ttl=120), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    f1 = topologia.foto()
    tamano = ruta.stat().st_size
    ruta.write_text(_modelos("a", ttl=300), encoding="utf-8")
    assert ruta.stat().st_size == tamano
    st = ruta.stat()
    os.utime(ruta, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    f2 = topologia.foto()
    assert f2.version > f1.version
    assert f2.ttl_efectivo("a") == 300


# --- Guardas de regresion sobre configs reales saneadas --------------------------------------


def test_config_de_hoy_un_solo_grupo_swap():
    f = topologia.leer(FIXTURES / "hoy.yaml")
    assert isinstance(f, Foto)
    reales = {g: c for g, c in f.grupos.items() if c.miembros}
    assert list(reales) == ["swap"]
    assert reales["swap"].swap is True
    assert f.choca("gemma4-26b-a4b", "qwen36-35b-a3b")
    assert f.choca("gemma3-4b", "gemma4-26b-a4b")
    assert f.residentes() == ()
    assert f.mmproj("gemma4-12b") == "MODELOS/mmproj-F16.gguf"
    assert f.ttl_efectivo("gemma4-12b") == 30


def test_config_pre_sin_residente_el_4b_persistente_no_choca_con_el_26b():
    f = topologia.leer(FIXTURES / "pre-sin-residente-20261006.yaml")
    assert isinstance(f, Foto)
    assert f.grupo("gemma3-4b") == "resident"
    assert f.grupos["resident"].persistent is True
    assert not f.choca("gemma3-4b", "gemma4-26b-a4b")
    assert f.choca("gemma4-26b-a4b", "qwen36-35b-a3b")
    assert f.ttl_efectivo("gemma3-4b") == 600
    assert f.residentes() == ()


def test_las_fixtures_reales_no_llevan_claves_ni_rutas_privadas():
    for ruta in FIXTURES.glob("*.yaml"):
        texto = ruta.read_text(encoding="utf-8")
        assert "C:\\Users" not in texto and "c:\\users" not in texto.lower()
        for linea in texto.splitlines():
            if "key" in linea.lower() and ":" in linea and not linea.lstrip().startswith("#"):
                valor = linea.split(":", 1)[1].strip()
                assert valor in ("", '"CLAVE-SUSTITUIDA"'), ruta.name
