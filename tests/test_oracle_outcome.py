"""Each outcome detector fires once"""

import asyncio

import pytest

import chaosloop as c
from tests.oracle_helpers import Context


async def deadlock():
    await asyncio.Future()


async def livelock():
    while True:
        await asyncio.sleep(0)


async def time_limit():
    await asyncio.sleep(100)


async def raises():
    raise AssertionError("broken")



@pytest.mark.parametrize(
    "error", [c.Deadlock("x"), c.StepBudgetExceeded("x"), c.TimeBudgetExceeded("x")]
)
def test_control_errors_do_not_double_report(error):
    assert c.UnhandledException().on_finish(Context(), c.Outcome(None, error, False)) is None



@pytest.mark.parametrize("hook", ["on_start", "on_finish"])
def test_hook_error_cleanup(hook):
    class Broken(c.OracleBase):
        pass

    def broken(*args):
        raise LookupError("bad hook")

    setattr(Broken, hook, broken)
    assert isinstance(
        c.trial(raises, oracles=[Broken()]).error, (c.OracleExecutionError, AssertionError)
    )

