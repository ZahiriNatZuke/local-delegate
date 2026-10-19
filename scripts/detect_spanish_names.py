#!/usr/bin/env python3
"""Detector de nombres en español en el código y los datos del paquete (REQ-044 y REQ-016).

Recorre los identificadores de Python (`src/local_delegate`, `tests/`, `scripts/`), las claves y
valores de máquina en cadenas, el bloque `<script>` del panel, los ids del DOM, las claves y
valores de los `.json` de `src/**/resources` y los nombres de fichero y directorio, y dice cuáles
están en español.

Cómo decide, palabra por palabra (un nombre se parte por `snake_case`, `camelCase`, `kebab-case`
y puntos):

1. una palabra con tilde o eñe es española;
2. si no, manda el léxico congelado `scripts/data/spanish_lexicon.json`: las palabras que salen en
   el propio repo, clasificadas una vez como español o inglés (el procedimiento está en
   `spanish_lexicon.README.md`);
3. si no está en el léxico, la heurística de sufijos españoles (`-cion`, `-miento`, `-idad`…);
4. lo que queda se informa como **sin clasificar**: no cuenta como inglés, para que el léxico no se
   quede viejo en silencio.

Un nombre es español si tiene alguna palabra española que no sea funcional (`de`, `en`, `o`…), o
dos o más funcionales.

No necesita red ni dependencias: solo la biblioteca estándar.

Uso:
    python scripts/detect_spanish_names.py                       # resumen por categoría
    python scripts/detect_spanish_names.py --json salida.json    # resumen y hallazgos completos
    python scripts/detect_spanish_names.py --exceptions otra_lista.json  # por defecto, la de scripts/data
    python scripts/detect_spanish_names.py --dump-words palabras.json  # para generar el léxico
"""

from __future__ import annotations

import argparse
import ast
import functools
import io
import json
import re
import sys
import tokenize
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatch, fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data"
LEXICON_PATH = DATA_DIR / "spanish_lexicon.json"
RESERVED_PATH = DATA_DIR / "reserved_words.json"
EXCEPTIONS_PATH = DATA_DIR / "name_exceptions.json"

ACCENTED = frozenset("áéíóúñüÁÉÍÓÚÑÜ")
# Sufijos españoles sobre la palabra ya plegada (sin tildes). Solo se aplican a palabras que NO
# están en el léxico y que miden al menos `_MIN_SUFFIX_WORD` letras. Falsos positivos conocidos:
# `suspicion` y `coercion` (inglés en `-cion`); si salen en el repo, el léxico los fija como inglés.
SPANISH_SUFFIXES = (
    "ciones",
    "cion",
    "mientos",
    "miento",
    "idades",
    "idad",
    "iendo",
    "mente",
    "ajes",
    "aje",
)
_MIN_SUFFIX_WORD = 6

# Cadenas que parecen un término de máquina: identificador, clave o valor de enumeración.
_MACHINE_STRING = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[.\-][A-Za-z0-9_]+)*$")
_WORD = re.compile(r"[A-ZÁÉÍÓÚÑÜ]?[a-záéíóúñü]+|[A-ZÁÉÍÓÚÑÜ]+(?![a-záéíóúñü])|\d+")


# --- Palabras -----------------------------------------------------------------
def fold(word: str) -> str:
    """Minúsculas y sin tildes: `Canción` → `cancion`."""
    decomposed = unicodedata.normalize("NFD", word)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


def split_identifier(name: str) -> list[str]:
    """Parte un nombre en palabras (sin plegar): `fmtNum` → `['fmt', 'Num']`."""
    words: list[str] = []
    for part in re.split(r"[_\-\s.:/]+", name):
        words += [w for w in _WORD.findall(part) if not w.isdigit()]
    return words


@dataclass(frozen=True)
class Lexicon:
    spanish: frozenset[str]
    english: frozenset[str]
    function_words: frozenset[str]

    @classmethod
    def load(cls, path: Path = LEXICON_PATH) -> Lexicon:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            spanish=frozenset(data["es"]),
            english=frozenset(data["en"]),
            function_words=frozenset(data["function_words"]),
        )

    def __contains__(self, word: str) -> bool:
        folded = fold(word)
        return folded in self.spanish or folded in self.english


def has_spanish_suffix(folded: str) -> bool:
    return len(folded) >= _MIN_SUFFIX_WORD and folded.endswith(SPANISH_SUFFIXES)


def classify_word(word: str, lexicon: Lexicon) -> str:
    """`es`, `en` o `unclassified` (ver el docstring del módulo para el orden)."""
    if any(c in ACCENTED for c in word):
        return "es"
    folded = fold(word)
    if folded in lexicon.spanish or folded in lexicon.function_words:
        return "es"
    if folded in lexicon.english:
        return "en"
    if has_spanish_suffix(folded):
        return "es"
    if len(folded) < 3:
        # Demasiado corta para decir nada (`x`, `i`, `ok` fuera del léxico): neutra.
        return "en"
    return "unclassified"


def spanish_words(name: str, lexicon: Lexicon) -> list[str]:
    return [fold(w) for w in split_identifier(name) if classify_word(w, lexicon) == "es"]


def unclassified_words(name: str, lexicon: Lexicon) -> list[str]:
    return [fold(w) for w in split_identifier(name) if classify_word(w, lexicon) == "unclassified"]


def is_spanish(name: str, lexicon: Lexicon) -> bool:
    words = spanish_words(name, lexicon)
    # Un nombre hecho de UNA sola palabra funcional (`o`, `en`) no cuenta.
    return any(w not in lexicon.function_words for w in words) or len(words) >= 2


@functools.cache
def _default_lexicon() -> Lexicon:
    return Lexicon.load()


def detect(name: str) -> bool:
    """`is_spanish` con el léxico del repo."""
    return is_spanish(name, _default_lexicon())


# --- Tokenizador de JS (sin dependencias) -------------------------------------
@dataclass(frozen=True)
class JsToken:
    kind: str  # name | string | template | regex | number | punct
    value: str
    line: int


_REGEX_AFTER_KEYWORDS = frozenset(
    [
        "return",
        "typeof",
        "case",
        "do",
        "else",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "instanceof",
        "yield",
        "await",
    ]
)
_REGEX_AFTER_PUNCT = frozenset(
    [
        "(",
        ",",
        "=",
        ":",
        "[",
        "!",
        "&",
        "|",
        "?",
        "{",
        "}",
        ";",
        "+",
        "-",
        "*",
        "%",
        "<",
        ">",
        "~",
        "^",
        "=>",
        "==",
        "===",
        "!=",
        "!==",
        "&&",
        "||",
    ]
)
_PUNCT3 = ("===", "!==", "**=", "...", ">>>", "<<=", ">>=", "&&=", "||=", "??=")
_PUNCT2 = (
    "=>",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "??",
    "?.",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<",
    ">>",
    "**",
)


def tokenize_js(src: str) -> list[JsToken]:
    """Tokens de JS con comillas, plantillas (`${…}` anidadas), comentarios y regex literales.

    Un `/` abre una expresión regular cuando el token significativo anterior no puede cerrar una
    expresión (operador, `(`, `,`, palabra clave como `return`…), y divide en otro caso. Es lo que
    hace falta para no perderse en `.replace(/`([^`]+)`/g, …)`, donde una comilla invertida dentro
    de la regex parecería abrir una plantilla.
    """
    tokens: list[JsToken] = []
    i, n, line = 0, len(src), 1
    # Pila de plantillas abiertas: cada entrada es la profundidad de llaves dentro de su `${`.
    template_stack: list[int] = []

    def regex_allowed() -> bool:
        if not tokens:
            return True
        prev = tokens[-1]
        if prev.kind == "punct":
            return prev.value in _REGEX_AFTER_PUNCT
        if prev.kind == "name":
            return prev.value in _REGEX_AFTER_KEYWORDS
        return False

    def scan_template(start: int, start_line: int) -> tuple[int, int]:
        """Lee desde `start` (tras la comilla o tras `}`) hasta el cierre o el siguiente `${`."""
        pos, ln, parts = start, start_line, []
        while pos < n:
            ch = src[pos]
            if ch == "\\":
                parts.append(src[pos : pos + 2])
                pos += 2
                continue
            if ch == "`":
                tokens.append(JsToken("template", "".join(parts), start_line))
                return pos + 1, ln
            if ch == "$" and pos + 1 < n and src[pos + 1] == "{":
                tokens.append(JsToken("template", "".join(parts), start_line))
                template_stack.append(0)
                return pos + 2, ln
            if ch == "\n":
                ln += 1
            parts.append(ch)
            pos += 1
        tokens.append(JsToken("template", "".join(parts), start_line))
        return pos, ln

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif src.startswith("//", i):
            end = src.find("\n", i)
            i = n if end == -1 else end
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n if end == -1 else end + 2
            line += src.count("\n", i, end)
            i = end
        elif c in "'\"":
            j, buf = i + 1, []
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\":
                    buf.append(src[j : j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            tokens.append(JsToken("string", "".join(buf), line))
            i = j + 1
        elif c == "`":
            i, line = scan_template(i + 1, line)
        elif c == "}" and template_stack and template_stack[-1] == 0:
            template_stack.pop()
            i, line = scan_template(i + 1, line)
        elif c == "/" and regex_allowed():
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                j += 1
            j += 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1  # flags
            tokens.append(JsToken("regex", src[i:j], line))
            i = j
        elif c.isalpha() or c in "_$":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            tokens.append(JsToken("name", src[i:j], line))
            i = j
        elif c.isdigit():
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "._"):
                j += 1
            tokens.append(JsToken("number", src[i:j], line))
            i = j
        else:
            for op in (*_PUNCT3, *_PUNCT2):
                if src.startswith(op, i):
                    break
            else:
                op = c
            if template_stack and op == "{":
                template_stack[-1] += 1
            elif template_stack and op == "}":
                template_stack[-1] -= 1
            tokens.append(JsToken("punct", op, line))
            i += len(op)
    return tokens


_DECL_KEYWORDS = frozenset({"const", "let", "var"})


def js_declared_names(tokens: list[JsToken]) -> list[tuple[str, int]]:
    """Nombres que el JS declara: variables, funciones, clases y parámetros (también de flechas)."""
    found: list[tuple[str, int]] = []
    for k, tok in enumerate(tokens):
        if tok.kind != "name":
            continue
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        if tok.value in _DECL_KEYWORDS and nxt is not None:
            found += _declarators(tokens, k + 1)
        elif tok.value in ("function", "class") and nxt is not None:
            j = k + 1
            if nxt.kind == "name":
                found.append((nxt.value, nxt.line))
                j += 1
            if tok.value == "function" and j < len(tokens) and tokens[j].value == "(":
                found += _names_until_close(tokens, j)
    # Parámetros de funciones flecha: `(a, b) =>` y `x =>`.
    for k, tok in enumerate(tokens):
        if tok.kind == "punct" and tok.value == "=>" and k > 0:
            prev = tokens[k - 1]
            if prev.kind == "name":
                found.append((prev.value, prev.line))
            elif prev.kind == "punct" and prev.value == ")":
                depth, j = 0, k - 1
                while j >= 0:
                    if tokens[j].value == ")":
                        depth += 1
                    elif tokens[j].value == "(":
                        depth -= 1
                        if depth == 0:
                            break
                    j -= 1
                if j >= 0:
                    found += _names_until_close(tokens, j)
    return found


_OPEN = frozenset("([{")
_CLOSE = frozenset(")]}")


def _declarators(tokens: list[JsToken], start: int) -> list[tuple[str, int]]:
    """Los nombres de una declaración `const`/`let`/`var`, también los que van tras una coma.

    `const a = 1, b = 2` declara `a` y `b`; `let {x}, [y] = z` declara `x` e `y`. La declaración
    acaba en el `;` de su nivel, en un cierre que baja del nivel (`for (let i = 0, j = 1 …)`,
    `for (const x of y)`) o, sin `;`, en un salto de línea que no deja la expresión a medias (la
    línea no termina en coma ni en operador). Las comas de dentro de `(…)`, `[…]` y `{…}` (llamadas,
    literales, parámetros) no separan declaradores.
    """
    found: list[tuple[str, int]] = []
    expect_name, depth = True, 0
    for j in range(start, len(tokens)):
        tok = tokens[j]
        if expect_name:
            expect_name = False
            if tok.kind == "name":
                found.append((tok.value, tok.line))
                continue
            if tok.kind == "punct" and tok.value in "{[":
                found += _names_until_close(tokens, j)
                # Se sigue recorriendo el patrón para llevar la cuenta de niveles.
            else:
                break
        prev = tokens[j - 1]
        if depth == 0 and tok.line > prev.line:
            continues = prev.kind == "punct" and prev.value not in _CLOSE
            if not continues:
                break
        if tok.kind != "punct":
            continue
        if tok.value in _OPEN:
            depth += 1
        elif tok.value in _CLOSE:
            depth -= 1
            if depth < 0:
                break
        elif depth == 0 and tok.value == ";":
            break
        elif depth == 0 and tok.value == ",":
            expect_name = True
    return found


def _names_until_close(tokens: list[JsToken], open_index: int) -> list[tuple[str, int]]:
    """Nombres de un grupo `(…)`, `{…}` o `[…]` que no van tras `=` ni `.` (parámetros y patrones)."""
    pairs = {"(": ")", "{": "}", "[": "]"}
    depth, names = 0, []
    in_default = False
    for j in range(open_index, len(tokens)):
        tok = tokens[j]
        if tok.kind == "punct" and tok.value in pairs:
            depth += 1
        elif tok.kind == "punct" and tok.value in pairs.values():
            depth -= 1
            if depth == 0:
                break
        elif tok.kind == "punct" and tok.value == "=":
            in_default = True
        elif tok.kind == "punct" and tok.value == ",":
            in_default = False
        elif tok.kind == "name" and not in_default:
            prev = tokens[j - 1]
            if not (prev.kind == "punct" and prev.value in (".", "?.", ":")):
                names.append((tok.value, tok.line))
    return names


# --- Hallazgos ----------------------------------------------------------------
@dataclass
class Finding:
    category: str
    file: str
    line: int
    name: str
    words: list[str] = field(default_factory=list)


@dataclass
class Scan:
    names: list[tuple[str, str, int, str]] = field(
        default_factory=list
    )  # category, file, line, name

    def add(self, category: str, file: str, line: int, name: str) -> None:
        if name:
            self.names.append((category, file, line, name))


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for base in (root / "src" / "local_delegate", root / "tests", root / "scripts"):
        if base.is_dir():
            files += [p for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts]
    return files


def _is_machine_constant(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and bool(_MACHINE_STRING.match(node.value))
    )


def scan_python(path: Path, root: Path, scan: Scan) -> None:
    rel = _rel(path, root)
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scan.add("identifier", rel, node.lineno, node.name)
            a = node.args
            extra = [x for x in (a.vararg, a.kwarg) if x is not None]
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, *extra]:
                if arg.arg not in ("self", "cls"):
                    scan.add("identifier", rel, arg.lineno, arg.arg)
        elif isinstance(node, ast.ClassDef):
            scan.add("identifier", rel, node.lineno, node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            scan.add("identifier", rel, node.lineno, node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            scan.add("identifier", rel, node.lineno, node.attr)
        elif isinstance(node, ast.alias) and node.asname:
            scan.add("identifier", rel, node.lineno, node.asname)
        elif isinstance(node, ast.keyword) and node.arg:
            scan.add("identifier", rel, node.value.lineno, node.arg)
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if _is_machine_constant(key):
                    scan.add("string_key", rel, key.lineno, key.value)
        elif isinstance(node, ast.Subscript):
            if _is_machine_constant(node.slice):
                scan.add("string_key", rel, node.lineno, node.slice.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop", "setdefault")
            and node.args
            and _is_machine_constant(node.args[0])
        ):
            scan.add("string_key", rel, node.lineno, node.args[0].value)
    # Valores de máquina en cadenas: con separador (`snake_case`, `kebab-case`, `a.b`). Las
    # palabras sueltas son casi siempre prosa para personas, que es el frente B.
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.STRING:
            continue
        try:
            value = ast.literal_eval(tok.string)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, str) and _MACHINE_STRING.match(value) and re.search(r"[_\-.]", value):
            scan.add("string_value", rel, tok.start[0], value)


def _panel_html(root: Path) -> tuple[str, int] | None:
    metrics = root / "src" / "local_delegate" / "web" / "metrics.py"
    if not metrics.is_file():
        return None
    tree = ast.parse(metrics.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "HTML" for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value, node.value.lineno
    return None


def scan_panel(root: Path, scan: Scan) -> None:
    found = _panel_html(root)
    if found is None:
        return
    html, base_line = found
    rel = "src/local_delegate/web/metrics.py"
    for m in re.finditer(r"""\bid\s*=\s*["']([^"']+)["']""", html):
        scan.add("dom_id", rel, base_line + html.count("\n", 0, m.start()), m.group(1))
    for m in re.finditer(
        r"<script(?![^>]*src=)[^>]*>(.*?)</script[^>]*>", html, re.DOTALL | re.IGNORECASE
    ):
        offset = base_line + html.count("\n", 0, m.start(1)) - 1
        tokens = tokenize_js(m.group(1))
        for name, line in js_declared_names(tokens):
            scan.add("js_identifier", rel, offset + line, name)
        for k, tok in enumerate(tokens):
            prev = tokens[k - 1] if k else None
            nxt = tokens[k + 1] if k + 1 < len(tokens) else None
            if tok.kind == "name" and prev is not None and prev.value in (".", "?."):
                scan.add("js_property", rel, offset + tok.line, tok.value)
            elif (
                tok.kind == "name"
                and nxt is not None
                and nxt.value == ":"
                and prev is not None
                and prev.value in ("{", ",")
            ):
                scan.add("js_key", rel, offset + tok.line, tok.value)
            elif tok.kind == "string" and _MACHINE_STRING.match(tok.value):
                keyish = (prev is not None and prev.value == "[") or (
                    nxt is not None and nxt.value == ":"
                )
                if keyish or re.search(r"[_\-.]", tok.value):
                    scan.add("js_string", rel, offset + tok.line, tok.value)


def _walk_json(value: object, rel: str, scan: Scan) -> None:
    if isinstance(value, dict):
        for key, sub in value.items():
            if _MACHINE_STRING.match(key):
                scan.add("json_key", rel, 0, key)
            _walk_json(sub, rel, scan)
    elif isinstance(value, list):
        for sub in value:
            _walk_json(sub, rel, scan)
    elif isinstance(value, str) and _MACHINE_STRING.match(value) and len(value) <= 60:
        scan.add("json_value", rel, 0, value)


def scan_resources_json(root: Path, scan: Scan) -> None:
    base = root / "src"
    for path in sorted(base.rglob("*.json")):
        if "resources" not in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        _walk_json(data, _rel(path, root), scan)


def scan_file_names(root: Path, scan: Scan) -> None:
    for base in (root / "src" / "local_delegate", root / "scripts"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if "__pycache__" in path.parts:
                continue
            name = path.name if path.is_dir() else path.stem
            scan.add("file_name", _rel(path, root), 0, name)


def collect(root: Path = ROOT) -> Scan:
    scan = Scan()
    for path in _python_files(root):
        scan_python(path, root, scan)
    scan_panel(root, scan)
    scan_resources_json(root, scan)
    scan_file_names(root, scan)
    return scan


# --- Excepciones (REQ-016) ----------------------------------------------------
@dataclass(frozen=True)
class ExceptionEntry:
    name: str
    file_glob: str
    reason: str
    section: str


def load_exceptions(path: Path = EXCEPTIONS_PATH) -> list[ExceptionEntry]:
    """Entradas `{name, file, reason}` de las secciones de `name_exceptions.json`.

    Un fichero que falta o una entrada sin nombre o sin motivo es un error, no una lista vacía: el
    guardián de REQ-016 no puede quedarse sin lista en silencio.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[ExceptionEntry] = []
    for section in data["sections"]:
        for item in section["entries"]:
            if not item.get("name") or not str(item.get("reason", "")).strip():
                raise ValueError(f"{path}: entrada sin nombre o sin motivo: {item!r}")
            entries.append(
                ExceptionEntry(
                    item["name"], item.get("file") or "*", item["reason"], section["title"]
                )
            )
    return entries


def is_excepted(finding: Finding, exceptions: list[ExceptionEntry]) -> bool:
    """El nombre y el fichero de la fila admiten comodines (`*` aparta todo el fichero).

    El nombre se compara distinguiendo mayúsculas (`fnmatchcase`): `EMPATE` y `empate` son filas
    distintas, también en Windows, donde `fnmatch` las igualaría.
    """
    return any(
        fnmatchcase(finding.name, e.name) and fnmatch(finding.file, e.file_glob) for e in exceptions
    )


# --- Informe ------------------------------------------------------------------
def analyse(scan: Scan, lexicon: Lexicon, exceptions: list[ExceptionEntry] | None = None) -> dict:
    exceptions = exceptions or []
    seen: set[tuple[str, str, str]] = set()
    findings: list[Finding] = []
    occurrences: Counter[str] = Counter()
    unclassified: dict[str, str] = {}
    for category, file, line, name in scan.names:
        for word in unclassified_words(name, lexicon):
            unclassified.setdefault(word, f"{file}:{line}")
        if not is_spanish(name, lexicon):
            continue
        occurrences[category] += 1
        key = (category, file, name)
        if key in seen:
            continue
        seen.add(key)
        findings.append(Finding(category, file, line, name, spanish_words(name, lexicon)))
    outside = [f for f in findings if not is_excepted(f, exceptions)]
    by_category = Counter(f.category for f in findings)
    by_file = Counter(f.file for f in findings)
    return {
        "unique_findings": len(findings),
        "occurrences_by_category": dict(sorted(occurrences.items())),
        "unique_findings_by_category": dict(sorted(by_category.items())),
        "unique_spanish_names": len({f.name for f in findings}),
        "outside_exceptions": len(outside),
        "unclassified_words": dict(sorted(unclassified.items())),
        "files_with_findings": len(by_file),
        "top_files": by_file.most_common(30),
        "findings": [f.__dict__ for f in outside],
    }


def all_words(scan: Scan) -> list[str]:
    """Todas las palabras plegadas que ve el detector: el universo del léxico."""
    return sorted({fold(w) for *_rest, name in scan.names for w in split_identifier(name)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="raíz del repo")
    parser.add_argument("--lexicon", type=Path, default=LEXICON_PATH)
    parser.add_argument(
        "--exceptions", type=Path, default=EXCEPTIONS_PATH, help="lista de excepciones (REQ-016)"
    )
    parser.add_argument("--json", type=Path, help="escribe el informe completo en este fichero")
    parser.add_argument(
        "--dump-words", type=Path, help="escribe todas las palabras vistas (para el léxico) y sale"
    )
    args = parser.parse_args(argv)

    scan = collect(args.root)
    if args.dump_words:
        args.dump_words.write_text(
            json.dumps(all_words(scan), ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
        )
        print(f"{len(all_words(scan))} palabras escritas en {args.dump_words}")
        return 0

    exceptions = load_exceptions(args.exceptions)
    report = analyse(scan, Lexicon.load(args.lexicon), exceptions)
    if args.json:
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    print(f"nombres en español (únicos por categoría y fichero): {report['unique_findings']}")
    for category, count in report["unique_findings_by_category"].items():
        print(f"  {category}: {count}")
    print(f"fuera de la lista de excepciones: {report['outside_exceptions']}")
    print(f"palabras sin clasificar: {len(report['unclassified_words'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
