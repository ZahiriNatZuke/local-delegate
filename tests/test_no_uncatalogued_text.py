"""Ningún texto de salida para personas fuera del catálogo (REQ-045).

El guardián recorre por AST el paquete (sin `vendor/`) y los tres scripts que ya tiene B1, y busca
literales de texto para personas en los **contextos de salida** declarados abajo. No depende de
detectar español: una etiqueta de una palabra con mayúscula («Latencia», «Cargando») también
cuenta. Aparte hay una red complementaria por tildes (`áéíóúñ¿¡`) para lo que salga por un
contexto que el clasificador no conoce.

Mientras dura el frente B, los ficheros que todavía no pasan por el catálogo están en
`tests/data/uncatalogued_pending/<surface>.json`, una lista por superficie con su ola dueña (plan
D5); cada ola vacía la suya. Las excepciones legítimas (contratos, nombres de máquina, ficheros
fuera del alcance) están en `tests/data/uncatalogued_exceptions.json`, cada una con su motivo.

Dos reglas impiden vaciar la lista en falso:

- un fichero pendiente tiene que tener al menos una aparición: si el escáner no lo ve, sacarlo de
  la lista no comprobaría nada (y si ya no tiene texto, sobra en la lista);
- `web/metrics.py` no puede salir de la lista mientras no exista el escáner del panel (JS y HTML),
  que escribe B4.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "local_delegate"
PENDING_DIR = ROOT / "tests" / "data" / "uncatalogued_pending"
EXCEPTIONS_FILE = ROOT / "tests" / "data" / "uncatalogued_exceptions.json"

#: Superficies de D5 con texto en Python y su ola dueña.
SURFACE_OWNERS = {
    "cli": "B1",
    "doctor": "B1",
    "mcp": "B2",
    "hooks": "B3",
    "panel": "B4",
    "install": "B5",
}
#: Superficies cuya ola ya vació su lista: su fichero de pendientes se borra (decisión 9 de B1).
CLOSED_SURFACES = frozenset({"doctor", "cli", "mcp", "panel", "hooks"})
#: Scripts del repo que entran en el alcance: sus rótulos los imprime B1 (A-close-5).
SCRIPTS_IN_SCOPE = ("measure_cooldown.py", "pair_sheet.py", "analyze_benchmark.py")
#: El escáner del panel (literales del JS y texto y atributos del HTML de `web/metrics.py`) lo
#: escribió B4, dueña de `metrics.py` (`scan_panel`, abajo).
PANEL_SCANNER_IMPLEMENTED = True
PANEL_FILE = "src/local_delegate/web/metrics.py"
#: Constantes de módulo que son la plantilla del panel: se recorren con `scan_panel` (JS y HTML) y
#: no como un solo literal de Python.
PANEL_TEMPLATES = {PANEL_FILE: frozenset({"HTML"})}
#: Prefijos de contrato que se quedan tal cual en cualquier idioma (i18n §1 c).
#: Prefijo de error y marcadores de REQ-010 (B2b-1): valores de máquina del contrato de las tools MCP.
CONTRACT_PREFIXES = (
    "[local-delegate error]",
    "[local-delegate warning: ",
    "[local-delegate fallback: ",
    "[local-delegate: input truncated — ",
)
EXCEPTION_KINDS = frozenset(
    {
        "contract_prefix",
        "json_dump",
        "path",
        "id",
        "machine_name",
        "format_only",
        "out_of_scope",
        "verbatim",
    }
)
#: Clases cuyo texto puede ser prosa: el prefijo de contrato (solo los de `CONTRACT_PREFIXES`) y
#: `verbatim`, el texto que se compara, se hashea o se ejecuta tal cual contra algo de fuera (el log
#: de llama-swap, las entradas congeladas del corpus de afinidad, los contadores de `typeperf`, el
#: código del arnés, un motivo que viaja entre procesos); traducirlo rompería esa comparación (B1c).
PROSE_KINDS = frozenset({"contract_prefix", "verbatim"})

# --- Clasificación de contextos -------------------------------------------------------------------

#: 1. Llamadas cuyos argumentos acaban en pantalla o en la respuesta.
SINK_CALLS = frozenset(
    {"print", "write", "exit", "error", "warn", "emit", "deny", "append", "extend", "echo"}
)
#: 3. Argumentos con nombre que llevan texto para personas (argparse, checks, avisos).
TEXT_KEYWORDS = frozenset(
    {
        "help",
        "description",
        "epilog",
        "title",
        "usage",
        "remedy",
        "detail",
        "message",
        "reason",
        "hint",
        "label",
        "summary",
    }
)
#: Funciones del catálogo: su primer argumento (el segundo en `t_lang`) es una clave, no un texto.
CATALOG_CALLS = {"t": 0, "t_lang": 1, "hook_text": 0}
#: Catálogos que viven en el código y no en `resources/i18n/` (fichero, nombre de la constante): los
#: hooks no pueden importar el paquete y llevan sus textos dentro (REQ-030). Van atados a su fichero
#: para que otra constante con el mismo nombre no esconda texto; la paridad y el ASCII de este
#: catálogo los vigila `tests/test_i18n_parity.py`.
INLINE_CATALOGS = frozenset({("src/local_delegate/resources/hooks/hook_common.py", "HOOK_TEXTS")})
# (2) el mensaje de `raise`, (4) el valor de `return` y (5) las constantes de módulo o de clase
# con texto se tratan en `_output_nodes`.

#: (5) Una constante de módulo o de clase cuenta si su valor es un literal (no una llamada).
_CONSTANTS = (ast.Constant, ast.JoinedStr, ast.Dict, ast.Tuple, ast.List, ast.Set, ast.BinOp)
#: Lo que se quita de los bordes de una palabra. Un punto o un guion AL PRINCIPIO no se quitan:
#: `.md` y `--flag` son nombres de máquina.
_LEADING_PUNCTUATION = "«¿¡([\"'`*"
_TRAILING_PUNCTUATION = "»)]\"'`.,:;!?…*"
_PLAIN_WORD = re.compile(r"^[A-Za-zÀ-ÿ]{2,}$")
_ACCENTS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    text: str
    net: str  # "context" | "accent"

    def __str__(self) -> str:
        return f"{self.file}:{self.line} [{self.net}] {self.text!r}"


def is_human_text(text: str) -> bool:
    """Texto para personas: dos o más palabras corrientes, o una sola con mayúscula o tilde.

    Una palabra corriente es solo letras (tras quitar la puntuación de los bordes). Lo que lleva
    `_ . / = { } %` o dígitos, el `camelCase` y lo que va en MAYÚSCULAS son nombres de máquina.
    Una sola palabra en minúsculas y ASCII (`"auto"`, `"system"`) es un valor de enumeración.
    """
    words = []
    for token in text.split():
        token = token.lstrip(_LEADING_PUNCTUATION).rstrip(_TRAILING_PUNCTUATION)
        if not _PLAIN_WORD.match(token) or token.isupper() or re.search(r"[a-z][A-Z]", token):
            continue
        words.append(token)
    if len(words) >= 2:
        return True
    return len(words) == 1 and (words[0][0].isupper() or not words[0].isascii())


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _catalog_key_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in CATALOG_CALLS:
            position = CATALOG_CALLS[_call_name(node)]
            if len(node.args) > position:
                ids.add(id(node.args[position]))
    return ids


def _inline_catalog_ids(tree: ast.Module, rel: str) -> set[int]:
    """Todos los nodos bajo el valor de un catálogo en código de `INLINE_CATALOGS`."""
    names = {name for file, name in INLINE_CATALOGS if file == rel}
    ids = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.AnnAssign | ast.Assign) and stmt.value is not None:
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if any(isinstance(t, ast.Name) and t.id in names for t in targets):
                ids.update(id(node) for node in ast.walk(stmt.value))
    return ids


def _output_nodes(tree: ast.Module) -> list[ast.AST]:
    """Las raíces de los contextos de salida; sus literales se recorren por debajo."""
    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _call_name(node) in SINK_CALLS:
                roots.extend(node.args)
            roots.extend(kw.value for kw in node.keywords if kw.arg in TEXT_KEYWORDS)
        elif isinstance(node, ast.Raise) and node.exc is not None:
            roots.append(node.exc)
        elif isinstance(node, ast.Return) and node.value is not None:
            roots.append(node.value)
    for scope in [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))]:
        for stmt in scope.body:
            if isinstance(stmt, ast.Assign | ast.AnnAssign) and isinstance(stmt.value, _CONSTANTS):
                roots.append(stmt.value)
    return roots


def _literals(root: ast.AST, skip: set[int]) -> list[tuple[int, str]]:
    """(línea, texto) de los literales bajo `root`; una f-string cuenta como un solo texto."""
    found = []
    inner: set[int] = set()
    for node in ast.walk(root):
        if id(node) in skip or id(node) in inner:
            continue
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                else:
                    parts.append("{}")
            for child in ast.walk(node):
                inner.add(id(child))
            found.append((node.lineno, "".join(parts)))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
    return found


def _template_nodes(tree: ast.Module, names: frozenset[str]) -> list[ast.Constant]:
    """Los literales asignados a las constantes de plantilla (`HTML = r\"\"\"…\"\"\"`)."""
    found = []
    for stmt in tree.body:
        targets = stmt.targets if isinstance(stmt, ast.Assign) else []
        if (
            any(isinstance(t, ast.Name) and t.id in names for t in targets)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            found.append(stmt.value)
    return found


def scan_source(source: str, rel: str) -> list[Hit]:
    """Las apariciones de texto para personas de un fichero Python, por las dos redes.

    Si el fichero tiene plantilla de panel (`PANEL_TEMPLATES`), esa constante no se mira como un
    literal de Python sino con `scan_panel`, con las líneas del fichero.
    """
    tree = ast.parse(source)
    skip = _docstring_ids(tree) | _catalog_key_ids(tree) | _inline_catalog_ids(tree, rel)
    hits: set[Hit] = set()
    for node in _template_nodes(tree, PANEL_TEMPLATES.get(rel, frozenset())):
        skip.add(id(node))
        hits.update(scan_panel(node.value, rel, first_line=node.lineno))
    for root in _output_nodes(tree):
        for line, text in _literals(root, skip):
            if is_human_text(text):
                hits.add(Hit(rel, line, text, "context"))
    for line, text in _literals(tree, skip):
        if _ACCENTS.search(text):
            hits.add(Hit(rel, line, text, "accent"))
    return sorted(hits, key=lambda hit: (hit.line, hit.net, hit.text))


# --- El panel: el JS y el HTML de la plantilla (B4) ----------------------------------------------
#
# En el panel TODO literal del JS puede acabar en pantalla, así que todos son contexto de salida; lo
# que los separa de un nombre de máquina es `is_human_text`, igual que en Python. Un literal con
# marcado (`'<th>Proceso</th>'`) se mira sin las etiquetas y, aparte, el valor de sus atributos
# visibles. En el HTML cuenta el texto entre etiquetas y esos mismos atributos; el CSS, los
# comentarios y los `data-i18n*` (claves del catálogo) no.

#: Atributos que el navegador enseña a la persona.
_VISIBLE_ATTRS = ("title", "aria-label", "placeholder", "alt", "content", "label")
_ATTR_RE = re.compile(r"\b(?:{})\s*=\s*\"([^\"]*)\"".format("|".join(_VISIBLE_ATTRS)))
_TAG_RE = re.compile(r"<[^<>]*>")
#: Lo que precede a una `/` que abre una expresión regular (y no una división).
_REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^") | {""}
_JS_KEYWORDS_BEFORE_REGEX = ("return", "typeof", "case", "in", "of")


def js_strings(js: str) -> list[tuple[int, str]]:
    """(línea, texto) de cada literal de cadena del JS, sin comentarios ni expresiones regulares.

    Un template cuenta como un solo texto con `{}` en cada `${…}`, y lo que va dentro del hueco se
    recorre como código (sus cadenas cuentan aparte).
    """
    found: list[tuple[int, str]] = []
    n = len(js)

    def line_of(i: int) -> int:
        return js.count("\n", 0, i) + 1

    def prev_token(i: int) -> str:
        j = i - 1
        while j >= 0 and js[j] in " \t\r\n":
            j -= 1
        if j < 0:
            return ""
        if js[j].isalnum() or js[j] in "_$":
            k = j
            while k >= 0 and (js[k].isalnum() or js[k] in "_$"):
                k -= 1
            return js[k + 1 : j + 1]
        return js[j]

    def quoted(i: int) -> int:
        quote, j, chars = js[i], i + 1, []
        while j < n and js[j] != quote:
            if js[j] == "\\" and j + 1 < n:
                chars.append(js[j + 1])
                j += 2
                continue
            chars.append(js[j])
            j += 1
        found.append((line_of(i), "".join(chars)))
        return j + 1

    def regex(i: int) -> int:
        j, in_class = i + 1, False
        while j < n:
            c = js[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                break
            j += 1
        j += 1
        while j < n and js[j].isalpha():
            j += 1
        return j

    def template(i: int) -> int:
        j, parts = i + 1, []
        while j < n and js[j] != "`":
            if js[j] == "\\" and j + 1 < n:
                parts.append(js[j + 1])
                j += 2
            elif js.startswith("${", j):
                parts.append("{}")
                j = code(j + 2, until_brace=True)
            else:
                parts.append(js[j])
                j += 1
        found.append((line_of(i), "".join(parts)))
        return j + 1

    def code(i: int, until_brace: bool = False) -> int:
        depth = 0
        while i < n:
            c = js[i]
            if js.startswith("//", i):
                i = js.find("\n", i)
                i = n if i < 0 else i
            elif js.startswith("/*", i):
                i = js.find("*/", i + 2)
                i = n if i < 0 else i + 2
            elif c in "'\"":
                i = quoted(i)
            elif c == "`":
                i = template(i)
            elif c == "/" and (
                prev_token(i) in _REGEX_PRECEDERS or prev_token(i) in _JS_KEYWORDS_BEFORE_REGEX
            ):
                i = regex(i)
            elif c == "{":
                depth += 1
                i += 1
            elif c == "}":
                if until_brace and depth == 0:
                    return i + 1
                depth -= 1
                i += 1
            else:
                i += 1
        return i

    code(0)
    return found


def _visible_parts(fragment: str) -> list[str]:
    """Lo que una persona lee de un trozo de HTML: el texto sin etiquetas y los atributos visibles."""
    attrs = _ATTR_RE.findall(fragment)
    text = _TAG_RE.sub(" ", _ATTR_RE.sub(" ", fragment))
    return [text, *attrs]


def scan_panel(template: str, rel: str, first_line: int = 1) -> list[Hit]:
    """Las apariciones de texto para personas en la plantilla del panel (JS y HTML)."""
    hits: set[Hit] = set()

    def add(offset: int, text: str) -> None:
        for part in _visible_parts(text):
            if is_human_text(part):
                hits.add(Hit(rel, first_line + offset, part.strip(), "context"))

    for m in re.finditer(
        r"<script\b[^>]*>(.*?)</script\b[^>]*>", template, re.DOTALL | re.IGNORECASE
    ):
        base = template.count("\n", 0, m.start(1))
        for line, text in js_strings(m.group(1)):
            add(base + line - 1, text)
    markup = re.sub(
        r"<script\b[^>]*>.*?</script\b[^>]*>|<style\b[^>]*>.*?</style\b[^>]*>|<!--.*?--!?>",
        lambda m: "\n" * m.group(0).count("\n"),
        template,
        flags=re.DOTALL | re.IGNORECASE,
    )
    for m in re.finditer(r">([^<]+)<", markup):
        if is_human_text(m.group(1)):
            hits.add(
                Hit(
                    rel,
                    first_line + markup.count("\n", 0, m.start()),
                    m.group(1).strip(),
                    "context",
                )
            )
    for m in _ATTR_RE.finditer(markup):
        if is_human_text(m.group(1)):
            hits.add(Hit(rel, first_line + markup.count("\n", 0, m.start()), m.group(1), "context"))
    return sorted(hits, key=lambda hit: (hit.line, hit.text))


# --- Datos: alcance, pendientes y excepciones -----------------------------------------------------


def excluded_files() -> set[str]:
    return {entry["path"] for entry in load_exceptions()["files"]}


def files_in_scope() -> list[str]:
    """El paquete (sin `vendor/`) y los scripts de B1, menos los ficheros excluidos con motivo."""
    files = [
        p.relative_to(ROOT).as_posix()
        for p in sorted(PACKAGE.rglob("*.py"))
        if "vendor" not in p.parts and "__pycache__" not in p.parts
    ]
    files += [f"scripts/{name}" for name in SCRIPTS_IN_SCOPE]
    return [f for f in files if f not in excluded_files()]


def load_pending() -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(PENDING_DIR.glob("*.json"))
    }


def pending_files() -> set[str]:
    return {f for entry in load_pending().values() for f in entry["files"]}


def load_exceptions() -> dict[str, list[dict]]:
    return json.loads(EXCEPTIONS_FILE.read_text(encoding="utf-8"))


def _hits_by_file() -> dict[str, list[Hit]]:
    return {
        rel: scan_source((ROOT / rel).read_text(encoding="utf-8"), rel) for rel in files_in_scope()
    }


def is_excepted(hit: Hit, exceptions: list[dict]) -> bool:
    return any(e["file"] == hit.file and e["text"] == hit.text for e in exceptions)


def exception_problems(entries: list[dict]) -> list[str]:
    """Una excepción de texto tiene que ser de máquina, con su clase y su motivo."""
    problems = []
    for entry in entries:
        name = f"{entry.get('file')}: {entry.get('text')!r}"
        if not str(entry.get("reason", "")).strip():
            problems.append(f"{name}: sin motivo")
        if entry.get("kind") not in EXCEPTION_KINDS:
            problems.append(f"{name}: clase {entry.get('kind')!r} desconocida")
        text = entry.get("text", "")
        if entry.get("kind") == "contract_prefix":
            if text not in CONTRACT_PREFIXES:
                problems.append(f"{name}: no es un prefijo de contrato conocido")
        elif entry.get("kind") not in PROSE_KINDS and _has_prose(text):
            problems.append(f"{name}: es texto para personas, no una excepción")
    return problems


def _has_prose(text: str) -> bool:
    """Dos palabras corrientes seguidas: eso ya es prosa, por corta que sea."""
    previous = False
    for token in text.split():
        plain = bool(
            _PLAIN_WORD.match(token.lstrip(_LEADING_PUNCTUATION).rstrip(_TRAILING_PUNCTUATION))
        )
        if plain and previous:
            return True
        previous = plain
    return False


# --- Tests del guardián ---------------------------------------------------------------------------


def test_no_uncatalogued_text_outside_pending():
    """REQ-045: fuera de la lista de pendientes, todo texto para personas pasa por el catálogo."""
    pending = pending_files()
    exceptions = load_exceptions()["texts"]
    found = [
        str(hit)
        for rel, hits in _hits_by_file().items()
        if rel not in pending
        for hit in hits
        if not is_excepted(hit, exceptions)
    ]
    assert found == [], (
        "Texto para personas fuera del catálogo (usa `i18n.t`, o añade una excepción con motivo "
        "si es un nombre de máquina):\n" + "\n".join(found)
    )


def test_the_pending_lists_are_well_formed():
    pending = load_pending()
    assert set(pending) == set(SURFACE_OWNERS) - CLOSED_SURFACES, sorted(pending)
    seen: dict[str, str] = {}
    scope = set(files_in_scope())
    for surface, entry in pending.items():
        assert entry["surface"] == surface
        assert entry["owner"] == SURFACE_OWNERS[surface], surface
        assert entry["files"], (
            f"{surface}: lista vacía: bórrala y pon la superficie en CLOSED_SURFACES"
        )
        assert entry["files"] == sorted(entry["files"]), f"{surface}: lista sin ordenar"
        for rel in entry["files"]:
            assert rel in scope, f"{surface}: {rel} no existe o no está en el alcance"
            assert rel not in seen, f"{rel} está en {seen.get(rel)} y en {surface}"
            seen[rel] = surface


def test_every_pending_file_is_seen_by_the_scanner():
    """Un pendiente que el escáner no ve no puede salir de la lista sin comprobar nada.

    Si un fichero pendiente ya no tiene texto, sobra: se quita de la lista. Si lo tiene y el
    escáner no lo ve, falta un contexto de salida en la clasificación de arriba.
    """
    hits = _hits_by_file()
    blind = sorted(rel for rel in pending_files() if not hits[rel])
    assert blind == [], f"pendientes sin ninguna aparición: {blind}"


def test_the_panel_stays_pending_until_its_scanner_exists():
    """El texto del panel vive en el JS y el HTML de `metrics.py`, que este escáner no recorre."""
    if not PANEL_SCANNER_IMPLEMENTED:
        assert PANEL_FILE in load_pending()["panel"]["files"]


def test_text_exceptions_are_live_and_machine_text():
    exceptions = load_exceptions()["texts"]
    problems = exception_problems(exceptions)
    hits = _hits_by_file()
    for entry in exceptions:
        if not any(h.text == entry["text"] for h in hits.get(entry["file"], [])):
            problems.append(f"{entry['file']}: {entry['text']!r}: caducada, ya no aparece")
    assert problems == [], "\n".join(problems)


def test_file_exceptions_are_live_and_have_a_reason():
    """Los ficheros que no se escanean, con su motivo; uno que desaparece se quita de la lista."""
    entries = load_exceptions()["files"]
    assert entries, "la lista de ficheros excluidos no puede estar vacía en el frente B"
    for entry in entries:
        assert (ROOT / entry["path"]).is_file(), f"{entry['path']}: ya no existe"
        assert entry["path"] not in pending_files(), f"{entry['path']}: excluido y pendiente"
        assert str(entry.get("reason", "")).strip(), f"{entry['path']}: sin motivo"


# --- El clasificador, sobre código sintético (control positivo permanente) ------------------------


def _texts(source: str, net: str = "context") -> list[str]:
    return [hit.text for hit in scan_source(source, "x.py") if hit.net == net]


@pytest.mark.parametrize(
    "source",
    [
        'print("Hola")',
        'raise ValueError("Latencia")',
        'parser.add_argument("--x", help="muestra la ayuda")',
        'def f():\n    return f"{n} acciones fallaron"',
        'LABELS = {"ok": "todo bien"}',
        'lines.append("Cotejo de precios")',
        "sys.stderr.write('no hay datos')",
    ],
)
def test_text_in_an_output_context_is_caught(source):
    assert _texts(source) != []


@pytest.mark.parametrize(
    "source",
    [
        'print(t("common.language.source.system"))',
        'print(t_lang("en", "common.language.source.system"))',
        'parser.add_argument("--flag", help="--flag")',
        'def f():\n    return "system"',
        'def f():\n    """Docstring con texto, que no es salida."""',
        "raise KeyError(key)",
        'print(f"{path}: {count}")',
        'ENV = "LOCAL_DELEGATE_LANG"',
        'x = foo("texto suelto que no sale")',
    ],
)
def test_machine_text_and_catalog_keys_are_not_caught(source):
    assert _texts(source) == []


def test_the_accent_net_catches_text_outside_any_context():
    assert _texts('x = foo("ubicación")', net="accent") == ["ubicación"]
    assert _texts('x = foo("ubicacion")', net="accent") == []


def test_an_exception_with_prose_is_rejected():
    entries = [{"file": "x.py", "text": "Hola mundo", "kind": "id", "reason": "porque sí"}]
    assert exception_problems(entries) == [
        "x.py: 'Hola mundo': es texto para personas, no una excepción"
    ]


def test_verbatim_text_may_be_prose_but_needs_a_reason():
    entry = {"file": "x.py", "text": "reloading configuration", "kind": "verbatim", "reason": "r"}
    assert exception_problems([entry]) == []
    assert exception_problems([{**entry, "reason": " "}]) == [
        "x.py: 'reloading configuration': sin motivo"
    ]
    assert exception_problems([{**entry, "kind": "machine_name"}]) == [
        "x.py: 'reloading configuration': es texto para personas, no una excepción"
    ]


def test_a_contract_prefix_must_be_a_known_one():
    known = {
        "file": "x.py",
        "text": "[local-delegate error]",
        "kind": "contract_prefix",
        "reason": "r",
    }
    unknown = {**known, "text": "[local-delegate otro aviso]"}
    assert exception_problems([known]) == []
    assert exception_problems([unknown]) != []


# --- El escáner del panel, sobre plantillas sintéticas y sobre la de verdad (control positivo) ---


@pytest.mark.parametrize(
    "template",
    [
        "<body><h2>Latencia</h2></body>",
        '<body><button title="Rango temporal"></button></body>',
        "<script>el.textContent = 'Cargando';</script>",
        "<script>h += '<th>Proceso</th>';</script>",
        "<script>x = `<td>${n} llamadas al backend</td>`;</script>",
        "<script>el.innerHTML = '<span title=\"Abrir el panel\">x</span>';</script>",
        "<script>x = `${a ? 'Sin datos' : ''}`;</script>",
    ],
)
def test_panel_text_outside_the_catalog_is_caught(template):
    assert scan_panel(template, "x.py") != []


@pytest.mark.parametrize(
    "template",
    [
        '<body><h2 data-i18n="backend.title"></h2></body>',
        "<script>el.textContent = T('kpi.latency.label');</script>",
        "<script>// Latencia del modelo\nconst re = /[&<>\"']/g; x = 'none';</script>",
        "<script>/* Un comentario\n con texto */ y = a / b / 'c';</script>",
        '<style>.x{content:"Hola mundo"}</style><!-- Un comentario largo -->',
        "<script>c.className = ['pill', 'org', o].join(' ');</script>",
        "<body><span>ES</span><b>·</b></body>",
    ],
)
def test_panel_machine_text_and_keys_are_not_caught(template):
    assert scan_panel(template, "x.py") == []


def test_the_real_panel_with_one_word_left_untranslated_is_caught():
    """Control positivo sobre la plantilla de verdad: «Latencia» fuera del catálogo salta."""
    from local_delegate.web import metrics

    assert scan_panel(metrics.HTML, PANEL_FILE) == []
    mutated = metrics.HTML.replace("lbl:A(T('kpi.latency.label'))", "lbl:'Latencia'")
    assert mutated != metrics.HTML
    assert [hit.text for hit in scan_panel(mutated, PANEL_FILE)] == ["Latencia"]


def test_the_panel_template_is_scanned_through_scan_source():
    """`metrics.py` entra al guardián por `scan_source`: su plantilla no es un literal opaco."""
    source = (ROOT / PANEL_FILE).read_text(encoding="utf-8")
    mutated = source.replace("lbl:A(T('kpi.latency.label'))", "lbl:'Latencia'")
    assert mutated != source
    hits = scan_source(mutated, PANEL_FILE)
    assert [hit.text for hit in hits] == ["Latencia"]
    assert (
        hits[0].line
        == source.splitlines().index(
            next(line for line in source.splitlines() if "kpi.latency.label" in line)
        )
        + 1
    )


def test_the_hook_catalog_is_skipped_only_in_its_file():
    """`HOOK_TEXTS` es el catálogo de los hooks (REQ-030) solo en `hook_common.py`.

    Control positivo: la misma constante en otro fichero se caza, para que el nombre no sirva de
    escondite.
    """
    source = 'HOOK_TEXTS = {"es": {"a.b": "Hola, mundo"}}\nLABELS = {"x": "otra cosa"}'
    catalog_file = "src/local_delegate/resources/hooks/hook_common.py"
    texts = [hit.text for hit in scan_source(source, catalog_file) if hit.net == "context"]
    assert texts == ["otra cosa"]
    elsewhere = [hit.text for hit in scan_source(source, "x.py") if hit.net == "context"]
    assert "Hola, mundo" in elsewhere


def test_a_hook_text_key_is_not_caught():
    assert _texts('print(hook_text("read.block", size_kb="1", path="p"))') == []
