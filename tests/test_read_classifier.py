"""El clasificador único de lectura (REQ-019; plan, Ola 5, lote F4-classifier).

Un solo módulo, `resources/hooks/read_classifier.py`, decide si una llamada lee un fichero, cuál y
con qué alcance. Lo usan los hooks de la entrega por settings y el mod de lectura (por
`hook classify`). Aquí se prueba:

- contra el corpus de comandos reales de F4-measure-reads (`tests/fixtures/read_corpus.jsonl`);
- que detecta las escrituras de shell (la guarda de REQ-022 depende de eso);
- el contrato de `hook classify`, `hook classify --list-tools` y `hook record-read`, por el camino
  instalado (`python -I -m local_delegate.hook`), que es como lo llama el mod;
- que los hooks de settings no llevan reglas propias y que su huella incluye el clasificador.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from local_delegate import config

ROOT = Path(__file__).parents[1]
HOOKS = ROOT / "src" / "local_delegate" / "resources" / "hooks"
CORPUS = ROOT / "tests" / "fixtures" / "read_corpus.jsonl"
TIMEOUT_S = 60


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # `dataclass` busca su módulo ahí
    spec.loader.exec_module(module)
    return module


classifier = _load("_rc_read_classifier", HOOKS / "read_classifier.py")
common = _load("_rc_hook_common", HOOKS / "hook_common.py")
measure = _load("_rc_measure_read_paths", ROOT / "scripts" / "measure_read_paths.py")


# --- El corpus -------------------------------------------------------------------------------------
#
# El corpus guarda la vía y el alcance que midió `measure_read_paths.py` sobre el comando ORIGINAL,
# pero el comando va anonimizado: rutas y argumentos como `<path:hash>`/`<arg:hash>`, el código
# como `<code:hash>`, los cuerpos de heredoc como una marca al final y como mucho 40 tokens. Para
# clasificarlo se deshace lo que se puede (`_deanonymise`), y una fila entra en la prueba solo si
# el propio script de la medición (con las reglas que tenía antes de importar el clasificador; ver
# `LOST_ROWS`), sobre ese texto, reproduce su etiqueta: si no, la anonimización
# se llevó la información (un comando truncado, `git show rev:ruta`, un intérprete con ruta…) y la
# fila no puede discriminar nada. `test_corpus_keeps_most_rows` vigila que ese filtro no se coma
# el corpus.

#: Las vías que F4 cubre con seguridad (evidence/F4-read-paths.md, «Qué vías cubre F4»): fichero y
#: alcance conocidos. En el resto el contrato dice `unclassifiable` (solo aviso y registro).
COVERED_VIAS = frozenset(
    {
        "read_whole",
        "read_range",
        "shell_sed",
        "shell_sed_pipe",
        "shell_head_tail",
        "shell_head_tail_pipe",
        "shell_cat",
        "shell_cat_pipe",
        "shell_cat_partial",
    }
)

#: Nombre de tool de cada vía de otro MCP: el corpus solo guarda las claves de la entrada.
MCP_TOOL_NAMES = {
    "mcp_obsidian": "mcp__obsidian__read_note",
    "mcp_pycharm": "mcp__pycharm__get_file_text_by_path",
}

_HEREDOC_MARK = re.compile(r" <heredoc(:reads-file)?>$")
_LEADING_ARG = re.compile(
    r"(^|[;|&(] )<arg:([0-9a-f]+)> (?=(?:python3?|py|uv|cat|grep|sed|head|tail|awk|rg|jq|nl)\b)"
)


def _deanonymise(command: str) -> str:
    """El comando anonimizado como un comando que se puede trocear."""
    reads_file = command.endswith(" <heredoc:reads-file>")
    text = _HEREDOC_MARK.sub("", command)
    text = text.replace("<code:reads-file>", "'open(f)'")
    text = re.sub(r"<code:([0-9a-f]+)>", r"'c_\1'", text)
    text = re.sub(r"<path:([0-9a-f]+)>", r"p_\1", text)
    # `PYTHONUTF8=1 python …`: la asignación se anonimiza como argumento suelto.
    text = _LEADING_ARG.sub(r"\1V_\2=1 ", text)
    text = re.sub(r"<arg:([0-9a-f]+)>", r"a_\1", text)
    if reads_file:
        match = re.search(r"<<-? ?([A-Za-z_][A-Za-z0-9_]*)", text)
        if match:
            text += f"\nopen(f)\n{match.group(1)}"
    return text


def _tool_call(row: dict) -> tuple[str, dict]:
    """(tool_name, tool_input) de una fila del corpus."""
    tool = row["tool"]
    if tool in ("Bash", "PowerShell"):
        return tool, {"command": _deanonymise(row["command"])}
    if tool == "Read":
        tool_input = dict(row["input"])
        if row["via"] == "read_image":
            # La extensión que delató la imagen (el resultado) se fue con la ruta anonimizada.
            tool_input["file_path"] += ".png"
        return "Read", tool_input
    keys = {key: "x" for key in row["input_keys"]}
    if tool == "Grep":
        return "Grep", keys
    return MCP_TOOL_NAMES[row["via"]], keys


def _expected(row: dict, tool_input: dict) -> tuple[str, str]:
    """(vía, alcance) que debe dar el clasificador para la fila."""
    via = row["via"]
    if via == "read_whole" and ("offset" in tool_input or "limit" in tool_input):
        # La medición vio en el resultado que la franja cubría el fichero entero; el clasificador
        # solo ve la entrada, y una franja pedida es una franja (el lado que no bloquea).
        return "read_range", "range"
    scope = row["scope"] if via in COVERED_VIAS else "unclassifiable"
    return via, scope


#: Las filas que el script de la medición, con sus propias reglas de entonces, NO reproducía sobre
#: el texto anonimizado (índices en el corpus). Se congelaron en F4-leftovers, cuando el script pasó
#: a importar este clasificador: desde entonces «el script la reproduce» sería «el clasificador la
#: reproduce», y el filtro dejaría fuera justo las filas que `test_corpus` tiene que ver fallar.
#: Si el corpus cambia, `test_corpus_is_the_frozen_one` lo dice y hay que volver a sacar la lista.
LOST_ROWS = frozenset(
    [217, 236, 243, 260, 272, 273, 274, 281, 283, 284, 301, 302, 313, 315, 316, 317, 318, 319]
    + [321, 325, 326, 330, 331, 332, 339, 363, *range(370, 413), 417, 419, 424, 441, 454, 458]
    + [467, 471, 472, 482, 486, 511, 514, 522, 540, 565, 578, 579, 585, 586, 594, 634, 639, 642]
    + [652, 655, 656, 657]
)
#: sha256 de las filas del corpus (JSON con claves ordenadas) para el que vale esa lista.
CORPUS_DIGEST = "6aaa4cce01dd956dde5ce8b8a94c2a17dd4d46305474dfcc772747b98d815a42"


def _corpus_digest(rows: list[dict]) -> str:
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _rows() -> list[dict]:
    return [json.loads(line) for line in CORPUS.read_text("utf-8").splitlines() if line]


def _row_id(index: int, row: dict) -> str:
    text = row.get("command") or json.dumps(row.get("input") or row.get("input_keys"))
    text = re.sub(r"<(path|arg|code):[0-9a-f]+>", r"<\1>", text)
    return f"{index:03d} {row['via']} {text[:60]}"


ALL_ROWS = _rows()
CORPUS_ROWS = [
    pytest.param(row, id=_row_id(i, row)) for i, row in enumerate(ALL_ROWS) if i not in LOST_ROWS
]


def test_corpus_is_the_frozen_one():
    """La lista de filas fuera vale solo para este corpus: si cambia, hay que rehacerla."""
    assert len(ALL_ROWS) == 759
    assert len(LOST_ROWS) == 97
    assert _corpus_digest(ALL_ROWS) == CORPUS_DIGEST


def test_measure_script_uses_this_classifier():
    """El script de la medición no lleva reglas propias: sus lecturas son las del clasificador."""
    assert not hasattr(measure, "_shell_read")
    assert not hasattr(measure, "_FAMILY")
    command = "grep -n foo notes.md; Get-Content -TotalCount 20 notes.md; sed -n 3,9p notes.md"
    reads = [a for a in classifier.classify_shell(command, "PowerShell") if a.kind == "read"]
    got = measure.classify_shell(command, "PowerShell")
    assert [(a.via, a.scope, a.path, a.lines) for a in got] == [
        (a.via, a.scope, a.path, a.lines) for a in reads
    ]
    assert len(got) == 3


def test_corpus_keeps_most_rows():
    """Guarda del filtro: si dejara fuera media prueba, `test_corpus` no probaría casi nada."""
    kept = {p.values[0]["via"] for p in CORPUS_ROWS}
    assert len(CORPUS_ROWS) >= 550, len(CORPUS_ROWS)
    # Toda vía que F4 cubre y las búsquedas siguen representadas.
    assert COVERED_VIAS | {"shell_grep", "shell_grep_pipe", "grep_tool", "none"} <= kept


@pytest.mark.parametrize("row", CORPUS_ROWS)
def test_corpus(row):
    tool_name, tool_input = _tool_call(row)
    found = classifier.accesses(tool_name, tool_input)
    reads = [a for a in found if a.kind == "read"]
    if row["via"] == "none":
        assert reads == []
        assert classifier.classify({"tool_name": tool_name, "tool_input": tool_input})["kind"] in {
            "other",
            "write",
        }
        return
    via, scope = _expected(row, tool_input)
    scopes = [a.scope for a in reads if a.via == via]
    assert scope in scopes, [(a.via, a.scope) for a in found]


@pytest.mark.parametrize(
    ("tool", "command", "via", "scope"),
    [
        ("PowerShell", "Get-Content notes.md", "shell_cat", "whole"),
        ("PowerShell", "Get-Content -Tail 5 notes.md", "shell_cat_partial", "partial"),
        ("PowerShell", "Get-Content notes.md -TotalCount 30", "shell_cat_partial", "range"),
        ("Bash", "grep -c TODO notes.md", "shell_grep", "unclassifiable"),
        ("Bash", "git show HEAD:docs/notes.md", "shell_git_show", "unclassifiable"),
        ("Bash", "head notes.md", "shell_head_tail", "range"),
        ("Bash", "tail -n 20 notes.md", "shell_head_tail", "partial"),
        ("Bash", "cat notes.md | head -n 30", "shell_cat_pipe", "range"),
        ("Bash", "sed -n '10,80p' notes.md", "shell_sed", "range"),
    ],
)
def test_rules_the_anonymised_corpus_cannot_show(tool, command, via, scope):
    """Formas que el corpus no conserva con claridad (`git show rev:ruta`) o que conviene fijar."""
    found = classifier.classify_shell(command, tool)
    assert [(a.via, a.scope) for a in found if a.kind == "read"] == [(via, scope)]


# --- Escrituras de shell (REQ-022) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "command"),
    [
        ("Bash", "echo hola > {t}"),
        ("Bash", "echo hola >> {t}"),
        ("Bash", "cat > {t} << EOF\nhola\nEOF"),
        ("Bash", "sed -i 's/a/b/' {t}"),
        ("Bash", "echo hola | tee {t}"),
        ("Bash", "echo hola | tee -a {t}"),
        ("Bash", "cp otro.md {t}"),
        ("Bash", "mv otro.md {t}"),
        ("Bash", "cat {t}; echo hola > {t}"),
        ("PowerShell", "Set-Content -Path {t} -Value hola"),
        ("PowerShell", "'hola' | Out-File {t}"),
        ("PowerShell", "Add-Content {t} hola"),
        ("PowerShell", "Copy-Item otro.md -Destination {t}"),
    ],
)
def test_shell_writes_detected(tmp_path, tool, command):
    target = tmp_path / "notes.md"
    target.write_text("x", encoding="utf-8")
    payload = {
        "tool_name": tool,
        "tool_input": {"command": command.format(t="notes.md")},
        "cwd": str(tmp_path),
    }
    result = classifier.classify(payload)
    assert (result["kind"], result["path"]) == ("write", str(target)), result


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        ("Write", {"file_path": "{t}", "content": "x"}),
        ("Edit", {"file_path": "{t}", "old_string": "a", "new_string": "b"}),
        ("MultiEdit", {"file_path": "{t}", "edits": []}),
        ("NotebookEdit", {"notebook_path": "{t}", "new_source": "x"}),
    ],
)
def test_write_tools_are_writes(tmp_path, tool_name, tool_input):
    target = tmp_path / "notes.md"
    tool_input = {k: (v.format(t=target) if v == "{t}" else v) for k, v in tool_input.items()}
    result = classifier.classify({"tool_name": tool_name, "tool_input": tool_input})
    assert (result["kind"], result["path"], result["via"]) == ("write", str(target), "write_tool")


@pytest.mark.parametrize(
    "command",
    ["cat notes.md > /dev/null", "grep -c x notes.md 2> err.log", "echo hola", "ls > $null"],
)
def test_what_is_not_a_write(tmp_path, command):
    """Control negativo: ni el destino nulo ni la salida de errores son escribir el fichero."""
    found = classifier.classify_shell(command, "Bash")
    assert [a for a in found if a.kind == "write"] == []


# --- El contrato de `hook classify` por el camino instalado ------------------------------------------


def _sandbox(base: Path) -> dict[str, str]:
    tmp = base / "tmp"
    data = base / "data"
    tmp.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in config.ENVIRONMENT_VARIABLES
        and name not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH"}
    }
    env.update(
        {
            "TMP": str(tmp),
            "TEMP": str(tmp),
            "TMPDIR": str(tmp),
            "LOCAL_DELEGATE_LOG_DIR": str(data),
            "LOCAL_DELEGATE_LANG": "es",
            "LD_HOOK_TELEMETRY_LOG": str(base / "telemetry.jsonl"),
            "LD_HOOK_READ_SWITCH_FILE": str(base / "block-off"),
        }
    )
    return env


def _hook(args: list[str], stdin: bytes, env: dict[str, str]):
    """Como lo llama el mod (`runLd`): el intérprete del entorno, aislado, por módulo."""
    return subprocess.run(
        [sys.executable, "-I", "-m", "local_delegate.hook", *args],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
        cwd=env["TMP"],
    )


def _script(script: str, stdin: bytes, env: dict[str, str], *args: str):
    """Como lo lanza la entrega por settings: `python <script>`."""
    return subprocess.run(
        [sys.executable, str(HOOKS / script), *args],
        input=stdin,
        capture_output=True,
        env={**env, "PYTHONUTF8": "1"},
        timeout=TIMEOUT_S,
        cwd=env["TMP"],
    )


def _telemetry(base: Path) -> list[dict]:
    path = base / "telemetry.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _block_notes(base: Path) -> list[dict]:
    path = base / "tmp" / common.FILE_NAMES["block_notes"][1]
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _prose(directory: Path, name: str = "report.md", kb: int = 20) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text("Texto de prosa para resumir.\n" * (kb * 1024 // 29 + 1), encoding="utf-8")
    return target


def _seed_backend_alive(base: Path) -> None:
    marker = base / "tmp" / common._health_path().name
    marker.write_text(json.dumps({"ts": time.time(), "ok": True}), encoding="utf-8")


CONTRACT_KEYS = [
    "kind",
    "path",
    "scope",
    "bytes",
    "range",
    "via",
    "read_switch",
    "summarizable",
    "describable",
]


def test_list_tools_covers_corpus_tools(tmp_path):
    result = _hook(["classify", "--list-tools"], b"", _sandbox(tmp_path))
    assert result.returncode == 0
    tools = json.loads(result.stdout)
    assert isinstance(tools, list) and all(isinstance(t, str) for t in tools)
    names = {t for t in tools if not t.endswith("*")}
    prefixes = [t[:-1] for t in tools if t.endswith("*")]

    def covered(name: str) -> bool:
        return name in names or any(name.startswith(p) for p in prefixes)

    corpus_tools = {MCP_TOOL_NAMES[r["via"]] if r["tool"] == "mcp" else r["tool"] for r in ALL_ROWS}
    assert corpus_tools == {
        "Bash",
        "PowerShell",
        "Read",
        "Grep",
        *MCP_TOOL_NAMES.values(),
    }, "el corpus cambió: revisa esta lista"
    assert [t for t in sorted(corpus_tools) if not covered(t)] == []
    # Y las que escriben, que la guarda de REQ-022 necesita ver.
    assert {"Edit", "MultiEdit", "NotebookEdit", "Write"} <= names


@pytest.mark.parametrize(
    ("env_extra", "switch_file", "expected"),
    [
        ({}, False, "inactive"),
        ({"LD_HOOK_READ_ENABLED": "1"}, False, "off_variable"),
        ({"LD_HOOK_READ_ENABLED": "1", "LD_HOOK_READ_BLOCK": "1"}, False, "on"),
        ({"LD_HOOK_READ_ENABLED": "1", "LD_HOOK_READ_BLOCK": "1"}, True, "off_file"),
        ({"LD_HOOK_READ_BLOCK": "1"}, False, "inactive"),
    ],
    ids=["inactive", "off_variable", "on", "off_file", "block-without-active"],
)
def test_classify_reports_read_switch(tmp_path, env_extra, switch_file, expected):
    env = {**_sandbox(tmp_path), **env_extra}
    if switch_file:
        Path(env["LD_HOOK_READ_SWITCH_FILE"]).write_text("", encoding="utf-8")
    prose = _prose(tmp_path / "docs")
    stdin = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -n 5,40p docs/report.md"},
            "cwd": str(tmp_path),
            "session_id": "s-test",
        }
    ).encode("utf-8")
    result = _hook(["classify"], stdin, env)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert list(out) == CONTRACT_KEYS
    assert out["read_switch"] == expected
    assert out == {
        "kind": "read",
        "path": str(prose),
        "scope": "range",
        "bytes": prose.stat().st_size,
        "range": [5, 40],
        "via": "shell_sed",
        "read_switch": expected,
        "summarizable": True,
        "describable": False,
    }


def test_classify_contract_for_other_and_bad_input(tmp_path):
    env = _sandbox(tmp_path)
    for stdin in (b'{"tool_name": "Bash", "tool_input": {"command": "git status"}}', b"no json"):
        result = _hook(["classify"], stdin, env)
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert out == {
            "kind": "other",
            "path": None,
            "scope": "unclassifiable",
            "bytes": None,
            "range": None,
            "via": "none",
            "read_switch": "inactive",
            "summarizable": False,
            "describable": False,
        }


@pytest.mark.parametrize(
    ("name", "via", "describable"),
    [
        ("shot.png", "read_image", True),
        ("photo.JPEG", "read_image", True),
        ("anim.webp", "read_image", True),
        ("logo.svg", "read_image", False),
        ("icon.ico", "read_image", False),
        ("spec.pdf", "read_document", False),
        ("notes.md", "read_whole", False),
    ],
)
def test_classify_says_whether_local_describe_image_takes_the_file(
    tmp_path, name, via, describable
):
    """Issue #469: the mod steers a large image to `local_describe_image` only when it is one."""
    target = tmp_path / name
    target.write_bytes(bytes([0x89]) + b"PNG" + bytes(40_000))
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(target)}}
    out = classifier.classify(payload, "on", environ={})
    assert out["via"] == via
    assert out["describable"] is describable


def test_describable_images_are_the_ones_the_server_takes():
    """The hooks cannot import the package: their copy of the list is held to `server` here."""
    from local_delegate import server

    assert set(server._IMAGE_MIME) == classifier.DESCRIBABLE_IMAGE_EXTENSIONS
    assert classifier.DESCRIBABLE_IMAGE_EXTENSIONS <= classifier.IMAGE_EXTENSIONS


def _sized(directory: Path, name: str, kb: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text("x = 1  # relleno\n" * (kb * 1024 // 17 + 1), encoding="utf-8")
    return target


@pytest.mark.parametrize(
    ("name", "kb", "env_extra", "expected"),
    [
        ("big.md", 20, {}, True),
        ("big.txt", 20, {}, True),
        ("big.py", 20, {}, False),
        ("big.json", 20, {}, False),
        # Sin datos de logs en evidence/F4-read-paths.md: se quedan fuera, como en el hook.
        ("big.log", 20, {}, False),
        ("small.md", 4, {}, False),
        # El umbral es la variable del hook, no un número propio.
        ("big.md", 20, {"LD_HOOK_READ_SUGGEST_KB": "100"}, False),
    ],
    ids=["md", "txt", "py", "json", "log", "small-md", "md-under-threshold"],
)
def test_classify_says_whether_the_file_is_summarizable(tmp_path, name, kb, env_extra, expected):
    """El mod solo resume la banda que bloquea el hook: prosa grande. El código pasa literal."""
    env = {**_sandbox(tmp_path), **env_extra}
    target = _sized(tmp_path / "work", name, kb)
    stdin = json.dumps(
        {"tool_name": "Read", "tool_input": {"file_path": str(target)}, "cwd": str(tmp_path)}
    ).encode("utf-8")
    result = _hook(["classify"], stdin, env)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert (out["kind"], out["scope"], out["bytes"]) == ("read", "whole", target.stat().st_size)
    assert out["summarizable"] is expected


def test_summarizable_uses_the_read_hook_constants():
    """Una sola fuente: el hook toma la prosa del clasificador y el umbral es el de `config`."""
    source = (HOOKS / "suggest_delegate_read.py").read_text("utf-8")
    assert "PROSE_EXTENSIONS = read_classifier.PROSE_EXTENSIONS" in source
    assert '".rst"' not in source
    assert classifier.PROSE_EXTENSIONS == frozenset({".md", ".txt", ".markdown", ".rst"})
    assert classifier.SUGGEST_KB_DEFAULT == config.HOOK_READ_SUGGEST_KB
    assert f'"{classifier.SUGGEST_KB_VARIABLE}"' in source
    # Y el borde es el del hook: hasta el umbral es «small», por encima se bloquea.
    limit = int(config.HOOK_READ_SUGGEST_KB * 1024)
    assert classifier.summarizable("a.md", limit) is False
    assert classifier.summarizable("a.md", limit + 1) is True
    assert classifier.summarizable("a.MD", limit + 1) is True
    assert classifier.summarizable("a.md", None) is False
    assert classifier.summarizable(None, limit + 1) is False


def test_unresolvable_read_is_unclassifiable(tmp_path):
    """`cat $F` lee algo, pero sin saber qué fichero no hay nada que resumir ni que acumular."""
    out = classifier.classify(
        {"tool_name": "Bash", "tool_input": {"command": "cat $F"}, "cwd": str(tmp_path)}
    )
    assert (out["kind"], out["path"], out["scope"], out["via"]) == (
        "read",
        None,
        "unclassifiable",
        "shell_cat",
    )


# --- Los hooks de settings usan el clasificador ------------------------------------------------------


SETTINGS_READ_HOOKS = ("suggest_delegate_read.py", "suggest_delegate_shell.py")


def test_settings_hooks_use_the_classifier(monkeypatch, capsys, tmp_path):
    from local_delegate import install

    registered = {entry[0] for entry in (install._SHELL_HOOK,)} | {"suggest_delegate_read.py"}
    assert registered == set(SETTINGS_READ_HOOKS)
    for name in SETTINGS_READ_HOOKS:
        source = (HOOKS / name).read_text("utf-8")
        assert "import read_classifier" in source, name
        # Sin reglas de lectura propias: ni troceo de comandos ni listas de verbos.
        for forbidden in ("import shlex", "re.compile", "get-content", "VERBS", "BOUNDING_FLAGS"):
            assert forbidden not in source, (name, forbidden)

    # Y de verdad decide el clasificador: si dice «no es un volcado», el hook no bloquea.
    sys.path.insert(0, str(HOOKS))
    try:
        shell_hook = _load("_rc_shell_hook", HOOKS / "suggest_delegate_shell.py")
    finally:
        sys.path.remove(str(HOOKS))
    prose = _prose(tmp_path, kb=40)
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    monkeypatch.setenv("LD_HOOK_READ_SWITCH_FILE", str(tmp_path / "missing"))
    monkeypatch.setattr(shell_hook, "backend_available", lambda **k: True)
    monkeypatch.setattr(shell_hook, "cooled_model", lambda model: False)

    def run() -> str:
        import io

        stdin = json.dumps({"tool_input": {"command": f"cat {prose}"}, "session_id": "s"})
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        shell_hook.main()
        return capsys.readouterr().out

    assert json.loads(run())["hookSpecificOutput"]["permissionDecision"] == "deny"
    monkeypatch.setattr(shell_hook.read_classifier, "simple_whole_dump", lambda found: None)
    assert run() == ""


# --- La huella de telemetría ---------------------------------------------------------------------


def test_classifier_change_moves_fingerprint(tmp_path):
    hooks = tmp_path / "hooks"
    shutil.copytree(HOOKS, hooks, ignore=shutil.ignore_patterns("__pycache__"))
    names = (*SETTINGS_READ_HOOKS, "suggest_delegate_prompt.py", "record_call.py")
    before = {n: common.version_de(str(hooks / n)) for n in names}
    assert all(before.values())

    rules = hooks / "read_classifier.py"
    rules.write_bytes(rules.read_bytes() + b"# a new rule\n")
    after = {n: common.version_de(str(hooks / n)) for n in names}

    for name in SETTINGS_READ_HOOKS:
        assert after[name] != before[name], name
    # Los que no leen no cambian de tramo.
    assert after["suggest_delegate_prompt.py"] == before["suggest_delegate_prompt.py"]
    assert after["record_call.py"] == before["record_call.py"]


# --- `hook record-read` ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hook_name", "script", "tool_name", "tool_input"),
    [
        ("read", "suggest_delegate_read.py", "Read", {"file_path": "{p}"}),
        ("shell", "suggest_delegate_shell.py", "Bash", {"command": "cat {p}"}),
    ],
    ids=["read", "shell"],
)
def test_record_read_writes_same_line_as_hook(tmp_path, hook_name, script, tool_name, tool_input):
    """Cuando el mod resume en vez de leer, la línea es la del hook que bloquea: la serie de P-4
    no se corta."""
    lines = {}
    notes = {}
    for kind in ("hook", "mod"):
        base = tmp_path / kind
        env = {**_sandbox(base), "LD_HOOK_READ_ENABLED": "1", "LD_HOOK_READ_BLOCK": "1"}
        _seed_backend_alive(base)
        prose = _prose(tmp_path / "docs")
        tool_input_n = {k: v.format(p=prose) for k, v in tool_input.items()}
        stdin = json.dumps(
            {
                "tool_name": tool_name,
                "tool_input": tool_input_n,
                "cwd": str(tmp_path),
                "session_id": "s-test",
            }
        ).encode("utf-8")
        if kind == "hook":
            run = _script(script, stdin, env)
            assert json.loads(run.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
        else:
            classified = _hook(["classify"], stdin, env)
            entry = {
                **json.loads(classified.stdout),
                "decision": "auto_summarized",
                "session_id": "s-test",
            }
            assert entry["read_switch"] == "on"
            run = _hook(["record-read"], json.dumps(entry).encode("utf-8"), env)
            assert (run.returncode, run.stdout) == (0, b"")
        events = _telemetry(base)
        assert len(events) == 1, events
        lines[kind] = events[0]
        notes[kind] = _block_notes(base)

    hook_line, mod_line = lines["hook"], lines["mod"]
    assert {"decision": "auto_summarized", "source": "mod"}.items() <= mod_line.items()
    ignored = {"ts", "id", "decision", "source"}
    assert {k: v for k, v in mod_line.items() if k not in ignored} == {
        k: v for k, v in hook_line.items() if k not in ignored
    }
    assert hook_line["via"] == ("read_whole" if hook_name == "read" else "shell_cat")
    # La nota del bloqueo también, con el id de la línea: el daemon cruza así la delegación.
    assert [n["id"] for n in notes["mod"]] == [mod_line["id"]]
    assert [n["sha"] for n in notes["mod"]] == [n["sha"] for n in notes["hook"]]


def test_record_read_keeps_unknown_decisions(tmp_path):
    """Una decisión que no está en la tabla se registra igual: perderla cortaría la serie."""
    env = _sandbox(tmp_path)
    entry = {
        "kind": "read",
        "path": None,
        "scope": "unclassifiable",
        "bytes": None,
        "range": None,
        "via": "shell_awk",
        "read_switch": "on",
        "decision": "Something Else!",
        "session_id": "s-test",
    }
    run = _hook(["record-read"], json.dumps(entry).encode("utf-8"), env)
    assert run.returncode == 0
    [event] = _telemetry(tmp_path)
    assert (event["decision"], event["reason"], event["suggested"]) == (
        "other",
        "mod_decision",
        False,
    )
    assert "blocked" not in event


def test_record_read_knows_every_mod_decision():
    """Cada `decision` que manda `mod/read.js` tiene su fila: si no, la línea saldría como
    `mod_decision` y la serie de P-4 contaría mal los resúmenes."""
    read_js = (
        ROOT / "src" / "local_delegate" / "resources" / "claude-plugin" / "local-delegate" / "mod"
    ) / "read.js"
    source = read_js.read_text("utf-8")
    sent = set(re.findall(r"decision = '([a-z_]+)'", source))
    sent |= set(re.findall(r"readPass\([^)]*'([a-z_]+)'", source))
    sent |= set(re.findall(r"readRecord\([^)]*'([a-z_]+)'", source))
    sent |= {w for pair in re.findall(r"\? '([a-z_]+)' : '([a-z_]+)'", source) for w in pair}
    assert {"summarized", "auto_summarized", "warned"} <= sent, sent
    assert sorted(sent - set(common.MOD_DECISIONS)) == []


# --- La vía barata del mod (F4-read-mod-perf, `evidence/F4-live.md`) ----------------------------------

READ_JS = ROOT / "src" / "local_delegate" / "resources" / "claude-plugin" / "local-delegate" / "mod"
READ_JS = READ_JS / "read.js"
#: Lo que la vía del mod no puede cargar: el servidor y el SDK de MCP (654 ms de importación medidos
#: por la vía `-m local_delegate hook`), ni `urllib`, que `classify` no usa.
HEAVY_MODULES = {"local_delegate.entrypoint", "local_delegate.server", "local_delegate.config"}


def _mod_args(name: str) -> list[str]:
    """Los argumentos que `mod/read.js` pasa a `runLd` en la constante `name`."""
    found = re.search(rf"const {name} = \[([^\]]*)\]", READ_JS.read_text("utf-8"))
    assert found, name
    return re.findall(r"'([^']*)'", found.group(1))


def _imported(stderr: bytes) -> set[str]:
    names = set()
    for line in stderr.decode("utf-8", "replace").splitlines():
        if line.startswith("import time:") and "|" in line:
            names.add(line.rsplit("|", 1)[1].strip())
    return names


def _as_the_mod(name: str, extra: list[str], stdin: bytes, env: dict[str, str]):
    """Como lo lanza el mod, con `-X importtime` delante para ver qué carga."""
    args = _mod_args(name)
    return subprocess.run(
        [sys.executable, "-X", "importtime", *args, *extra],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
        cwd=env["TMP"],
    )


def _heavy(modules: set[str]) -> set[str]:
    heavy = {m for m in modules if m in HEAVY_MODULES or m == "mcp" or m.startswith("mcp.")}
    return heavy | {m for m in modules if m == "urllib.request"}


def test_mod_classify_path_does_not_import_server(tmp_path):
    env = {**_sandbox(tmp_path), "LD_HOOK_READ_ENABLED": "1"}
    prose = _prose(tmp_path / "docs")
    stdin = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": f"cat {prose}"}, "cwd": str(tmp_path)}
    ).encode("utf-8")
    for extra, feed in (([], stdin), (["--config"], b"")):
        run = _as_the_mod("READ_CLASSIFY", extra, feed, env)
        assert run.returncode == 0
        modules = _imported(run.stderr)
        # Guarda: el clasificador contestó de verdad y `-X importtime` informa.
        assert "local_delegate.hook_entry" in modules, sorted(modules)[:20]
        answer = json.loads(run.stdout)
        assert answer["tools"] if extra else answer["summarizable"] is True
        assert _heavy(modules) == set(), sorted(_heavy(modules))


def test_mod_record_read_path_does_not_import_server(tmp_path):
    env = _sandbox(tmp_path)
    entry = {
        "kind": "read",
        "path": None,
        "scope": "unclassifiable",
        "bytes": None,
        "range": None,
        "via": "shell_awk",
        "read_switch": "on",
        "decision": "warned",
        "session_id": "s-test",
    }
    run = _as_the_mod("READ_RECORD", [], json.dumps(entry).encode("utf-8"), env)
    assert run.returncode == 0
    modules = _imported(run.stderr)
    # Guarda: la línea se escribió, así que `record-read` corrió entero.
    assert len(_telemetry(tmp_path)) == 1
    assert "local_delegate.hook_entry" in modules
    loaded = {m for m in modules if m in HEAVY_MODULES or m == "mcp" or m.startswith("mcp.")}
    assert loaded == set(), sorted(loaded)


def test_classify_config_is_the_classifier_data(tmp_path):
    """`hook classify --config`: lo que el prefiltro del mod necesita, sacado del clasificador."""
    env = _sandbox(tmp_path)
    run = _hook(["classify", "--config"], b"", env)
    assert run.returncode == 0
    answer = json.loads(run.stdout)
    assert answer == {
        "tools": classifier.list_tools(),
        "prose_extensions": sorted(classifier.PROSE_EXTENSIONS),
        "min_bytes": 8192,
        "harmless_first": list(classifier.HARMLESS_FIRST),
    }
    assert answer == classifier.prefilter_config({})
    # El umbral sigue a la variable del hook de lectura, como `summarizable`.
    moved = _hook(["classify", "--config"], b"", {**env, classifier.SUGGEST_KB_VARIABLE: "16"})
    assert json.loads(moved.stdout)["min_bytes"] == 16 * 1024
    broken = _hook(["classify", "--config"], b"", {**env, classifier.SUGGEST_KB_VARIABLE: "x"})
    assert json.loads(broken.stdout)["min_bytes"] == 8192


@pytest.mark.parametrize("first", ["echo", "printf", "write-host", "write-output"])
def test_output_commands_are_harmless(first):
    """`echo` y compañía no leen ni escriben sin redirección: el mod los descarta sin proceso."""
    assert first in classifier.HARMLESS_FIRST
    assert classifier.classify_shell(f"{first} docs/notes.md") == []


def test_harmless_first_tokens_never_write():
    """Un primer token inofensivo, sin redirección, nunca es una escritura que la guarda deba ver."""
    for first in classifier.HARMLESS_FIRST:
        found = classifier.classify_shell(f"{first} docs/notes.md")
        assert all(a.kind != "write" for a in found), (first, found)
