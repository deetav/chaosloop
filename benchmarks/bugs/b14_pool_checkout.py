"""b14: 2 handshakes return the same connection from a stale availability check"""

import asyncio

import chaosloop
from benchmarks.bugs._primitives import BuggyPool

BUG_ID = "b14"
DESCRIPTION = "A pool checks out one connection to two borrowers"
DEPTH = 1 # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "invariant"


async def scenario() -> None:
    pool = BuggyPool()
    borrowers: dict[str, int] = {}
    chaosloop.invariant(
        "one borrower per connection", lambda: all(n <= 1 for n in borrowers.values())
    )

    async def use(delayed: bool) -> None:
        if delayed:
            await asyncio.sleep(0)
        connection = await pool.acquire()
        borrowers[connection] = borrowers.get(connection, 0) + 1
        try:
            await asyncio.sleep(0)
        finally:
            borrowers[connection] -= 1
            pool.release(connection)

    await asyncio.gather(use(False), use(True))


def invariants() -> list[chaosloop.Invariant]:
    return []
