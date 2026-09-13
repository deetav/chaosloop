"""b05: broken semaphore fails to reserve a woken waiter's permit"""

import asyncio
from collections import deque

import chaosloop

BUG_ID = "b05"
DESCRIPTION = "A newcomer steals a permit before an already-woken waiter resumes"
DEPTH = 1
EXPECTED_ORACLE = "invariant"

class BrokenSemaphore:
    def __init__(self) -> None:
        self.value = 1
        self.waiters: deque[asyncio.Future[None]] = deque()

    async def acquire(self) -> None:
        if self.value <= 0:
            future = asyncio.get_running_loop().create_future()
            self.waiters.append(future)
            await future
        self.value = -1

    def release(self) -> None:
        self.value += 1 #BUG: this becomes publicly available even when waking a waiter
        while self.waiters:
            future = self.waiters.popleft()
            if not future.done():
                future.set_result(None)
                break

async def scenario() -> None:
    sem = BrokenSemaphore()
    waiting = asyncio.Event()
    acquired = asyncio.Event()
    gate = asyncio.Event()
    active = 0
    chaosloop.invariant(
        "one permit means one active worker",
        lambda: active <= 1,
        detail=lambda: f"active={active}, permits={sem.value}",
    )

    async def owner() -> None:
        await sem.acquire()
        acquired.set()
        await waiting.wait()
        sem.release()  # Queues the waiter first under Fifo.
        gate.set()  # Then queues the newcomer, Random can reverse their execution.

    async def worker(newcomer: bool) -> None:
        nonlocal active
        if newcomer:
            await gate.wait()
        else:
            waiting.set()
        await sem.acquire()
        active += 1
        try:
            await asyncio.sleep(0)
        finally:
            active -= 1
            sem.release()

    # Owner acquires its initial permit before the worker tasks exist.
    task = asyncio.create_task(owner())
    await acquired.wait()
    await asyncio.gather(task, worker(False), worker(True))


def invariants() -> list[chaosloop.Invariant]:
    return []