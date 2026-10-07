"""T11: editor y CLI de residencia sobre copias (REQ-029 a REQ-033, REQ-035, REQ-038 de ficheros).

Todo se escribe sobre copias en `tmp_path`: la config real de llama-swap no se toca nunca. Las
copias de las configs reales (`tests/fixtures/residencia/`) llevan las claves sustituidas por
`clave-falsa-N`, y un test lo comprueba. La consulta del CLI al daemon la corta la fixture autouse
`conftest.daemon_real_cortado`.
"""

from __future__ import annotations

import builtins
import difflib
import hashlib
import os
import re
import struct
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml
from conftest import CUT_DAEMON, PUERTO_MUERTO

from local_delegate import checks, cli, residencia, topologia
from local_delegate import llamaswap_config as lc
from local_delegate.residencia import (
    AnadirMiembro,
    BorrarGrupo,
    CrearGrupo,
    ErrorResidencia,
    PonerTTL,
    QuitarMiembro,
)

FIXTURES = Path(__file__).parent / "fixtures" / "residencia"
HOY = FIXTURES / "hoy.yaml"
PRE_SIN_RESIDENTE = FIXTURES / "pre-sin-residente-20261006.yaml"
PRE_B10909 = FIXTURES / "pre-b10909-20260915.yaml"

# Cifras medidas en F2 (insumos/llamaswap-grupos.md §2), en GiB; el 2B no se midió (extremo alto).
VRAM_MEDIDA = {
    "gemma3-4b": "3,19",
    "gemma4-12b": "8,85",
    "qwen36-35b-a3b": "9,88",
    "gemma4-26b-a4b": "10,29",
    "qwen35-2b": "3,5",
}


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _copia(origen: Path, tmp_path: Path, nombre: str = "config.yaml") -> Path:
    destino = tmp_path / nombre
    destino.write_bytes(origen.read_bytes())
    return destino


def _escribe(tmp_path: Path, contenido: bytes, nombre: str = "config.yaml") -> Path:
    ruta = tmp_path / nombre
    ruta.write_bytes(contenido)
    return ruta


def _cambiadas(antes: bytes, despues: bytes) -> list[tuple[str, str]]:
    """Las líneas que cambian, CON su fin de línea: un cambio de LF a CRLF también cuenta."""
    a = antes.decode("utf-8").splitlines(keepends=True)
    b = despues.decode("utf-8").splitlines(keepends=True)
    salida: list[tuple[str, str]] = []
    for etiqueta, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        if etiqueta != "equal":
            salida += [("-", linea) for linea in a[i1:i2]]
            salida += [("+", linea) for linea in b[j1:j2]]
    return salida


def _residencia(*argv: str) -> int:
    return cli.run(["llamaswap", "residency", *argv])


def _vram_args() -> list[str]:
    args: list[str] = []
    for modelo, gib in VRAM_MEDIDA.items():
        args += ["--vram-model", f"{modelo}={gib}"]
    return args


# --- Guarda: ningún fixture lleva una clave real ---------------------------------------------

_SENSIBLE = re.compile(r"(?i)key|token|secret|password|bearer")
_FALSA = re.compile(r"^clave-falsa-\d+$")


def _con_forma_de_clave(texto: str) -> list[str]:
    """Cadenas con forma de clave que no son `clave-falsa-N`. Nunca devuelve la cadena entera."""
    halladas: list[str] = []
    lista_sensible: int | None = None

    def valor(crudo: str) -> str:
        crudo = crudo.split(" #", 1)[0].strip()
        return crudo.strip("\"'")

    for n, linea in enumerate(texto.splitlines(), 1):
        cuerpo = linea.lstrip("\ufeff")
        sangria = len(cuerpo) - len(cuerpo.lstrip(" "))
        limpio = cuerpo.strip()
        if lista_sensible is not None:
            item = re.match(r"^#?\s*-\s+(.*)$", limpio)
            if item and sangria > lista_sensible:
                if not _FALSA.match(valor(item.group(1))):
                    halladas.append(f"línea {n}: elemento de una lista de claves")
                continue
            if limpio and not limpio.startswith("#"):
                lista_sensible = None
        if _SENSIBLE.search(cuerpo) and not limpio.startswith("#") and ":" in limpio:
            clave, _, resto = limpio.partition(":")
            if not valor(resto):
                lista_sensible = sangria
            elif _SENSIBLE.search(clave) and not _FALSA.match(valor(resto)):
                halladas.append(f"línea {n}: valor de `{clave.strip()}`")
        for patron, nombre in (
            (r"\bsk-[A-Za-z0-9_-]{8,}", "sk-…"),
            (r"(?i)\bbearer\s+(?!clave-falsa-)\S+", "Bearer …"),
            (r"--api-key[ =](?!clave-falsa-)\S+", "--api-key …"),
            (r"(?<![\w.-])[A-Za-z0-9_+/=]{32,}(?![\w.-])", "token largo"),
        ):
            if re.search(patron, cuerpo):
                halladas.append(f"línea {n}: {nombre}")
    return halladas


def test_ningun_fixture_lleva_una_clave_real():
    ficheros = sorted(FIXTURES.glob("*.yaml"))
    assert len(ficheros) >= 3, "no hay fixtures que comprobar"
    for fichero in ficheros:
        texto = fichero.read_bytes().decode("utf-8")
        assert _con_forma_de_clave(texto) == [], fichero.name
        assert "clave-falsa-1" in texto, (
            f"{fichero.name}: la sustitución no llegó a la lista apiKeys"
        )
        assert not re.search(r"(?i)[a-z]:[\\/]users[\\/]", texto), fichero.name
        assert not re.search(r"\b100\.\d+\.\d+\.\d+|ts\.net", texto), fichero.name


@pytest.mark.parametrize(
    "plantada",
    [
        'apiKeys:\n  - "sk-abcdefgh12345678"\n',
        "apiKeys:\n  - otra-cosa-que-no-es-falsa\n",
        "apiKeys:\n  # - comentada-pero-real\n",
        "auth:\n  apiKey: 'de-verdad'\n",
        "models:\n  a:\n    cmd: llama-server --api-key secreta123 --model a.gguf\n",
        "x: Bearer abc.def\n",
        "token_largo: Zx9" + "q" * 40 + "\n",
    ],
)
def test_la_guarda_detecta_una_clave_plantada(plantada):
    """Control positivo de la guarda de arriba: cada forma de clave plantada se detecta."""
    assert _con_forma_de_clave(plantada) != []


@pytest.mark.parametrize("plantada", ['"sk-plantada0123456789"', "'cualquier-valor'"])
def test_la_guarda_detecta_una_clave_plantada_en_un_fixture_real(plantada):
    texto = HOY.read_text(encoding="utf-8")
    assert '"clave-falsa-1"' in texto
    assert _con_forma_de_clave(texto.replace('"clave-falsa-1"', plantada)) != []


def test_la_guarda_no_salta_con_lo_que_si_vale():
    texto = (FIXTURES / "hoy.yaml").read_text(encoding="utf-8")
    assert _con_forma_de_clave(texto) == []
    assert _con_forma_de_clave('apiKeys:\n  - "clave-falsa-7"\n') == []


# --- Edición quirúrgica ----------------------------------------------------------------------

_SANGRADA = b"""models:
  a:
    cmd: llama-server --model a.gguf
    ttl: 60
  b:
    cmd: llama-server --model b.gguf
    ttl: 60
  c:
    cmd: llama-server --model c.gguf
    ttl: 60
groups:
  g:
    swap: true
    exclusive: false
    members:
      - a
      - b
"""

_COMENTARIOS = b"""# cabecera que safe_dump perderia
models:
  a:
    cmd: llama-server --model a.gguf  # en linea
    ttl: 60
  b:
    cmd: llama-server --model b.gguf
    ttl: 60
  c:
    cmd: llama-server --model c.gguf
    ttl: 60
groups:
  g:   # grupo principal
    swap: true
    members:
    - a  # el primero
    # entre miembros
    - b  # el segundo
    # despues del ultimo
"""

_PLEGADO = b"""models:
  a:
    cmd: 'llama-server --port ${PORT}
      --model a.gguf

      '
  b:
    cmd: llama-server --model b.gguf
    ttl: 60
"""

_LITERAL = b"""models:
  a:
    cmd: |
      llama-server
      --model a.gguf

  b:
    cmd: >
      llama-server
      --model b.gguf
  c:
    cmd: llama-server --model c.gguf
    ttl: 60
"""

_SIN_SALTO_FINAL = b"""models:
  a:
    cmd: llama-server --model a.gguf
    ttl: 60
  b:
    cmd: llama-server --model b.gguf
    ttl: 60
  c:
    cmd: llama-server --model c.gguf
    ttl: 60
groups:
  g:
    members:
    - a
    - b"""

_BOM_CRLF = (
    b"\xef\xbb\xbfmodels:\r\n  a:\r\n    cmd: llama-server --model a.gguf\r\n    ttl: 60\r\n"
    b"  b:\r\n    cmd: llama-server --model b.gguf\r\n"
)

_COMILLAS = b"""models:
  "a":
    cmd: "llama-server --model a.gguf"
    'ttl': 60
  'b':
    cmd: llama-server --model b.gguf
    ttl: 60
  c:
    cmd: llama-server --model c.gguf
    ttl: 60
groups:
  "g":
    members:
    - "a"
    - 'b'
"""

_ROUTING = b"""globalTTL: 120
models:
  a:
    cmd: llama-server --model a.gguf
  b:
    cmd: llama-server --model b.gguf
routing:
  router:
    use: group
    settings:
      groups:
        g1:
          persistent: true
          swap: false
          exclusive: false
          members:
          - a
        g2:
          swap: true
          members:
          - b
"""

_LINEAS_GRUPO_RESIDENTE_HOY = [
    ("+", "  residente:\n"),
    ("+", "    persistent: true\n"),
    ("+", "    swap: false\n"),
    ("+", "    exclusive: false\n"),
    ("+", "    members:\n"),
    ("+", "    - gemma3-4b\n"),
]

_CASOS = {
    "secuencia sangrada": (
        _SANGRADA,
        [AnadirMiembro("g", "c")],
        [("+", "      - c\n")],
    ),
    "secuencia sin sangrar (config de hoy)": (
        HOY.read_bytes(),
        [
            QuitarMiembro("swap", "gemma3-4b"),
            CrearGrupo("residente", True, False, False, ("gemma3-4b",)),
            PonerTTL("gemma3-4b", 0),
        ],
        [
            ("-", "    ttl: 120\n"),
            ("+", "    ttl: 0\n"),
            ("-", "    - gemma3-4b\n"),
            *_LINEAS_GRUPO_RESIDENTE_HOY,
        ],
    ),
    "comentarios en linea y entre miembros": (
        _COMENTARIOS,
        [QuitarMiembro("g", "b"), AnadirMiembro("g", "c")],
        [("-", "    - b  # el segundo\n"), ("+", "    - c\n")],
    ),
    "ttl tras un cmd plegado entre comillas": (
        _PLEGADO,
        [PonerTTL("a", 120)],
        [("+", "    ttl: 120\n")],
    ),
    "ttl tras un escalar | y tras uno >": (
        _LITERAL,
        [PonerTTL("a", 120), PonerTTL("b", 30)],
        [("+", "    ttl: 120\n"), ("+", "    ttl: 30\n")],
    ),
    "grupo al final sin salto final": (
        _SIN_SALTO_FINAL,
        [AnadirMiembro("g", "c")],
        [("-", "    - b"), ("+", "    - b\n"), ("+", "    - c")],
    ),
    "fin de linea mixto (config del 2026-09-15)": (
        PRE_B10909.read_bytes(),
        [BorrarGrupo("resident"), AnadirMiembro("swap", "gemma3-4b")],
        [
            ("-", "  resident:\r\n"),
            ("-", "    persistent: true\r\n"),
            ("-", "    swap: false\r\n"),
            ("-", "    exclusive: false\r\n"),
            ("-", "    members:\r\n"),
            ("-", "    - gemma3-4b\r\n"),
            ("+", "    - gemma3-4b\n"),
        ],
    ),
    "BOM y CRLF": (
        _BOM_CRLF,
        [PonerTTL("a", 90), PonerTTL("b", 30)],
        [("-", "    ttl: 60\r\n"), ("+", "    ttl: 90\r\n"), ("+", "    ttl: 30\r\n")],
    ),
    "claves entre comillas": (
        _COMILLAS,
        [PonerTTL("a", 90), AnadirMiembro("g", "c")],
        [("-", "    'ttl': 60\n"), ("+", "    'ttl': 90\n"), ("+", "    - 'c'\n")],
    ),
    "sintaxis routing": (
        _ROUTING,
        [BorrarGrupo("g1"), AnadirMiembro("g2", "a")],
        [
            ("-", "        g1:\n"),
            ("-", "          persistent: true\n"),
            ("-", "          swap: false\n"),
            ("-", "          exclusive: false\n"),
            ("-", "          members:\n"),
            ("-", "          - a\n"),
            ("+", "          - a\n"),
        ],
    ),
}


@pytest.mark.parametrize("caso", list(_CASOS))
def test_edicion_quirurgica_solo_cambia_las_lineas_pedidas(caso):
    original, cambios, esperadas = _CASOS[caso]
    nuevo = residencia.editar(original, cambios)
    lineas_cambiadas = _cambiadas(original, nuevo)
    assert lineas_cambiadas == esperadas
    # Lo que no se pidió queda igual: BOM, y el salto final o su ausencia.
    assert nuevo.startswith(residencia.BOM) == original.startswith(residencia.BOM)
    assert nuevo.endswith(b"\n") == original.endswith(b"\n")


def test_la_tabla_cubre_lo_que_pide_la_spec():
    """Guarda: los casos que la spec nombra están en la tabla y cada uno pide algún cambio."""
    assert len(_CASOS) == 10
    assert all(cambios and esperadas for _o, cambios, esperadas in _CASOS.values())
    assert (
        b"\r\n" in PRE_B10909.read_bytes() and b"\n    - qwen3-vl-8b\n" in PRE_B10909.read_bytes()
    )


_NEGATIVAS = {
    "flujo": (
        b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\ngroups:\n  g:\n    members: [a]\n",
        "estilo flujo",
    ),
    "ancla": (b"models:\n  a:\n    cmd: &c x --model a.gguf\n    ttl: 60\n", "ancla"),
    "alias": (
        b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\n  b:\n    cmd: *c\n",
        "alias",
    ),
    "fusion": (b"models:\n  a:\n    <<:\n      cmd: x --model a.gguf\n    ttl: 60\n", "fusión"),
    "duplicadas": (
        b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\n    ttl: 90\n",
        "clave duplicada",
    ),
    "matrix": (
        (
            b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\nrouting:\n  router:\n"
            b"    use: matrix\n    settings:\n      matrix:\n        sets:\n          s1: a\n"
        ),
        "matrix",
    ),
    "dos sintaxis": (
        (
            b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\ngroups:\n  g:\n    members:\n"
            b"    - a\nrouting:\n  router:\n    use: group\n"
        ),
        "dos sintaxis",
    ),
}


@pytest.mark.parametrize("caso", list(_NEGATIVAS))
def test_negativas_con_motivo_y_fichero_intacto(caso, tmp_path, capsys):
    contenido, motivo = _NEGATIVAS[caso]
    with pytest.raises(ErrorResidencia, match=motivo):
        residencia.editar(contenido, [PonerTTL("a", 30)])
    ruta = _escribe(tmp_path, contenido)
    antes = _sha(ruta)
    assert _residencia("--config", str(ruta), "--ttl", "a=30", "--now") == 2
    assert motivo in capsys.readouterr().err
    assert _sha(ruta) == antes
    assert not list(tmp_path.glob("*.bak"))


def test_claves_duplicadas_se_niegan_con_su_motivo():
    """Sin la negativa, el editor tocaría la PRIMERA `ttl` y `safe_load` se quedaría con la última:
    la autocomprobación también lo pararía, pero con otro mensaje. Por eso el `match`."""
    contenido = b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\n    ttl: 90\n"
    with pytest.raises(ErrorResidencia, match="clave duplicada"):
        residencia.editar(contenido, [PonerTTL("a", 30)])


def test_la_autocomprobacion_para_un_resultado_que_no_cuadra(monkeypatch):
    """Si una edición de texto se equivoca, no se devuelve nada (aquí se fuerza el fallo)."""
    monkeypatch.setattr(residencia, "_aplicar_ediciones", lambda t, e: t.replace("60", "61", 1))
    with pytest.raises(ErrorResidencia, match="autocomprobación no cuadra"):
        residencia.editar(_SANGRADA, [PonerTTL("a", 90)])


# --- La consulta al daemon y la config que no se sabe ------------------------------------------


def test_la_fixture_corta_el_daemon_real(request):
    """La consulta del CLI va al servidor que corta (`conftest.RejectingServer`), no al daemon:
    falla en el acto (no los ~2,1 s de un puerto cerrado en Windows) y el corte la recibió."""
    import httpx2

    puerto_muerto = request.node.stash.get(PUERTO_MUERTO, None)
    puerto = urlsplit(cli._url_del_daemon()).port
    assert puerto == puerto_muerto
    assert puerto != checks.daemon_host_port()[1], "la consulta iría al puerto del daemon real"
    cortado = request.node.stash[CUT_DAEMON]
    antes = cortado.accepted
    inicio = time.monotonic()
    with pytest.raises(httpx2.HTTPError):
        httpx2.get(f"{cli._url_del_daemon()}/api/llamaswap/status", timeout=5)
    assert time.monotonic() - inicio < 0.5
    assert cortado.accepted > antes, "la conexión no llegó al servidor que corta"


def _espia_de_ficheros(monkeypatch) -> list[tuple[str, object]]:
    abiertos: list[tuple[str, object]] = []
    vigilados = {"local_delegate.residencia", "local_delegate.cli"}

    def espia(original):
        def envuelta(*args, **kwargs):
            modulo = sys._getframe(1).f_globals.get("__name__")
            if modulo in vigilados:
                abiertos.append((modulo, args[0] if args else None))
            return original(*args, **kwargs)

        return envuelta

    monkeypatch.setattr(builtins, "open", espia(builtins.open))
    monkeypatch.setattr(Path, "read_bytes", espia(Path.read_bytes))
    monkeypatch.setattr(Path, "read_text", espia(Path.read_text))
    monkeypatch.setattr(Path, "open", espia(Path.open))
    return abiertos


def test_sin_config_no_se_sabe(monkeypatch, tmp_path, capsys):
    # Un `config.yaml` en el directorio actual: una caída a una ruta por defecto lo abriría.
    _copia(HOY, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    abiertos = _espia_de_ficheros(monkeypatch)

    rc = _residencia()
    assert abiertos == []
    assert rc == 2
    assert "no se sabe" in capsys.readouterr().err

    # Guarda: el espía sí ve una lectura de la config cuando hay `--config`.
    assert _residencia("--config", str(tmp_path / "config.yaml")) == 0
    assert abiertos, "el espía no ve las lecturas: la comprobación de arriba no valdría"


# --- Escenarios ------------------------------------------------------------------------------


def test_ver_la_residencia(tmp_path, capsys):
    ruta = _copia(HOY, tmp_path)
    assert _residencia("--config", str(ruta)) == 0
    salida = capsys.readouterr().out
    assert "sin residente (recomendado)" in salida
    filas = {
        linea.split()[0]: linea.split()
        for linea in salida.splitlines()
        if linea.split() and linea.split()[0] in topologia.leer(ruta).modelos
    }
    assert len(filas) == 5
    ttls = {m: fila[5] for m, fila in filas.items()}
    assert ttls == {
        "gemma3-4b": "120",
        "qwen35-2b": "120",
        "gemma4-26b-a4b": "120",
        "qwen36-35b-a3b": "120",
        "gemma4-12b": "30",
    }
    assert "llama-server" not in salida
    assert "--port" not in salida
    assert "clave-falsa" not in salida


def test_config_sin_global_ttl_ni_ttl_todos_residentes(tmp_path, capsys):
    """Aclarado el 2026-10-07: sin `globalTTL` ni `ttl`, todos tienen TTL efectivo 0."""
    ruta = _escribe(
        tmp_path,
        b"models:\n  a:\n    cmd: x --model a.gguf\n  b:\n    cmd: x --model b.gguf\n"
        b"groups:\n  g:\n    swap: true\n    exclusive: false\n    members:\n    - a\n    - b\n",
    )
    cargada = residencia.cargar(ruta)
    vista = residencia.vista(cargada.foto, cargada.datos)
    modelos = ["a", "b"]
    assert set(vista.residentes) == set(modelos)
    texto = vista.texto()
    assert "residente: a" in texto and "residente: b" in texto
    assert "sin `globalTTL` ni `ttl`, el TTL efectivo es 0" in texto
    # --none pide --ttl para todos y dice que no hay TTL que sugerir.
    assert _residencia("--config", str(ruta), "--none") == 2
    err = capsys.readouterr().err
    assert "no queda ningún TTL distinto de 0 que sugerir" in err
    assert "--ttl MODEL=SECONDS" in err


def test_ninguno_sugiere_el_ttl_mas_frecuente_sin_mmproj(tmp_path, capsys):
    ruta = _escribe(
        tmp_path,
        b"models:\n  r:\n    cmd: x --model r.gguf\n    ttl: 0\n"
        b"  a:\n    cmd: x --model a.gguf\n    ttl: 120\n"
        b"  b:\n    cmd: x --model b.gguf\n    ttl: 120\n"
        b"  v1:\n    cmd: x --model v.gguf --mmproj m.gguf\n    ttl: 30\n"
        b"  v2:\n    cmd: x --model w.gguf --mmproj n.gguf\n    ttl: 30\n"
        b"  v3:\n    cmd: x --model z.gguf --mmproj o.gguf\n    ttl: 30\n"
        b"groups:\n  swap:\n    swap: true\n    exclusive: false\n    members:\n    - r\n    - a\n"
        b"    - b\n    - v1\n    - v2\n    - v3\n",
    )
    antes = _sha(ruta)
    assert _residencia("--config", str(ruta), "--none", "--now") == 2
    assert "--ttl r=120" in capsys.readouterr().err
    assert _sha(ruta) == antes
    assert _residencia("--config", str(ruta), "--none", "--ttl", "r=120", "--now") == 0
    assert yaml.safe_load(ruta.read_bytes())["models"]["r"]["ttl"] == 120


def test_volver_a_ningun_residente_desde_la_config_del_2026_09_15(tmp_path, capsys):
    ruta = _copia(PRE_SIN_RESIDENTE, tmp_path)
    original = ruta.read_bytes()
    assert _residencia("--none", "--config", str(ruta), "--now") == 0
    diff = _cambiadas(original, ruta.read_bytes())
    esperado = [
        ("-", "  resident:\n"),
        ("-", "    persistent: true\n"),
        ("-", "    swap: false\n"),
        ("-", "    exclusive: false\n"),
        ("-", "    members:\n"),
        ("-", "    - gemma3-4b\n"),
        ("+", "    - gemma3-4b\n"),
    ]
    assert diff == esperado
    copias = list(tmp_path.glob("config.yaml.*.bak"))
    assert len(copias) == 1 and copias[0].read_bytes() == original
    datos = yaml.safe_load(original)
    del datos["groups"]["resident"]
    datos["groups"]["swap"]["members"].append("gemma3-4b")
    assert yaml.safe_load(ruta.read_bytes()) == datos
    assert datos["models"]["gemma3-4b"]["ttl"] == 600


def test_ninguno_sin_un_unico_grupo_swap_pide_grupo(tmp_path, capsys):
    ruta = _escribe(
        tmp_path,
        b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\n"
        b"  b:\n    cmd: x --model b.gguf\n    ttl: 60\n  c:\n    cmd: x --model c.gguf\n    ttl: 60\n"
        b"groups:\n  fijo:\n    persistent: true\n    swap: false\n    exclusive: false\n"
        b"    members:\n    - a\n  g1:\n    swap: true\n    members:\n    - b\n"
        b"  g2:\n    members:\n    - c\n",
    )
    antes = _sha(ruta)
    assert _residencia("--config", str(ruta), "--none", "--now") == 2
    assert "--group" in capsys.readouterr().err
    assert _sha(ruta) == antes
    assert _residencia("--config", str(ruta), "--none", "--group", "g2", "--now") == 0
    assert yaml.safe_load(ruta.read_bytes())["groups"] == {
        "g1": {"swap": True, "members": ["b"]},
        "g2": {"members": ["c", "a"]},
    }


def test_ninguno_con_la_config_de_hoy_no_escribe(tmp_path, capsys):
    ruta = _copia(HOY, tmp_path)
    os.utime(ruta, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    antes = os.stat(ruta).st_mtime_ns
    assert _residencia("--config", str(ruta), "--none", "--now") == 0
    assert os.stat(ruta).st_mtime_ns == antes
    assert "nada que cambiar" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.bak"))


def test_ttl_cero_remite_a_fijar_y_menos_uno_solo_con_global_ttl(tmp_path, capsys):
    ruta = _copia(HOY, tmp_path)
    cargada = residencia.cargar(ruta)
    with pytest.raises(ErrorResidencia, match="--pin gemma4-12b"):
        residencia.plan_ttl({"gemma4-12b": 0}, cargada.datos, cargada.foto)
    assert _residencia("--config", str(ruta), "--ttl", "gemma4-12b=0", "--now") == 2
    assert "--pin" in capsys.readouterr().err
    with pytest.raises(ErrorResidencia, match="globalTTL"):
        residencia.plan_ttl({"gemma4-12b": -1}, cargada.datos, cargada.foto)

    con_global = _escribe(
        tmp_path,
        b"globalTTL: 300\nmodels:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\n",
        "g.yaml",
    )
    cargada = residencia.cargar(con_global)
    assert residencia.plan_ttl({"a": -1}, cargada.datos, cargada.foto) == [PonerTTL("a", -1)]


def test_fijar_un_residente_que_no_cabe(tmp_path, capsys):
    ruta = _copia(HOY, tmp_path)
    antes = _sha(ruta)
    rc = _residencia(
        "--config",
        str(ruta),
        "--pin",
        "gemma4-26b-a4b",
        "--vram-gb",
        "16",
        "--reserve-gb",
        "2",
        *_vram_args(),
        "--now",
    )
    salida = capsys.readouterr().err
    assert rc == 2
    assert "10,29 + 9,88" in salida
    assert "faltan 6,17 GiB" in salida
    assert _sha(ruta) == antes


def test_fijar_el_4b_con_la_config_de_hoy_se_acepta(tmp_path, capsys):
    ruta = _copia(HOY, tmp_path)
    rc = _residencia(
        "--config",
        str(ruta),
        "--pin",
        "gemma3-4b",
        "--vram-gb",
        "16",
        "--reserve-gb",
        "2",
        *_vram_args(),
        "--now",
    )
    salida = capsys.readouterr()
    aceptado = rc == 0 and ruta.read_bytes() != HOY.read_bytes()
    assert aceptado, salida.err
    assert "ocupará 3,19 GiB de VRAM de forma permanente" in salida.out
    datos = yaml.safe_load(ruta.read_bytes())
    assert datos["groups"]["residente"]["members"] == ["gemma3-4b"]
    assert datos["models"]["gemma3-4b"]["ttl"] == 0
    assert "gemma3-4b" not in datos["groups"]["swap"]["members"]


def test_fijar_escribe_exclusive_false_explicito(tmp_path):
    """Aclarado el 2026-10-07: sin la clave, v255 la toma como `true` y el residente desalojaría
    a los demás grupos al cargar."""
    ruta = _copia(HOY, tmp_path)
    rc = _residencia(
        "--config", str(ruta), "--pin", "gemma3-4b", "--vram-gb", "16", *_vram_args(), "--now"
    )
    assert rc == 0
    grupo = yaml.safe_load(ruta.read_bytes())["groups"]["residente"]
    assert grupo.get("exclusive") is False
    assert grupo.get("persistent") is True and grupo.get("swap") is False
    foto = topologia.leer(ruta)
    residente = "gemma3-4b"
    assert foto.residentes() == (residente,)
    assert not foto.choca(residente, "gemma4-26b-a4b")


def _gguf_minimo(ruta: Path, tamano: int) -> None:
    """Cabecera GGUF válida sin tensores, rellenada hasta `tamano` bytes (pocos KB)."""
    cabecera = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", 0)
    ruta.write_bytes(cabecera + b"\0" * (tamano - len(cabecera)))


def _config_con_gguf(tmp_path: Path) -> Path:
    modelos = []
    for nombre in ("a", "b"):
        gguf = tmp_path / f"{nombre}.gguf"
        _gguf_minimo(gguf, 4096)
        modelos.append(
            f"  {nombre}:\n    cmd: llama-server --model {gguf.as_posix()}\n    ttl: 60\n"
        )
    texto = (
        "models:\n" + "".join(modelos) + "groups:\n  g:\n    swap: true\n    exclusive: false\n"
        "    members:\n    - a\n    - b\n"
    )
    return _escribe(tmp_path, texto.encode())


def test_fijar_con_el_estimador_solo_si_paso_su_control(tmp_path, monkeypatch, capsys):
    ruta = _config_con_gguf(tmp_path)
    monkeypatch.setattr(lc, "ESTIMADOR_NCMOE_VALIDADO", False)
    assert _residencia("--config", str(ruta), "--pin", "a", "--vram-gb", "16", "--now") == 2
    err = capsys.readouterr().err
    assert "--vram-model a=GiB" in err and "--vram-model b=GiB" in err

    monkeypatch.setattr(lc, "ESTIMADOR_NCMOE_VALIDADO", True)
    assert _residencia("--config", str(ruta), "--pin", "a", "--vram-gb", "16", "--now") == 0
    assert yaml.safe_load(ruta.read_bytes())["groups"]["residente"]["members"] == ["a"]


def test_copia_con_fecha_sin_pisar(tmp_path, monkeypatch):
    ruta = _copia(HOY, tmp_path)
    monkeypatch.setattr(residencia, "_ahora", lambda: datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC))
    assert _residencia("--config", str(ruta), "--ttl", "gemma4-12b=60", "--now") == 0
    assert _residencia("--config", str(ruta), "--ttl", "gemma4-12b=90", "--now") == 0
    baks = sorted(tmp_path.glob("config.yaml.*.bak"))
    assert len(baks) == 2
    assert [b.name for b in baks] == [
        "config.yaml.20261007-120000-1.bak",
        "config.yaml.20261007-120000.bak",
    ]
    assert baks[1].read_bytes() == HOY.read_bytes()


def _replace_que_falla(veces: int):
    real = os.replace
    llamadas = {"n": 0}

    def falso(origen, destino):
        llamadas["n"] += 1
        if llamadas["n"] <= veces:
            raise PermissionError(13, "violación de compartición", None, 32)
        return real(origen, destino)

    return falso, llamadas


def test_reemplazo_atomico_reintenta_y_si_no_deja_el_original(tmp_path, monkeypatch):
    monkeypatch.setattr(residencia, "_dormir", lambda s: None)
    ruta = _copia(HOY, tmp_path)
    nuevo = residencia.editar(ruta.read_bytes(), [PonerTTL("gemma4-12b", 60)])

    falso, llamadas = _replace_que_falla(2)
    monkeypatch.setattr(residencia.os, "replace", falso)
    try:
        residencia.reemplazar_atomico(ruta, nuevo)
    except ErrorResidencia:
        pass  # se comprueba abajo: tenía que haberse escrito
    escrito = ruta.read_bytes() == nuevo
    assert escrito
    assert llamadas["n"] == 3

    ruta.write_bytes(HOY.read_bytes())
    falso, llamadas = _replace_que_falla(5)
    monkeypatch.setattr(residencia.os, "replace", falso)
    with pytest.raises(ErrorResidencia, match="5 intentos"):
        residencia.reemplazar_atomico(ruta, nuevo)
    assert ruta.read_bytes() == HOY.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.yaml"]


def test_restaurar_una_copia(tmp_path, capsys):
    ruta = _copia(HOY, tmp_path)
    assert _residencia("--config", str(ruta), "--ttl", "gemma4-12b=60", "--now") == 0
    (copia,) = tmp_path.glob("config.yaml.*.bak")
    cambiada = ruta.read_bytes()
    capsys.readouterr()
    assert _residencia("--config", str(ruta), "--restore", str(copia), "--now") == 0
    salida = capsys.readouterr().out
    assert ruta.read_bytes() == copia.read_bytes() == HOY.read_bytes()
    otras = [p for p in tmp_path.glob("config.yaml.*.bak") if p != copia]
    assert len(otras) == 1 and otras[0].read_bytes() == cambiada
    assert "no se puede confirmar la recarga" in salida


def test_restaurar_una_copia_que_no_cumple_load_go_se_niega(tmp_path, capsys):
    ruta = _copia(HOY, tmp_path)
    mala = _escribe(tmp_path, b"models:\n  a:\n    cmd: x\n    ttl: -5\n", "mala.bak")
    antes = _sha(ruta)
    assert _residencia("--config", str(ruta), "--restore", str(mala), "--now") == 2
    assert "load.go" in capsys.readouterr().err
    assert _sha(ruta) == antes


def test_un_lector_en_bucle_nunca_ve_un_yaml_a_medias(tmp_path, monkeypatch):
    """Restauración lenta (la escritura se para a mitad) con un lector leyendo sin parar."""
    ruta = _copia(HOY, tmp_path)
    copia = _copia(PRE_SIN_RESIDENTE, tmp_path, "copia.bak")
    validos = {HOY.read_bytes(), copia.read_bytes()}
    escribiendo = threading.Event()

    def escribir_lento(f, datos):
        f.write(datos[: len(datos) // 2])
        f.flush()
        escribiendo.set()
        time.sleep(0.4)
        f.write(datos[len(datos) // 2 :])

    monkeypatch.setattr(residencia, "_escribir_bytes", escribir_lento)
    vistos_rotos: list[int] = []
    lecturas = {"durante": 0}
    parar = threading.Event()

    def lector():
        while not parar.is_set():
            try:
                with open(ruta, "rb") as f:
                    visto = f.read()
            except OSError:
                continue
            if escribiendo.is_set():
                lecturas["durante"] += 1
            if visto not in validos:
                vistos_rotos.append(len(visto))
            time.sleep(0.005)

    hilo = threading.Thread(target=lector, daemon=True)
    hilo.start()
    try:
        residencia.reemplazar_atomico(ruta, copia.read_bytes())
    finally:
        parar.set()
        hilo.join(5)
    assert lecturas["durante"] >= 10, "el lector no leyó mientras se escribía"
    assert not vistos_rotos
    assert ruta.read_bytes() == copia.read_bytes()


def test_dry_run_solo_lineas_cambiadas_y_oculta_las_de_key(tmp_path, capsys):
    ruta = _escribe(
        tmp_path,
        b"# cabecera\nmodels:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60  # key: clave-falsa-2\n"
        b"  b:\n    cmd: x --model b.gguf\n    ttl: 60\n",
    )
    antes = _sha(ruta)
    assert _residencia("--config", str(ruta), "--ttl", "a=90", "--ttl", "b=30", "--dry-run") == 0
    salida = capsys.readouterr().out
    assert "clave-falsa" not in salida
    assert re.search(r"^-    5 \|     ttl: \*\*\*$", salida, re.MULTILINE)
    assert re.search(r"^\+    5 \|     ttl: \*\*\*$", salida, re.MULTILINE)
    assert re.search(r"^\+    8 \|     ttl: 30$", salida, re.MULTILINE)
    assert "cabecera" not in salida and "cmd" not in salida
    assert _sha(ruta) == antes


def test_toda_escritura_sin_ahora_se_niega(tmp_path, capsys):
    """Corte de T11: la comprobación previa (T13) aún contesta «no se sabe»."""
    ruta = _copia(HOY, tmp_path)
    antes = _sha(ruta)
    for argv in (
        ["--ttl", "gemma4-12b=60"],
        ["--pin", "gemma3-4b", "--vram-gb", "16", *_vram_args()],
    ):
        assert _residencia("--config", str(ruta), *argv) == 2
        assert "no se sabe si hay delegaciones en curso" in capsys.readouterr().err
    copia = _copia(PRE_SIN_RESIDENTE, tmp_path, "c.bak")
    assert _residencia("--config", str(ruta), "--restore", str(copia)) == 2
    assert "no se sabe si hay delegaciones en curso" in capsys.readouterr().err
    assert _sha(ruta) == antes
    assert not list(tmp_path.glob("config.yaml.*.bak"))


def test_init_llamaswap_ayuda_presenta_resident_como_opt_in(capsys):
    with pytest.raises(SystemExit):
        cli.run(["init-llamaswap", "--help"])
    ayuda = " ".join(capsys.readouterr().out.split())
    assert "residencia OPT-IN" in ayuda
    assert "default 0" in ayuda


def test_residencia_ayuda_explica_el_ttl_efectivo_cero(capsys):
    with pytest.raises(SystemExit):
        cli.run(["llamaswap", "residency", "--help"])
    ayuda = " ".join(capsys.readouterr().out.split())
    assert "SIN `globalTTL` NI `ttl` TODOS LOS MODELOS TIENEN TTL EFECTIVO 0" in ayuda


# --- Corrección tras la revisión de la ola 5 ---------------------------------------------------

_FINES_DE_LINEA = {
    "hoy.yaml": (0, 66),
    "pre-sin-residente-20261006.yaml": (0, 71),
    "pre-b10909-20260915.yaml": (47, 11),
}


def _fines_de_linea(datos: bytes) -> tuple[int, int]:
    """(CRLF, LF suelto)."""
    crlf = datos.count(b"\r\n")
    return crlf, datos.count(b"\n") - crlf


def test_los_fixtures_conservan_su_fin_de_linea():
    """`.gitattributes` los marca `-text`: un checkout de Windows con `autocrlf` no los convierte.
    Si los convirtiera, la tabla de edición probaría otra cosa (y el CI de Windows caería)."""
    assert sorted(_FINES_DE_LINEA) == sorted(p.name for p in FIXTURES.glob("*.yaml"))
    for nombre, esperado in _FINES_DE_LINEA.items():
        assert _fines_de_linea((FIXTURES / nombre).read_bytes()) == esperado, nombre


def test_restaurar_dry_run_tapa_las_listas_de_claves_y_los_token_de_env(tmp_path, capsys):
    actual = _escribe(
        tmp_path,
        b'apiKeys:\n  - "clave-falsa-actual-1"\n  - "clave-falsa-actual-2"\nmodels:\n  a:\n'
        b'    cmd: x --model a.gguf\n    env:\n      - "HF_TOKEN=clave-falsa-hf-actual"\n'
        b"    ttl: 60\n",
    )
    copia = _escribe(
        tmp_path,
        b'apiKeys:\n  - "clave-falsa-copia-1"\nmodels:\n  a:\n    cmd: x --model a.gguf\n'
        b'    env:\n      - "HF_TOKEN=clave-falsa-hf-copia"\n    ttl: 90\n',
        "copia.bak",
    )
    rc = _residencia("--config", str(actual), "--restore", str(copia), "--dry-run")
    salida = capsys.readouterr().out
    assert "clave-falsa" not in salida
    assert rc == 0
    # Guarda: el diff sí enseña lo que cambia, con los valores tapados.
    assert re.search(r"^-    2 \|   - \*\*\*$", salida, re.MULTILINE)
    assert '- "HF_TOKEN=***"' in salida
    assert re.search(r"^\+    8 \|     ttl: 90$", salida, re.MULTILINE)


def test_fijar_cuenta_los_residentes_que_ya_hay(tmp_path, capsys):
    """Sonda de la revisión: `r` (6 GiB) ya es residente; `--pin a` (6) con `big` (7) no cabe en
    14: 6 + 6 + 7 = 19. Con la fórmula vieja (`a` + el mayor de los demás) daba 13 y lo aceptaba."""
    ruta = _escribe(
        tmp_path,
        b"models:\n  r:\n    cmd: x --model r.gguf\n    ttl: 0\n"
        b"  a:\n    cmd: x --model a.gguf\n    ttl: 60\n  big:\n    cmd: x --model big.gguf\n"
        b"    ttl: 60\ngroups:\n  fijo:\n    persistent: true\n    swap: false\n    exclusive: false\n"
        b"    members:\n    - r\n  swap:\n    swap: true\n    exclusive: false\n    members:\n"
        b"    - a\n    - big\n",
    )
    antes = _sha(ruta)
    rc = _residencia(
        "--config",
        str(ruta),
        "--pin",
        "a",
        "--vram-gb",
        "16",
        "--vram-model",
        "r=6",
        "--vram-model",
        "a=6",
        "--vram-model",
        "big=7",
        "--now",
    )
    err = capsys.readouterr().err
    assert "faltan 5,00 GiB" in err
    assert "6,00 (residentes que ya hay: r)" in err
    assert rc == 2
    assert _sha(ruta) == antes


def test_fijar_un_grupo_swap_false_cuenta_entero(tmp_path, capsys):
    """Un grupo `swap: false` carga a todos sus miembros a la vez: el peor caso es su suma."""
    ruta = _escribe(
        tmp_path,
        b"models:\n  m:\n    cmd: x --model m.gguf\n    ttl: 60\n  p:\n    cmd: x --model p.gguf\n"
        b"    ttl: 60\n  q:\n    cmd: x --model q.gguf\n    ttl: 60\n"
        b"groups:\n  juntos:\n    swap: false\n    exclusive: false\n    members:\n    - p\n    - q\n",
    )
    rc = _residencia(
        "--config",
        str(ruta),
        "--pin",
        "m",
        "--vram-gb",
        "16",
        "--vram-model",
        "m=5",
        "--vram-model",
        "p=5",
        "--vram-model",
        "q=5",
        "--now",
    )
    assert "faltan 1,00 GiB" in capsys.readouterr().err
    assert rc == 2


def test_error_de_yaml_no_cita_el_fragmento(tmp_path, capsys):
    contenido = b'apiKeys:\n  - "clave-secreta-sin-cerrar\nmodels:\n  a:\n    cmd: x\n'
    with pytest.raises(yaml.YAMLError) as crudo:
        yaml.safe_load(contenido)
    assert "clave-secreta-sin-cerrar" in str(crudo.value)  # guarda: PyYAML sí lo citaría
    with pytest.raises(ErrorResidencia) as e:
        residencia.editar(contenido, [PonerTTL("a", 30)])
    assert "clave-secreta-sin-cerrar" not in str(e.value)
    assert "línea" in str(e.value)
    with pytest.raises(ErrorResidencia) as e:
        residencia.validar_copia(contenido)
    assert "clave-secreta-sin-cerrar" not in str(e.value)
    ruta = _escribe(tmp_path, contenido)
    assert _residencia("--config", str(ruta)) == 2
    err = capsys.readouterr().err
    assert "clave-secreta-sin-cerrar" not in err
    assert "no se puede leer" in err


def test_dry_run_numera_las_lineas_y_dice_que_el_modelo_sale_de_swap(tmp_path, capsys):
    ruta = _copia(HOY, tmp_path)
    lineas = HOY.read_text(encoding="utf-8").splitlines()
    n_miembro = lineas.index("    - gemma3-4b") + 1
    rc = _residencia(
        "--config", str(ruta), "--pin", "gemma3-4b", "--vram-gb", "16", *_vram_args(), "--dry-run"
    )
    assert rc == 0
    salida = capsys.readouterr().out
    assert "# gemma3-4b sale del grupo `swap`" in salida
    assert re.search(r"^- +" + str(n_miembro) + r" \|     - gemma3-4b$", salida, re.MULTILINE)
    assert re.search(r"^\+ +" + str(len(lineas)) + r" \|   residente:$", salida, re.MULTILINE)
    assert ruta.read_bytes() == HOY.read_bytes()


def test_toda_consulta_del_cli_al_daemon_pasa_por_su_destino():
    """Cada llamada a `httpx2` de `cli.py` construye su URL con `_url_del_daemon()` (que sale de
    `_destino_del_daemon`, lo que corta la fixture autouse). Guarda para T13."""
    import ast
    import inspect

    arbol = ast.parse(inspect.getsource(cli))
    llamadas = [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Attribute)
        and isinstance(nodo.func.value, ast.Name)
        and nodo.func.value.id == "httpx2"
        and nodo.func.attr in {"get", "post", "put", "delete", "request", "stream"}
    ]
    assert llamadas, "no hay ninguna consulta: la guarda no comprobaría nada"
    for llamada in llamadas:
        url = llamada.args[0] if llamada.args else None
        usa_destino = url is not None and any(
            isinstance(n, ast.Name) and n.id == "_url_del_daemon" for n in ast.walk(url)
        )
        assert usa_destino, f"cli.py:{llamada.lineno} pregunta al daemon sin `_url_del_daemon()`"


def test_routing_que_no_es_un_mapa_es_una_negativa(tmp_path, capsys):
    contenido = b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\nrouting: 5\n"
    with pytest.raises(ErrorResidencia, match="`routing` no es un mapa"):
        residencia.editar(contenido, [PonerTTL("a", 30)])
    ruta = _escribe(tmp_path, contenido)
    assert _residencia("--config", str(ruta), "--ttl", "a=30", "--now") == 2
    assert "`routing` no es un mapa" in capsys.readouterr().err


def test_fijar_un_modelo_que_ya_esta_en_un_grupo_residente_solo_pone_ttl_0(tmp_path):
    ruta = _copia(PRE_SIN_RESIDENTE, tmp_path)
    original = ruta.read_bytes()
    rc = _residencia(
        "--config", str(ruta), "--pin", "gemma3-4b", "--vram-gb", "16", *_vram_args(), "--now"
    )
    assert rc == 0
    assert _cambiadas(original, ruta.read_bytes()) == [
        ("-", "    ttl: 600\n"),
        ("+", "    ttl: 0\n"),
    ]


def test_config_cambiada_durante_la_edicion_no_se_escribe(tmp_path, monkeypatch, capsys):
    ruta = _copia(HOY, tmp_path)
    modificado = HOY.read_bytes().replace(b"    ttl: 30\n", b"    ttl: 45\n")
    assert modificado != HOY.read_bytes()
    real = residencia.editar_con_diff

    def editar_y_que_otro_toque(original, cambios):
        resultado = real(original, cambios)
        ruta.write_bytes(modificado)  # otro editor guarda entre la carga y la escritura
        return resultado

    monkeypatch.setattr(residencia, "editar_con_diff", editar_y_que_otro_toque)
    rc = _residencia("--config", str(ruta), "--ttl", "gemma4-26b-a4b=60", "--now")
    assert ruta.read_bytes() == modificado
    assert rc == 2
    assert "cambió mientras se editaba" in capsys.readouterr().err
    assert not list(tmp_path.glob("config.yaml.*.bak"))


def test_la_ayuda_de_residency_no_tiene_opciones_en_espanol(capsys):
    """Los nombres del CLI van en inglés, como el resto (decisión del usuario, 2026-10-07)."""
    with pytest.raises(SystemExit):
        cli.run(["llamaswap", "residency", "--help"])
    ayuda = capsys.readouterr().out
    assert "--none" in ayuda and "--pin" in ayuda  # guarda: es la ayuda de verdad
    for espanol in (
        "--ninguno",
        "--fijar",
        "--restaurar",
        "--ahora",
        "--vram-modelo",
        "--grupo",
        "--reserva-gb",
    ):
        assert espanol not in ayuda, espanol
    with pytest.raises(SystemExit):
        cli.run(["llamaswap", "residencia"])
