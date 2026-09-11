import math

import pytest

from chaosloop.clock import VirtualClock
from chaosloop.exceptions import TimeBudgetExceeded


def test_starts_at_zero() -> None:
    assert VirtualClock().now == 0.0

def test_advances_without_wallclock_wait() -> None:
    clock = VirtualClock()
    clock.advance_to(1000000)
    assert clock.now == 1000000

@pytest.mark.parametrize("deadline", [-10.0, 0.0, 2.0, 3.0])
def test_already_due_deadline_do_not_reverse_time(deadline: float) -> None:
    clock = VirtualClock(now=3.0)
    clock.advance_to(deadline)
    assert clock.now == 3.0

@pytest.mark.parametrize("invalid", [-1.0, float("nan"), float("inf"), float("-inf")])
def test_invalid_duration_leaves_clock_unchanged(invalid: float) -> None:
    clock = VirtualClock(now=2.0)
    with pytest.raises(ValueError, match="invalid duration"):
        clock.advance_by(invalid)
    assert clock.now == 2.0


@pytest.mark.parametrize("duration", [0.0, -0.0, 0.5, 15.0])
def test_advance_by_adds_duration(duration: float) -> None:
    clock = VirtualClock(now=2.0)
    clock.advance_by(duration)
    assert clock.now == 2.0 + duration


def test_budget_allows_exact_boundary() -> None:
    clock = VirtualClock(max_time=3.0)
    clock.advance_to(3.0)
    clock.advance_by(0.0)
    assert clock.now == 3.0


def test_budget_failure_does_not_commit_new_time() -> None:
    clock = VirtualClock(now=1.0, max_time=3.0)
    with pytest.raises(TimeBudgetExceeded, match="exceeds"):
        clock.advance_to(4.0)
    assert clock.now == 1.0
    clock.advance_to(2.0)
    assert clock.now == 2.0


def test_relative_advance_checks_absolute_budget() -> None:
    clock = VirtualClock(now=2.0, max_time=3.0)
    with pytest.raises(TimeBudgetExceeded):
        clock.advance_by(2.0)
    assert clock.now == 2.0


def test_zero_budget_permits_only_time_zero() -> None:
    clock = VirtualClock(max_time=0.0)
    clock.advance_to(-1.0)
    clock.advance_by(0.0)
    with pytest.raises(TimeBudgetExceeded):
        clock.advance_to(0.001)


@pytest.mark.parametrize("invalid", [-1.0, float("nan"), float("inf"), float("-inf")])
def test_invalid_initial_time_is_rejected(invalid: float) -> None:
    with pytest.raises(ValueError, match="now"):
        VirtualClock(now=invalid)


@pytest.mark.parametrize("invalid", [-1.0, float("nan"), float("inf"), float("-inf")])
def test_invalid_budget_is_rejected(invalid: float) -> None:
    with pytest.raises(ValueError, match="max_time"):
        VirtualClock(max_time=invalid)


def test_initial_time_cannot_exceed_budget() -> None:
    with pytest.raises(TimeBudgetExceeded):
        VirtualClock(now=4.0, max_time=3.0)


def test_initial_time_can_equal_budget() -> None:
    assert VirtualClock(now=3.0, max_time=3.0).now == 3.0


def test_finite_addition_overflow_is_rejected() -> None:
    clock = VirtualClock(now=1e308)
    with pytest.raises(ValueError, match="invalid time"):
        clock.advance_by(1e308)
    assert clock.now == 1e308


def test_large_timestamps_preserve_representable_progress() -> None:
    clock = VirtualClock(now=1e16)
    next_time = math.nextafter(clock.now, math.inf)
    clock.advance_to(next_time)
    assert clock.now == next_time


def test_sub_resolution_duration_cannot_move_backwards() -> None:
    clock = VirtualClock(now=1e16)
    clock.advance_by(0.1)
    assert clock.now == 1e16


def test_independent_clock_instances_share_no_state() -> None:
    first, second = VirtualClock(), VirtualClock()
    first.advance_by(5.0)
    assert second.now == 0.0
