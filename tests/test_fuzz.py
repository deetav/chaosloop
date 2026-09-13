import asyncio
import importlib
import io
import itertools

import pytest

import chaosloop as c
from examples.race import scenario as race


async def clean():
    await asyncio.sleep(0)
    return 42


async def bad():
    raise ValueError("bad scenario")


def test_clean_search_runs_requested_trials():
    result = c.fuzz(clean, trials=7, corpus=None)
    assert result.ok and result.trials_run == result.fresh_trials_run == 7
    assert result.stopped_early == "trials"
    assert result.trials_per_second > 0
    assert "7 trials" in result.summary()
    assert "No failures" in result.report()


def test_fail_fast_stops_and_full_search_collects():
    result = c.fuzz(bad, trials=10, corpus=None)
    assert result.trials_run == 1 and result.stopped_early == "fail_fast"
    result = c.fuzz(bad, trials=10, fail_fast=False, corpus=None)
    assert len(result.failures) == 10 and len(result.buckets) == 1


def test_explicit_seeds_and_fresh_scheduler_factory():
    seen = []

    def factory(seed):
        seen.append(seed)
        return c.Random(seed)

    result = c.fuzz(bad, seeds=[7, 42, 99], scheduler_factory=factory, fail_fast=False, corpus=None)
    assert seen == [7, 42, 99]
    assert [run.seed for run in result.failures] == seen
    assert result.stopped_early is None


def test_infinite_seed_stream_is_bounded_and_lazy():
    calls = []

    def seeds():
        for i in itertools.count():
            calls.append(i)
            yield i

    result = c.fuzz(clean, seeds=seeds(), trials=4, corpus=None)
    assert result.trials_run == 4 and calls == [0, 1, 2, 3]


def test_custom_fifo_factory():
    assert c.fuzz(race, trials=30, scheduler_factory=lambda seed: c.Fifo(), corpus=None).ok


def test_invariants_are_forwarded():
    result = c.fuzz(clean, trials=4, invariants=[c.Invariant("no", lambda: False)], corpus=None)
    assert result.failures[0].findings[0].oracle == "invariant"


def test_fresh_custom_oracle_instances_per_trial():
    instances = []

    class Stateful(c.OracleBase):
        def __init__(self):
            self.count = 0

        def on_start(self, ctx):
            instances.append(self)
            assert self.count == 0
            self.count = 1

    original = Stateful()
    assert c.fuzz(clean, trials=4, oracles=[original], corpus=None).ok
    assert len({id(item) for item in instances}) == 4
    assert original.count == 0


def test_progress_throttles_and_has_final_notification():
    events = []
    result = c.fuzz(clean, trials=63, corpus=None, on_progress=events.append)
    assert [event.trials_done for event in events] == [25, 50, 63]
    assert events[-1].trials_total == 63
    assert events[-1].elapsed >= 0 and result.ok


def test_fail_fast_still_reports_final_progress():
    events = []
    c.fuzz(bad, trials=100, on_progress=events.append, corpus=None)
    assert len(events) == 1 and events[0].failures == 1 and events[0].distinct == 1


def test_wall_budget_stops_between_trials(monkeypatch):
    module = importlib.import_module("chaosloop.fuzz")
    values = itertools.count(0.0, 0.01)
    monkeypatch.setattr(module.time, "perf_counter", lambda: next(values))
    result = c.fuzz(clean, trials=100, time_budget=0.015, corpus=None)
    assert result.stopped_early == "time_budget" and result.trials_run == 1


def test_zero_budget_does_no_work_or_files(tmp_path):
    path = tmp_path / "absent"
    result = c.fuzz(bad, time_budget=0, corpus=path)
    assert result.trials_run == 0 and not path.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trials": -1},
        {"trials": True},
        {"trials": 1.5},
        {"max_steps": 0},
        {"max_time": -1},
        {"time_budget": -1},
        {"time_budget": float("nan")},
        {"time_budget": float("inf")},
    ],
)
def test_invalid_budget_is_api_misuse(kwargs):
    with pytest.raises((ValueError, TypeError)):
        c.fuzz(clean, corpus=None, **kwargs)


def test_invalid_scenario_and_seed():
    with pytest.raises(TypeError):
        c.fuzz(42, corpus=None)
    with pytest.raises(TypeError):
        c.fuzz(clean, seeds=[True], corpus=None)


def test_zero_trials_and_empty_seed_stream():
    result = c.fuzz(clean, trials=0, corpus=None)
    assert result.trials_run == 0 and result.ok
    assert c.fuzz(clean, seeds=[], corpus=None).trials_run == 0
    assert c.FuzzResult("x").trials_per_second == 0


def test_default_progress_silent_off_tty(monkeypatch):
    module = importlib.import_module("chaosloop.fuzz")
    stream = io.StringIO()
    monkeypatch.setattr(module.sys, "stderr", stream)
    c.default_progress(c.Progress(1, 2, 1, 1, 0.1, 7))
    assert stream.getvalue() == ""


def test_default_progress_on_tty(monkeypatch):
    module = importlib.import_module("chaosloop.fuzz")

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    stream = Terminal()
    monkeypatch.setattr(module.sys, "stderr", stream)
    c.default_progress(c.Progress(1, 2, 1, 1, 0.1, 7))
    assert "1/2" in stream.getvalue()


def test_reports_repeat_despite_timing_difference():
    first = c.fuzz(race, trials=60, fail_fast=False, corpus=None)
    second = c.fuzz(race, trials=60, fail_fast=False, corpus=None)
    assert first.report() == second.report()
    assert "trials/s" in first.report(include_timing=True)


def test_warnings_do_not_stop_search():
    result = c.fuzz(
        clean,
        trials=4,
        invariants=[c.Invariant("warn", lambda: False, c.Severity.WARNING)],
        corpus=None,
    )
    assert result.ok and len(result.warnings) == 4
    assert "warnings suppressed" in result.report()
    assert "WARNING invariant" in result.report(show_warnings=True)


def test_report_repro_includes_explicit_config():
    result = c.fuzz(clean, invariants=[c.Invariant("no", lambda: False)], corpus=None)
    assert "oracles=oracles, invariants=invariants" in result.report()
