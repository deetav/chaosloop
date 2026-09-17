from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace

import pytest

from chaosloop.schedulers import Candidate, Fifo, Pct, Random, Replay, Scheduler, StepEvent


def fake_candidate(index: int) -> Candidate:
    return Candidate(index * 2 + 2, f"task-{index}", "task_step", "resume", "demo.py:10")

def assert_scheduler_contract(make_scheduler: Callable[[], Scheduler]) -> None:
    """Exercise determinism, bounds, immutability, feedback, and replay history."""
    original = tuple(fake_candidate(index) for index in range(3))
    a, b = make_scheduler(), make_scheduler()
    picks: list[int] = []
    for step in range(50):
        candidates = original[: step % 3 + 1]
        selected = a.choose(candidates)
        assert type(selected) is int
        assert 0 <= selected < len(candidates)
        assert selected == b.choose(candidates)
        picks.append(selected)
        event = StepEvent(step, step / 10, selected, candidates[selected].task_id, len(candidates))
        a.observe(event)
        b.observe(event)
        assert candidates == original[: len(candidates)]
    assert a.decisions == picks
    a.decisions.clear()
    assert a.decisions == picks
    assert make_scheduler().choose((fake_candidate(0),)) == 0


FACTORIES: list[Callable[[], Scheduler]] = [
    Fifo,
    lambda: Pct(42, steps=50),
    lambda: Random(42),
    lambda: Replay([0, 1, 0, 2, 1]),
    lambda: Replay([0] * 50, strict=True),
]


@pytest.mark.parametrize(
    "make", FACTORIES, ids=["fifo", "pct", "random", "replay", "strict-replay"]
)
def test_scheduler_contract(make: Callable[[], Scheduler]) -> None:
    assert_scheduler_contract(make)


@pytest.mark.parametrize(
    "make", FACTORIES, ids=["fifo", "pct", "random", "replay", "strict-replay"]
)
def test_strategies_satisfy_runtime_protocol(make: Callable[[], Scheduler]) -> None:
    assert isinstance(make(), Scheduler)


@pytest.mark.parametrize(
    "make", FACTORIES, ids=["fifo", "pct", "random", "replay", "strict-replay"]
)
def test_empty_input_does_not_record_a_decision(make: Callable[[], Scheduler]) -> None:
    scheduler = make()
    with pytest.raises(ValueError, match="empty"):
        scheduler.choose(())
    assert scheduler.decisions == []


@pytest.mark.parametrize(
    "make", FACTORIES, ids=["fifo", "pct", "random", "replay", "strict-replay"]
)
def test_display_metadata_cannot_change_choices(make: Callable[[], Scheduler]) -> None:
    candidates = tuple(fake_candidate(index) for index in range(3))
    renamed = tuple(
        replace(item, label="different 0x1234", location="other.py:999") for item in candidates
    )
    a, b = make(), make()
    assert [a.choose(candidates) for _ in range(25)] == [b.choose(renamed) for _ in range(25)]


def test_candidate_is_frozen() -> None:
    candidate = fake_candidate(0)
    with pytest.raises(FrozenInstanceError):
        candidate.index = 8


def test_step_event_is_frozen() -> None:
    event = StepEvent(1, 0.0, 0, "task-1", 1)
    with pytest.raises(FrozenInstanceError):
        event.chosen = 1
