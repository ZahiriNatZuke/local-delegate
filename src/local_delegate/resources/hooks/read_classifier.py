"""The single read classifier (REQ-019): is this tool call «read file X», and how much of it?

Un solo módulo decide si una llamada lee un fichero, cuál y con qué alcance. Lo usan los hooks de
la entrega por settings (`suggest_delegate_read.py`, `suggest_delegate_shell.py`) y el mod de
lectura de la entrega por plugin (por `hook classify`). Cubrir una vía nueva es tocar solo este
fichero; los hooks no llevan reglas de lectura propias.

Las reglas salen de la medición de F4-measure-reads (`scripts/measure_read_paths.py`,
`evidence/F4-read-paths.md`), y el corpus `tests/fixtures/read_corpus.jsonl` las ata.

El alcance (`scope`) es el del contrato de `hook classify`:

- `whole`: el fichero entero (`Read` sin franja, `cat X`, `Get-Content X`);
- `range`: una franja de líneas conocida (`Read` con `offset`/`limit`, `sed -n 10,80p`,
  `head -n 40`, `cat X | head -n 40`, `Get-Content -TotalCount 40`);
- `partial`: un volcado parcial sin líneas conocidas (`tail`, `head -c`, `cat X | grep …`);
- `unclassifiable`: no se puede decir con seguridad qué se lee. Búsquedas (`grep`, la tool `Grep`),
  `awk`, `python`, `git show`, otras tools de lectura (`nl`, `jq`…), imágenes y las tools de otros
  MCP. Con ese alcance el mod solo avisa y registra, nunca bloquea (REQ-021).

Falso negativo antes que falso positivo: lo que no se entiende no es una lectura.

Sin dependencias (stdlib únicamente): corre dentro de los hooks de la entrega por settings.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

#: Tools sin shell que leen ficheros (y las de shell, que pueden hacerlo).
READ_TOOLS = ("Read", "Grep")
SHELL_TOOLS = ("Bash", "PowerShell")
#: Tools que escriben un fichero (la guarda de REQ-022 las mira).
WRITE_TOOLS = ("Edit", "MultiEdit", "NotebookEdit", "Write")
#: Prefijo de las tools de otros MCP. En `--list-tools` va como `mcp__*`.
MCP_PREFIX = "mcp__"
#: Nuestro propio MCP: `local_summarize(path=…)` no es una lectura al contexto.
OWN_MCP_SERVERS = frozenset({"local-delegate", "local_delegate"})

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
_POWERSHELL_ONLY = frozenset({"type", "gc", "sc", "ac"})
#: Opciones que llevan valor, por familia (para no tomar el valor por el fichero).
_VALUE_FLAGS = {
    "head_tail": {"-n", "-c"},
    "sed": {"-e", "-f"},
    "awk": {"-f", "-v", "-F"},
    "grep": {"-e", "-f", "-A", "-B", "-C", "-m", "--max-count", "-g", "-t", "--type"},
    "other": set(),
    "cat": {
        "-totalcount",
        "-head",
        "-first",
        "-tail",
        "-last",
        "-skip",
        "-encoding",
        "-readcount",
        "-delimiter",
        "-path",
        "-literalpath",
    },
}
#: Prefijos que no son el verbo: se saltan para llegar a él.
_WRAPPERS = frozenset({"sudo", "time", "command", "exec", "nohup", "env"})
#: Verbos que escriben un fichero, por cómo se saca el destino.
_WRITE_COPY = frozenset({"cp", "mv", "copy-item", "move-item", "cpi", "mi", "copy", "move"})
_WRITE_CONTENT = frozenset({"set-content", "add-content", "out-file", "sc", "ac"})
#: Destinos de una redirección que no son un fichero.
_NULL_TARGETS = frozenset({"/dev/null", "$null", "nul", "null", "&1", "&2"})
#: Extensiones que `Read` no entrega como texto: el resumen local no las sustituye.
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"})
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".ipynb"})
#: Prosa: lo que un resumen puede sustituir, y lo único que bloquea el hook de lectura (motivo
#: `large_prose`). Vive aquí para que el hook y el campo `summarizable` de `hook classify` (lo que
#: el mod resume) salgan de la misma lista. `.log` no entra: la medición de
#: `evidence/F4-read-paths.md` no trae datos por extensión y el hook no tuvo ni un aviso de logs.
PROSE_EXTENSIONS = frozenset({".md", ".txt", ".markdown", ".rst"})
#: El umbral bajo del hook de lectura: hasta él una lectura es `small`. El default lo ata
#: `config.HOOK_READ_SUGGEST_KB` en los tests.
SUGGEST_KB_VARIABLE = "LD_HOOK_READ_SUGGEST_KB"
SUGGEST_KB_DEFAULT = 8.0

_TOKEN = re.compile(
    r"""'[^']*'|"(?:\\.|[^"\\])*"|\|\||&&|>>|<<-?|2>&1|2>|[|;<>()&]|\n|[^\s|;<>()&'"]+"""
)
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_HERESTRING = re.compile(r"@'.*?'@|@\".*?\"@", re.DOTALL)
_SED_RANGE = re.compile(r"^(\d+)(?:,(\d+))?p$")
_SED_QUIET = re.compile(r"-[a-zA-Z]*n[a-zA-Z]*")
_NEGATIVE_NUMBER = re.compile(r"-\d+")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_GIT_BASH_DRIVE = re.compile(r"^/([a-zA-Z])/(.*)$")
_ABSOLUTE = re.compile(r"^([A-Za-z]:[\\/]|[\\/]|~)")
#: Nombres de tools de otros MCP que leen (por la parte tras el servidor).
_MCP_READ = re.compile(
    r"(^|_)(read|get_file|file_contents|get_note|convert_to_markdown|get_page|fetch_file|cat)"
)
_PY_READS = ("open(", "read_text", "read_bytes", "readlines")
#: Caracteres que impiden saber a qué fichero apunta una ruta (comodines, variables, código).
_UNRESOLVABLE = "*?$`<>|\n"

#: Prioridad de los alcances para elegir LA lectura de un comando con varias.
_SCOPE_PRIORITY = {"whole": 0, "range": 1, "partial": 2, "unclassifiable": 3}


@dataclass
class Access:
    """Una lectura o una escritura de un fichero, tal como sale del comando o de la entrada."""

    kind: str  # read | write
    via: str
    scope: str  # whole | range | partial | unclassifiable
    path: str | None = None
    lines: tuple[int, int | None] | None = None  # (primera, última) 1-based; última None = al final
    #: El comando entero es exactamente «verbo + una ruta», sin tubería, redirección, encadenado,
    #: sustitución ni opciones. Solo con esto bloquea el hook de shell de la entrega por settings.
    simple: bool = False


# --- Trocear el comando ----------------------------------------------------------------------------


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
    """Un comando de la línea: sus etapas de tubería y adónde va su salida."""

    stages: list[list[str]]
    redirected: bool = False
    heredoc: bool = False
    targets: list[str] | None = None  # destinos de `>`/`>>`


def segments(tokens: list[str]) -> list[Segment]:
    found: list[Segment] = []
    current = Segment([[]], targets=[])
    skip_next = False
    capture_next = False

    def close() -> None:
        current.stages = [s for s in current.stages if s]
        if current.stages or current.targets:
            found.append(current)

    for tok in tokens:
        if capture_next:
            capture_next = False
            assert current.targets is not None
            current.targets.append(_unquote(tok))
            continue
        if skip_next:
            skip_next = False
            continue
        if tok in {"&&", "||", ";", "\n", "&", "(", ")"}:
            close()
            current = Segment([[]], targets=[])
        elif tok == "|":
            current.stages.append([])
        elif tok in {">", ">>"}:
            current.redirected = True
            capture_next = True
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
    return found


def _verb(stage: list[str]) -> tuple[str, list[str], int]:
    """(verbo normalizado, argumentos, posición del verbo), saltando asignaciones y envoltorios."""
    i = 0
    while i < len(stage):
        word = stage[i].lower()
        if _ASSIGNMENT.match(stage[i]) or word in _WRAPPERS:
            i += 1
        elif word == "uv" and i + 1 < len(stage) and stage[i + 1] == "run":
            i += 2
            while i < len(stage) and stage[i].startswith("-"):
                i += 1  # opciones de `uv run`
        else:
            break
    if i >= len(stage):
        return "", [], i
    word = _unquote(stage[i]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    word = word.removesuffix(".exe")
    return word, stage[i + 1 :], i


def _operands(args: list[str], value_flags: set[str]) -> list[str]:
    """Los argumentos que no son opciones (ni el valor de las que lo llevan)."""
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("-") and len(a) > 1 and not _NEGATIVE_NUMBER.fullmatch(a):
            # Las opciones largas de PowerShell no distinguen mayúsculas; `-E` y `-e` de grep sí.
            if a in value_flags or (len(a) > 2 and a.lower() in value_flags):
                skip = True
            continue
        if _NEGATIVE_NUMBER.fullmatch(a):
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


def _is_absolute(path: str) -> bool:
    return bool(_ABSOLUTE.match(path))


# --- Lecturas de shell -----------------------------------------------------------------------------


def _shell_read(
    verb: str, args: list[str], piped: bool, tool: str, bodies: Sequence[str]
) -> Access | None:
    """La lectura de la primera etapa de una tubería, o `None` si no lee un fichero."""
    family = _FAMILY.get(verb)
    if verb in _POWERSHELL_ONLY and tool not in ("PowerShell", ""):
        return None
    if verb == "git" and args[:1] == ["show"] and any(":" in a for a in args[1:]):
        family = "git_show"
    if family is None:
        return None
    positional = _operands(args, _VALUE_FLAGS.get(family, set()))
    path: str | None = None
    scope = "unclassifiable"
    lines: tuple[int, int | None] | None = None
    lowered = [a.lower() for a in args]
    if family == "cat":
        path = _flag_value(args, "-path", "-literalpath") or (positional[0] if positional else None)
        head = _int(_flag_value(args, "-totalcount", "-head", "-first"))
        if path is None:
            return None
        if head is not None:
            scope, lines = "range", (1, head)
        elif "-tail" in lowered or "-last" in lowered:
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
            (_int(a[1:]) for a in args if _NEGATIVE_NUMBER.fullmatch(a)), None
        )
        if verb == "head" and "-c" not in args:
            scope, lines = "range", (1, n or 10)
        else:
            scope = "partial"
    elif family == "sed":
        if any(a.startswith("-i") or a == "--in-place" for a in args) or not any(
            _SED_QUIET.fullmatch(a) for a in args
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
        path = positional[-1]
    elif family == "grep":
        # Una búsqueda devuelve líneas sueltas o una cuenta, no el fichero ni una franja: el
        # resumen local no la sustituye (evidence/F4-read-paths.md, «Qué vías cubre F4»).
        has_pattern_flag = "-e" in args or "-f" in args
        if len(positional) < (1 if has_pattern_flag else 2):
            return None
        path = positional[-1]
    elif family == "python":
        code = _flag_value(args, "-c") or ("\n".join(bodies) if "-" in args or not args else "")
        if not code or not any(k in code for k in _PY_READS):
            return None
    elif family == "other":
        if not positional:
            return None
        path = positional[-1]
    via = f"shell_{family}" + ("_pipe" if piped else "")
    return Access("read", via, scope, path, lines)


def _shell_writes(verb: str, args: list[str], tool: str) -> list[str]:
    """Los ficheros que escribe una etapa de un comando (sin contar las redirecciones)."""
    if verb in _POWERSHELL_ONLY and tool not in ("PowerShell", ""):
        return []
    if verb == "tee":
        return _operands(args, set())
    if verb == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
        positional = _operands(args, _VALUE_FLAGS["sed"])
        return positional[-1:] if len(positional) >= 2 or "-e" in args else []
    if verb in _WRITE_COPY:
        target = _flag_value(args, "-destination")
        if target:
            return [target]
        positional = _operands(args, {"-path", "-literalpath"})
        return positional[-1:] if len(positional) >= 2 else []
    if verb in _WRITE_CONTENT:
        target = _flag_value(args, "-path", "-filepath", "-literalpath")
        if target:
            return [target]
        positional = _operands(args, {"-value", "-encoding", "-inputobject", "-width"})
        return positional[:1]
    return []


def classify_shell(command: str, tool: str = "Bash") -> list[Access]:
    """Las lecturas y escrituras de un comando de shell, en orden.

    Una ruta relativa se une al último `cd` del propio comando; la de la llamada (`cwd`) se pone
    después, en `resolve`. Un comando con su salida redirigida a un fichero (`cat a > b`) no lee
    al contexto: escribe `b`.
    """
    stripped, bodies = strip_heredocs(command)
    parts = segments(tokenize(stripped))
    found: list[Access] = []
    cwd: str | None = None
    compound = len(parts) != 1 or "$(" in command or "`" in command

    def anchored(path: str) -> str:
        if cwd and not _is_absolute(path):
            return os.path.join(cwd, path)
        return path

    for segment in parts:
        for target in segment.targets or []:
            if target.lower() not in _NULL_TARGETS:
                found.append(Access("write", "shell_write", "unclassifiable", anchored(target)))
        if not segment.stages:
            continue
        verb, args, at = _verb(segment.stages[0])
        if verb in {"cd", "set-location", "pushd", "sl"} and args:
            target = _unquote(args[0])
            cwd = target if cwd is None or _is_absolute(target) else os.path.join(cwd, target)
            continue
        for stage in segment.stages:
            stage_verb, stage_args, _ = _verb(stage)
            for target in _shell_writes(stage_verb, stage_args, tool):
                found.append(Access("write", "shell_write", "unclassifiable", anchored(target)))
        if segment.redirected and len(segment.stages) == 1:
            continue  # `cat a > b`: copia, no lectura al contexto
        call = _shell_read(verb, args, len(segment.stages) > 1, tool, bodies)
        if call is None:
            continue
        if call.via == "shell_cat_pipe" and call.lines is None:
            # `cat f | head -n N` (o `| Select-Object -First N`) es la franja 1..N.
            next_verb, next_args, _ = _verb(segment.stages[1])
            if next_verb in {"head", "select-object"}:
                n = _int(_flag_value(next_args, "-n", "-first")) or next(
                    (_int(a[1:]) for a in next_args if _NEGATIVE_NUMBER.fullmatch(a)), None
                )
                if n:
                    call.scope, call.lines = "range", (1, n)
        call.simple = (
            not compound
            and call.via == "shell_cat"
            and call.scope == "whole"
            and at == 0
            and len(segment.stages[0]) == 2
            and not args[0].startswith("-")
            and not segment.heredoc
        )
        if call.path:
            call.path = anchored(call.path)
        found.append(call)
    return found


# --- Tools sin shell -------------------------------------------------------------------------------


def _extension(path: object) -> str:
    return os.path.splitext(str(path))[1].lower() if isinstance(path, str) else ""


def classify_tool(name: str, tool_input: dict) -> Access | None:
    """La lectura o escritura de una tool que no es de shell, o `None` si no toca un fichero."""
    if name == "Read":
        path = tool_input.get("file_path")
        if not isinstance(path, str) or not path:
            return None
        ext = _extension(path)
        if ext in IMAGE_EXTENSIONS:
            return Access("read", "read_image", "unclassifiable", path)
        if ext in DOCUMENT_EXTENSIONS:
            return Access("read", "read_document", "unclassifiable", path)
        offset, limit = tool_input.get("offset"), tool_input.get("limit")
        if isinstance(offset, int) or isinstance(limit, int):
            start = max(offset if isinstance(offset, int) else 1, 1)
            end = start + limit - 1 if isinstance(limit, int) and limit > 0 else None
            return Access("read", "read_range", "range", path, (start, end))
        return Access("read", "read_whole", "whole", path)
    if name == "Grep":
        path = tool_input.get("path")
        return Access(
            "read", "grep_tool", "unclassifiable", path if isinstance(path, str) else None
        )
    if name in WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return Access(
            "write", "write_tool", "unclassifiable", path if isinstance(path, str) else None
        )
    if name.startswith(MCP_PREFIX):
        parts = name.split("__")
        if (
            len(parts) >= 3
            and parts[1] not in OWN_MCP_SERVERS
            and _MCP_READ.search(parts[-1].lower())
        ):
            path = next(
                (
                    tool_input.get(k)
                    for k in ("path", "file_path", "filePath", "uri")
                    if tool_input.get(k)
                ),
                None,
            )
            if path is None and isinstance(tool_input.get("paths"), list) and tool_input["paths"]:
                path = tool_input["paths"][0]
            server = re.sub(r"[^a-z0-9]+", "_", parts[1].lower()).strip("_")
            return Access(
                "read", f"mcp_{server}", "unclassifiable", path if isinstance(path, str) else None
            )
    return None


def accesses(tool_name: str, tool_input: dict) -> list[Access]:
    """Todas las lecturas y escrituras de una llamada, con las rutas tal como vienen."""
    if not isinstance(tool_input, dict):
        return []
    if tool_name in SHELL_TOOLS or (not tool_name and "command" in tool_input):
        command = tool_input.get("command")
        if not isinstance(command, str) or not command.strip():
            return []
        return classify_shell(command, tool_name)
    single = classify_tool(tool_name, tool_input)
    return [single] if single else []


def primary(found: Sequence[Access]) -> Access | None:
    """La lectura o escritura que representa a la llamada.

    Gana una escritura: la guarda de REQ-022 no puede perderse una escritura sobre un fichero
    resumido porque el mismo comando lea otro. Entre lecturas, la de mayor alcance (entero, franja,
    parcial, no clasificable); a igualdad, la primera.
    """
    writes = [a for a in found if a.kind == "write"]
    if writes:
        return writes[0]
    reads = [a for a in found if a.kind == "read"]
    if not reads:
        return None
    return min(reads, key=lambda a: _SCOPE_PRIORITY[a.scope])


def simple_whole_dump(found: Sequence[Access]) -> str | None:
    """La ruta (tal como viene) si el comando (`classify_shell`) es SOLO volcar un fichero entero:
    `cat X`, `Get-Content X`, `type X` en PowerShell… Es lo único que bloquea el hook de shell."""
    if len(found) == 1 and found[0].simple and found[0].path:
        return found[0].path
    return None


# --- Rutas y salida del contrato -------------------------------------------------------------------


def resolve(path: str | None, cwd: str | None) -> str | None:
    """La ruta absoluta en disco de un operando (con `~`, `/d/…` de Git Bash y el `cwd` de la
    llamada), o `None` si no se puede saber a qué fichero apunta."""
    if not path or any(c in path for c in _UNRESOLVABLE):
        return None
    path = os.path.expanduser(path)
    m = _GIT_BASH_DRIVE.match(path.replace("\\", "/"))
    if m and os.name == "nt":
        path = f"{m.group(1).upper()}:/{m.group(2)}"
    if not os.path.isabs(path):
        if not cwd:
            return None
        path = os.path.join(cwd, path)
    return os.path.normpath(path)


def summarizable(path: str | None, size: int | None) -> bool:
    """Si el fichero está en la banda que bloquea el hook de lectura: prosa por encima del umbral
    bajo. Es lo único que el mod de lectura resume; el código, la config y los datos pasan."""
    if not path or size is None or _extension(path) not in PROSE_EXTENSIONS:
        return False
    try:
        threshold_kb = float(os.environ.get(SUGGEST_KB_VARIABLE, str(SUGGEST_KB_DEFAULT)))
    except ValueError:
        return False
    return size / 1024 > threshold_kb


def classify(payload: dict, read_switch: str | None = None) -> dict:
    """La respuesta de `hook classify` para la entrada de un hook `PreToolUse`.

    Campos y valores fijados por el plan (Ola 5, «Contrato de `hook classify`»):
    `kind` (`read`/`write`/`other`), `path` (absoluta o `null`), `scope`, `bytes` (tamaño del
    fichero o `null`), `range` (`[primera, última]`, última `null` = hasta el final; o `null`),
    `via` (nombre de la vía, `none` si no toca un fichero), `read_switch` y `summarizable` (si es
    una lectura de un fichero en la banda que bloquea el hook, `summarizable()`).

    Una lectura cuyo fichero no se puede resolver (comodines, variables) sale `unclassifiable`:
    sin fichero no hay nada que resumir ni que acumular. Para `write` y `other` el alcance es
    `unclassifiable`, porque el alcance describe una lectura.
    """
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd")
    access = primary(accesses(tool_name, tool_input if isinstance(tool_input, dict) else {}))
    if access is None:
        return {
            "kind": "other",
            "path": None,
            "scope": "unclassifiable",
            "bytes": None,
            "range": None,
            "via": "none",
            "read_switch": read_switch,
            "summarizable": False,
        }
    path = resolve(access.path, cwd if isinstance(cwd, str) else None)
    scope = access.scope if access.kind == "read" else "unclassifiable"
    if path is None:
        scope = "unclassifiable"
    size: int | None = None
    if path is not None:
        try:
            size = os.path.getsize(path) if os.path.isfile(path) else None
        except OSError:
            size = None
    return {
        "kind": access.kind,
        "path": path,
        "scope": scope,
        "bytes": size,
        "range": list(access.lines) if access.lines and scope == "range" else None,
        "via": access.via,
        "read_switch": read_switch,
        "summarizable": access.kind == "read" and summarizable(path, size),
    }


def list_tools() -> list[str]:
    """Los nombres de tool que pueden leer o escribir un fichero. `mcp__*` es un prefijo."""
    return sorted({*READ_TOOLS, *SHELL_TOOLS, *WRITE_TOOLS}) + [MCP_PREFIX + "*"]
