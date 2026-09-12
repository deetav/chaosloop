"""fixed program + fixed inputs + fixed scheduler = 1 trace"""
import pytest

import chaosloop
from tests.scenarios import determinism_scenario


def test_same_seed_same_digest_twenty_times():
    results = [chaosloop.trial(determinism_scenario, seed=1234) for _ in range(20)]
    assert all(result.ok for result in results)
    assert len({result.digest for result in results}) == 1
    assert all(result.value == results[0].value for result in results)

def test_same_seed_same_decisions_twenty_times():
    decisions = [chaosloop.trial(determinism_scenario, seed=1234).decisions for _ in range(20)]
    assert all(value == decisions[0] for value in decisions)

def test_different_seeds_explore_interleaving():
    digests = {chaosloop.trial(determinism_scenario, seed=seed).digest for seed in range(50)}
    assert len(digests) > 10

def test_fifo_is_deterministic_twenty_times():
    digests = {
        chaosloop.trial(determinism_scenario, scheduler=chaosloop.Fifo()).digest for _ in range(20)
    }
    assert len(digests) == 1

def test_strict_replay_reproduces_the_entire_successful_run():
    original = chaosloop.trial(determinism_scenario, seed=7)
    replayed = chaosloop.trial(
        determinism_scenario, scheduler=chaosloop.Replay(original.decisions, strict=True)
    )
    assert original.ok and replayed.ok
    assert replayed.digest == original.digest
    assert replayed.decisions == original.decisions
    assert replayed.value == original.value
    assert replayed.trace.steps == original.trace.steps

@pytest.mark.nightly
def test_thousand_run_determinism_soak():
    digests = set()
    for _ in range(1000):
        result = chaosloop.trial(determinism_scenario, seed=99)
        assert result.ok
        digests.add(result.digest)
    assert len(digests) == 1



