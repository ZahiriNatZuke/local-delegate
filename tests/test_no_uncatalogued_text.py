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
#: Scripts del repo que entran en el alcance: sus rótulos los imprime B1 (A-close-5).
SCRIPTS_IN_SCOPE = ("measure_cooldown.py", "pair_sheet.py", "analyze_benchmark.py")
#: El escáner del panel (literales del JS y texto y atributos del HTML de `web/metrics.py`) lo
#: escribe B4, dueña de `metrics.py`. Mientras sea `False`, `metrics.py` no puede salir de la lista.
PANEL_SCANNER_IMPLEMENTED = False
PANEL_FILE = "src/local_delegate/web/metrics.py"
#: Prefijos de contrato que se quedan tal cual en cualquier idioma (i18n §1 c).
CONTRACT_PREFIXES = ("[local-delegate error]",)
EXCEPTION_KINDS = frozenset(
    {"contract_prefix", "json_dump", "path", "id", "machine_name", "format_only", "out_of_scope"}
)

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
CATALOG_CALLS = {"t": 0, "t_lang": 1}
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


def scan_source(source: str, rel: str) -> list[Hit]:
    """Las apariciones de texto para personas de un fichero Python, por las dos redes."""
    tree = ast.parse(source)
    skip = _docstring_ids(tree) | _catalog_key_ids(tree)
    hits: set[Hit] = set()
    for root in _output_nodes(tree):
        for line, text in _literals(root, skip):
            if is_human_text(text):
                hits.add(Hit(rel, line, text, "context"))
    for line, text in _literals(tree, skip):
        if _ACCENTS.search(text):
            hits.add(Hit(rel, line, text, "accent"))
    return sorted(hits, key=lambda hit: (hit.line, hit.net, hit.text))


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
        elif _has_prose(text):
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
    assert set(pending) == set(SURFACE_OWNERS), sorted(pending)
    seen: dict[str, str] = {}
    scope = set(files_in_scope())
    for surface, entry in pending.items():
        assert entry["surface"] == surface
        assert entry["owner"] == SURFACE_OWNERS[surface], surface
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
