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

from local_delegate import topology
from local_delegate.topology import NoTopology, Snapshot

FIXTURES = Path(__file__).parent / "fixtures" / "topologia"


def _snapshot(tmp_path: Path, yaml_text: str) -> Snapshot | NoTopology:
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
    return topology.read(path)


def _models(*ids: str, ttl: int | None = 120) -> str:
    lines = ["models:"]
    for mid in ids:
        lines.append(f"  {mid}:")
        lines.append(f"    cmd: llama-server --model /m/{mid}.gguf")
        if ttl is not None:
            lines.append(f"    ttl: {ttl}")
    return "\n".join(lines) + "\n"


@pytest.fixture(autouse=True)
def _clean_cache():
    topology._forget()
    yield
    topology._forget()


# --- Tabla de casos contra EvictionFor -------------------------------------------------------


def test_same_group_with_swap_clashes_without_swap_not(tmp_path):
    f = _snapshot(
        tmp_path,
        _models("a", "b", "c", "d")
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
    assert isinstance(f, Snapshot)
    assert f.clashes("a", "b")
    assert f.clashes("b", "a")
    assert not f.clashes("c", "d")
    assert not f.clashes("d", "c")


def test_group_without_keys_evicts_other_group(tmp_path):
    # «g1» no dice nada: por defecto es exclusive. «g2» no es exclusive ni persistent.
    f = _snapshot(
        tmp_path,
        _models("a", "b")
        + """\
groups:
  g1:
    members: [a]
  g2:
    exclusive: false
    members: [b]
""",
    )
    assert f.clashes("a", "b")
    assert f.groups["g1"].exclusive is True


def test_exclusive_only_in_b_clashes_both_ways(tmp_path):
    f = _snapshot(
        tmp_path,
        _models("a", "b")
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
    assert not f._evicts("a", "b")
    assert f._evicts("b", "a")
    assert f.clashes("a", "b")
    assert f.clashes("b", "a")


def test_exclusive_against_persistent(tmp_path):
    f = _snapshot(
        tmp_path,
        _models("a", "b", "p")
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
    assert not f.clashes("a", "b")
    assert not f.clashes("b", "a")
    # Un grupo persistent con exclusive por defecto SI desaloja a los demas al cargar.
    assert f.clashes("p", "a")
    assert f.clashes("a", "p")


def test_model_never_clashes_with_itself(tmp_path):
    f = _snapshot(tmp_path, _models("a", "b") + "groups:\n  g:\n    members: [a, b]\n")
    assert f.clashes("a", "b")
    assert not f.clashes("a", "a")


def test_model_not_in_config_compatible_with_all(tmp_path):
    f = _snapshot(tmp_path, _models("a", "b") + "groups:\n  g:\n    members: [a, b]\n")
    assert not f.clashes("fantasma", "a")
    assert not f.clashes("a", "fantasma")
    assert f.effective_ttl("fantasma") is None


# --- (default) -------------------------------------------------------------------------------


def test_ungrouped_models_go_to_default_and_clash_with_non_persistent(tmp_path):
    f = _snapshot(
        tmp_path,
        _models("suelto", "gemma4-26b-a4b", "fijo")
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
    assert f.clashes("suelto", "gemma4-26b-a4b")
    assert f.group("suelto") == "(default)"
    assert f.groups["(default)"].members == ("suelto",)
    assert not f.clashes("suelto", "fijo")


def test_without_groups_all_go_to_default(tmp_path):
    f = _snapshot(tmp_path, _models("a", "b"))
    assert f.groups["(default)"].members == ("a", "b")
    assert f.clashes("a", "b")


# --- Las dos sintaxis y matrix ---------------------------------------------------------------

# Con estos grupos «a» (persistent, no exclusive) no choca con «b»; «b» y «c» comparten
# grupo con swap. Si se leyera mal la sintaxis, los tres irian a `(default)` y «a» chocaria
# con «b».
_GROUPS = """\
    g1:
      persistent: true
      swap: false
      exclusive: false
      members: [a]
    g2:
      exclusive: false
      members: [b, c]
"""


def test_routing_router_settings_groups_syntax(tmp_path):
    f = _snapshot(
        tmp_path,
        _models("a", "b", "c")
        + "routing:\n  router:\n    use: group\n    settings:\n      groups:\n"
        + textwrap.indent(_GROUPS, "    "),
    )
    assert isinstance(f, Snapshot)
    assert not f.clashes("a", "b")
    assert f.clashes("b", "c")
    assert f.group("a") == "g1"


def test_groups_syntax_on_top(tmp_path):
    f = _snapshot(
        tmp_path,
        _models("a", "b", "c") + "groups:\n" + textwrap.indent(textwrap.dedent(_GROUPS), "  "),
    )
    assert not f.clashes("a", "b")
    assert f.clashes("b", "c")
    assert f.group("a") == "g1"


def test_both_syntaxes_at_once(tmp_path):
    f = _snapshot(
        tmp_path,
        _models("a", "b")
        + "groups:\n  g:\n    members: [a]\n"
        + "routing:\n  router:\n    settings:\n      groups:\n        h:\n          members: [b]\n",
    )
    assert f == NoTopology("dos sintaxis")


def test_router_matrix(tmp_path):
    f = _snapshot(
        tmp_path,
        _models("a", "b")
        + "routing:\n  router:\n    use: matrix\n    settings:\n      matrix:\n        sets: {}\n",
    )
    assert f == NoTopology("matrix")
    g = _snapshot(tmp_path, _models("a") + "matrix:\n  sets: {}\n")
    assert g == NoTopology("matrix")


# --- Alias -----------------------------------------------------------------------------------


def test_alias_clashes_like_real_id(tmp_path):
    f = _snapshot(
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
    assert f.clashes("alias-del-26b", "qwen36-35b-a3b")
    assert f.clashes("gemma4-26b-a4b", "qwen36-35b-a3b")
    assert f.resolve("alias-del-26b") == "gemma4-26b-a4b"
    assert not f.clashes("alias-del-26b", "gemma3-4b")


# --- TTL efectivo, residentes, mmproj y precarga ---------------------------------------------


def test_effective_ttl_and_residents(tmp_path):
    f = _snapshot(
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
    assert f.effective_ttl("menos_uno") == 120
    assert f.effective_ttl("ausente") == 120
    assert f.effective_ttl("cero") == 0
    assert f.effective_ttl("treinta") == 30
    assert f.residents() == ("cero",)


def test_without_global_ttl_absence_is_zero_and_resident(tmp_path):
    # En v255 `globalTTL` vale 0 si falta: un modelo sin `ttl` no se descarga nunca.
    f = _snapshot(tmp_path, _models("a", ttl=None))
    assert f.effective_ttl("a") == 0
    assert f.residents() == ("a",)


def test_mmproj_and_preloaded(tmp_path):
    f = _snapshot(
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
    assert f.preloaded() == ("vision", "texto")


# --- Sin topologia ---------------------------------------------------------------------------


def test_without_variable(monkeypatch):
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    assert topology.snapshot() == NoTopology("sin LLAMASWAP_CONFIG")


def test_without_pyyaml(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(_models("a"), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))
    monkeypatch.setattr(topology, "yaml", None)
    assert topology.snapshot() == NoTopology("sin PyYAML")
    assert topology.read(path) == NoTopology("sin PyYAML")


def test_unreadable(monkeypatch, tmp_path):
    assert _snapshot(tmp_path, "models: [a\n") == NoTopology("ilegible")
    assert topology.read(tmp_path / "no-existe.yaml") == NoTopology("ilegible")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(tmp_path / "no-existe.yaml"))
    assert topology.snapshot() == NoTopology("ilegible")


def test_config_rejected_by_load_go(tmp_path):
    f = _snapshot(
        tmp_path, _models("a") + "groups:\n  g:\n    members: [a]\n  h:\n    members: [a]\n"
    )
    assert f == NoTopology("no cumple load.go")
    assert "dos grupos" in f.detail


# YAML valido con un tipo que el `Config` de v255 no puede deserializar. Antes lanzaban
# AttributeError/TypeError desde `read`, que promete no lanzar nunca (REQ-002: van sin turno).
_ODD_SHAPES = [
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
    ("extra", "chunk"), [(e, t) for _, e, t in _ODD_SHAPES], ids=[i for i, _, _ in _ODD_SHAPES]
)
def test_valid_odd_shaped_yaml_does_not_raise_and_runs_without_turn(tmp_path, extra, chunk):
    try:
        f = _snapshot(tmp_path, _models("a") + extra)
    except Exception as e:
        f = f"excepcion {type(e).__name__}: {e}"
    assert f == NoTopology("no cumple load.go"), f"leer no devolvio SinTopologia: {f}"
    assert chunk in f.detail


@pytest.mark.parametrize(
    ("cfg_a", "chunk"),
    [
        ("    aliases: 7\n", "`aliases` no es una lista"),
        ("    aliases: [[x]]\n", "un alias no es un texto"),
        ("    cmd: [llama-server]\n", "`cmd` no es un texto"),
    ],
    ids=["aliases_es_numero", "alias_es_lista", "cmd_es_lista"],
)
def test_odd_shaped_model_does_not_raise(tmp_path, cfg_a, chunk):
    try:
        f = _snapshot(tmp_path, "models:\n  a:\n" + cfg_a)
    except Exception as e:
        f = f"excepcion {type(e).__name__}: {e}"
    assert f == NoTopology("no cumple load.go"), f"leer no devolvio SinTopologia: {f}"
    assert chunk in f.detail


def test_validate_like_load_go_does_not_raise_on_odd_shape():
    data = {"models": {"a": {}}, "groups": {"g": ["a"]}, "hooks": [1]}
    try:
        errors = topology.validate_like_load_go(data)
    except Exception as e:
        errors = [f"excepcion {type(e).__name__}: {e}"]
    assert "grupo g: no es un mapa" in errors, errors
    assert "`hooks` no es un mapa" in errors, errors


def test_transient_open_failure_not_cached(monkeypatch, tmp_path):
    """Un OSError al abrir (violacion de comparticion en Windows, REQ-033) no se queda en la cache:
    la siguiente llamada, con la misma mtime y tamano, vuelve a leer y da la foto."""
    path = tmp_path / "config.yaml"
    path.write_text(_models("a"), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))
    really_open = Path.open

    def open_locked(self, *args, **kwargs):
        if self == path:
            raise PermissionError(13, "El proceso no tiene acceso al archivo")
        return really_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_locked)
    assert topology.snapshot() == NoTopology("ilegible")
    monkeypatch.setattr(Path, "open", really_open)
    st = path.stat()
    f = topology.snapshot()
    assert path.stat().st_mtime_ns == st.st_mtime_ns  # misma clave: solo cambia el open
    assert isinstance(f, Snapshot), f"el fallo pasajero quedo cacheado: {f}"
    assert f.models == ("a",)


def test_broken_yaml_is_cached(monkeypatch, tmp_path):
    """El contrapeso del anterior: un YAML mal escrito no es pasajero y no se relee sin cambios."""
    path = tmp_path / "config.yaml"
    path.write_text("models: [a\n", encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))
    assert topology.snapshot() == NoTopology("ilegible")
    read_ones = topology.reads()
    assert topology.snapshot() == NoTopology("ilegible")
    assert topology.reads() == read_ones


# --- validate_like_load_go --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "chunk"),
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
def test_validate_like_load_go_rejects(data, chunk):
    errors = topology.validate_like_load_go(data)
    assert any(chunk in e for e in errors), errors


def test_validate_like_load_go_accepts_alias_member_and_minus_one():
    data = {
        "models": {"a": {"aliases": ["x"], "ttl": -1}, "b": {"ttl": 0}},
        "groups": {"g": {"members": ["x", "b"]}},
    }
    assert topology.validate_like_load_go(data) == []


# --- Relectura (REQ-009) ---------------------------------------------------------------------


def test_reread_by_mtime_and_size(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(_models("a", "b"), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))
    f1 = topology.snapshot()
    read_ones = topology.reads()
    assert topology.snapshot() is f1
    assert topology.reads() == read_ones  # sin tocar el fichero no se relee

    path.write_text(_models("a", "b") + "groups:\n  g:\n    swap: false\n    members: [a, b]\n")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    f2 = topology.snapshot()
    assert f2.version > f1.version
    assert topology.reads() == read_ones + 1
    assert f1.clashes("a", "b") and not f2.clashes("a", "b")


def test_reread_by_mtime_only_with_same_size(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(_models("a", ttl=120), encoding="utf-8")
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))
    f1 = topology.snapshot()
    size = path.stat().st_size
    path.write_text(_models("a", ttl=300), encoding="utf-8")
    assert path.stat().st_size == size
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    f2 = topology.snapshot()
    assert f2.version > f1.version
    assert f2.effective_ttl("a") == 300


# --- Guardas de regresion sobre configs reales saneadas --------------------------------------


def test_todays_config_single_swap_group():
    f = topology.read(FIXTURES / "hoy.yaml")
    assert isinstance(f, Snapshot)
    real = {g: c for g, c in f.groups.items() if c.members}
    assert list(real) == ["swap"]
    assert real["swap"].swap is True
    assert f.clashes("gemma4-26b-a4b", "qwen36-35b-a3b")
    assert f.clashes("gemma3-4b", "gemma4-26b-a4b")
    assert f.residents() == ()
    assert f.mmproj("gemma4-12b") == "MODELOS/mmproj-F16.gguf"
    assert f.effective_ttl("gemma4-12b") == 30


def test_pre_no_resident_config_persistent_4b_does_not_clash_with_26b():
    f = topology.read(FIXTURES / "pre-sin-residente-20261006.yaml")
    assert isinstance(f, Snapshot)
    assert f.group("gemma3-4b") == "resident"
    assert f.groups["resident"].persistent is True
    assert not f.clashes("gemma3-4b", "gemma4-26b-a4b")
    assert f.clashes("gemma4-26b-a4b", "qwen36-35b-a3b")
    assert f.effective_ttl("gemma3-4b") == 600
    assert f.residents() == ()


def test_real_fixtures_have_no_keys_or_private_paths():
    for path in FIXTURES.glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        assert "C:\\Users" not in text and "c:\\users" not in text.lower()
        for line in text.splitlines():
            if "key" in line.lower() and ":" in line and not line.lstrip().startswith("#"):
                value = line.split(":", 1)[1].strip()
                assert value in ("", '"CLAVE-SUSTITUIDA"'), path.name
