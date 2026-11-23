"""Measure that a cost grows linearly with the input (REQ-022 of `extract-locate-by-program`).

An absolute ceiling in seconds measures the runner: the same code took 0.5 s of CPU on the dev PC
and 1.7 s on a CI runner. The ratio between the CPU time of a large input and that of one ten times
smaller does not depend on the runner: about 10 when the cost is linear, about 100 when it is
quadratic.

How the ratio is taken, after the CI of #723 gave 27 to 40 for costs that measure 10 to 12 on the
dev PC (Windows and Ubuntu runners, with the other pytest workers on the same cores):

- each round measures the small input and then the large one, so both sides see the same load,
  and the round with the lowest ratio wins: load inflates one round, never all, and a quadratic
  cost gives about 100 in every round;
- each side repeats its input until it has spent `MIN_ROUND_SECONDS` of CPU, so that the coarse
  clock of Windows (15.6 ms) does not decide the ratio: with a fixed 10 repeats the small side
  measured 3 ticks and one tick of error was a third of it.
"""

from __future__ import annotations

import time
from collections.abc import Callable

SIZE_RATIO = 10
# linear gives ~10 (a bit more for the caches of a larger input); quadratic gives ~100. The
# ceiling is their geometric mean, so a loaded runner has the same margin as a quadratic regression.
MAX_GROWTH = 33.0
# at least ~13 ticks of the Windows clock per round, so one tick is under 8 % of the measure
MIN_ROUND_SECONDS = 0.2


def _cpu_per_run(run: Callable[[], object]) -> float:
    count = 0
    started = time.process_time()
    while True:
        run()
        count += 1
        elapsed = time.process_time() - started
        if elapsed >= MIN_ROUND_SECONDS:
            return elapsed / count


def cpu_growth(
    run_small: Callable[[], object],
    run_big: Callable[[], object],
    *,
    rounds: int = 5,
) -> tuple[float, float, float]:
    """(CPU of one small run, CPU of one big run, big / small) of the round with the lowest ratio."""
    run_small()  # warm up: imports and compiled regexes do not count on either side
    measured = []
    for _ in range(rounds):
        small = _cpu_per_run(run_small)
        big = _cpu_per_run(run_big)
        measured.append((small, big, big / small))
    return min(measured, key=lambda m: m[2])
