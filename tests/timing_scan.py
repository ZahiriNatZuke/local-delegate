"""Find the tests that put a ceiling on a clock reading (SDD ci-root-cause, REQ-005).

Used by `tests/test_timing_marker_guard.py`. A test "caps time" when one of its `assert`s compares
with `<`, `<=`, `>` or `>=` a value that comes from a clock: a direct call to `time.time`,
`time.perf_counter`, `time.process_time` or `time.monotonic` (and their `_ns` forms, also when
imported by name), a local name assigned from one of those, or the result of a function of the same
module that returns such a value. The helpers of `tests/perf.py` count as a clock too: a test that
measures growth is a `perf` test by definition.

A clock used only as a deadline of a wait (`while time.monotonic() < deadline:`) is not a cap: the
loop ends either way, and the assertion that follows says what was waited for, not how long it took.

The analysis is per module and on purpose shallow: it follows names inside a function and calls to
functions of the same module, not attributes, fixtures or other modules. What it misses is covered
by the second rule of the guard, which is textual: no `process_time` anywhere in `tests/`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

CLOCK_FUNCTIONS = frozenset(
    {
        "time",
        "time_ns",
        "perf_counter",
        "perf_counter_ns",
        "process_time",
        "process_time_ns",
        "monotonic",
        "monotonic_ns",
    }
)
#: The measuring helpers of `tests/perf.py`, by name.
PERF_HELPERS = frozenset({"growth", "assert_linear", "ns_per_run", "max_growth"})
#: The markers that put a timed test outside the parallel run of the gate.
TIMING_MARKERS = frozenset({"perf", "real_io"})
_ORDERING = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


@dataclass(frozen=True)
class TimedTest:
    name: str
    line: int
    markers: frozenset[str]


class _Module:
    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.clock_names: set[str] = set()  # `from time import perf_counter [as pc]`
        self.time_modules: set[str] = set()  # `import time [as t]`
        self.perf_modules: set[str] = set()  # `import perf`
        self.perf_names: set[str] = set()  # `from perf import growth`
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "time":
                        self.time_modules.add(alias.asname or "time")
                    if alias.name == "perf":
                        self.perf_modules.add(alias.asname or "perf")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if node.module == "time" and alias.name in CLOCK_FUNCTIONS:
                        self.clock_names.add(alias.asname or alias.name)
                    if node.module == "perf" and alias.name in PERF_HELPERS:
                        self.perf_names.add(alias.asname or alias.name)
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        self.returns_time: set[str] = set()
        self.caps: set[str] = set()
        self._solve()

    # -- what is a clock reading -------------------------------------------------------------

    def is_clock_call(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in self.time_modules and func.attr in CLOCK_FUNCTIONS:
                return True
            if func.value.id in self.perf_modules and func.attr in PERF_HELPERS:
                return True
        if isinstance(func, ast.Name):
            if func.id in self.clock_names or func.id in self.perf_names:
                return True
            if func.id in self.returns_time:
                return True
        return False

    def _timed_expr(self, node: ast.AST, tainted: set[str]) -> bool:
        for sub in ast.walk(node):
            if self.is_clock_call(sub):
                return True
            if isinstance(sub, ast.Name) and sub.id in tainted:
                return True
        return False

    def _tainted_names(self, func: ast.AST) -> set[str]:
        tainted: set[str] = set()
        while True:
            before = len(tainted)
            for node in ast.walk(func):
                if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
                    value = node.value
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if value is not None and self._timed_expr(value, tainted):
                        for target in targets:
                            for sub in ast.walk(target):
                                if isinstance(sub, ast.Name):
                                    tainted.add(sub.id)
                elif isinstance(node, ast.NamedExpr) and self._timed_expr(node.value, tainted):
                    tainted.add(node.target.id)
            if len(tainted) == before:
                return tainted

    def _calls(self, func: ast.AST) -> set[str]:
        return {
            node.func.id
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in self.functions
        }

    def _solve(self) -> None:
        while True:
            before = (len(self.returns_time), len(self.caps))
            for name, func in self.functions.items():
                tainted = self._tainted_names(func)
                for node in ast.walk(func):
                    if (
                        isinstance(node, ast.Return)
                        and node.value is not None
                        and self._timed_expr(node.value, tainted)
                    ):
                        self.returns_time.add(name)
                    if isinstance(node, ast.Assert) and self._ordering_on_time(node.test, tainted):
                        self.caps.add(name)
                if self._uses_perf_helper(func):
                    self.caps.add(name)
                if self._calls(func) & self.caps:
                    self.caps.add(name)
            if (len(self.returns_time), len(self.caps)) == before:
                return

    def _uses_perf_helper(self, func: ast.AST) -> bool:
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if isinstance(target, ast.Name) and target.id in self.perf_names:
                return True
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in self.perf_modules
                and target.attr in PERF_HELPERS
            ):
                return True
        return False

    def _ordering_on_time(self, test: ast.AST, tainted: set[str]) -> bool:
        for node in ast.walk(test):
            if (
                isinstance(node, ast.Compare)
                and any(isinstance(op, _ORDERING) for op in node.ops)
                and self._timed_expr(node, tainted)
            ):
                return True
        return False


def _marker_names(decorators: list[ast.expr]) -> set[str]:
    names = set()
    for decorator in decorators:
        node = decorator.func if isinstance(decorator, ast.Call) else decorator
        # pytest.mark.<name>
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "mark"
        ):
            names.add(node.attr)
    return names


def _module_markers(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            values = (
                node.value.elts if isinstance(node.value, ast.List | ast.Tuple) else [node.value]
            )
            names |= _marker_names(list(values))
    return names


def timed_tests(source: str) -> list[TimedTest]:
    """The tests of a module that cap a clock reading, with the markers they carry."""
    tree = ast.parse(source)
    module = _Module(tree)
    module_markers = _module_markers(tree)
    found: list[TimedTest] = []

    def visit(body: list[ast.stmt], inherited: set[str]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                visit(node.body, inherited | _marker_names(node.decorator_list))
            elif (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name.startswith("test")
                and node.name in module.caps
            ):
                markers = inherited | _marker_names(node.decorator_list)
                found.append(TimedTest(node.name, node.lineno, frozenset(markers)))

    visit(tree.body, module_markers)
    return found
