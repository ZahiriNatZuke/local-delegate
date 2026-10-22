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
import os
import re
import secrets
import statistics
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_delegate import config, test_windows

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

SHELL_TOOLS = frozenset({"Bash", "PowerShell"})

#: Familia de cada verbo de shell que lee un fichero.
_FAMILY = {
    **dict.fromkeys(("cat", "type", "get-content", "gc", "more", "less", "bat", "tac"), "cat"),
    **dict.fromkeys(("head", "tail"), "head_tail"),
    "sed": "sed",
    **dict.fromkeys(("awk", "gawk"), "awk"),
    **dict.fromkeys(
        ("grep", "egrep", "fgrep", "rg", "ag", "findstr", "select-string", "sls"), "grep"
    ),
    **dict.fromkeys(("python", "python3", "py", "pythonw"), "python"),
    **dict.fromkeys(("nl", "xxd", "od", "strings", "jq", "yq", "hexdump"), "other"),
}
#: Verbos que solo leen en PowerShell (en Bash, `type` dice qué es un comando).
_POWERSHELL_ONLY = frozenset({"type", "gc"})
#: Opciones que llevan valor, por familia (para no tomar el valor por el fichero).
_VALUE_FLAGS = {
    "head_tail": {"-n", "-c"},
    "sed": {"-e", "-f"},
    "awk": {"-f", "-v", "-F"},
    "grep": {"-e", "-f", "-A", "-B", "-C", "-m", "--max-count", "-g", "-t", "--type"},
    "other": set(),
    "cat": set(),
}
#: Prefijos que no son el verbo: se saltan para llegar a él.
_WRAPPERS = frozenset({"sudo", "time", "command", "exec", "nohup", "env"})
#: Verbos que el corpus conserva tal cual (además de los de `_FAMILY`).
_KEEP_WORDS_TEXT = """
        git show diff log status ls dir cd echo find wc sort uniq cut tr xargs select-object
        measure-object where-object foreach-object format-table out-string get-childitem test-path
        uv run pytest ruff node pnpm npm gh pr checks bash sh pwsh powershell set-location mkdir cp
        mv rm touch printf true false test if then else fi for do done while in
        """
_KEEP_WORDS = frozenset(set(_FAMILY) | _WRAPPERS | set(_KEEP_WORDS_TEXT.split()))
_OPERATORS = frozenset({"|", "||", "&&", ";", ">", ">>", "<", "<<", "2>&1", "2>", "(", ")", "&"})

_TOKEN = re.compile(
    r"""'[^']*'|"(?:\\.|[^"\\])*"|\|\||&&|>>|<<-?|2>&1|2>|[|;<>()&]|\n|[^\s|;<>()&'"]+"""
)
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_HERESTRING = re.compile(r"@'.*?'@|@\".*?\"@", re.DOTALL)
_FLAG = re.compile(r"^--?[A-Za-z][A-Za-z0-9-]{0,30}$")
_NUMERIC = re.compile(r"^[+-]?\d+(?:,\d+)?p?$|^\d+[a-z]?$")
_SED_RANGE = re.compile(r"^(\d+)(?:,(\d+))?p$")
_GIT_BASH_DRIVE = re.compile(r"^/([a-zA-Z])/(.*)$")
_LINE_PREFIX = re.compile(r"^\s*(\d+)\t", re.MULTILINE)
#: Nombres de tools de otros MCP que leen (por la parte tras el servidor).
_MCP_READ = re.compile(
    r"(^|_)(read|get_file|file_contents|get_note|convert_to_markdown|get_page|fetch_file|cat)"
)
_PY_READS = ("open(", "read_text", "read_bytes", "readlines")


# --- Clasificar ----------------------------------------------------------------------------------


@dataclass
class ReadCall:
    """Una lectura clasificada: vía, alcance y lo que se sabe del fichero."""

    via: str
    scope: str  # whole | range | partial | unknown
    path: str | None = None
    lines: tuple[int, int | None] | None = None  # (primera, última) 1-based; última None = al final


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    return token


def strip_heredocs(command: str) -> tuple[str, list[str]]:
    """(comando sin los cuerpos de heredocs y here-strings, los cuerpos)."""
    bodies = [m.group(0) for m in _HERESTRING.finditer(command)]
    command = _HERESTRING.sub("@''@", command)
    out: list[str] = []
    lines = command.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        delimiters = [m.group(2) for m in _HEREDOC.finditer(line)]
        i += 1
        for delimiter in delimiters:
            body: list[str] = []
            while i < len(lines) and lines[i].strip() != delimiter:
                body.append(lines[i])
                i += 1
            i += 1  # el delimitador de cierre
            bodies.append("\n".join(body))
    return "\n".join(out), bodies


def tokenize(command: str) -> list[str]:
    return _TOKEN.findall(command)


@dataclass
class Segment:
    """Un comando de la línea: sus etapas de tubería y si su salida va a un fichero."""

    stages: list[list[str]]
    redirected: bool = False
    heredoc: bool = False


def _segments(tokens: list[str]) -> list[Segment]:
    segments: list[Segment] = []
    current = Segment([[]])
    skip_next = False

    def close() -> None:
        current.stages = [s for s in current.stages if s]
        if current.stages:
            segments.append(current)

    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok in {"&&", "||", ";", "\n", "&", "(", ")"}:
            close()
            current = Segment([[]])
        elif tok == "|":
            current.stages.append([])
        elif tok in {">", ">>"}:
            current.redirected = True
            skip_next = True
        elif tok in {"2>", "<"}:
            skip_next = True  # stderr a un fichero, o la entrada: no son operandos
        elif tok.startswith("<<"):
            current.heredoc = True
            skip_next = True  # el delimitador
        elif tok == "2>&1":
            continue
        else:
            current.stages[-1].append(tok)
    close()
    return segments


def _verb(stage: list[str]) -> tuple[str, list[str]]:
    """(verbo normalizado, argumentos) de una etapa, saltando asignaciones y envoltorios."""
    i = 0
    while i < len(stage):
        word = stage[i].lower()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", stage[i]) or word in _WRAPPERS:
            i += 1
        elif word == "uv" and i + 1 < len(stage) and stage[i + 1] == "run":
            i += 2
            while i < len(stage) and stage[i].startswith("-"):
                i += 1  # opciones de `uv run`
        else:
            break
    if i >= len(stage):
        return "", []
    word = _unquote(stage[i]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    word = word.removesuffix(".exe")
    return word, stage[i + 1 :]


def _operands(args: list[str], value_flags: set[str]) -> list[str]:
    """Los argumentos que no son opciones (ni el valor de las que lo llevan)."""
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("-") and len(a) > 1 and not re.fullmatch(r"-\d+", a):
            if a in value_flags:
                skip = True
            continue
        if re.fullmatch(r"-\d+", a):
            continue
        out.append(_unquote(a))
    return out


def _flag_value(args: list[str], *names: str) -> str | None:
    lowered = [a.lower() for a in args]
    for name in names:
        if name in lowered:
            index = lowered.index(name)
            if index + 1 < len(args):
                return _unquote(args[index + 1])
    return None


def _int(text: str | None) -> int | None:
    try:
        return int(str(text).lstrip("+-")) if text is not None else None
    except ValueError:
        return None


def _shell_read(
    verb: str, args: list[str], piped: bool, tool: str, bodies: Sequence[str]
) -> ReadCall | None:
    """La lectura de la primera etapa de una tubería, o `None` si no lee un fichero."""
    family = _FAMILY.get(verb)
    if verb in _POWERSHELL_ONLY and tool != "PowerShell":
        return None
    if verb == "git" and args[:1] == ["show"] and any(":" in a for a in args[1:]):
        family = "git_show"
    if family is None:
        return None
    positional = _operands(args, _VALUE_FLAGS.get(family, set()))
    path: str | None = None
    scope = "unknown"
    lines: tuple[int, int | None] | None = None
    lowered = [a.lower() for a in args]
    if family == "cat":
        path = _flag_value(args, "-path", "-literalpath") or (positional[0] if positional else None)
        head = _int(_flag_value(args, "-totalcount", "-head", "-first"))
        if path is None:
            return None
        if head is not None:
            scope, lines = "range", (1, head)
        elif "-tail" in lowered:
            scope = "partial"
        else:
            scope = "partial" if piped else "whole"
        if scope in {"range", "partial"} and not piped:
            family = "cat_partial"
    elif family == "head_tail":
        if not positional:
            return None
        path = positional[-1]
        n = _int(_flag_value(args, "-n")) or next(
            (_int(a[1:]) for a in args if re.fullmatch(r"-\d+", a)), None
        )
        if verb == "head" and "-c" not in args:
            scope, lines = "range", (1, n or 10)
        else:
            scope = "partial"
    elif family == "sed":
        if any(a.startswith("-i") for a in args) or not any(
            re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", a) for a in args
        ):
            return None
        if len(positional) < 2:
            return None
        path = positional[-1]
        m = _SED_RANGE.match(positional[0])
        if m:
            first = int(m.group(1))
            scope, lines = "range", (first, int(m.group(2) or first))
        else:
            scope = "partial"
    elif family == "awk":
        if len(positional) < 2:
            return None
        path, scope = positional[-1], "unknown"
    elif family == "grep":
        has_pattern_flag = "-e" in args or "-f" in args
        if len(positional) < (1 if has_pattern_flag else 2):
            return None
        path, scope = positional[-1], "partial"
    elif family == "python":
        code = _flag_value(args, "-c") or ("\n".join(bodies) if "-" in args or not args else "")
        if not code or not any(k in code for k in _PY_READS):
            return None
        scope = "unknown"
    elif family == "other":
        if not positional:
            return None
        path, scope = positional[-1], "whole"
    elif family == "git_show":
        scope = "whole"
    via = f"shell_{family}" + ("_pipe" if piped else "")
    return ReadCall(via, scope, path, lines)


def classify_shell(command: str, tool: str = "Bash") -> list[ReadCall]:
    """Las lecturas de un comando de shell cuya salida entra al contexto.

    Una ruta relativa se une al último `cd` del propio comando; la de la llamada (`cwd`) se pone
    después, en `resolve`.
    """
    stripped, bodies = strip_heredocs(command)
    found: list[ReadCall] = []
    cwd: str | None = None
    for segment in _segments(tokenize(stripped)):
        verb, args = _verb(segment.stages[0])
        if verb in {"cd", "set-location", "pushd"} and args:
            target = _unquote(args[0])
            cwd = target if cwd is None or _is_absolute(target) else os.path.join(cwd, target)
            continue
        if segment.redirected and len(segment.stages) == 1:
            continue  # `cat a > b`: copia, no lectura al contexto
        call = _shell_read(verb, args, len(segment.stages) > 1, tool, bodies)
        if call is None:
            continue
        if call.via == "shell_cat_pipe" and call.lines is None:
            # `cat f | head -n N` (o `| Select-Object -First N`) es la franja 1..N.
            next_verb, next_args = _verb(segment.stages[1])
            if next_verb in {"head", "select-object"}:
                n = _int(_flag_value(next_args, "-n", "-first")) or next(
                    (_int(a[1:]) for a in next_args if re.fullmatch(r"-\d+", a)), None
                )
                if n:
                    call.scope, call.lines = "range", (1, n)
        if call.path and cwd and not _is_absolute(call.path):
            call.path = os.path.join(cwd, call.path)
        found.append(call)
    return found


def classify_tool(name: str, tool_input: dict) -> ReadCall | None:
    """La lectura de una tool que no es de shell, o `None` si no lee un fichero."""
    if name == "Read":
        path = tool_input.get("file_path")
        offset, limit = tool_input.get("offset"), tool_input.get("limit")
        if isinstance(offset, int) or isinstance(limit, int):
            start = max(offset if isinstance(offset, int) else 1, 1)
            end = start + limit - 1 if isinstance(limit, int) and limit > 0 else None
            return ReadCall("read_range", "range", path, (start, end))
        return ReadCall("read_whole", "whole", path)
    if name == "Grep":
        return ReadCall("grep_tool", "partial", tool_input.get("path"))
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3 and _MCP_READ.search(parts[-1].lower()):
            path = next(
                (tool_input.get(k) for k in ("path", "file_path", "uri") if tool_input.get(k)),
                None,
            )
            server = re.sub(r"[^a-z0-9]+", "_", parts[1].lower()).strip("_")
            return ReadCall(f"mcp_{server}", "whole", path if isinstance(path, str) else None)
    return None


# --- Rutas y tamaños -----------------------------------------------------------------------------


def _is_absolute(path: str) -> bool:
    return bool(re.match(r"^([A-Za-z]:[\\/]|[\\/]|~)", path))


def resolve(path: str | None, cwd: str | None) -> Path | None:
    """La ruta en disco de un operando (con `~`, `/d/…` de Git Bash y el `cwd` de la llamada)."""
    if not path or any(c in path for c in "*?$`<>|\n"):
        return None
    path = os.path.expanduser(path)
    m = _GIT_BASH_DRIVE.match(path.replace("\\", "/"))
    if m and os.name == "nt":
        path = f"{m.group(1).upper()}:/{m.group(2)}"
    p = Path(path)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    return p


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
        return ReadCall("read_image", "whole", call.path), None, None
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
            return ReadCall("read_whole", "whole", call.path), seen, total
        return ReadCall("read_range", "range", call.path, (start, start + num - 1)), None, total
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
