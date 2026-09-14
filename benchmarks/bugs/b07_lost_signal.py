"""b07: a late subscriber misses a short set/clear publication window"""

import asyncio

import chaosloop

BUG_ID = "b07"
DESCRIPTION = "An Event pulse is lost before subscription"
DEPTH = 1
EXPECTED_ORACLE = "deadlock"


async def scenario() -> None:
    published = asyncio.Event()

    async def publish() -> None:
        published.set()
        await asyncio.sleep(0)
        published.clear()  # BUG: no acknowledgement that the result was consumed.

    async def consume() -> None:
        await published.wait()

    await asyncio.gather(publish(), consume())


def invariants() -> list[chaosloop.Invariant]:
    return []
