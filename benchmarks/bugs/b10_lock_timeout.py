"""b10: Lost wakeup via unhandled lock cancellation"""

import asyncio

import chaosloop
from benchmarks.bugs._primitives import BuggyLock

BUG_ID = "b10"
DESCRIPTION = "Timed-out lock waiter loses the ownership handoff"
DEPTH = 1
EXPECTED_ORACLE = "deadlock"


async def scenario() -> None:
    lock = BuggyLock()
    await lock.acquire()

    async def impatient() -> None:
        try:
            async with asyncio.timeout(0):
                await lock.acquire()
                lock.release()
        except TimeoutError:
            pass  # Expected timeout; the successor should still acquire.

    async def patient() -> None:
        await asyncio.sleep(0)
        await lock.acquire()
        lock.release()

    async def owner() -> None:
        await asyncio.sleep(0)
        lock.release()

    await asyncio.gather(impatient(), patient(), owner())


def invariants() -> list[chaosloop.Invariant]:
    return []
