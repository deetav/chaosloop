"""b08: checking done flag cannot wake a consumer already blocked on get()"""

import asyncio

import chaosloop

BUG_ID= "b08"
DESCRIPTION = "consumer waits after the final queue item"
DEPTH = 1 # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "deadlock"

async def scenario() -> None:
    queue: asyncio.Queue[str] = asyncio.Queue()
    done = False

    async def produce() -> None:
        nonlocal done
        queue.put_nowait("last item")
        await asyncio.sleep(0)
        done = True

    async def consume() -> None:
        await asyncio.sleep(0)
        while not done or not queue.empty():
            await queue.get()
            queue.task_done()

    await asyncio.gather(produce(), consume())

def invariants() -> list[chaosloop.Invariant]:
    return []
