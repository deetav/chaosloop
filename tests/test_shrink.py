import asyncio
import importlib
from dataclasses import replace

import pytest

import chaosloop as c
from benchmarks.bugs import BUGS, settings
from benchmarks.bugs import b01_lost_update as race
from chaosloop.shrink import failure_findings, lower_each, make_interesting, truncate, zero_spans

module = importlib.import_module("chaosloop.shrink")


def first_failure(bug):
    return next(
        t for seed in range(2000) if not (t := c.trial(bug.scenario, seed=seed, **settings(bug))).ok
    )


@pytest.mark.parametrize("bug", BUGS, ids=lambda b: b.BUG_ID)
def test_every_bug_shrinks_and_replays_its_signature(bug):
    original = first_failure(bug)
    reduced = c.shrink(bug.scenario, original, oracles=settings(bug)["oracles"])
    replayed = c.trial(
        bug.scenario,
        scheduler=c.Replay(reduced.minimal, task_ids=reduced.minimal_task_ids, strict=True),
        **settings(bug),
    )
    assert reduced.verified and not replayed.diverged and not replayed.unused_decisions
    assert reduced.finding.signature in {f.signature for f in failure_findings(replayed)}
    assert replayed.digest == reduced.final_trial.digest
    assert reduced.minimal_deviations <= reduced.original_deviations
    assert not reduced.minimal or reduced.minimal[-1] != 0
    assert len(reduced.minimal_task_ids) == len(reduced.minimal)
    assert reduced.minimal_deviations <= 6
    assert "seed=" not in reduced.reproduction()
    assert "recorded choices" in reduced.report()


def test_full_and_fast_search_choose_same_result():
    original = first_failure(race)
    slow = c.shrink(race.scenario, original, record_trace=True)
    fast = c.shrink(race.scenario, original, record_trace=False)
    assert fast.minimal == slow.minimal and fast.replays == slow.replays
    assert original.report(shrink_result=fast) == fast.report()
    assert "FIFO (passes)" in fast.report()


@pytest.mark.parametrize("replays", [0, 1, 2, 3, 4, 5, 10, 100])
def test_budget_never_overruns_and_only_returns_verified_changes(replays):
    original = first_failure(race)
    budget = c.ShrinkBudget(replays, 60)
    result = c.shrink(race.scenario, original, budget=budget)
    assert budget.replays_used == result.replays <= replays
    assert result.verified == (replays > 0)
    if result.minimal != result.original:
        assert result.verified and result.final_trial.trace.recording
    if replays <= 1:
        assert result.minimal == original.decisions and result.hit_budget


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_replays": -1},
        {"max_replays": True},
        {"max_seconds": -1},
        {"max_seconds": float("inf")},
        {"max_seconds": float("nan")},
        {"max_seconds": True},
    ],
)
def test_invalid_budget(kwargs):
    with pytest.raises(ValueError):
        c.ShrinkBudget(**kwargs)


def test_clock_starts_on_first_spend_and_enforces_time(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: now[0])
    budget = c.ShrinkBudget(5, 2)
    now[0] = 100.0
    assert budget.elapsed == 0 and budget.spend()
    now[0] = 102.0
    assert budget.exhausted and not budget.spend() and budget.replays_used == 1


def test_cache_hits_are_free_even_after_budget_exhaustion():
    original = first_failure(race)
    budget = c.ShrinkBudget(1)
    interesting = make_interesting(race.scenario, failure_findings(original)[0], budget=budget)
    assert interesting(original.decisions)
    assert interesting(original.decisions)  # The sole replay slot is already used.
    assert budget.replays_used == 1 and not interesting([])
    with pytest.raises(ValueError):
        interesting([-1])


def test_signature_pinning_rejects_another_failure():
    original = first_failure(race)
    other = c.Finding("other", c.Severity.FAILURE, "other bug")
    assert not make_interesting(race.scenario, other)(original.decisions)
    with pytest.raises(ValueError, match="FAILURE"):
        make_interesting(race.scenario, c.Finding("w", c.Severity.WARNING, "warning"))
    with pytest.raises(c.ShrinkError, match="target"):
        c.shrink(race.scenario, original, finding=other)


def test_mutated_search_uses_new_positions_not_original_identities():
    original = first_failure(race)
    reduced = c.shrink(race.scenario, original)
    assert reduced.minimal_deviations < reduced.original_deviations
    interesting = make_interesting(race.scenario, failure_findings(original)[0])
    # Invalid large positional choices really run FIFO and are not interesting.
    assert not interesting([999] * len(original.decisions))


def test_entry_guard_rejects_changed_state():
    fail = [True]

    async def scenario():
        assert not fail[0], "original"

    original = c.trial(scenario)
    fail[0] = False
    with pytest.raises(c.ShrinkError, match="original did not reproduce"):
        c.shrink(scenario, original)


def test_final_verification_is_a_fresh_full_trial(monkeypatch):
    original = first_failure(race)
    real = module.trial
    calls = []

    def spy(*args, **kwargs):
        calls.append(kwargs.get("record_trace", True))
        result = real(*args, **kwargs)
        if len(calls) > 2 and calls[-1]:
            return replace(result, findings=(), error=None)
        return result

    monkeypatch.setattr(module, "trial", spy)
    with pytest.raises(c.ShrinkError, match="final candidate"):
        c.shrink(race.scenario, original)
    assert calls[:2] == [True, True] and False in calls[2:-1] and calls[-1]


def test_wall_timeout_before_final_reverts_to_guard(monkeypatch):
    original = first_failure(race)
    real, now = module.trial, [0.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: now[0])

    def timed(*args, **kwargs):
        result = real(*args, **kwargs)
        if not kwargs.get("record_trace", True):
            now[0] = 61.0
        return result

    monkeypatch.setattr(module, "trial", timed)
    result = c.shrink(race.scenario, original)
    assert result.hit_budget and result.verified and result.minimal == original.decisions
    assert result.final_trial.trace.recording


def test_clean_and_divergent_inputs_are_rejected():
    async def clean():
        return None

    with pytest.raises(c.ShrinkError, match="failing"):
        c.shrink(clean, c.trial(clean))
    original = first_failure(race)
    with pytest.raises(c.ShrinkError, match="unfaithful"):
        c.shrink(race.scenario, replace(original, unused_decisions=1))


def test_explicit_empty_oracles_preserve_direct_error_signature():
    async def scenario():
        raise AssertionError("always broken")

    original = c.trial(scenario, oracles=())
    result = c.shrink(scenario, original, oracles=())
    assert result.finding.oracle == "execution_error" and result.minimal == []
    assert result.reduction == 0 and "FIFO (fails)" in result.report()


def test_zero_spans_skips_zeros_and_does_not_mutate_input():
    calls = []
    original = [0] * 300 + [2]

    def interesting(candidate):
        calls.append(candidate)
        return False

    assert zero_spans(original, interesting, c.ShrinkBudget()) == original
    assert len(calls) <= 9


def test_lower_each_capped_ladder_and_no_success_terminates():
    calls = []

    def interesting(candidate):
        calls.append(candidate[0])
        return False

    assert lower_each([10_000], interesting, c.ShrinkBudget()) == [10_000]
    assert calls == [0, 1, 5000, 9999]
    assert lower_each([8], lambda ds: ds[0] >= 2, c.ShrinkBudget()) == [2]


def test_truncation_keeps_required_prefix_then_fifo():
    original = [0, 2, 0, 0, 0]
    assert truncate(original, lambda ds: len(ds) >= 2 and ds[1] == 2, c.ShrinkBudget()) == [0, 2]
    assert original == [0, 2, 0, 0, 0]
    assert truncate([], lambda ds: True, c.ShrinkBudget()) == []


def test_ten_thousand_steps_stays_within_sixty_seconds():
    async def scenario():
        for _ in range(10_000):
            await asyncio.sleep(0)
        await race.scenario()

    original = next(t for seed in range(50) if not (t := c.trial(scenario, seed=seed)).ok)
    assert original.steps >= 10_000
    reduced = c.shrink(scenario, original, budget=c.ShrinkBudget(5000, 60))
    assert reduced.verified and reduced.elapsed < 60 and reduced.minimal_deviations <= 1
