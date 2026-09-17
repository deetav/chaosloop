"""b01: a delayed reader can take a stale counter snapshot before another write."""

import asyncio

import chaosloop

BUG_ID = "b01"
DESCRIPTION = "Lost update across an await"
DEPTH = 1  # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "invariant"


async def scenario() -> None:
    state = {"value": 0, "finished": 0}
    chaosloop.invariant(
        "all increments retained",
        lambda: state["finished"] < 2 or state["value"] == 2,
        detail=lambda: f"counter={state['value']}, completed={state['finished']}",
    )

    async def increment(delayed: bool) -> None:
        if delayed:
            await asyncio.sleep(0)
        old = state["value"]
        await asyncio.sleep(0)  # BUG: read/write is not one atomic operation.
        state["value"] = old + 1
        state["finished"] += 1

    await asyncio.gather(increment(False), increment(True))


def invariants() -> list[chaosloop.Invariant]:
    return []  # Runtime registration closes over fresh state inside scenario.
