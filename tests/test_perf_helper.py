"""The cost helper of `tests/perf.py` tells linear from quadratic (SDD ci-root-cause, REQ-003).

The controls are simulated costs whose growth is known: a single loop and a nested one. If the
helper could not fail the quadratic one, every `perf` test that relies on it would be decoration.
"""

from __future__ import annotations

import perf
import pytest

pytestmark = pytest.mark.perf


def _linear(n: int) -> int:
    total = 0
    for i in range(n):
        total += i
    return total


def _quadratic(n: int) -> int:
    total = 0
    for i in range(n):
        for j in range(n):
            total += i ^ j
    return total


def test_each_side_is_measured_for_at_least_the_minimum_round():
    calls = []
    per_run = perf.ns_per_run(lambda: calls.append(_linear(1_000)))
    assert len(calls) * per_run >= perf.MIN_ROUND_NS
    assert per_run > 0


def test_the_ceiling_is_the_geometric_mean_of_linear_and_quadratic():
    assert perf.max_growth(10) == pytest.approx(10**1.5)
    assert 10 < perf.max_growth(10) < 100
    assert 4 < perf.max_growth(4) < 16


def test_a_linear_cost_passes():
    measured = perf.assert_linear(
        lambda: _linear(20_000), lambda: _linear(200_000), size_ratio=10, label="linear"
    )
    assert measured.ratio < perf.max_growth(10)


def test_control_a_quadratic_cost_fails():
    with pytest.raises(AssertionError, match="quadratic: 10x the input cost"):
        perf.assert_linear(
            lambda: _quadratic(30), lambda: _quadratic(300), size_ratio=10, label="quadratic"
        )


def test_the_first_round_under_the_ceiling_ends_the_measure(monkeypatch):
    """A noisy first round does not decide: the helper measures again, and stops at a good one."""
    sides = iter([1.0, 50.0, 1.0, 9.0, 1.0, 9.0])
    rounds = []

    def fake(_run):
        value = next(sides)
        rounds.append(value)
        return value

    monkeypatch.setattr(perf, "ns_per_run", fake)
    measured = perf.growth(lambda: None, lambda: None, ceiling=31.6)
    assert measured.ratio == 9.0
    assert rounds == [1.0, 50.0, 1.0, 9.0], "it must stop at the first good round"
