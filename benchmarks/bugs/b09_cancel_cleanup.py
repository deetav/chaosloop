"""b09: cancellation inside finally interrupts an asynchronous release"""

import asyncio

import chaosloop

BUG_ID = "b09"
DESCRIPTION = "Cancellation interrupts resource release"
DEPTH = 1 # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "invariant"


async def scenario() -> None:
    state = {"acquired": False, "finished": False}
    cleaning = asyncio.Event()
    chaosloop.invariant(
        "terminated worker releases its resource",
        lambda: not state["finished"] or not state["acquired"],
    )

    async def work() -> None:
        state["acquired"] = True
        try:
            await asyncio.sleep(0)
        finally:
            cleaning.set()
            await asyncio.sleep(0)  # BUG: cancellation here skips the next line.
            state["acquired"] = False

    worker = asyncio.create_task(work())

    async def cancel() -> None:
        await cleaning.wait()
        await asyncio.sleep(0)
        worker.cancel()

    await asyncio.gather(worker, cancel(), return_exceptions=True)
    state["finished"] = True


def invariants() -> list[chaosloop.Invariant]:
    return []
