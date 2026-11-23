"""Measure that a cost grows linearly with the input (REQ-022 of `extract-locate-by-program`).

An absolute ceiling in seconds measures the runner: the same code took 0.5 s of CPU on the dev PC
and 1.7 s on a CI runner. The ratio between the CPU time of a large input and that of one ten times
smaller does not depend on the runner: about 10 when the cost is linear, about 100 when it is
quadratic. Each side is the best of several rounds, because another process on the same core
inflates one round, never all; the small side runs several times per round so that the coarse
clock of Windows (15.6 ms) does not decide the ratio.
"""

from __future__ import annotations

import time
from collections.abc import Callable

SIZE_RATIO = 10
# linear gives ~10 (a bit more for the caches of a larger input); quadratic gives ~100
MAX_GROWTH = 25.0


def _best_cpu(run: Callable[[], object], repeats: int, rounds: int) -> float:
    best = float("inf")
    for _ in range(rounds):
        started = time.process_time()
        for _ in range(repeats):
            run()
        best = min(best, (time.process_time() - started) / repeats)
    return best


def cpu_growth(
    run_small: Callable[[], object],
    run_big: Callable[[], object],
    *,
    rounds: int = 3,
    small_repeats: int = 10,
) -> tuple[float, float, float]:
    """(CPU of one small run, CPU of one big run, big / small), each the best of `rounds`."""
    run_small()  # warm up: imports and compiled regexes do not count on either side
    small = _best_cpu(run_small, small_repeats, rounds)
    big = _best_cpu(run_big, 1, rounds)
    return small, big, big / small
