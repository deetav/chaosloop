"""b06: an error branch handles its exception but forgets to cancel a helper"""

import asyncio

import chaosloop

BUG_ID = "b06"
DESCRIPTION = "Background task leaked on a handled error path"
DEPTH = 0 # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "task_leak"


async def scenario() -> None:
    started = asyncio.Event()

    async def helper() -> None:
        started.set()
        await asyncio.Future()

    task = asyncio.create_task(helper())
    await started.wait()
    try:
        raise ValueError("request failed")
    except ValueError:
        return  # BUG: forgot task.cancel() and await its completion.
    finally:
        assert not task.done()


def invariants() -> list[chaosloop.Invariant]:
    return []
