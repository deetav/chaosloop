"""b11: independent retry failures amplify a shared delay 60+"""

import asyncio

import chaosloop
from benchmarks.bugs._primitives import SharedBackoff

BUG_ID = "b11"
DESCRIPTION = "Independent retries multiply one shared backoff"
DEPTH = 1
EXPECTED_ORACLE = "time_budget"
MAX_TIME = 60.0


async def scenario() -> None:
    backoff = SharedBackoff()

    async def retry() -> None:
        delay = await backoff.failure()
        await asyncio.sleep(delay)

    async def healthy_request() -> None:
        backoff.success()

    await asyncio.gather(retry(), retry(), retry(), healthy_request())


def invariants() -> list[chaosloop.Invariant]:
    return []