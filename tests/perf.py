"""The one way to measure cost in a test (SDD ci-root-cause, REQ-004).

A ceiling in seconds measures the runner, not the code: the same call took 0.5 s of CPU on the dev
PC and 1.7 s on a CI runner, and on Windows `time.process_time` advances in steps of 15.6 ms, so the
ratio between two small measures jumped from 10 to 40 with nothing changed (CI of #723). Between
2026-11-03 and 2026-11-23 about 28 red runs came from such ceilings.

So a cost test compares the same work on two sizes: a linear cost grows like the size ratio, a
quadratic one like its square. The ceiling is their geometric mean (`size_ratio ** 1.5`), so a
noisy runner has the same margin as a quadratic regression.

How each side is measured:

- `time.perf_counter_ns`, never `process_time`: its resolution is fine on every system, and the
  `perf` tests run alone (`ci.yml`, job `perf`, without `-n`), so wall time is CPU time;
- each side repeats its call until it has spent `MIN_ROUND_NS` (50 ms), so that no clock tick decides
  the ratio;
- each round measures the small side and then the big one, so both see the same load, and the
  first round under the ceiling wins: load inflates one round, a quadratic cost inflates them all.

Every test that uses this module carries `@pytest.mark.perf`; `tests/test_timing_marker_guard.py`
fails otherwise.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable
from typing import NamedTuple

#: Minimum time measured per side and round: about 3 200 ticks of the coarsest clock.
MIN_ROUND_NS = 50_000_000
ROUNDS = 5


class Growth(NamedTuple):
    small_ns: float
    big_ns: float
    ratio: float


def max_growth(size_ratio: float) -> float:
    """Geometric mean of the linear (`size_ratio`) and the quadratic (`size_ratio ** 2`) growth."""
    return size_ratio**1.5


def ns_per_run(run: Callable[[], object]) -> float:
    """Nanoseconds of one call of `run`, repeated until `MIN_ROUND_NS` have passed.

    With the garbage collector off: its pauses grow with the objects alive, and made a linear run
    look quadratic on the Ubuntu runner (`test_codex_guard_shell_writes`, #724).
    """
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        count = 0
        started = time.perf_counter_ns()
        while True:
            run()
            count += 1
            elapsed = time.perf_counter_ns() - started
            if elapsed >= MIN_ROUND_NS:
                return elapsed / count
    finally:
        if enabled:
            gc.enable()


def growth(
    run_small: Callable[[], object],
    run_big: Callable[[], object],
    *,
    ceiling: float = float("inf"),
    rounds: int = ROUNDS,
) -> Growth:
    """The first round whose ratio is under `ceiling`, or the lowest of `rounds` rounds."""
    run_small()  # warm up: imports and compiled patterns count on neither side
    best: Growth | None = None
    for _ in range(rounds):
        small = ns_per_run(run_small)
        big = ns_per_run(run_big)
        measured = Growth(small, big, big / small)
        if best is None or measured.ratio < best.ratio:
            best = measured
        if measured.ratio < ceiling:
            break
    assert best is not None
    return best


def assert_linear(
    run_small: Callable[[], object],
    run_big: Callable[[], object],
    *,
    size_ratio: float,
    label: str = "",
) -> Growth:
    """Fails when the big input costs more than `max_growth(size_ratio)` times the small one."""
    ceiling = max_growth(size_ratio)
    measured = growth(run_small, run_big, ceiling=ceiling)
    assert measured.ratio < ceiling, (
        f"{label + ': ' if label else ''}{size_ratio:g}x the input cost {measured.ratio:.1f}x "
        f"(ceiling {ceiling:.1f}x; small {measured.small_ns / 1e6:.2f} ms, "
        f"big {measured.big_ns / 1e6:.2f} ms)"
    )
    return measured
