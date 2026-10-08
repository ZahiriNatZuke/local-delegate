"""T11: editor y CLI de residencia sobre copias (REQ-029 a REQ-033, REQ-035, REQ-038 de ficheros).

Todo se escribe sobre copias en `tmp_path`: la config real de llama-swap no se toca nunca. Las
copias de las configs reales (`tests/fixtures/residencia/`) llevan las claves sustituidas por
`clave-falsa-N`, y un test lo comprueba. La consulta del CLI al daemon la corta la fixture autouse
`conftest.real_daemon_down`.
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
from conftest import CUT_DAEMON, DEAD_PORT

from local_delegate import checks, cli, residency, topology
from local_delegate import llamaswap_config as lc
from local_delegate.residency import (
    AddMember,
    CreateGroup,
    DeleteGroup,
    RemoveMember,
    ResidencyError,
    SetTTL,
)

FIXTURES = Path(__file__).parent / "fixtures" / "residencia"
TODAY = FIXTURES / "hoy.yaml"
PRE_NO_RESIDENT = FIXTURES / "pre-sin-residente-20261006.yaml"
PRE_B10909 = FIXTURES / "pre-b10909-20260915.yaml"

# Cifras medidas en F2 (insumos/llamaswap-grupos.md §2), en GiB; el 2B no se midió (extremo alto).
MEASURED_VRAM = {
    "gemma3-4b": "3,19",
    "gemma4-12b": "8,85",
    "qwen36-35b-a3b": "9,88",
    "gemma4-26b-a4b": "10,29",
    "qwen35-2b": "3,5",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(origin: Path, tmp_path: Path, name: str = "config.yaml") -> Path:
    target = tmp_path / name
    target.write_bytes(origin.read_bytes())
    return target


def _writes(tmp_path: Path, content: bytes, name: str = "config.yaml") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _changed(before: bytes, after: bytes) -> list[tuple[str, str]]:
    """Las líneas que cambian, CON su fin de línea: un cambio de LF a CRLF también cuenta."""
    a = before.decode("utf-8").splitlines(keepends=True)
    b = after.decode("utf-8").splitlines(keepends=True)
    output: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            output += [("-", line) for line in a[i1:i2]]
            output += [("+", line) for line in b[j1:j2]]
    return output


def _residency(*argv: str) -> int:
    return cli.run(["llamaswap", "residency", *argv])


def _vram_args() -> list[str]:
    args: list[str] = []
    for model, gib in MEASURED_VRAM.items():
        args += ["--vram-model", f"{model}={gib}"]
    return args


# --- Guarda: ningún fixture lleva una clave real ---------------------------------------------

_SENSIBLE = re.compile(r"(?i)key|token|secret|password|bearer")
_FAKE = re.compile(r"^clave-falsa-\d+$")


def _key_shaped(text: str) -> list[str]:
    """Cadenas con forma de clave que no son `clave-falsa-N`. Nunca devuelve la cadena entera."""
    found_ones: list[str] = []
    sensitive_list: int | None = None

    def value(raw: str) -> str:
        raw = raw.split(" #", 1)[0].strip()
        return raw.strip("\"'")

    for n, line in enumerate(text.splitlines(), 1):
        body = line.lstrip("\ufeff")
        sangria = len(body) - len(body.lstrip(" "))
        clean = body.strip()
        if sensitive_list is not None:
            item = re.match(r"^#?\s*-\s+(.*)$", clean)
            if item and sangria > sensitive_list:
                if not _FAKE.match(value(item.group(1))):
                    found_ones.append(f"línea {n}: elemento de una lista de claves")
                continue
            if clean and not clean.startswith("#"):
                sensitive_list = None
        if _SENSIBLE.search(body) and not clean.startswith("#") and ":" in clean:
            key, _, rest = clean.partition(":")
            if not value(rest):
                sensitive_list = sangria
            elif _SENSIBLE.search(key) and not _FAKE.match(value(rest)):
                found_ones.append(f"línea {n}: valor de `{key.strip()}`")
        for patron, name in (
            (r"\bsk-[A-Za-z0-9_-]{8,}", "sk-…"),
            (r"(?i)\bbearer\s+(?!clave-falsa-)\S+", "Bearer …"),
            (r"--api-key[ =](?!clave-falsa-)\S+", "--api-key …"),
            (r"(?<![\w.-])[A-Za-z0-9_+/=]{32,}(?![\w.-])", "token largo"),
        ):
            if re.search(patron, body):
                found_ones.append(f"línea {n}: {name}")
    return found_ones


def test_no_fixture_has_real_key():
    files_list = sorted(FIXTURES.glob("*.yaml"))
    assert len(files_list) >= 3, "no hay fixtures que comprobar"
    for file in files_list:
        text = file.read_bytes().decode("utf-8")
        assert _key_shaped(text) == [], file.name
        assert "clave-falsa-1" in text, f"{file.name}: la sustitución no llegó a la lista apiKeys"
        assert not re.search(r"(?i)[a-z]:[\\/]users[\\/]", text), file.name
        assert not re.search(r"\b100\.\d+\.\d+\.\d+|ts\.net", text), file.name


@pytest.mark.parametrize(
    "planted",
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
def test_guard_detects_planted_key(planted):
    """Control positivo de la guarda de arriba: cada forma de clave plantada se detecta."""
    assert _key_shaped(planted) != []


@pytest.mark.parametrize("planted", ['"sk-plantada0123456789"', "'cualquier-valor'"])
def test_guard_detects_key_planted_in_real_fixture(planted):
    text = TODAY.read_text(encoding="utf-8")
    assert '"clave-falsa-1"' in text
    assert _key_shaped(text.replace('"clave-falsa-1"', planted)) != []


def test_guard_does_not_fire_on_valid_content():
    text = (FIXTURES / "hoy.yaml").read_text(encoding="utf-8")
    assert _key_shaped(text) == []
    assert _key_shaped('apiKeys:\n  - "clave-falsa-7"\n') == []


# --- Edición quirúrgica ----------------------------------------------------------------------

_INDENTED = b"""models:
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

_COMMENTS = b"""# cabecera que safe_dump perderia
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

_FOLDED = b"""models:
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

_NO_FINAL_NEWLINE = b"""models:
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

_QUOTES = b"""models:
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

_RESIDENT_GROUP_LINES_TODAY = [
    ("+", "  residente:\n"),
    ("+", "    persistent: true\n"),
    ("+", "    swap: false\n"),
    ("+", "    exclusive: false\n"),
    ("+", "    members:\n"),
    ("+", "    - gemma3-4b\n"),
]

_CASES = {
    "secuencia sangrada": (
        _INDENTED,
        [AddMember("g", "c")],
        [("+", "      - c\n")],
    ),
    "secuencia sin sangrar (config de hoy)": (
        TODAY.read_bytes(),
        [
            RemoveMember("swap", "gemma3-4b"),
            CreateGroup("residente", True, False, False, ("gemma3-4b",)),
            SetTTL("gemma3-4b", 0),
        ],
        [
            ("-", "    ttl: 120\n"),
            ("+", "    ttl: 0\n"),
            ("-", "    - gemma3-4b\n"),
            *_RESIDENT_GROUP_LINES_TODAY,
        ],
    ),
    "comentarios en linea y entre miembros": (
        _COMMENTS,
        [RemoveMember("g", "b"), AddMember("g", "c")],
        [("-", "    - b  # el segundo\n"), ("+", "    - c\n")],
    ),
    "ttl tras un cmd plegado entre comillas": (
        _FOLDED,
        [SetTTL("a", 120)],
        [("+", "    ttl: 120\n")],
    ),
    "ttl tras un escalar | y tras uno >": (
        _LITERAL,
        [SetTTL("a", 120), SetTTL("b", 30)],
        [("+", "    ttl: 120\n"), ("+", "    ttl: 30\n")],
    ),
    "grupo al final sin salto final": (
        _NO_FINAL_NEWLINE,
        [AddMember("g", "c")],
        [("-", "    - b"), ("+", "    - b\n"), ("+", "    - c")],
    ),
    "fin de linea mixto (config del 2026-09-15)": (
        PRE_B10909.read_bytes(),
        [DeleteGroup("resident"), AddMember("swap", "gemma3-4b")],
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
        [SetTTL("a", 90), SetTTL("b", 30)],
        [("-", "    ttl: 60\r\n"), ("+", "    ttl: 90\r\n"), ("+", "    ttl: 30\r\n")],
    ),
    "claves entre comillas": (
        _QUOTES,
        [SetTTL("a", 90), AddMember("g", "c")],
        [("-", "    'ttl': 60\n"), ("+", "    'ttl': 90\n"), ("+", "    - 'c'\n")],
    ),
    "sintaxis routing": (
        _ROUTING,
        [DeleteGroup("g1"), AddMember("g2", "a")],
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


@pytest.mark.parametrize("case", list(_CASES))
def test_surgical_edit_only_changes_requested_lines(case):
    original, changes, expected = _CASES[case]
    new = residency.edit(original, changes)
    changed_lines = _changed(original, new)
    assert changed_lines == expected
    # Lo que no se pidió queda igual: BOM, y el salto final o su ausencia.
    assert new.startswith(residency.BOM) == original.startswith(residency.BOM)
    assert new.endswith(b"\n") == original.endswith(b"\n")


def test_table_covers_spec_requirements():
    """Guarda: los casos que la spec nombra están en la tabla y cada uno pide algún cambio."""
    assert len(_CASES) == 10
    assert all(changes and expected for _o, changes, expected in _CASES.values())
    assert (
        b"\r\n" in PRE_B10909.read_bytes() and b"\n    - qwen3-vl-8b\n" in PRE_B10909.read_bytes()
    )


_REFUSALS = {
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


@pytest.mark.parametrize("case", list(_REFUSALS))
def test_refusals_with_reason_and_file_intact(case, tmp_path, capsys):
    content, reason = _REFUSALS[case]
    with pytest.raises(ResidencyError, match=reason):
        residency.edit(content, [SetTTL("a", 30)])
    path = _writes(tmp_path, content)
    before = _sha(path)
    assert _residency("--config", str(path), "--ttl", "a=30", "--now") == 2
    assert reason in capsys.readouterr().err
    assert _sha(path) == before
    assert not list(tmp_path.glob("*.bak"))


def test_duplicate_keys_refused_with_reason():
    """Sin la negativa, el editor tocaría la PRIMERA `ttl` y `safe_load` se quedaría con la última:
    la autocomprobación también lo pararía, pero con otro mensaje. Por eso el `match`."""
    content = b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\n    ttl: 90\n"
    with pytest.raises(ResidencyError, match="clave duplicada"):
        residency.edit(content, [SetTTL("a", 30)])


def test_self_check_stops_on_inconsistent_result(monkeypatch):
    """Si una edición de texto se equivoca, no se devuelve nada (aquí se fuerza el fallo)."""
    monkeypatch.setattr(residency, "_apply_edits", lambda t, e: t.replace("60", "61", 1))
    with pytest.raises(ResidencyError, match="autocomprobación no cuadra"):
        residency.edit(_INDENTED, [SetTTL("a", 90)])


# --- La consulta al daemon y la config que no se sabe ------------------------------------------


def test_fixture_cuts_real_daemon(request):
    """La consulta del CLI va al servidor que corta (`conftest.RejectingServer`), no al daemon:
    falla en el acto (no los ~2,1 s de un puerto cerrado en Windows) y el corte la recibió."""
    import httpx2

    dead_port = request.node.stash.get(DEAD_PORT, None)
    port = urlsplit(cli._daemon_url()).port
    assert port == dead_port
    assert port != checks.daemon_host_port()[1], "la consulta iría al puerto del daemon real"
    cut = request.node.stash[CUT_DAEMON]
    before = cut.accepted
    start_ts = time.monotonic()
    with pytest.raises(httpx2.HTTPError):
        httpx2.get(f"{cli._daemon_url()}/api/llamaswap/status", timeout=5)
    assert time.monotonic() - start_ts < 0.5
    assert cut.accepted > before, "la conexión no llegó al servidor que corta"


def _file_spy(monkeypatch) -> list[tuple[str, object]]:
    open_ones: list[tuple[str, object]] = []
    watched = {"local_delegate.residency", "local_delegate.cli"}

    def spy(original):
        def wrapped(*args, **kwargs):
            module = sys._getframe(1).f_globals.get("__name__")
            if module in watched:
                open_ones.append((module, args[0] if args else None))
            return original(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(builtins, "open", spy(builtins.open))
    monkeypatch.setattr(Path, "read_bytes", spy(Path.read_bytes))
    monkeypatch.setattr(Path, "read_text", spy(Path.read_text))
    monkeypatch.setattr(Path, "open", spy(Path.open))
    return open_ones


def test_without_config_unknown(monkeypatch, tmp_path, capsys):
    # Un `config.yaml` en el directorio actual: una caída a una ruta por defecto lo abriría.
    _copy(TODAY, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    open_ones = _file_spy(monkeypatch)

    rc = _residency()
    assert open_ones == []
    assert rc == 2
    assert "no se sabe" in capsys.readouterr().err

    # Guarda: el espía sí ve una lectura de la config cuando hay `--config`.
    assert _residency("--config", str(tmp_path / "config.yaml")) == 0
    assert open_ones, "el espía no ve las lecturas: la comprobación de arriba no valdría"


# --- Escenarios ------------------------------------------------------------------------------


def test_show_residency(tmp_path, capsys):
    path = _copy(TODAY, tmp_path)
    assert _residency("--config", str(path)) == 0
    output = capsys.readouterr().out
    assert "sin residente (recomendado)" in output
    rows = {
        line.split()[0]: line.split()
        for line in output.splitlines()
        if line.split() and line.split()[0] in topology.read(path).models
    }
    assert len(rows) == 5
    ttls = {m: row[5] for m, row in rows.items()}
    assert ttls == {
        "gemma3-4b": "120",
        "qwen35-2b": "120",
        "gemma4-26b-a4b": "120",
        "qwen36-35b-a3b": "120",
        "gemma4-12b": "30",
    }
    assert "llama-server" not in output
    assert "--port" not in output
    assert "clave-falsa" not in output


def test_config_without_global_ttl_or_ttl_all_resident(tmp_path, capsys):
    """Aclarado el 2026-10-07: sin `globalTTL` ni `ttl`, todos tienen TTL efectivo 0."""
    path = _writes(
        tmp_path,
        b"models:\n  a:\n    cmd: x --model a.gguf\n  b:\n    cmd: x --model b.gguf\n"
        b"groups:\n  g:\n    swap: true\n    exclusive: false\n    members:\n    - a\n    - b\n",
    )
    loaded_one = residency.load(path)
    view = residency.view(loaded_one.snapshot, loaded_one.data)
    models = ["a", "b"]
    assert set(view.residents) == set(models)
    text = view.text()
    assert "residente: a" in text and "residente: b" in text
    assert "sin `globalTTL` ni `ttl`, el TTL efectivo es 0" in text
    # --none pide --ttl para todos y dice que no hay TTL que sugerir.
    assert _residency("--config", str(path), "--none") == 2
    err = capsys.readouterr().err
    assert "no queda ningún TTL distinto de 0 que sugerir" in err
    assert "--ttl MODEL=SECONDS" in err


def test_none_suggests_most_frequent_ttl_without_mmproj(tmp_path, capsys):
    path = _writes(
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
    before = _sha(path)
    assert _residency("--config", str(path), "--none", "--now") == 2
    assert "--ttl r=120" in capsys.readouterr().err
    assert _sha(path) == before
    assert _residency("--config", str(path), "--none", "--ttl", "r=120", "--now") == 0
    assert yaml.safe_load(path.read_bytes())["models"]["r"]["ttl"] == 120


def test_back_to_no_resident_from_2026_09_15_config(tmp_path, capsys):
    path = _copy(PRE_NO_RESIDENT, tmp_path)
    original = path.read_bytes()
    assert _residency("--none", "--config", str(path), "--now") == 0
    diff = _changed(original, path.read_bytes())
    expected = [
        ("-", "  resident:\n"),
        ("-", "    persistent: true\n"),
        ("-", "    swap: false\n"),
        ("-", "    exclusive: false\n"),
        ("-", "    members:\n"),
        ("-", "    - gemma3-4b\n"),
        ("+", "    - gemma3-4b\n"),
    ]
    assert diff == expected
    copies = list(tmp_path.glob("config.yaml.*.bak"))
    assert len(copies) == 1 and copies[0].read_bytes() == original
    data = yaml.safe_load(original)
    del data["groups"]["resident"]
    data["groups"]["swap"]["members"].append("gemma3-4b")
    assert yaml.safe_load(path.read_bytes()) == data
    assert data["models"]["gemma3-4b"]["ttl"] == 600


def test_none_without_single_swap_group_asks_group(tmp_path, capsys):
    path = _writes(
        tmp_path,
        b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\n"
        b"  b:\n    cmd: x --model b.gguf\n    ttl: 60\n  c:\n    cmd: x --model c.gguf\n    ttl: 60\n"
        b"groups:\n  fijo:\n    persistent: true\n    swap: false\n    exclusive: false\n"
        b"    members:\n    - a\n  g1:\n    swap: true\n    members:\n    - b\n"
        b"  g2:\n    members:\n    - c\n",
    )
    before = _sha(path)
    assert _residency("--config", str(path), "--none", "--now") == 2
    assert "--group" in capsys.readouterr().err
    assert _sha(path) == before
    assert _residency("--config", str(path), "--none", "--group", "g2", "--now") == 0
    assert yaml.safe_load(path.read_bytes())["groups"] == {
        "g1": {"swap": True, "members": ["b"]},
        "g2": {"members": ["c", "a"]},
    }


def test_none_with_todays_config_writes_nothing(tmp_path, capsys):
    path = _copy(TODAY, tmp_path)
    os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    before = os.stat(path).st_mtime_ns
    assert _residency("--config", str(path), "--none", "--now") == 0
    assert os.stat(path).st_mtime_ns == before
    assert "nada que cambiar" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.bak"))


def test_ttl_zero_points_to_pin_and_minus_one_only_with_global_ttl(tmp_path, capsys):
    path = _copy(TODAY, tmp_path)
    loaded_one = residency.load(path)
    with pytest.raises(ResidencyError, match="--pin gemma4-12b"):
        residency.plan_ttl({"gemma4-12b": 0}, loaded_one.data, loaded_one.snapshot)
    assert _residency("--config", str(path), "--ttl", "gemma4-12b=0", "--now") == 2
    assert "--pin" in capsys.readouterr().err
    with pytest.raises(ResidencyError, match="globalTTL"):
        residency.plan_ttl({"gemma4-12b": -1}, loaded_one.data, loaded_one.snapshot)

    with_global = _writes(
        tmp_path,
        b"globalTTL: 300\nmodels:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\n",
        "g.yaml",
    )
    loaded_one = residency.load(with_global)
    assert residency.plan_ttl({"a": -1}, loaded_one.data, loaded_one.snapshot) == [SetTTL("a", -1)]


def test_pin_resident_that_does_not_fit(tmp_path, capsys):
    path = _copy(TODAY, tmp_path)
    before = _sha(path)
    rc = _residency(
        "--config",
        str(path),
        "--pin",
        "gemma4-26b-a4b",
        "--vram-gb",
        "16",
        "--reserve-gb",
        "2",
        *_vram_args(),
        "--now",
    )
    output = capsys.readouterr().err
    assert rc == 2
    assert "10,29 + 9,88" in output
    assert "faltan 6,17 GiB" in output
    assert _sha(path) == before


def test_pin_4b_with_todays_config_accepted(tmp_path, capsys):
    path = _copy(TODAY, tmp_path)
    rc = _residency(
        "--config",
        str(path),
        "--pin",
        "gemma3-4b",
        "--vram-gb",
        "16",
        "--reserve-gb",
        "2",
        *_vram_args(),
        "--now",
    )
    output = capsys.readouterr()
    accepted = rc == 0 and path.read_bytes() != TODAY.read_bytes()
    assert accepted, output.err
    assert "ocupará 3,19 GiB de VRAM de forma permanente" in output.out
    data = yaml.safe_load(path.read_bytes())
    assert data["groups"]["residente"]["members"] == ["gemma3-4b"]
    assert data["models"]["gemma3-4b"]["ttl"] == 0
    assert "gemma3-4b" not in data["groups"]["swap"]["members"]


def test_pin_writes_explicit_exclusive_false(tmp_path):
    """Aclarado el 2026-10-07: sin la clave, v255 la toma como `true` y el residente desalojaría
    a los demás grupos al cargar."""
    path = _copy(TODAY, tmp_path)
    rc = _residency(
        "--config", str(path), "--pin", "gemma3-4b", "--vram-gb", "16", *_vram_args(), "--now"
    )
    assert rc == 0
    group = yaml.safe_load(path.read_bytes())["groups"]["residente"]
    assert group.get("exclusive") is False
    assert group.get("persistent") is True and group.get("swap") is False
    snapshot = topology.read(path)
    resident = "gemma3-4b"
    assert snapshot.residents() == (resident,)
    assert not snapshot.clashes(resident, "gemma4-26b-a4b")


def _minimal_gguf(path: Path, size: int) -> None:
    """Cabecera GGUF válida sin tensores, rellenada hasta `size` bytes (pocos KB)."""
    header = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", 0)
    path.write_bytes(header + b"\0" * (size - len(header)))


def _config_with_gguf(tmp_path: Path) -> Path:
    models = []
    for name in ("a", "b"):
        gguf = tmp_path / f"{name}.gguf"
        _minimal_gguf(gguf, 4096)
        models.append(f"  {name}:\n    cmd: llama-server --model {gguf.as_posix()}\n    ttl: 60\n")
    text = (
        "models:\n" + "".join(models) + "groups:\n  g:\n    swap: true\n    exclusive: false\n"
        "    members:\n    - a\n    - b\n"
    )
    return _writes(tmp_path, text.encode())


def test_pin_with_estimator_only_if_control_passed(tmp_path, monkeypatch, capsys):
    path = _config_with_gguf(tmp_path)
    monkeypatch.setattr(lc, "NCMOE_ESTIMATOR_VALIDATED", False)
    assert _residency("--config", str(path), "--pin", "a", "--vram-gb", "16", "--now") == 2
    err = capsys.readouterr().err
    assert "--vram-model a=GiB" in err and "--vram-model b=GiB" in err

    monkeypatch.setattr(lc, "NCMOE_ESTIMATOR_VALIDATED", True)
    assert _residency("--config", str(path), "--pin", "a", "--vram-gb", "16", "--now") == 0
    assert yaml.safe_load(path.read_bytes())["groups"]["residente"]["members"] == ["a"]


def test_dated_copy_without_overwrite(tmp_path, monkeypatch):
    path = _copy(TODAY, tmp_path)
    monkeypatch.setattr(residency, "_now", lambda: datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC))
    assert _residency("--config", str(path), "--ttl", "gemma4-12b=60", "--now") == 0
    assert _residency("--config", str(path), "--ttl", "gemma4-12b=90", "--now") == 0
    baks = sorted(tmp_path.glob("config.yaml.*.bak"))
    assert len(baks) == 2
    assert [b.name for b in baks] == [
        "config.yaml.20261007-120000-1.bak",
        "config.yaml.20261007-120000.bak",
    ]
    assert baks[1].read_bytes() == TODAY.read_bytes()


def _failing_replace(times: int):
    real = os.replace
    calls = {"n": 0}

    def fake(origin, target):
        calls["n"] += 1
        if calls["n"] <= times:
            raise PermissionError(13, "violación de compartición", None, 32)
        return real(origin, target)

    return fake, calls


def test_atomic_replace_retries_else_keeps_original(tmp_path, monkeypatch):
    monkeypatch.setattr(residency, "_sleep", lambda s: None)
    path = _copy(TODAY, tmp_path)
    new = residency.edit(path.read_bytes(), [SetTTL("gemma4-12b", 60)])

    fake, calls = _failing_replace(2)
    monkeypatch.setattr(residency.os, "replace", fake)
    try:
        residency.atomic_replace(path, new)
    except ResidencyError:
        pass  # se comprueba abajo: tenía que haberse escrito
    written_one = path.read_bytes() == new
    assert written_one
    assert calls["n"] == 3

    path.write_bytes(TODAY.read_bytes())
    fake, calls = _failing_replace(5)
    monkeypatch.setattr(residency.os, "replace", fake)
    with pytest.raises(ResidencyError, match="5 intentos"):
        residency.atomic_replace(path, new)
    assert path.read_bytes() == TODAY.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.yaml"]


def test_restore_a_copy(tmp_path, capsys):
    path = _copy(TODAY, tmp_path)
    assert _residency("--config", str(path), "--ttl", "gemma4-12b=60", "--now") == 0
    (copy,) = tmp_path.glob("config.yaml.*.bak")
    changed = path.read_bytes()
    capsys.readouterr()
    assert _residency("--config", str(path), "--restore", str(copy), "--now") == 0
    output = capsys.readouterr().out
    assert path.read_bytes() == copy.read_bytes() == TODAY.read_bytes()
    other_ones = [p for p in tmp_path.glob("config.yaml.*.bak") if p != copy]
    assert len(other_ones) == 1 and other_ones[0].read_bytes() == changed
    assert "no se puede confirmar la recarga" in output


def test_restore_copy_failing_load_go_refused(tmp_path, capsys):
    path = _copy(TODAY, tmp_path)
    bad_one = _writes(tmp_path, b"models:\n  a:\n    cmd: x\n    ttl: -5\n", "mala.bak")
    before = _sha(path)
    assert _residency("--config", str(path), "--restore", str(bad_one), "--now") == 2
    assert "load.go" in capsys.readouterr().err
    assert _sha(path) == before


def test_looping_reader_never_sees_half_written_yaml(tmp_path, monkeypatch):
    """Restauración lenta (la escritura se para a mitad) con un lector leyendo sin parar."""
    path = _copy(TODAY, tmp_path)
    copy = _copy(PRE_NO_RESIDENT, tmp_path, "copia.bak")
    valid = {TODAY.read_bytes(), copy.read_bytes()}
    writing = threading.Event()

    def write_slow(f, data):
        f.write(data[: len(data) // 2])
        f.flush()
        writing.set()
        time.sleep(0.4)
        f.write(data[len(data) // 2 :])

    monkeypatch.setattr(residency, "_write_bytes", write_slow)
    seen_broken: list[int] = []
    reads = {"durante": 0}
    stop_now = threading.Event()

    def reader():
        while not stop_now.is_set():
            try:
                with open(path, "rb") as f:
                    seen = f.read()
            except OSError:
                continue
            if writing.is_set():
                reads["durante"] += 1
            if seen not in valid:
                seen_broken.append(len(seen))
            time.sleep(0.005)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        residency.atomic_replace(path, copy.read_bytes())
    finally:
        stop_now.set()
        thread.join(5)
    assert reads["durante"] >= 10, "el lector no leyó mientras se escribía"
    assert not seen_broken
    assert path.read_bytes() == copy.read_bytes()


def test_dry_run_only_changed_lines_and_hides_key_lines(tmp_path, capsys):
    path = _writes(
        tmp_path,
        b"# cabecera\nmodels:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60  # key: clave-falsa-2\n"
        b"  b:\n    cmd: x --model b.gguf\n    ttl: 60\n",
    )
    before = _sha(path)
    assert _residency("--config", str(path), "--ttl", "a=90", "--ttl", "b=30", "--dry-run") == 0
    output = capsys.readouterr().out
    assert "clave-falsa" not in output
    assert re.search(r"^-    5 \|     ttl: \*\*\*$", output, re.MULTILINE)
    assert re.search(r"^\+    5 \|     ttl: \*\*\*$", output, re.MULTILINE)
    assert re.search(r"^\+    8 \|     ttl: 30$", output, re.MULTILINE)
    assert "cabecera" not in output and "cmd" not in output
    assert _sha(path) == before


def test_every_write_without_now_is_refused(tmp_path, capsys):
    """Corte de T11: la comprobación previa (T13) aún contesta «no se sabe»."""
    path = _copy(TODAY, tmp_path)
    before = _sha(path)
    for argv in (
        ["--ttl", "gemma4-12b=60"],
        ["--pin", "gemma3-4b", "--vram-gb", "16", *_vram_args()],
    ):
        assert _residency("--config", str(path), *argv) == 2
        assert "no se sabe si hay delegaciones en curso" in capsys.readouterr().err
    copy = _copy(PRE_NO_RESIDENT, tmp_path, "c.bak")
    assert _residency("--config", str(path), "--restore", str(copy)) == 2
    assert "no se sabe si hay delegaciones en curso" in capsys.readouterr().err
    assert _sha(path) == before
    assert not list(tmp_path.glob("config.yaml.*.bak"))


def test_init_llamaswap_help_presents_resident_as_opt_in(capsys):
    with pytest.raises(SystemExit):
        cli.run(["init-llamaswap", "--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert "residencia OPT-IN" in help_text
    assert "default 0" in help_text


def test_residency_help_explains_zero_effective_ttl(capsys):
    with pytest.raises(SystemExit):
        cli.run(["llamaswap", "residency", "--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert "SIN `globalTTL` NI `ttl` TODOS LOS MODELOS TIENEN TTL EFECTIVO 0" in help_text


# --- Corrección tras la revisión de la ola 5 ---------------------------------------------------

_LINE_ENDINGS = {
    "hoy.yaml": (0, 66),
    "pre-sin-residente-20261006.yaml": (0, 71),
    "pre-b10909-20260915.yaml": (47, 11),
}


def _line_endings(data: bytes) -> tuple[int, int]:
    """(CRLF, LF suelto)."""
    crlf = data.count(b"\r\n")
    return crlf, data.count(b"\n") - crlf


def test_fixtures_keep_their_line_ending():
    """`.gitattributes` los marca `-text`: un checkout de Windows con `autocrlf` no los convierte.
    Si los convirtiera, la tabla de edición probaría otra cosa (y el CI de Windows caería)."""
    assert sorted(_LINE_ENDINGS) == sorted(p.name for p in FIXTURES.glob("*.yaml"))
    for name, expected in _LINE_ENDINGS.items():
        assert _line_endings((FIXTURES / name).read_bytes()) == expected, name


def test_restore_dry_run_masks_key_lists_and_env_tokens(tmp_path, capsys):
    actual = _writes(
        tmp_path,
        b'apiKeys:\n  - "clave-falsa-actual-1"\n  - "clave-falsa-actual-2"\nmodels:\n  a:\n'
        b'    cmd: x --model a.gguf\n    env:\n      - "HF_TOKEN=clave-falsa-hf-actual"\n'
        b"    ttl: 60\n",
    )
    copy = _writes(
        tmp_path,
        b'apiKeys:\n  - "clave-falsa-copia-1"\nmodels:\n  a:\n    cmd: x --model a.gguf\n'
        b'    env:\n      - "HF_TOKEN=clave-falsa-hf-copia"\n    ttl: 90\n',
        "copia.bak",
    )
    rc = _residency("--config", str(actual), "--restore", str(copy), "--dry-run")
    output = capsys.readouterr().out
    assert "clave-falsa" not in output
    assert rc == 0
    # Guarda: el diff sí enseña lo que cambia, con los valores tapados.
    assert re.search(r"^-    2 \|   - \*\*\*$", output, re.MULTILINE)
    assert '- "HF_TOKEN=***"' in output
    assert re.search(r"^\+    8 \|     ttl: 90$", output, re.MULTILINE)


def test_pin_counts_existing_residents(tmp_path, capsys):
    """Sonda de la revisión: `r` (6 GiB) ya es residente; `--pin a` (6) con `big` (7) no cabe en
    14: 6 + 6 + 7 = 19. Con la fórmula vieja (`a` + el mayor de los demás) daba 13 y lo aceptaba."""
    path = _writes(
        tmp_path,
        b"models:\n  r:\n    cmd: x --model r.gguf\n    ttl: 0\n"
        b"  a:\n    cmd: x --model a.gguf\n    ttl: 60\n  big:\n    cmd: x --model big.gguf\n"
        b"    ttl: 60\ngroups:\n  fijo:\n    persistent: true\n    swap: false\n    exclusive: false\n"
        b"    members:\n    - r\n  swap:\n    swap: true\n    exclusive: false\n    members:\n"
        b"    - a\n    - big\n",
    )
    before = _sha(path)
    rc = _residency(
        "--config",
        str(path),
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
    assert _sha(path) == before


def test_pin_swap_false_group_counts_whole(tmp_path, capsys):
    """Un grupo `swap: false` carga a todos sus miembros a la vez: el peor caso es su suma."""
    path = _writes(
        tmp_path,
        b"models:\n  m:\n    cmd: x --model m.gguf\n    ttl: 60\n  p:\n    cmd: x --model p.gguf\n"
        b"    ttl: 60\n  q:\n    cmd: x --model q.gguf\n    ttl: 60\n"
        b"groups:\n  juntos:\n    swap: false\n    exclusive: false\n    members:\n    - p\n    - q\n",
    )
    rc = _residency(
        "--config",
        str(path),
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


def test_yaml_error_does_not_quote_fragment(tmp_path, capsys):
    content = b'apiKeys:\n  - "clave-secreta-sin-cerrar\nmodels:\n  a:\n    cmd: x\n'
    with pytest.raises(yaml.YAMLError) as raw:
        yaml.safe_load(content)
    assert "clave-secreta-sin-cerrar" in str(raw.value)  # guarda: PyYAML sí lo citaría
    with pytest.raises(ResidencyError) as e:
        residency.edit(content, [SetTTL("a", 30)])
    assert "clave-secreta-sin-cerrar" not in str(e.value)
    assert "línea" in str(e.value)
    with pytest.raises(ResidencyError) as e:
        residency.validate_copy(content)
    assert "clave-secreta-sin-cerrar" not in str(e.value)
    path = _writes(tmp_path, content)
    assert _residency("--config", str(path)) == 2
    err = capsys.readouterr().err
    assert "clave-secreta-sin-cerrar" not in err
    assert "no se puede leer" in err


def test_dry_run_numbers_lines_and_says_model_leaves_swap(tmp_path, capsys):
    path = _copy(TODAY, tmp_path)
    lines = TODAY.read_text(encoding="utf-8").splitlines()
    n_member = lines.index("    - gemma3-4b") + 1
    rc = _residency(
        "--config", str(path), "--pin", "gemma3-4b", "--vram-gb", "16", *_vram_args(), "--dry-run"
    )
    assert rc == 0
    output = capsys.readouterr().out
    assert "# gemma3-4b sale del grupo `swap`" in output
    assert re.search(r"^- +" + str(n_member) + r" \|     - gemma3-4b$", output, re.MULTILINE)
    assert re.search(r"^\+ +" + str(len(lines)) + r" \|   residente:$", output, re.MULTILINE)
    assert path.read_bytes() == TODAY.read_bytes()


def test_every_cli_query_to_daemon_goes_through_its_target():
    """Cada llamada a `httpx2` de `cli.py` construye su URL con `_daemon_url()` (que sale de
    `_daemon_target`, lo que corta la fixture autouse). Guarda para T13."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(cli))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "httpx2"
        and node.func.attr in {"get", "post", "put", "delete", "request", "stream"}
    ]
    assert calls, "no hay ninguna consulta: la guarda no comprobaría nada"
    for call in calls:
        url = call.args[0] if call.args else None
        uses_target = url is not None and any(
            isinstance(n, ast.Name) and n.id == "_daemon_url" for n in ast.walk(url)
        )
        assert uses_target, f"cli.py:{call.lineno} pregunta al daemon sin `_daemon_url()`"


def test_routing_not_a_map_is_refused(tmp_path, capsys):
    content = b"models:\n  a:\n    cmd: x --model a.gguf\n    ttl: 60\nrouting: 5\n"
    with pytest.raises(ResidencyError, match="`routing` no es un mapa"):
        residency.edit(content, [SetTTL("a", 30)])
    path = _writes(tmp_path, content)
    assert _residency("--config", str(path), "--ttl", "a=30", "--now") == 2
    assert "`routing` no es un mapa" in capsys.readouterr().err


def test_pin_model_already_in_resident_group_only_sets_ttl_0(tmp_path):
    path = _copy(PRE_NO_RESIDENT, tmp_path)
    original = path.read_bytes()
    rc = _residency(
        "--config", str(path), "--pin", "gemma3-4b", "--vram-gb", "16", *_vram_args(), "--now"
    )
    assert rc == 0
    assert _changed(original, path.read_bytes()) == [
        ("-", "    ttl: 600\n"),
        ("+", "    ttl: 0\n"),
    ]


def test_config_changed_during_edit_not_written(tmp_path, monkeypatch, capsys):
    path = _copy(TODAY, tmp_path)
    modified = TODAY.read_bytes().replace(b"    ttl: 30\n", b"    ttl: 45\n")
    assert modified != TODAY.read_bytes()
    real = residency.edit_with_diff

    def edit_while_another_touches(original, changes):
        result = real(original, changes)
        path.write_bytes(modified)  # otro editor guarda entre la carga y la escritura
        return result

    monkeypatch.setattr(residency, "edit_with_diff", edit_while_another_touches)
    rc = _residency("--config", str(path), "--ttl", "gemma4-26b-a4b=60", "--now")
    assert path.read_bytes() == modified
    assert rc == 2
    assert "cambió mientras se editaba" in capsys.readouterr().err
    assert not list(tmp_path.glob("config.yaml.*.bak"))


def test_residency_help_has_no_spanish_options(capsys):
    """Los nombres del CLI van en inglés, como el resto (decisión del usuario, 2026-10-07)."""
    with pytest.raises(SystemExit):
        cli.run(["llamaswap", "residency", "--help"])
    help_text = capsys.readouterr().out
    assert "--none" in help_text and "--pin" in help_text  # guarda: es la ayuda de verdad
    for spanish in (
        "--ninguno",
        "--fijar",
        "--restaurar",
        "--ahora",
        "--vram-modelo",
        "--grupo",
        "--reserva-gb",
    ):
        assert spanish not in help_text, spanish
    with pytest.raises(SystemExit):
        cli.run(["llamaswap", "residencia"])
