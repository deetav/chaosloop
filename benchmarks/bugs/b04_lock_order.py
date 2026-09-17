"""b04: AB and BA acquisition paths deadlock only when BA gets ahead early"""

import asyncio

import chaosloop

BUG_ID = "b04"
DESCRIPTION = "Opposite lock ordering under a particular interleaving"
DEPTH = 2 # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "deadlock"

async def scenario() -> None:
    a, b = asyncio.Lock(), asyncio.Lock()

    async def ab() -> None:
        async with a, b:
            await asyncio.sleep(0)

    async def ba() -> None:
        await asyncio.sleep(0)
        async with b:
            await asyncio.sleep(0)
            async with a:
                pass
    await asyncio.gather(ab(), ba())

def invariants() -> list[chaosloop.Invariant]:
    return []
