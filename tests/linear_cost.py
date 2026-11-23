"""Measure that a cost grows linearly with the input (REQ-022 of `extract-locate-by-program`).

An absolute ceiling in seconds measures the runner: the same code took 0.5 s of CPU on the dev PC
and 1.7 s on a CI runner. The ratio between the CPU time of a large input and that of one ten times
smaller does not depend on the runner: about 10 when the cost is linear, about 100 when it is
quadratic. Each side is the best of several rounds, because another process on the same core
inflates one round, never all. Each round repeats its input until it has spent at least
`MIN_ROUND_SECONDS` of CPU, so that the coarse clock of Windows (15.6 ms) does not decide the ratio:
with a fixed 10 repeats the small side of #723 measured 3 ticks, one tick of error was a third of
it, and a linear cost came out as 30.
"""

from __future__ import annotations

import time
from collections.abc import Callable

SIZE_RATIO = 10
# linear gives ~10 (a bit more for the caches of a larger input); quadratic gives ~100
MAX_GROWTH = 25.0
# at least ~13 ticks of the Windows clock per round, so one tick is under 8 % of the measure
MIN_ROUND_SECONDS = 0.2


def _best_cpu(run: Callable[[], object], rounds: int) -> float:
    best = float("inf")
    for _ in range(rounds):
        count = 0
        started = time.process_time()
        while True:
            run()
            count += 1
            elapsed = time.process_time() - started
            if elapsed >= MIN_ROUND_SECONDS:
                break
        best = min(best, elapsed / count)
    return best


def cpu_growth(
    run_small: Callable[[], object],
    run_big: Callable[[], object],
    *,
    rounds: int = 3,
) -> tuple[float, float, float]:
    """(CPU of one small run, CPU of one big run, big / small), each the best of `rounds`."""
    run_small()  # warm up: imports and compiled regexes do not count on either side
    small = _best_cpu(run_small, rounds)
    big = _best_cpu(run_big, rounds)
    return small, big, big / small
