"""No test puts a ceiling on a clock unless it is marked `perf` or `real_io` (SDD ci-root-cause).

Between 2026-11-03 and 2026-11-23 about 28 red runs came from tests that compared a clock reading
with a fixed number of seconds while `-n auto` made the workers fight for the cores, and from
`time.process_time`, which on Windows advances in steps of 15.6 ms. The rule now:

- a cost (how a computation grows) is measured with `tests/perf.py` and marked `perf`: it runs
  alone, in the `perf` job of `ci.yml`;
- a wait for a real process, socket or clock with a ceiling is marked `real_io`: it still runs on
  the three systems, but in its own step, without `-n` and with one retry;
- `process_time` does not appear in `tests/` at all.

`tests/timing_scan.py` says which tests cap a clock; this module fails on any of them without one
of the two markers, and proves with synthetic sources that the scan can see what it is meant to.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest
from timing_scan import TIMING_MARKERS, timed_tests

TESTS = Path(__file__).parent
#: Files allowed to name `process_time`: this guard, which forbids it, and the scan, which looks
#: for it.
_PROCESS_TIME_ALLOWED = {"test_timing_marker_guard.py", "timing_scan.py", "perf.py"}


def _scan(source: str) -> dict[str, frozenset[str]]:
    return {t.name: t.markers for t in timed_tests(textwrap.dedent(source))}


# --- The scan sees what it must (positive controls) and nothing else ------------------------


def test_a_direct_ceiling_on_perf_counter_is_seen():
    found = _scan(
        """
        import time

        def test_fast():
            start = time.perf_counter()
            work()
            assert time.perf_counter() - start < 1.0
        """
    )
    assert found == {"test_fast": frozenset()}


@pytest.mark.parametrize("clock", ["time", "process_time", "monotonic", "perf_counter_ns"])
def test_every_clock_is_seen_through_a_local_name(clock):
    found = _scan(
        f"""
        import time

        def test_fast():
            started = time.{clock}()
            work()
            elapsed = time.{clock}() - started
            assert elapsed < 2
        """
    )
    assert "test_fast" in found


def test_a_clock_imported_by_name_is_seen():
    found = _scan(
        """
        from time import perf_counter as pc

        def test_fast():
            t0 = pc()
            assert pc() - t0 <= 1
        """
    )
    assert "test_fast" in found


def test_a_helper_that_returns_the_elapsed_time_is_followed():
    found = _scan(
        """
        import time

        def _timed(func):
            start = time.perf_counter()
            result = func()
            return result, time.perf_counter() - start

        def test_fast():
            result, elapsed = _timed(work)
            assert elapsed < 1.0
        """
    )
    assert "test_fast" in found


def test_a_helper_that_asserts_the_ceiling_is_followed():
    found = _scan(
        """
        import time

        def _check(func):
            start = time.monotonic()
            func()
            assert time.monotonic() - start < 5

        def test_fast():
            _check(work)
        """
    )
    assert "test_fast" in found


def test_the_perf_helper_counts_as_a_clock():
    found = _scan(
        """
        from perf import assert_linear

        def test_linear():
            assert_linear(small, big, size_ratio=10)
        """
    )
    assert "test_linear" in found


def test_the_markers_are_read_from_the_function_the_class_and_the_module():
    found = _scan(
        """
        import time
        import pytest

        pytestmark = [pytest.mark.real_io]

        @pytest.mark.perf
        def test_a():
            s = time.perf_counter()
            assert time.perf_counter() - s < 1

        class TestB:
            def test_b(self):
                s = time.perf_counter()
                assert time.perf_counter() - s < 1
        """
    )
    assert found == {"test_a": {"perf", "real_io"}, "test_b": {"real_io"}}


def test_a_clock_used_only_as_the_deadline_of_a_wait_is_not_a_ceiling():
    found = _scan(
        """
        import time

        def test_waits():
            deadline = time.monotonic() + 5
            while not ready() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert ready()
        """
    )
    assert found == {}


def test_an_ordering_assert_on_something_else_is_not_a_ceiling():
    found = _scan(
        """
        import time

        def test_counts():
            stamp = time.time()
            rows = load()
            assert len(rows) > 2
            assert stamp
        """
    )
    assert found == {}


# --- The guard over the real tests ---------------------------------------------------------


def _test_files() -> list[Path]:
    return sorted(TESTS.glob("test_*.py"))


def test_every_test_that_caps_a_clock_is_marked_perf_or_real_io():
    unmarked = []
    for path in _test_files():
        for found in timed_tests(path.read_text(encoding="utf-8")):
            if not found.markers & TIMING_MARKERS:
                unmarked.append(f"{path.name}:{found.line} {found.name}")
    assert not unmarked, (
        "Tests that compare a clock with a ceiling and run in the parallel step of the gate. "
        "A cost goes through `tests/perf.py` with `@pytest.mark.perf`; a wait for a real "
        "process, socket or clock takes `@pytest.mark.real_io`:\n  " + "\n  ".join(unmarked)
    )


def test_the_scan_reaches_the_real_tests():
    """Guard of the guard: if the scan saw nothing in `tests/`, the test above would be green on
    zero checks. Dozens of real tests cap a clock, every one of them now marked."""
    found = [t for path in _test_files() for t in timed_tests(path.read_text(encoding="utf-8"))]
    assert len(found) > 50
    assert sum("perf" in t.markers for t in found) > 20
    assert sum("real_io" in t.markers for t in found) > 20


def test_no_process_time_in_the_tests():
    """`process_time` advances in steps of 15.6 ms on Windows; `tests/perf.py` uses
    `perf_counter_ns`. Textual on purpose: it also sees code inside strings run in a child."""
    offenders = [
        path.name
        for path in sorted(TESTS.rglob("*.py"))
        if path.name not in _PROCESS_TIME_ALLOWED
        and "process_time" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"`process_time` in: {', '.join(offenders)}"


def test_the_perf_marker_is_only_where_the_helper_measures():
    """A `perf` test measures with `tests/perf.py`: a `perf` mark on a test that times itself by
    hand would dodge the helper and its rule."""
    hand_timed = []
    for path in _test_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        uses_helper = any(
            (isinstance(node, ast.ImportFrom) and node.module == "perf")
            or (isinstance(node, ast.Import) and any(a.name == "perf" for a in node.names))
            for node in ast.walk(tree)
        )
        for found in timed_tests(source):
            if "perf" in found.markers and not uses_helper:
                hand_timed.append(f"{path.name}:{found.line} {found.name}")
    assert not hand_timed, "`perf` tests that do not use `tests/perf.py`:\n  " + "\n  ".join(
        hand_timed
    )
