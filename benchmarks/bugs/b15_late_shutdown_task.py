"""b15: a shutdown task snapshot misses work by a task it is awaiting"""

import asyncio

import chaosloop

BUG_ID = "b15"
DESCRIPTION = "Shutdown misses a child created after its task snapshot"
DEPTH = 1 # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "task_leak"


async def scenario() -> None:
    parent = asyncio.current_task()

    async def helper() -> None:
        await asyncio.sleep(10)  # Finishes normally if shutdown actually awaits it.

    async def spawn() -> None:
        await asyncio.sleep(0)
        asyncio.create_task(helper(), name="late-helper")  # noqa: RUF006

    async def shutdown() -> None:
        await asyncio.sleep(0)
        current = asyncio.current_task()
        snapshot = sorted(
            (task for task in asyncio.all_tasks() if task not in (parent, current)),
            key=lambda task: task.get_name(),
        )
        await asyncio.gather(*snapshot)

    await asyncio.gather(spawn(), shutdown())


def invariants() -> list[chaosloop.Invariant]:
    return []
