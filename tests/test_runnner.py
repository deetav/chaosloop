"""public api results, misuse, budgets and cleanup boundaries"""

import asyncio

import pytest

import chaosloop


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

