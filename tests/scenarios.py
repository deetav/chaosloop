"""Reusable state local scenarios"""

import asyncio


async def determinism_scenario() -> tuple[list[str], list[str]]:
    """Exercise scheduling, distinct timers, lock waiters, and gather callbacks"""
    events: list[str] = []
    lock = asyncio.Lock()

    async def worker(name: str, delay: float) -> str:
        events.append(f"{name}:start")
        await asyncio.sleep(0)
        async with lock:
            events.append(f"{name}:locked")
            await asyncio.sleep(0)
        await asyncio.sleep(delay)
        events.append(f"{name}:done")
        return name
    # gather will return results in argument order not completion order
    values = await asyncio.gather(*(worker(name, i + 1.0) for i, name in enumerate("abcd")))
    return events, values

async def leftover_scenario() -> list[str]:
    """Expose cleanup order through the returned shared event list"""
    events: list[str] = []
    started = asyncio.Queue[str]()
    tasks: list[asyncio.Task[None]] = []

    async def worker(name: str) -> None:
        started.put_nowait(name)
        try:
            await asyncio.Future[None]()
        finally:
            events.append(f"{name}:cancel")
            await asyncio.sleep(0)
            events.append(f"{name}:closed")

    for name in ("alpha", "beta", "gamma"):
        tasks.append(asyncio.create_task(worker(name), name=name))
    for _ in tasks:
        await started.get()
    return events



async def pair() -> str:
    order = []

    async def append(letter):
        order.append(letter)

    await asyncio.gather(append("A"), append("B"))
    return "".join(order)


async def one_deviation() -> None:
    assert await pair() != "BA", "reversed pair"


async def two_deviations() -> None:
    first = await pair()
    second = await pair()
    # Each round joins before starting the next. Reversing BOTH pairs requires
    # an independent non-FIFO task choice in each round.
    assert (first, second) != ("BA", "BA"), "both pairs reversed"


async def clean() -> None:
    await pair()


async def empty() -> None:
    pass


async def branching() -> str:
    """Only a non-FIFO path creates the third task"""
    seen = []

    async def a():
        seen.append("A")

    async def child():
        seen.append("C")

    async def b():
        if not seen:
            await asyncio.create_task(child())
        seen.append("B")

    await asyncio.gather(a(), b())
    return "".join(seen)

