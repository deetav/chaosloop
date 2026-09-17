"""Measured corpus metadata is an empirical proxy"""

import pytest

from benchmarks.bugs import BUGS
from benchmarks.measure_depth import measure_depth
from chaosloop import ShrinkBudget


@pytest.mark.slow
@pytest.mark.parametrize("bug", BUGS, ids=lambda b: b.BUG_ID)
def test_declared_depth_matches_measurement(bug):
    assert measure_depth(bug, seeds=range(200)).empirical == bug.DEPTH


def test_distribution_counts_unique_failing_seeds_and_executed_steps():
    result = measure_depth(BUGS[2], seeds=[0, 0, 1])
    assert result.samples == 2 and result.distribution == {0: 2}
    assert result.empirical == 0 and result.min_steps > 0


def test_budget_template_is_not_consumed():
    budget = ShrinkBudget(20, 10)
    result = measure_depth(BUGS[2], seeds=[0, 1], shrink_budget=budget)
    assert result.samples == 2 and budget.replays_used == 0


def test_unverified_results_are_not_evidence():
    result = measure_depth(BUGS[2], seeds=[0], shrink_budget=ShrinkBudget(0, 0))
    assert result.empirical is None and result.samples == 0 and result.unverified > 0
