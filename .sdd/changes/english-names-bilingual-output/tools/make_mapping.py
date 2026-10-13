#!/usr/bin/env python3
"""Fichero de correspondencias de una ola del renombrado (D13) y su aplicador acotado.

Dos subcomandos:

``build``  Recorre `src/local_delegate`, `tests/` y `scripts/`, resuelve nombres por AST (ámbitos,
           atributos e imports) y escribe `waves/<ola>-mapping.csv` con **una fila por
           definición** en español (lo decide el detector de A0, `scripts/detect_spanish_names.py`),
           filtrada por los ficheros de la ola (`--paths`, globs relativos a la raíz).

``apply``  Aplica las filas `method=search_edit` de ámbito `function_local` (variables locales) y
           `unreferenced_test` (funciones `test_*` sin referencias) de un mapping **aprobado**
           (`# approved-by-main: <fecha>`). Una variable local se reemplaza **solo dentro del tramo
           de su función**, nunca en todo el fichero. Abre y escribe con `newline=""`, así que no
           cambia los saltos de línea.

Columnas del CSV: `old`, `new` (propuesta; la rellena el agente y la revisa la sesión principal),
`kind`, `definition` (`fichero:línea@ámbito`), `scope` (`cross_module`, `module_local`,
`function_local`, `unreferenced_test` o `unresolved`), `method` (`pycharm` o `search_edit`),
`reason` (obligatorio con `search_edit`) y `verified` (lo escribe el agente).

Uso:
    python make_mapping.py build --wave A3 --paths "src/local_delegate/fallos.py" --out waves/A3-mapping.csv
    python make_mapping.py apply --mapping waves/A9a-1-mapping.csv [--dry-run]
"""

from __future__ import annotations

import argparse
import ast
import csv
import importlib.util
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[4]
COLUMNS = ("old", "new", "kind", "definition", "scope", "method", "reason", "verified")
SEARCH_EDIT_SCOPES = ("function_local", "unreferenced_test")
APPROVAL_PREFIX = "# approved-by-main"
_DYNAMIC_CALLS = frozenset({"getattr", "setattr", "hasattr", "delattr", "patch", "object"})


# --- Detector -----------------------------------------------------------------
def load_detector(root: Path):
    path = root / "scripts" / "detect_spanish_names.py"
    spec = importlib.util.spec_from_file_location("detect_spanish_names", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"no se pudo cargar el detector: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("detect_spanish_names", module)
    spec.loader.exec_module(module)
    return module


# --- Modelo -------------------------------------------------------------------
@dataclass
class Scope:
    kind: str  # module | class | function
    qualname: str
    parent: Scope | None
    span: tuple[int, int]
    symbols: dict[str, Definition] = field(default_factory=dict)
    globals: set[str] = field(default_factory=set)
    nonlocals: set[str] = field(default_factory=set)


@dataclass
class Definition:
    name: str
    kind: str
    file: str
    line: int
    scope: Scope
    refs: list[tuple[str, int]] = field(default_factory=list)  # (fichero, línea)

    @property
    def definition(self) -> str:
        return f"{self.file}:{self.line}@{self.scope.qualname}"


@dataclass
class Project:
    root: Path
    modules: dict[str, str] = field(default_factory=dict)  # nombre con puntos -> fichero
    definitions: list[Definition] = field(default_factory=list)
    attr_refs: dict[str, list[tuple[str, int]]] = field(default_factory=lambda: defaultdict(list))
    kw_refs: dict[str, list[tuple[str, int]]] = field(default_factory=lambda: defaultdict(list))
    dyn_refs: dict[str, list[tuple[str, int]]] = field(default_factory=lambda: defaultdict(list))
    # (fichero del módulo, nombre) -> referencias desde OTROS ficheros (imports y `mod.nombre`)
    cross_refs: dict[tuple[str, str], list[tuple[str, int]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    imported_modules: dict[str, list[tuple[str, int]]] = field(
        default_factory=lambda: defaultdict(list)
    )


def module_name(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts[0] == "src" or parts[0] in ("tests", "scripts"):
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def python_files(root: Path) -> list[str]:
    out = []
    for base in ("src/local_delegate", "tests", "scripts"):
        directory = root / base
        if directory.is_dir():
            out += [
                p.relative_to(root).as_posix()
                for p in sorted(directory.rglob("*.py"))
                if "__pycache__" not in p.parts
            ]
    return out


# --- Análisis por fichero -----------------------------------------------------
class FileAnalysis:
    """Dos pasadas: la primera define (ámbitos y símbolos), la segunda resuelve las lecturas."""

    def __init__(self, project: Project, rel: str, tree: ast.Module) -> None:
        self.p = project
        self.rel = rel
        self.tree = tree
        self.scope_of: dict[int, Scope] = {}
        self.module_scope = Scope("module", "<module>", None, (1, 10**9))
        self.import_alias: dict[str, str] = {}  # alias local -> módulo (nombre con puntos)

    # pasada 1
    def define(self, scope: Scope, name: str, kind: str, line: int) -> None:
        target = scope
        if name in scope.globals:
            target = self.module_scope
        elif name in scope.nonlocals:
            target = scope.parent
            while target is not None and (target.kind != "function" or name not in target.symbols):
                target = target.parent
            target = target or scope
        if name not in target.symbols:
            d = Definition(name, kind, self.rel, line, target)
            target.symbols[name] = d
            self.p.definitions.append(d)

    def collect(self, node: ast.AST, scope: Scope) -> None:
        self.scope_of[id(node)] = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "method" if scope.kind == "class" else "function"
            self.define(scope, node.name, kind, node.lineno)
            for deco in node.decorator_list:
                self.collect(deco, scope)
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    self.collect(default, scope)
            qual = node.name if scope.kind == "module" else f"{scope.qualname}.{node.name}"
            inner = Scope("function", qual, scope, (node.lineno, node.end_lineno or node.lineno))
            self.scope_of[id(node)] = inner
            a = node.args
            extra = [x for x in (a.vararg, a.kwarg) if x is not None]
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, *extra]:
                self.scope_of[id(arg)] = inner
                if arg.arg not in ("self", "cls"):
                    self.define(inner, arg.arg, "param", arg.lineno)
            for stmt in node.body:
                self.collect(stmt, inner)
            return
        if isinstance(node, ast.ClassDef):
            self.define(scope, node.name, "class", node.lineno)
            for item in [*node.decorator_list, *node.bases, *node.keywords]:
                self.collect(item, scope)
            qual = node.name if scope.kind == "module" else f"{scope.qualname}.{node.name}"
            inner = Scope("class", qual, scope, (node.lineno, node.end_lineno or node.lineno))
            self.scope_of[id(node)] = inner
            for stmt in node.body:
                self.collect(stmt, inner)
            return
        if isinstance(node, ast.Global):
            scope.globals.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            scope.nonlocals.update(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            kind = "constant" if node.id.isupper() else "variable"
            self.define(scope, node.id, kind, node.lineno)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            cls = self._enclosing_class(scope)
            if cls is not None and isinstance(node.value, ast.Name) and node.value.id == "self":
                self.define(cls, node.attr, "attribute", node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            self._collect_import(node, scope)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            self.define(scope, node.name, "variable", node.lineno)
        for child in ast.iter_child_nodes(node):
            self.collect(child, scope)

    def _enclosing_class(self, scope: Scope) -> Scope | None:
        s = scope
        while s is not None and s.kind != "class":
            s = s.parent
        return s

    def _sibling(self, name: str | None) -> str | None:
        """`import x` / `from x import y` plano que es un VECINO del fichero (un script que el
        intérprete importa por `sys.path[0]`, como `from hook_common import …` entre hooks).

        Sin esto los símbolos que un hook importa de otro salían `module_local` (ola A2)."""
        if not name or name in self.p.modules:
            return None
        package = module_name(self.rel).split(".")[:-1]
        sibling = ".".join([*package, name])
        return sibling if sibling in self.p.modules else None

    def _resolve_module(self, node: ast.ImportFrom) -> str | None:
        if node.level == 0:
            return self._sibling(node.module) or node.module
        package = module_name(self.rel).split(".")
        if not self.rel.endswith("__init__.py"):
            package = package[:-1]
        if node.level > 1:
            package = package[: len(package) - (node.level - 1)]
        return ".".join([*package, *([node.module] if node.module else [])])

    def _collect_import(self, node: ast.Import | ast.ImportFrom, scope: Scope) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                sibling = self._sibling(alias.name)
                if sibling is not None:
                    self.import_alias[local] = sibling
                    self._note_module_import(sibling, node.lineno)
                else:
                    self.import_alias[local] = alias.name if alias.asname else local
                    self._note_module_import(alias.name, node.lineno)
                if alias.asname:
                    self.define(scope, alias.asname, "import_alias", node.lineno)
            return
        base = self._resolve_module(node)
        if base is None:
            return
        for alias in node.names:
            local = alias.asname or alias.name
            full = f"{base}.{alias.name}"
            if full in self.p.modules:  # `from paquete import modulo`
                self.import_alias[local] = full
                self._note_module_import(full, node.lineno)
            elif base in self.p.modules:
                target = self.p.modules[base]
                if target != self.rel:
                    self.p.cross_refs[(target, alias.name)].append((self.rel, node.lineno))
            if alias.asname:
                self.define(scope, alias.asname, "import_alias", node.lineno)

    def _note_module_import(self, dotted: str, line: int) -> None:
        if dotted in self.p.modules and self.p.modules[dotted] != self.rel:
            self.p.imported_modules[self.p.modules[dotted]].append((self.rel, line))

    # pasada 2
    def resolve(self) -> None:
        for node in ast.walk(self.tree):
            scope = self.scope_of.get(id(node), self.module_scope)
            if isinstance(node, ast.Name):
                d = self._lookup(scope, node.id)
                if d is not None and not (d.line == node.lineno and d.file == self.rel):
                    d.refs.append((self.rel, node.lineno))
            elif isinstance(node, ast.Attribute):
                self.p.attr_refs[node.attr].append((self.rel, node.lineno))
                if isinstance(node.value, ast.Name) and node.value.id in self.import_alias:
                    target = self.p.modules.get(self.import_alias[node.value.id])
                    if target is not None and target != self.rel:
                        self.p.cross_refs[(target, node.attr)].append((self.rel, node.lineno))
            elif isinstance(node, ast.keyword) and node.arg:
                self.p.kw_refs[node.arg].append((self.rel, node.value.lineno))
            elif isinstance(node, ast.Call):
                self._dynamic(node)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if "." in value and all(part.isidentifier() for part in value.split(".")):
                    self.p.dyn_refs[value.rsplit(".", 1)[1]].append((self.rel, node.lineno))

    def _dynamic(self, node: ast.Call) -> None:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in _DYNAMIC_CALLS:
            return
        for arg in node.args[:3]:
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.isidentifier()
            ):
                self.p.dyn_refs[arg.value].append((self.rel, node.lineno))

    def _lookup(self, scope: Scope, name: str) -> Definition | None:
        if name in scope.globals:
            return self.module_scope.symbols.get(name)
        s: Scope | None = scope
        first = True
        while s is not None:
            if (first or s.kind != "class") and name in s.symbols:
                return s.symbols[name]
            first = False
            s = s.parent
        return None


def analyse_project(root: Path) -> Project:
    project = Project(root)
    files = python_files(root)
    for rel in files:
        project.modules[module_name(rel)] = rel
    analyses = []
    for rel in files:
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        fa = FileAnalysis(project, rel, tree)
        fa.collect(tree, fa.module_scope)
        analyses.append(fa)
    for fa in analyses:
        fa.resolve()
    return project


# --- Clasificación ------------------------------------------------------------
def classify(d: Definition, p: Project) -> str:
    other_files = lambda refs: [r for r in refs if r[0] != d.file]
    if d.scope.kind == "function":
        if d.kind == "param" and p.kw_refs.get(d.name):
            return "cross_module" if other_files(p.kw_refs[d.name]) else "module_local"
        return "function_local"
    if d.scope.kind == "module":
        if other_files(p.cross_refs.get((d.file, d.name), [])):
            return "cross_module"
        if p.dyn_refs.get(d.name):
            return "unresolved"
        if _is_unreferenced_test(d, p):
            return "unreferenced_test"
        return "module_local"
    # miembros de clase: atributos y métodos se leen como `x.nombre`, sin tipo conocido
    if _is_unreferenced_test(d, p):
        return "unreferenced_test"
    if other_files(p.attr_refs.get(d.name, [])):
        return "cross_module"
    if p.dyn_refs.get(d.name):
        return "unresolved"
    return "module_local"


def _is_unreferenced_test(d: Definition, p: Project) -> bool:
    return (
        d.file.startswith("tests/")
        and d.kind in ("function", "method")
        and d.name.startswith("test_")
        and not d.refs
        and not p.attr_refs.get(d.name)
        and not p.dyn_refs.get(d.name)
    )


def build_rows(root: Path, paths: list[str]) -> list[dict[str, str]]:
    detector = load_detector(root)
    lexicon = detector.Lexicon.load(root / "scripts" / "data" / "spanish_lexicon.json")
    project = analyse_project(root)
    rows = []
    for d in project.definitions:
        if paths and not any(fnmatch(d.file, pat) for pat in paths):
            continue
        if not detector.is_spanish(d.name, lexicon):
            continue
        scope = classify(d, project)
        method = "search_edit" if scope in SEARCH_EDIT_SCOPES else "pycharm"
        reason = {
            "function_local": "variable local: reemplazo acotado a su función (apply)",
            "unreferenced_test": "test sin referencias: reemplazo del nombre en su def (apply)",
        }.get(scope, "")
        rows.append(
            dict(  # noqa: C408
                old=d.name, new="", kind=d.kind, definition=d.definition, scope=scope,
                method=method, reason=reason, verified="",
            )
        )  # fmt: skip
    # Módulos con nombre en español (el fichero en sí).
    for rel in project.modules.values():
        stem = rel.rsplit("/", 1)[1][:-3]
        if stem == "__init__" or (paths and not any(fnmatch(rel, pat) for pat in paths)):
            continue
        if detector.is_spanish(stem, lexicon):
            scope = "cross_module" if project.imported_modules.get(rel) else "module_local"
            rows.append(
                dict(  # noqa: C408
                    old=stem, new="", kind="module", definition=f"{rel}:1@<module>",
                    scope=scope, method="pycharm", reason="", verified="",
                )
            )  # fmt: skip
    rows.sort(key=lambda r: (r["definition"].split(":")[0], _line(r["definition"]), r["old"]))
    return rows


def _line(definition: str) -> int:
    return int(definition.split(":", 1)[1].split("@", 1)[0])


def write_mapping(rows: list[dict[str, str]], out: Path, wave: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        fh.write(
            f"# wave={wave} generated={datetime.now(UTC).date().isoformat()} by tools/make_mapping.py; "
            "pendiente de aprobación (la sesión principal añade «# approved-by-main: <fecha>»)\n"
        )
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_mapping(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = path.read_text(encoding="utf-8")
    comments = [line for line in text.splitlines() if line.startswith("#")]
    body = [line for line in text.splitlines() if not line.startswith("#")]
    return comments, list(csv.DictReader(body))


# --- Aplicador acotado --------------------------------------------------------
def _child_statements(node: ast.AST) -> list[ast.stmt]:
    """Las sentencias de los bloques de una sentencia compuesta (`if`, `try`, `with`, `match`…)."""
    out: list[ast.stmt] = []
    for block in ("body", "orelse", "finalbody", "handlers", "cases"):
        for child in getattr(node, block, None) or []:
            if isinstance(child, (ast.ExceptHandler, ast.match_case)):
                out.extend(child.body)
            elif isinstance(child, ast.stmt):
                out.append(child)
    return out


def _find_function(tree: ast.AST, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    parts = qualname.split(".")

    def walk(nodes, depth):
        for node in nodes:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == parts[depth]
            ):
                if depth == len(parts) - 1:
                    return node if not isinstance(node, ast.ClassDef) else None
                found = walk(node.body, depth + 1)
                if found is not None:
                    return found
            elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Una anidada puede vivir dentro de un `if`, `for`, `while`, `try` o `with` de su
                # función (`local_commit_msg._build_map`, A7b): se baja por esos bloques sin
                # sumar un nivel al nombre cualificado.
                found = walk(_child_statements(node), depth)
                if found is not None:
                    return found
        return None

    return walk(getattr(tree, "body", []), 0)


def _char_col(line_text: str, byte_col: int) -> int:
    return len(line_text.encode("utf-8")[:byte_col].decode("utf-8"))


def _local_edits(tree, lines, row) -> list[tuple[int, int, str, str]]:
    """(línea, columna, viejo, nuevo) de cada aparición de la variable dentro de SU función."""
    definition = row["definition"]
    qualname = definition.split("@", 1)[1]
    func = _find_function(tree, qualname)
    if func is None:
        raise ValueError(f"no se encontró la función {qualname} ({definition})")
    old, new = row["old"], row["new"]
    edits = []
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Name)
            and node.id == old
            or isinstance(node, ast.arg)
            and node.arg == old
        ):
            edits.append((node.lineno, node.col_offset))
    return [(ln, _char_col(lines[ln - 1], col), old, new) for ln, col in sorted(set(edits))]


def _test_def_edit(lines, row) -> list[tuple[int, int, str, str]]:
    line_no = _line(row["definition"])
    text = lines[line_no - 1]
    marker = f"def {row['old']}("
    col = text.find(marker)
    if col == -1:
        raise ValueError(f"no está `{marker}` en {row['definition']}")
    return [(line_no, col + 4, row["old"], row["new"])]


def apply_mapping(mapping: Path, root: Path, dry_run: bool = False) -> dict[str, int]:
    comments, rows = read_mapping(mapping)
    if not any(c.startswith(APPROVAL_PREFIX) for c in comments):
        raise SystemExit(f"{mapping} no está aprobado (falta «{APPROVAL_PREFIX}: <fecha>»)")
    todo = [
        r
        for r in rows
        if r["method"] == "search_edit" and r["scope"] in SEARCH_EDIT_SCOPES and r["new"].strip()
    ]
    by_file: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in todo:
        by_file[r["definition"].split(":", 1)[0]].append(r)
    counts: dict[str, int] = {}
    for rel, file_rows in by_file.items():
        path = root / rel
        with path.open(encoding="utf-8", newline="") as fh:
            source = fh.read()
        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
        edits = []
        for r in file_rows:
            edits += (
                _local_edits(tree, lines, r)
                if r["scope"] == "function_local"
                else (_test_def_edit(lines, r))
            )
        # De atrás adelante para que las columnas de una línea no se desplacen.
        # Sin repetidas: la fila de una función recorre también sus anidadas (A7a, `cadena`).
        edits = sorted(set(edits), reverse=True)
        for ln, col, old, new in edits:
            text = lines[ln - 1]
            if text[col : col + len(old)] != old:
                raise ValueError(f"{rel}:{ln}:{col} no contiene `{old}`")
            lines[ln - 1] = text[:col] + new + text[col + len(old) :]
        counts[rel] = len(edits)
        if not dry_run:
            with path.open("w", encoding="utf-8", newline="") as fh:
                fh.write("".join(lines))
    return counts


# --- CLI ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="genera el mapping de una ola")
    b.add_argument("--wave", required=True)
    b.add_argument("--paths", nargs="*", default=[], help="globs de los ficheros de la ola")
    b.add_argument("--out", type=Path, help="por defecto, waves/<ola>-mapping.csv")
    a = sub.add_parser("apply", help="aplica las filas search_edit acotadas de un mapping aprobado")
    a.add_argument("--mapping", type=Path, required=True)
    a.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "build":
        rows = build_rows(args.root, args.paths)
        out = args.out or Path(__file__).resolve().parents[1] / "waves" / f"{args.wave}-mapping.csv"
        write_mapping(rows, out, args.wave)
        by_scope: dict[str, int] = defaultdict(int)
        for r in rows:
            by_scope[r["scope"]] += 1
        print(
            f"{len(rows)} filas en {out}: "
            + ", ".join(f"{k}={v}" for k, v in sorted(by_scope.items()))
        )
        return 0
    counts = apply_mapping(args.mapping, args.root, args.dry_run)
    for rel, n in counts.items():
        print(f"{rel}: {n} reemplazo(s){' (ensayo)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
