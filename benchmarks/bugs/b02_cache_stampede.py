"""b02: cache existence is checked before an awaited load"""

import asyncio

import chaosloop

BUG_ID = "b02"
DESCRIPTION = "Two loads race for the same cache key"
DEPTH = 1
EXPECTED_ORACLE = "unhandled_exception"


async def scenario() -> None:
    cache = {}
    loads = 0

    async def get(delayed: bool) -> int:
        nonlocal loads
        if delayed:
            await asyncio.sleep(0)
        if "key" not in cache:
            loads += 1
            await asyncio.sleep(0)  # Another task may see the same absent key.
            cache["key"] = 42
        return cache["key"]

    await asyncio.gather(get(False), get(True))
    assert loads == 1, f"expected 1 load, got {loads}"


def invariants() -> list[chaosloop.Invariant]:
    return []
