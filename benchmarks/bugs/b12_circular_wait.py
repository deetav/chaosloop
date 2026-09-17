"""b12: 3 distinct first lock owners are needed to  close a circular wait"""

import asyncio

import chaosloop

BUG_ID = "b12"
DESCRIPTION = "Three tasks acquire A->B, B->C, C->A"
DEPTH = 2 # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "deadlock"


async def scenario() -> None:
    locks = [asyncio.Lock() for _ in range(3)]

    async def request(index: int) -> None:
        for _ in range(index):
            await asyncio.sleep(0)  # Different amounts of preparation work.
        async with locks[index]:
            await asyncio.sleep(0)
            async with locks[(index + 1) % 3]:
                pass

    await asyncio.gather(*(request(index) for index in range(3)))


def invariants() -> list[chaosloop.Invariant]:
    return []
