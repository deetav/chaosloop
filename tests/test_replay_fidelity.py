import pytest

import chaosloop as c
from benchmarks.bugs import BUGS, settings


def signature(run):
    return [finding.signature for finding in run.findings]

def faithful(bug, original):
    replayed = c.trial(
        bug.scenario, scheduler=c.Replay.from_trace(original.trace, strict=True), **settings(bug)
    )
    assert not replayed.diverged and not replayed.unused_decisions
    assert replayed.digest == original.digest
    assert signature(replayed) == signature(original)
    assert replayed.ok == original.ok
    return replayed

@pytest.mark.parametrize("bug", BUGS, ids=lambda bug: bug.BUG_ID)
def test_fifty_seeds_and_idempotent_replay(bug):
    for seed in range(50):
        original = c.trial(bug.scenario, seed=seed, **settings(bug))
        replayed = faithful(bug, original)
        faithful(bug, replayed)
        positional = c.trial(
            bug.scenario,
            scheduler=c.Replay.from_decisions(original.decisions, strict=True),
            **settings(bug)
        )
        assert positional.digest == original.digest

@pytest.mark.parametrize("bug", BUGS, ids=lambda bug: bug.BUG_ID)
def test_failure_reproduce_one_hundred_times(bug):
    original = next(
        run
        for seed in range(2000)
        if not (run := c.trial(bug.scenario, seed=seed, **settings(bug))).ok
    )
    for _ in range(100):
        faithful(bug, original)

@pytest.mark.nightly
def test_fidelity_soak():
    for seed in range(1000):
        bug = BUGS[seed % len(BUGS)]
        faithful(bug, c.trial(bug.scenario, seed=seed, **settings(bug)))
