"""public api results, misuse, budgets and cleanup boundaries"""

import asyncio

import pytest

import chaosloop
from examples.race import scenario as race_scenario
from tests.scenarios import leftover_scenario


async def answer():
    await asyncio.sleep(0)
    return {"answer": 42}


async def failure():
    raise ValueError("scenario failed")


def test_run_returns_value():
    assert chaosloop.run(answer()) == {"answer": 42}


def test_run_propagates_scenario_exception():
    with pytest.raises(ValueError, match="scenario failed"):
        chaosloop.run(failure())


def test_trial_success_records_value_and_metadata():
    result = chaosloop.trial(answer, seed=42)
    assert result.ok
    assert result.value == {"answer": 42}
    assert result.error is None
    assert result.seed == 42
    assert result.steps == len(result.trace.steps) > 0
    assert result.decisions == result.trace.decisions
    assert result.digest == result.trace.digest()
    assert result.vtime == 0


def test_trial_captures_ordinary_scenario_failure():
    result = chaosloop.trial(failure)
    assert not result.ok
    assert result.value is None
    assert isinstance(result.error, ValueError)
    assert str(result.error) == "scenario failed"


def test_callback_failure_is_reported_by_trial():
    def broken_callback():
        raise LookupError("callback failed")

    async def main():
        asyncio.get_running_loop().call_soon(broken_callback)
        await asyncio.sleep(0)

    result = chaosloop.trial(main)
    assert not result.ok
    assert isinstance(result.error, LookupError)


def test_unobserved_background_task_failure_is_reported():
    tasks = []

    async def broken():
        raise LookupError("background failed")

    async def main():
        tasks.append(asyncio.create_task(broken()))
        await asyncio.sleep(0)

    result = chaosloop.trial(main)
    assert not result.ok
    assert isinstance(result.error, LookupError)


def test_explicitly_handled_child_failure_does_not_fail_trial():
    async def broken():
        raise LookupError("expected failure")

    async def main():
        task = asyncio.create_task(broken())
        try:
            await task
        except LookupError:
            return "handled"

    result = chaosloop.trial(main)
    assert result.ok and result.value == "handled"


def test_trial_captures_factory_failure():
    def factory():
        raise LookupError("factory failed")

    result = chaosloop.trial(factory)
    assert not result.ok
    assert isinstance(result.error, LookupError)


def test_factory_called_exactly_once_per_trial():
    calls = []

    def factory():
        calls.append("called")
        return answer()

    assert chaosloop.trial(factory).ok
    assert calls == ["called"]


def test_trial_captures_deadlock():
    async def stuck():
        await asyncio.Future()

    result = chaosloop.trial(stuck)
    assert not result.ok
    assert isinstance(result.error, chaosloop.Deadlock)
    assert result.steps >= 1


def test_trial_captures_cancelled_main_task():
    async def cancelled():
        raise asyncio.CancelledError("user cancelled")

    result = chaosloop.trial(cancelled)
    assert not result.ok
    assert isinstance(result.error, asyncio.CancelledError)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_process_control_exceptions_propagate(interrupt):
    async def interrupted():
        raise interrupt("stop")

    with pytest.raises(interrupt, match="stop"):
        chaosloop.trial(interrupted)


def test_seed_and_scheduler_are_mutually_exclusive():
    with pytest.raises(TypeError):
        chaosloop.trial(answer, seed=42, scheduler=chaosloop.Fifo())


def test_run_seed_and_scheduler_are_mutually_exclusive():
    coroutine = answer()
    try:
        with pytest.raises(TypeError):
            chaosloop.run(coroutine, seed=42, scheduler=chaosloop.Fifo())
    finally:
        coroutine.close()


def test_default_scheduler_is_fifo():
    result = chaosloop.trial(answer)
    assert result.trace.scheduler == "Fifo"
    assert set(result.decisions) == {0}


def test_scheduler_object_seed_is_retained_in_result():
    result = chaosloop.trial(answer, scheduler=chaosloop.Random(17))
    assert result.seed == 17


def test_repeated_pending_leftovers_have_identical_digests():
    first = chaosloop.trial(leftover_scenario, seed=81)
    second = chaosloop.trial(leftover_scenario, seed=81)
    assert first.ok and second.ok
    assert first.digest == second.digest
    assert first.value == second.value
    assert len(first.value) == 6


def test_cleanup_runs_even_when_main_raises():
    events = []

    async def main():
        started = asyncio.Event()

        async def child():
            started.set()
            try:
                await asyncio.Future()
            finally:
                events.append("closed")

        task = asyncio.create_task(child())
        await started.wait()
        assert not task.done()
        raise ValueError("main failed")

    result = chaosloop.trial(main)
    assert isinstance(result.error, ValueError)
    assert events == ["closed"]


def test_shutdown_closes_asynchronous_generators():
    events = []
    generators = []

    async def stream():
        try:
            yield 1
            yield 2
        finally:
            await asyncio.sleep(0)
            events.append("closed")

    async def main():
        generator = stream()
        generators.append(generator)  # Keep it alive until runner shutdown.
        return await anext(generator)

    result = chaosloop.trial(main)
    assert result.ok and result.value == 1
    assert events == ["closed"]


def test_step_budget_is_a_captured_finding_and_cleanup_can_finish():
    events = []

    async def livelock():
        try:
            while True:
                await asyncio.sleep(0)
        finally:
            await asyncio.sleep(0)
            events.append("closed")

    result = chaosloop.trial(livelock, max_steps=5)
    assert isinstance(result.error, chaosloop.StepBudgetExceeded)
    assert result.steps == 5
    assert events == ["closed"]


def test_cleanup_that_ignores_cancellation_has_an_independent_bound():
    tasks = []

    async def main():
        started = asyncio.Event()

        async def stubborn():
            started.set()
            while True:
                try:
                    await asyncio.sleep(0)
                except asyncio.CancelledError:
                    # This deliberately broken task refuses the runner's
                    # cancellation request; cleanup must still return.
                    continue

        tasks.append(asyncio.create_task(stubborn()))
        await started.wait()

    try:
        result = chaosloop.trial(main, max_steps=20)
        assert isinstance(result.error, chaosloop.StepBudgetExceeded)
        assert "cleanup" in str(result.error).lower()
        assert result.steps < 20
    finally:
        # The test deliberately created an uncooperative coroutine. Explicitly
        # close its frame once the loop is closed, so the test retains no live
        # suspended generator after proving that the runner is bounded.
        for task in tasks:
            task.get_coro().close()


def test_time_budget_is_a_captured_finding():
    async def too_late():
        await asyncio.sleep(6)

    result = chaosloop.trial(too_late, max_time=5)
    assert isinstance(result.error, chaosloop.TimeBudgetExceeded)
    assert result.vtime <= 5


@pytest.mark.parametrize("max_steps", [0, -1, 1.5, True])
def test_invalid_step_budget_is_api_misuse(max_steps):
    with pytest.raises((TypeError, ValueError)):
        chaosloop.trial(answer, max_steps=max_steps)


@pytest.mark.parametrize("max_time", [-1, float("nan"), float("inf"), float("-inf")])
def test_invalid_time_budget_is_api_misuse(max_time):
    with pytest.raises((TypeError, ValueError)):
        chaosloop.trial(answer, max_time=max_time)


def test_zero_time_budget_allows_zero_duration_work():
    assert chaosloop.trial(answer, max_time=0).ok


def test_trial_rejects_a_coroutine_object():
    coroutine = answer()
    try:
        with pytest.raises(TypeError):
            chaosloop.trial(coroutine)
    finally:
        coroutine.close()


def test_run_rejects_a_factory():
    with pytest.raises(TypeError):
        chaosloop.run(answer)


def test_trial_rejects_a_factory_that_does_not_return_a_coroutine():
    with pytest.raises(TypeError):
        chaosloop.trial(lambda: 42)


def test_task_group_failure_cancels_and_joins_siblings():
    events = []

    async def main():
        started = asyncio.Event()

        async def sibling():
            started.set()
            try:
                await asyncio.Future()
            finally:
                await asyncio.sleep(0)
                events.append("joined")

        async def broken():
            await started.wait()
            raise AssertionError("task group failed")

        async with asyncio.TaskGroup() as group:
            group.create_task(sibling())
            group.create_task(broken())

    result = chaosloop.trial(main)
    assert isinstance(result.error, ExceptionGroup)
    assert isinstance(result.error.exceptions[0], AssertionError)
    assert events == ["joined"]


def test_nested_runner_rejected_without_changing_running_loop():
    async def main():
        before = asyncio.get_running_loop()
        with pytest.raises(RuntimeError):
            chaosloop.trial(answer)
        assert asyncio.get_running_loop() is before
        return "still running"

    assert asyncio.run(main()) == "still running"


def test_failure_report_includes_error_deviations_and_reproduction():
    result = next(
        result for seed in range(50) if not (result := chaosloop.trial(race_scenario, seed=seed)).ok
    )
    report = result.report()
    assert "AssertionError" in report
    assert "changed under me" in report
    assert "deviation" in report.lower()
    assert "step" in report.lower()
    assert "Reproduce" in report
    assert f"seed={result.seed}" in report


def test_success_report_is_useful():
    report = chaosloop.trial(answer).report()
    assert "PASS" in report.upper() or "OK" in report.upper()
    assert "step" in report.lower()


def test_private_event_loop_is_not_a_public_export():
    assert "ChaosEventLoop" not in chaosloop.__all__
    assert "ReplayMismatch" in chaosloop.__all__
    assert "StepEvent" in chaosloop.__all__

