"""`scripts/measure_read_paths.py`: por qué vías se leen los ficheros (REQ-018 de
`claude-plugin-and-mods`, lote F4-measure-reads).

El script recorre los transcripts de Claude Code y cuenta las lecturas de ficheros por vía: `Read`
entero y por franjas, cada forma de shell (con tuberías), `Grep` y las tools de lectura de otros MCP.
Solo cuenta: ni el contenido de los ficheros ni la salida de las tools salen del proceso, y el
corpus para el clasificador de REQ-019 va anonimizado.

Cada escenario arma un `LOG_DIR` y un `~/.claude/projects` de mentira en `tmp_path`: la suite nunca
lee los reales.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from local_delegate import test_windows

ROOT = Path(__file__).parents[1]
CORPUS_FIXTURE = ROOT / "tests" / "fixtures" / "read_corpus.jsonl"


def _load():
    spec = importlib.util.spec_from_file_location(
        "measure_read_paths", ROOT / "scripts" / "measure_read_paths.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_read_paths"] = module
    spec.loader.exec_module(module)
    return module


measure_read_paths = _load()

SINCE = "2026-10-10T00:00:00Z"
UNTIL = "2026-10-20T00:00:00Z"
TS = "2026-10-12T10:00:00Z"
#: Va en el contenido de los ficheros y en la salida de las tools: nunca debe salir del proceso.
SECRET = "SENTINEL-CONTENT-7f3a91"
#: Va en las rutas: nunca debe salir sin anonimizar.
PRIVATE_DIR = "secret-private-dir"


class World:
    """Un `LOG_DIR`, un `projects/` y unos ficheros reales en `tmp_path`, con un transcript."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.log_dir = root / "logs"
        self.projects = root / "projects"
        self.files = root / PRIVATE_DIR
        for d in (self.log_dir, self.projects, self.files):
            d.mkdir()
        self._lines: list[dict] = []
        self._n = 0

    def file(self, name: str, lines: int) -> Path:
        path = self.files / name
        path.write_text("".join(f"{SECRET} line {i}\n" for i in range(lines)), encoding="utf-8")
        return path

    def call(
        self,
        name: str,
        tool_input: dict,
        *,
        result: dict | str | None = None,
        output: str = SECRET,
        is_error: bool = False,
        ts: str = TS,
    ) -> str:
        self._n += 1
        tid = f"toolu_{self._n:04d}"
        self._lines.append(
            {
                "type": "assistant",
                "timestamp": ts,
                "cwd": str(self.files),
                "message": {
                    "content": [{"type": "tool_use", "id": tid, "name": name, "input": tool_input}]
                },
            }
        )
        line = {
            "type": "user",
            "timestamp": ts,
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": output,
                        "is_error": is_error,
                    }
                ]
            },
        }
        if result is not None:
            line["toolUseResult"] = result
        self._lines.append(line)
        return tid

    def read(self, path: Path, total: int, start: int = 1, num: int | None = None, **extra) -> None:
        num = total if num is None else num
        content = "".join(f"{SECRET} line {i}\n" for i in range(start - 1, start - 1 + num))
        self.call(
            "Read",
            {"file_path": str(path), **extra},
            result={
                "type": "text",
                "file": {
                    "filePath": str(path),
                    "content": content,
                    "numLines": num,
                    "startLine": start,
                    "totalLines": total,
                },
            },
            output=content,
        )

    def shell(self, command: str, tool: str = "Bash") -> None:
        self.call(tool, {"command": command}, result={"stdout": SECRET, "stderr": ""})

    def write(self) -> Path:
        project = self.projects / "D--proj"
        project.mkdir(exist_ok=True)
        path = project / "session-1.jsonl"
        head = {"type": "user", "entrypoint": "cli", "timestamp": TS, "sessionId": "s1"}
        path.write_text(
            "".join(json.dumps(x) + "\n" for x in [head, *self._lines]), encoding="utf-8"
        )
        return path

    def run(self, capsys, *extra: str) -> tuple[dict, str]:
        self.write()
        code = measure_read_paths.main(
            [
                "--projects",
                str(self.projects),
                "--log-dir",
                str(self.log_dir),
                "--since",
                SINCE,
                "--until",
                UNTIL,
                *extra,
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        return json.loads(out), out


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _seed_every_kind(world: World) -> None:
    big = world.file("big.md", 400)
    small = world.file("small.py", 10)
    world.read(big, 400)  # entero
    world.read(big, 400, start=100, num=50, offset=100, limit=50)  # franja
    world.read(big, 400, start=150, num=50, offset=150, limit=50)  # otra franja
    world.shell(f"cat {big}")
    world.shell(f"cd {world.files} && cat big.md | head -n 20")
    world.shell(f"sed -n 10,40p {big}")
    world.shell(f"head -n 30 {small}")
    world.shell(f"awk 'NR<5' {small}")
    world.shell(f"grep -n foo {big}")
    world.shell(f"python -c \"print(open(r'{small}').read())\"")
    world.shell(f"Get-Content {big} -TotalCount 20", tool="PowerShell")
    world.shell("git status")  # no es una lectura
    world.shell("ls -la | grep foo")  # tampoco: el grep filtra la tubería
    world.call(
        "Grep",
        {"pattern": "foo", "path": str(big), "output_mode": "content"},
        result={"mode": "content", "content": SECRET * 500, "numLines": 400},
        output=SECRET * 500,
    )
    world.call("mcp__filesystem__read_text_file", {"path": str(big)}, output=SECRET)
    world.call("mcp__obsidian__read_note", {"path": "notes/x.md"}, output=SECRET)
    world.call("mcp__obsidian__patch_note", {"path": "notes/x.md"}, output="ok")  # escribe
    world.call(
        "Read",
        {"file_path": str(big)},
        output="PreToolUse:Read hook error: Este archivo pesa 9 KB y es prosa.",
        is_error=True,
    )
    # El patrón que motiva REQ-020: el hook bloquea el `Read` entero y se rehace por franjas.
    mid = world.file("mid.md", 100)
    world.call(
        "Read",
        {"file_path": str(mid)},
        output="PreToolUse:Read hook error: Este archivo pesa 9 KB y es prosa.",
        is_error=True,
    )
    world.read(mid, 100, start=1, num=50, offset=1, limit=50)
    world.read(mid, 100, start=51, num=40, offset=51, limit=40)


def test_counts_each_path_kind(world, capsys):
    _seed_every_kind(world)
    report, _ = world.run(capsys)
    by_via = {row["via"]: row for row in report["by_via"]}

    assert by_via["read_whole"]["done"] == 1
    assert by_via["read_whole"]["blocked"] == 2  # los `Read` que paró el hook
    assert by_via["read_range"]["done"] == 4
    assert by_via["shell_cat"]["count"] == 1
    assert by_via["shell_cat_pipe"]["count"] == 1  # `cd … && cat … | head`
    assert by_via["shell_sed"]["count"] == 1
    assert by_via["shell_head_tail"]["count"] == 1
    assert by_via["shell_awk"]["count"] == 1
    assert by_via["shell_grep"]["count"] == 1
    assert by_via["shell_python"]["count"] == 1
    assert by_via["shell_cat"]["by_tool"] == {"Bash": 1}
    assert by_via["shell_head_tail"]["by_tool"] == {"Bash": 1}
    assert by_via["grep_tool"]["count"] == 1
    assert by_via["mcp_filesystem"]["count"] == 1
    assert by_via["mcp_obsidian"]["count"] == 1  # `patch_note` escribe: no cuenta
    # El `Get-Content -TotalCount` de PowerShell es una lectura parcial de la familia `cat`.
    assert by_via["shell_cat_partial"]["by_tool"] == {"PowerShell": 1}
    # `git status` y el `grep` que filtra una tubería no son lecturas de ficheros.
    assert report["not_reads"]["shell"] == 2
    # El tamaño del fichero sale de disco: `big.md` (400 líneas) cae en su tramo.
    assert by_via["shell_sed"]["by_size"] == {"8k_32k": 1}
    assert by_via["shell_head_tail"]["by_size"] == {"lt8k": 1}
    # Franjas de `big.md` por todas las vías: `Read` 100-149 y 150-199, `sed` 10-40, `head` 1-20
    # (dos veces). Su unión son 140 de 400 líneas: el 35 %. `small.py` (10 líneas) tiene una sola
    # franja, `head -n 30`, que lo cubre entero.
    # `mid.md` (100 líneas): bloqueado y rehecho con dos franjas, 90 de 100 líneas.
    coverage = report["range_coverage"]
    assert coverage["files_with_ranges"] == 3
    assert coverage["multi_range"]["n"] == 2
    assert coverage["multi_range"]["p25"] == pytest.approx(0.35)
    assert coverage["multi_range"]["p75"] == pytest.approx(0.9)
    assert coverage["single_range"]["n"] == 1
    assert coverage["single_range"]["p50"] == pytest.approx(1.0)
    assert coverage["after_block"]["n"] == 1
    assert coverage["after_block"]["p50"] == pytest.approx(0.9)
    # Qué parte de los ficheros llega a cada umbral candidato de REQ-020.
    assert coverage["at_least"]["multi_range"]["0.8"] == pytest.approx(0.5)
    assert coverage["at_least"]["multi_range"]["0.9"] == pytest.approx(0.5)
    assert coverage["at_least"]["after_block"]["0.8"] == pytest.approx(1.0)
    assert coverage["at_least"]["single_range"]["0.5"] == pytest.approx(1.0)


def test_never_emits_file_contents(world, capsys, tmp_path):
    _seed_every_kind(world)
    corpus = tmp_path / "corpus.jsonl"
    report, out = world.run(capsys, "--corpus", str(corpus))

    assert report["by_via"], "el escenario debe medir algo para que la guarda signifique algo"
    text = corpus.read_text(encoding="utf-8")
    assert text.strip(), "el corpus debe tener filas para que la guarda signifique algo"
    for emitted in (out, text):
        assert SECRET not in emitted
        assert PRIVATE_DIR not in emitted
        assert str(world.root) not in emitted


#: Lo que nunca puede aparecer en el corpus: rutas de Windows o POSIX con usuario, unidades,
#: correos, y los tokens que el anonimizador no reconoce y deja tal cual.
_LEAKS = [
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(?i)[\\/](users|home)[\\/]"),
    re.compile(r"[\w.-]+@[\w-]+\.\w+"),
    re.compile(r"(?i)yohan|gonz[aá]lez|almaguer"),
]
_PLACEHOLDER = re.compile(r"<(?:(?:path|arg|code):[0-9a-f]{8}|code:reads-file)>")


def _assert_anonymised(rows: list[dict]) -> None:
    for row in rows:
        blob = json.dumps(row, ensure_ascii=False)
        for leak in _LEAKS:
            assert not leak.search(blob), (leak.pattern, blob)
        for token in row.get("command", "").split():
            if "/" in token or "\\" in token:
                assert _PLACEHOLDER.fullmatch(token), token
        path = (row.get("input") or {}).get("file_path")
        if path is not None:
            assert _PLACEHOLDER.fullmatch(path), path


def test_corpus_is_anonymised(world, capsys, tmp_path):
    _seed_every_kind(world)
    corpus = tmp_path / "corpus.jsonl"
    world.run(capsys, "--corpus", str(corpus))
    rows = [json.loads(x) for x in corpus.read_text(encoding="utf-8").splitlines()]

    assert {r["via"] for r in rows} >= {"read_whole", "read_range", "shell_sed", "shell_cat_pipe"}
    _assert_anonymised(rows)
    # La forma del comando se conserva: el verbo, las opciones y la franja de `sed`.
    sed = next(r for r in rows if r["via"] == "shell_sed")
    assert re.fullmatch(r"sed -n 10,40p <path:[0-9a-f]{8}>", sed["command"]), sed["command"]
    # Control positivo del validador: una ruta real sí la detecta.
    with pytest.raises(AssertionError):
        _assert_anonymised([{"via": "x", "command": f"cat {world.files / 'big.md'}"}])

    # El corpus versionado para REQ-019 cumple lo mismo.
    fixture = [json.loads(x) for x in CORPUS_FIXTURE.read_text(encoding="utf-8").splitlines()]
    assert len(fixture) >= 20
    _assert_anonymised(fixture)


def test_test_windows_excluded(world, capsys):
    big = world.file("big.md", 400)
    world.shell(f"cat {big}", tool="Bash")
    world.call(
        "Bash",
        {"command": f"sed -n 1,5p {big}"},
        result={"stdout": SECRET},
        ts="2026-10-12T11:00:00Z",
    )
    test_windows.add(world.log_dir, "2026-10-12T10:59:00Z", "2026-10-12T11:01:00Z", "prueba")
    report, _ = world.run(capsys)
    by_via = {row["via"]: row for row in report["by_via"]}

    assert by_via["shell_cat"]["count"] == 1
    assert "shell_sed" not in by_via
    assert report["excluded"]["test_window"] == 1
