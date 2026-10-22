"""Por qué vías se leen los ficheros (REQ-018 de `claude-plugin-and-mods`, lote F4-measure-reads).

Recorre los transcripts de Claude Code (`~/.claude/projects/**/*.jsonl`, los de subagentes
incluidos) y cuenta cada lectura de fichero por vía:

- `Read` entero (`read_whole`), por franjas (`read_range`) y de imágenes (`read_image`);
- cada forma de shell (`Bash` y `PowerShell`), por familia de verbo: `cat`/`type`/`Get-Content`,
  `head`/`tail`, `sed -n`, `awk`, `grep` sobre ficheros, `python -c "open(…)"` (o con el código en
  un heredoc), `git show rev:ruta` y otros (`nl`, `jq`…). Una lectura que sigue en una tubería
  lleva `_pipe` (`shell_cat_pipe`), y un `Get-Content` con `-TotalCount`/`-Head`/`-Tail` lleva
  `_partial`. Lo que se redirige a un fichero (`cat a > b`) no entra al contexto: no es lectura;
- `Grep` (`grep_tool`), con el tamaño de su salida;
- las tools de lectura de otros MCP (`mcp_<servidor>`: `filesystem`, `obsidian`, `github`,
  `markitdown`…).

Para cada lectura anota el resultado (`done`, `blocked` por un hook, `denied` por permisos,
`error`, o `no_result` si la llamada no tiene resultado), el tamaño del fichero (de disco hoy; el
de un `Read` entero, de lo que devolvió) y los caracteres que entraron al contexto. Con eso saca:

- la tabla por vía y tramo de tamaño (`by_via`);
- las vías que, de mayor a menor, suman el `COVER_SHARE` de los caracteres que entraron al
  contexto desde ficheros grandes (`f4_candidates`): de ahí sale qué vías cubre F4;
- la cobertura de las franjas por fichero y transcript (`range_coverage`), de la que sale el umbral
  de REQ-020.

La vía, el alcance y la ruta de cada llamada los da el clasificador único de REQ-019
(`resources/hooks/read_classifier.py`): el script no lleva reglas de lectura propias, así que mide
lo mismo que deciden los hooks y el mod. Solo el resultado de un `Read` las afina (una imagen, o
una franja que en realidad cubrió el fichero entero).

No cuentan las llamadas dentro de una ventana de `local-delegate test-window` (`excluded`).

**Privacidad.** Ni el contenido de los ficheros ni la salida de las tools salen del proceso: solo
cifras. Con `--corpus RUTA` escribe además un corpus de comandos para los tests del clasificador de
REQ-019 en el que todo lo que no es un verbo conocido, una opción o un número va sustituido por un
hash con sal aleatoria de cada corrida (`<path:…>`, `<arg:…>`, `<code:…>`): ni las rutas, ni los
patrones, ni el código salen.

Uso:  uv run python scripts/measure_read_paths.py [--days 30] [--corpus RUTA]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import hmac
import json
import re
import secrets
import statistics
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_delegate import config, test_windows
from local_delegate.hook_entry import hooks_dir

# Las reglas de lectura viven en un solo sitio, el clasificador de REQ-019 (PR #416), que es un
# módulo suelto de `resources/hooks/`: se importa como lo importan los hooks entre sí.
if str(hooks_dir()) not in sys.path:
    sys.path.insert(0, str(hooks_dir()))
import read_classifier

#: Desde este tamaño un fichero es «grande» para decidir qué vías cubre F4 (el hook de lectura
#: actual bloquea la prosa desde 8 KB).
LARGE_FILE_BYTES = 8 * 1024
#: Las vías que, sumadas de mayor a menor, llegan a esta parte del volumen son candidatas de F4.
COVER_SHARE = 0.9
#: Tramos de tamaño de fichero, en bytes (el último no tiene techo).
SIZE_BUCKETS = (
    ("lt8k", 8 * 1024),
    ("8k_32k", 32 * 1024),
    ("32k_128k", 128 * 1024),
    ("ge128k", None),
)
#: Umbrales candidatos de REQ-020: el informe da qué parte de los ficheros llega a cada uno.
COVERAGE_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)
#: Cuántas filas del corpus por vía, como mucho (las que no son lecturas, `none`, igual).
CORPUS_PER_VIA = 40
#: Cuántos tokens de un comando van al corpus.
CORPUS_MAX_TOKENS = 40

SHELL_TOOLS = frozenset(read_classifier.SHELL_TOOLS)

#: Verbos que el corpus conserva tal cual (además de los que leen y los envoltorios).
_KEEP_WORDS_TEXT = """
        git show diff log status ls dir cd echo find wc sort uniq cut tr xargs select-object
        measure-object where-object foreach-object format-table out-string get-childitem test-path
        uv run pytest ruff node pnpm npm gh pr checks bash sh pwsh powershell set-location mkdir cp
        mv rm touch printf true false test if then else fi for do done while in
        """
_KEEP_WORDS = frozenset(
    set(read_classifier._FAMILY) | read_classifier._WRAPPERS | set(_KEEP_WORDS_TEXT.split())
)
_OPERATORS = frozenset({"|", "||", "&&", ";", ">", ">>", "<", "<<", "2>&1", "2>", "(", ")", "&"})

_FLAG = re.compile(r"^--?[A-Za-z][A-Za-z0-9-]{0,30}$")
_NUMERIC = re.compile(r"^[+-]?\d+(?:,\d+)?p?$|^\d+[a-z]?$")
_LINE_PREFIX = re.compile(r"^\s*(\d+)\t", re.MULTILINE)
_PY_READS = read_classifier._PY_READS
_unquote = read_classifier._unquote
strip_heredocs = read_classifier.strip_heredocs
tokenize = read_classifier.tokenize


# --- Clasificar ----------------------------------------------------------------------------------

#: Una lectura clasificada (`kind="read"`): vía, alcance y lo que se sabe del fichero.
ReadCall = read_classifier.Access


def classify_shell(command: str, tool: str = "Bash") -> list[ReadCall]:
    """Las lecturas de un comando de shell cuya salida entra al contexto (las del clasificador).

    Una ruta relativa se une al último `cd` del propio comando; la de la llamada (`cwd`) se pone
    después, en `resolve`.
    """
    return [a for a in read_classifier.classify_shell(command, tool) if a.kind == "read"]


def classify_tool(name: str, tool_input: dict) -> ReadCall | None:
    """La lectura de una tool que no es de shell, o `None` si no lee un fichero."""
    access = read_classifier.classify_tool(name, tool_input)
    return access if access is not None and access.kind == "read" else None


# --- Rutas y tamaños -----------------------------------------------------------------------------


def resolve(path: str | None, cwd: str | None) -> Path | None:
    """La ruta en disco de un operando (con `~`, `/d/…` de Git Bash y el `cwd` de la llamada)."""
    resolved = read_classifier.resolve(path, cwd)
    return Path(resolved) if resolved is not None else None


def _stat_size(path: Path) -> int | None:
    try:
        return path.stat().st_size if path.is_file() else None
    except (OSError, ValueError):
        return None


def _count_lines(path: Path) -> int | None:
    """Las líneas de un fichero hoy. Solo cuenta: el contenido no sale de aquí."""
    try:
        with path.open("rb") as fh:
            data = fh.read()
    except (OSError, ValueError):
        return None
    return data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)


def size_bucket(size: int | None) -> str:
    if size is None:
        return "unknown"
    for name, ceiling in SIZE_BUCKETS:
        if ceiling is None or size < ceiling:
            return name
    return SIZE_BUCKETS[-1][0]


def _text_len(content: object) -> int:
    """Los caracteres de texto de un `tool_result` (las imágenes no cuentan)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(
            len(b.get("text") or "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return 0


def _head_text(content: object, limit: int = 400) -> str:
    if isinstance(content, str):
        return content[:limit]
    if isinstance(content, list):
        return " ".join((b.get("text") or "")[:limit] for b in content if isinstance(b, dict))[
            :limit
        ]
    return ""


def outcome(is_error: bool, content: object, has_result: bool = True) -> str:
    """done | blocked (lo paró un hook) | denied (permiso) | error | no_result."""
    if not has_result:
        return "no_result"
    if not is_error:
        return "done"
    head = _head_text(content)
    if "hook error" in head or head.startswith("PreToolUse") or "tool local" in head:
        return "blocked"
    if "denied" in head.lower():
        return "denied"
    return "error"


# --- Recorrer los transcripts --------------------------------------------------------------------


@dataclass
class Event:
    transcript: Path
    subagent: bool
    ts: str
    cwd: str | None
    name: str
    tool_input: dict
    has_result: bool = False
    is_error: bool = False
    content: object = None
    result: object = None


def transcripts(projects: Path, since: datetime) -> list[Path]:
    found = []
    for path in sorted(Path(projects).glob("**/*.jsonl")):
        try:
            if path.stat().st_mtime >= since.timestamp():
                found.append(path)
        except OSError:
            continue
    return found


def events(path: Path) -> Iterator[Event]:
    """Cada llamada a una tool del transcript, con su resultado si lo tiene."""
    subagent = "subagents" in path.parts
    pending: dict[str, Event] = {}
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            message = data.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                    tool_input = block.get("input")
                    pending[block["id"]] = Event(
                        path,
                        subagent,
                        str(data.get("timestamp") or ""),
                        data.get("cwd") if isinstance(data.get("cwd"), str) else None,
                        str(block.get("name") or ""),
                        tool_input if isinstance(tool_input, dict) else {},
                    )
                elif block.get("type") == "tool_result":
                    event = pending.pop(str(block.get("tool_use_id")), None)
                    if event is None:
                        continue
                    event.has_result = True
                    event.is_error = bool(block.get("is_error"))
                    event.content = block.get("content")
                    event.result = data.get("toolUseResult")
                    yield event
    yield from pending.values()


# --- Medir ---------------------------------------------------------------------------------------


@dataclass
class ViaStats:
    count: int = 0
    outcomes: collections.Counter = field(default_factory=collections.Counter)
    by_tool: collections.Counter = field(default_factory=collections.Counter)
    by_size: collections.Counter = field(default_factory=collections.Counter)
    by_scope: collections.Counter = field(default_factory=collections.Counter)
    subagent: int = 0
    output_chars: int = 0
    large_output_chars: int = 0
    files: set = field(default_factory=set)

    def row(self, via: str) -> dict:
        return {
            "via": via,
            "count": self.count,
            **{k: self.outcomes[k] for k in ("done", "blocked", "denied", "error", "no_result")},
            "subagent": self.subagent,
            "by_tool": dict(sorted(self.by_tool.items())),
            "by_scope": dict(sorted(self.by_scope.items())),
            "by_size": dict(sorted(self.by_size.items())),
            "output_chars": self.output_chars,
            "large_file_output_chars": self.large_output_chars,
            "distinct_files": len(self.files),
        }


def _refine_read(call: ReadCall, event: Event) -> tuple[ReadCall, int | None, int | None]:
    """Ajusta un `Read` con su resultado: (llamada, tamaño visto, líneas totales)."""
    result = event.result
    if (isinstance(result, dict) and result.get("type") == "image") or (
        isinstance(event.content, list)
        and any(isinstance(b, dict) and b.get("type") == "image" for b in event.content)
    ):
        return ReadCall("read", "read_image", "unclassifiable", call.path), None, None
    file = result.get("file") if isinstance(result, dict) else None
    if not isinstance(file, dict):
        if not event.is_error and isinstance(event.content, str) and call.scope == "range":
            numbers = [int(n) for n in _LINE_PREFIX.findall(event.content)]
            if numbers:
                call.lines = (numbers[0], numbers[-1])
        return call, None, None
    start, num, total = file.get("startLine"), file.get("numLines"), file.get("totalLines")
    seen = len(str(file.get("content") or "").encode("utf-8"))
    if isinstance(start, int) and isinstance(num, int) and isinstance(total, int):
        if start <= 1 and num >= total:
            return ReadCall("read", "read_whole", "whole", call.path), seen, total
        return (
            ReadCall("read", "read_range", "range", call.path, (start, start + num - 1)),
            None,
            total,
        )
    return call, (seen if call.scope == "whole" else None), None


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p25": None, "p50": None, "p75": None, "p90": None}
    values = sorted(values)

    def q(p: float) -> float:
        return round(values[min(len(values) - 1, int(p * (len(values) - 1) + 0.5))], 4)

    return {
        "n": len(values),
        "p25": q(0.25),
        "p50": round(statistics.median(values), 4),
        "p75": q(0.75),
        "p90": q(0.9),
    }


def _union(intervals: list[tuple[int, int]]) -> int:
    total = 0
    last_end = 0
    for start, end in sorted(intervals):
        start = max(start, last_end + 1)
        if end >= start:
            total += end - start + 1
            last_end = end
    return total


class Anonymiser:
    """Sustituye lo que no es un verbo, una opción o un número por un hash con sal de la corrida."""

    def __init__(self) -> None:
        self._salt = secrets.token_bytes(16)

    def _h(self, text: str) -> str:
        return hmac.new(self._salt, text.encode("utf-8"), hashlib.sha256).hexdigest()[:8]

    def path(self, text: str) -> str:
        return f"<path:{self._h(text)}>"

    def token(self, tok: str) -> str:
        if tok == "\n":
            return ";"
        if tok in _OPERATORS or tok.startswith("<<"):
            return tok
        bare = _unquote(tok)
        if bare.lower() in _KEEP_WORDS or bare == "-" or _FLAG.match(bare) or _NUMERIC.match(bare):
            return bare
        if bare.startswith("-") and "=" in bare and _FLAG.match(bare.split("=", 1)[0]):
            return bare.split("=", 1)[0] + f"=<arg:{self._h(bare)}>"
        if any(k in bare for k in _PY_READS):
            return "<code:reads-file>"
        if re.search(r"[\s()]", bare):
            return f"<code:{self._h(bare)}>"
        if "/" in bare or "\\" in bare or re.search(r"\.[A-Za-z0-9]{1,6}$", bare):
            return f"<path:{self._h(bare)}>"
        return f"<arg:{self._h(bare)}>"

    def command(self, command: str) -> str:
        stripped, bodies = strip_heredocs(command)
        tokens = tokenize(stripped)[:CORPUS_MAX_TOKENS]
        text = " ".join(self.token(t) for t in tokens).strip(" ;")
        if any(any(k in b for k in _PY_READS) for b in bodies):
            text += " <heredoc:reads-file>"
        elif bodies:
            text += " <heredoc>"
        return text


@dataclass
class _Coverage:
    """Franjas leídas por (transcript, fichero), para el umbral de REQ-020."""

    ranges: dict = field(default_factory=lambda: collections.defaultdict(list))
    totals: dict = field(default_factory=dict)
    blocked_first: set = field(default_factory=set)
    lines_cache: dict = field(default_factory=dict)

    def note(
        self,
        key: tuple[Path, str],
        resolved: Path,
        result: str,
        call: ReadCall,
        total_lines: int | None,
    ) -> None:
        if result == "blocked" and key not in self.ranges:
            self.blocked_first.add(key)
        if total_lines is not None:
            self.totals[key] = total_lines
        if result != "done" or call.scope != "range" or not call.lines:
            return
        if key not in self.totals:
            if resolved not in self.lines_cache:
                self.lines_cache[resolved] = _count_lines(resolved)
            if self.lines_cache[resolved] is not None:
                self.totals[key] = self.lines_cache[resolved]
        first, last = call.lines
        self.ranges[key].append((first, last if last is not None else sys.maxsize))

    def report(self) -> dict:
        single: list[float] = []
        multi: list[float] = []
        after_block: list[float] = []
        histogram: collections.Counter = collections.Counter()
        for key, intervals in self.ranges.items():
            total = self.totals.get(key)
            if not total:
                continue
            clipped = [(max(1, a), min(b, total)) for a, b in intervals if a <= total]
            frac = min(1.0, _union(clipped) / total)
            (multi if len(intervals) >= 2 else single).append(frac)
            if key in self.blocked_first:
                after_block.append(frac)
            if len(intervals) >= 2:
                histogram[f"{min(int(frac * 10), 9) * 10:02d}"] += 1

        def at_least(values: list[float]) -> dict:
            return {
                f"{t:.1f}": (
                    round(sum(v >= t for v in values) / len(values), 4) if values else None
                )
                for t in COVERAGE_THRESHOLDS
            }

        return {
            "files_with_ranges": len(single) + len(multi),
            "at_least": {
                "single_range": at_least(single),
                "multi_range": at_least(multi),
                "after_block": at_least(after_block),
            },
            "single_range": _percentiles(single),
            "multi_range": _percentiles(multi),
            "after_block": _percentiles(after_block),
            "multi_range_histogram": dict(sorted(histogram.items())),
        }


def _candidates(rows: list[dict]) -> list[dict]:
    """Las vías que, de mayor a menor, suman `COVER_SHARE` de lo leído de ficheros grandes."""
    total = sum(r["large_file_output_chars"] for r in rows)
    out: list[dict] = []
    acc = 0
    for r in sorted(rows, key=lambda r: -r["large_file_output_chars"]):
        if not total or not r["large_file_output_chars"] or acc / total >= COVER_SHARE:
            break
        acc += r["large_file_output_chars"]
        out.append({"via": r["via"], "cumulative_share": round(acc / total, 4)})
    return out


def measure(
    projects: Path,
    log_dir: Path,
    since: datetime,
    until: datetime,
    corpus: list[dict] | None = None,
) -> dict:
    windows = test_windows.load(Path(log_dir))
    stats: dict[str, ViaStats] = collections.defaultdict(ViaStats)
    excluded: collections.Counter = collections.Counter()
    not_reads: collections.Counter = collections.Counter()
    sizes: dict[Path, int | None] = {}
    coverage = _Coverage()
    anonymiser = Anonymiser()
    corpus_counts: collections.Counter = collections.Counter()
    corpus_seen: set[str] = set()
    n_transcripts = 0

    def add_corpus(row: dict) -> None:
        if corpus is None:
            return
        key = json.dumps(row, sort_keys=True)
        if key in corpus_seen or corpus_counts[row["via"]] >= CORPUS_PER_VIA:
            return
        corpus_seen.add(key)
        corpus_counts[row["via"]] += 1
        corpus.append(row)

    for path in transcripts(projects, since):
        n_transcripts += 1
        for event in events(path):
            try:
                ts = test_windows.parse_instant(event.ts)
            except (ValueError, TypeError):
                continue
            if not since <= ts < until:
                continue
            if windows.find(event.ts):
                excluded["test_window"] += 1
                continue
            if event.name in SHELL_TOOLS:
                command = str(event.tool_input.get("command") or "")
                calls = classify_shell(command, event.name)
                masked = anonymiser.command(command) if corpus is not None else ""
                if not calls:
                    not_reads["shell"] += 1
                    if masked:
                        add_corpus(
                            {"tool": event.name, "via": "none", "scope": "none", "command": masked}
                        )
                for call in calls:
                    add_corpus(
                        {
                            "tool": event.name,
                            "via": call.via,
                            "scope": call.scope,
                            "command": masked,
                        }
                    )
            else:
                single = classify_tool(event.name, event.tool_input)
                calls = [single] if single else []
            for call in calls:
                seen_size: int | None = None
                total_lines: int | None = None
                if event.name == "Read":
                    call, seen_size, total_lines = _refine_read(call, event)
                    limits = {
                        k: event.tool_input[k]
                        for k in ("offset", "limit")
                        if isinstance(event.tool_input.get(k), int)
                    }
                    add_corpus(
                        {
                            "tool": "Read",
                            "via": call.via,
                            "scope": call.scope,
                            "input": {
                                "file_path": anonymiser.path(str(call.path)),
                                **limits,
                            },
                        }
                    )
                elif event.name not in SHELL_TOOLS:
                    add_corpus(
                        {
                            "tool": "Grep" if event.name == "Grep" else "mcp",
                            "via": call.via,
                            "scope": call.scope,
                            "input_keys": sorted(event.tool_input),
                        }
                    )
                resolved = None if call.via.startswith("mcp_") else resolve(call.path, event.cwd)
                if resolved is not None and resolved not in sizes:
                    sizes[resolved] = _stat_size(resolved)
                size = seen_size if seen_size is not None else sizes.get(resolved)
                result = outcome(event.is_error, event.content, event.has_result)
                out_chars = _text_len(event.content) if result == "done" else 0
                s = stats[call.via]
                s.count += 1
                s.outcomes[result] += 1
                s.by_tool["mcp" if event.name.startswith("mcp__") else event.name] += 1
                s.by_scope[call.scope] += 1
                s.by_size[size_bucket(size)] += 1
                s.subagent += int(event.subagent)
                s.output_chars += out_chars
                if size is not None and size >= LARGE_FILE_BYTES:
                    s.large_output_chars += out_chars
                if resolved is not None:
                    key = str(resolved).lower()
                    s.files.add(key)
                    coverage.note((path, key), resolved, result, call, total_lines)

    rows = sorted((s.row(via) for via, s in stats.items()), key=lambda r: (-r["count"], r["via"]))
    return {
        "since": since.isoformat(timespec="seconds"),
        "until": until.isoformat(timespec="seconds"),
        "transcripts": n_transcripts,
        "reads": sum(r["count"] for r in rows),
        "by_via": rows,
        "not_reads": dict(sorted(not_reads.items())),
        "excluded": dict(sorted(excluded.items())),
        "large_file_bytes": LARGE_FILE_BYTES,
        "cover_share": COVER_SHARE,
        "f4_candidates": _candidates(rows),
        "range_coverage": coverage.report(),
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--projects", type=Path, default=Path.home() / ".claude" / "projects")
    ap.add_argument("--log-dir", type=Path, default=Path(config.LOG_DIR))
    ap.add_argument("--days", type=int, default=30, help="how many days back (default 30)")
    ap.add_argument("--since", help="start instant (ISO 8601); overrides --days")
    ap.add_argument("--until", help="end instant (ISO 8601); now by default")
    ap.add_argument("--corpus", type=Path, help="write the anonymised corpus (JSONL) here")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    until = test_windows.parse_instant(args.until) if args.until else datetime.now(UTC)
    since = (
        test_windows.parse_instant(args.since) if args.since else until - timedelta(days=args.days)
    )
    corpus: list[dict] | None = [] if args.corpus else None
    report = measure(args.projects, args.log_dir, since, until, corpus)
    if args.corpus and corpus is not None:
        corpus.sort(key=lambda r: (r["via"], json.dumps(r, sort_keys=True)))
        args.corpus.parent.mkdir(parents=True, exist_ok=True)
        with args.corpus.open("w", encoding="utf-8", newline="\n") as fh:
            for row in corpus:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        report["corpus_rows"] = len(corpus)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
