import asyncio
from collections import deque


class BuggyLock:
    """A canceled already woken waiter loses its reserved lock handoff"""
    def __init__(self) -> None:
        self.locked = False
        self.waiters: deque[asyncio.Future[None]] = deque()

    async def acquire(self) -> None:
        if not self.locked:
            self.locked = True
            return
        waiter = asyncio.get_running_loop().create_future()
        self.waiters.append(waiter)
        try:
            await waiter
        finally:
            self.waiters.remove(waiter)
            # BUG: cancellation after set_result needs another wakeup here

    def release(self) -> None:
        for waiter in self.waiters:
            if not waiter.done():
                waiter.set_result(None)
                return #keeping locked=True ownership is reserved for this waiter
        self.locked = False

# owner releases -> A gets reserved ownership -> A canceled before resuming ->
# reservation disappears => B waits

class BuggySemaphore:
    """wake everybody without reserving permits, so awakened waiter over-admit"""

    def __init__(self, value: int = 1) -> None:
        self.value = value
        self.waiters: deque[asyncio.Future[None]] = deque()

    async def acquire(self) -> None:
        if self.value == 0:
            waiter = asyncio.get_running_loop().create_future()
            self.waiters.append(waiter)
            try:
                await waiter
            finally:
                self.waiters.remove(waiter)
        self.value -= 1 #BUG: every awakened task treats the same permit as its own

    def release(self) -> None:
        self.value += 1
        for waiter in self.waiters:
            if not waiter.done():
                waiter.set_result(None)

class BuggyPool:
    """returns a cached available connection after an unprotected handshake"""
    def __init__(self) -> None:
        self.available = ["connection-1"]
        self.changed = asyncio.Event()

    async def acquire(self) -> str:
        while not self.available:
            self.changed.clear()
            await self.changed.wait()
        connection = self.available[0]
        await asyncio.sleep(0) # BUG: another task can check out this connection
        if connection in self.available:
            self.available.remove(connection)
        return connection

    def release(self, connection:str) -> None:
        self.available.append(connection)
        self.changed.set()


class SharedBackoff:
    """Independent operations accidentally share an exponentially growing delay"""
    def __init__(self) -> None:
        self.delay = 8.0

    async def failure(self) -> float:
        self.delay *= 2
        await asyncio.sleep(0)
        return self.delay #BUG: reads everyone's new delay instead of this operation's

    def success(self) -> None:
        self.delay = 8.0
