import random
from dataclasses import replace

import pytest

import chaosloop as c
from tests.scenarios import clean


def candidates(count=3):
    return tuple(
        c.Candidate(2 * i + 3, f"t{i}", "task_step", "display", None) for i in range(count)
    )


@pytest.mark.parametrize("seed", [0, 1, -1, 42, 2**100])
def test_same_seed_same_history(seed):
    a, b = c.Pct(seed, steps=30), c.Pct(seed, steps=30)
    assert [a.choose(candidates()) for _ in range(50)] == [
        b.choose(candidates()) for _ in range(50)
    ]


def test_different_seeds_explore_different_histories():
    histories = set()
    for seed in range(20):
        scheduler = c.Pct(seed, steps=30)
        histories.add(tuple(scheduler.choose(candidates()) for _ in range(30)))
    assert len(histories) > 10


def test_depth_one_keeps_highest_runnable_priority():
    scheduler = c.Pct(3, depth=1)
    choices = [scheduler.choose(candidates()) for _ in range(40)]
    assert len(set(choices)) == 1 and scheduler.demotions == ()
    blocked = choices[0]
    remaining = tuple(item for i, item in enumerate(candidates()) if i != blocked)
    assert scheduler.choose(remaining) in range(2)
    assert scheduler.choose(candidates()) == blocked  # Higher priority wakes again.


def test_exactly_depth_minus_one_demotions():
    scheduler = c.Pct(7, depth=3, steps=50)
    for _ in range(60):
        scheduler.choose(candidates())
    assert len(scheduler.demotions) == 2
    assert tuple(step for step, _ in scheduler.demotions) == scheduler.change_points
    assert scheduler.unused_change_points == 0


def test_demotion_affects_the_next_selection():
    scheduler = c.Pct(4, depth=2, steps=2)  # Only possible point is step 1.
    first = scheduler.choose(candidates(2))
    assert scheduler.choose(candidates(2)) != first


def test_new_task_outranks_previously_demoted_task():
    scheduler = c.Pct(4, depth=2, steps=2)
    assert scheduler.choose(candidates(1)) == 0
    assert scheduler.choose(candidates(2)) == 1
    assert scheduler.tasks_seen == 2


def test_short_execution_reports_unused_points():
    scheduler = c.Pct(3, steps=1_000_000)
    scheduler.choose(candidates())
    assert scheduler.unused_change_points == 2


def test_depth_greater_than_horizon_is_explicitly_expanded():
    scheduler = c.Pct(2, depth=5, steps=3)
    assert scheduler.steps == 3 and scheduler.horizon == 5
    assert scheduler.change_points == (1, 2, 3, 4)


def test_duplicate_id_ties_choose_lowest_tuple_position():
    same = (candidates()[0], replace(candidates()[0], index=100))
    assert c.Pct(0).choose(same) == 0


def test_history_is_detached():
    scheduler = c.Pct(0)
    scheduler.choose(candidates(1))
    scheduler.decisions.clear()
    assert scheduler.decisions == [0]


def test_global_rng_untouched():
    state = random.getstate()
    scheduler = c.Pct(0)
    scheduler.choose(candidates())
    assert random.getstate() == state


def test_invalid_empty_input_does_not_advance_rng_or_history():
    a, b = c.Pct(0), c.Pct(0)
    with pytest.raises(ValueError):
        a.choose(())
    assert a.choose(candidates()) == b.choose(candidates())
    assert a.decisions == b.decisions


@pytest.mark.parametrize(
    "field,value",
    [("depth", 0), ("depth", -1), ("depth", True), ("steps", 0), ("steps", 1.5), ("steps", None)],
)
def test_invalid_settings(field, value):
    with pytest.raises(ValueError):
        c.Pct(0, **{field: value})


@pytest.mark.parametrize("seed", [True, "1", None])
def test_invalid_seed(seed):
    with pytest.raises(TypeError):
        c.Pct(seed)


def test_pct_trial_replays_by_choices_not_a_random_seed():
    original = c.trial(clean, scheduler=c.Pct(7, steps=20))
    repeated = c.trial(clean, scheduler=c.Replay.from_trace(original.trace))
    assert original.seed == 7 and original.digest == repeated.digest
    assert "Replay" in original.reproduction()
