"""Small importable scenarios shared by CLI tests and doctor workers."""

import asyncio
import time


async def clean():
    await asyncio.sleep(0)
    return {"answer": 42}


async def broken():
    raise AssertionError("example bug")


async def noisy():
    print("scenario log")
    return await clean()


async def clock_user():
    return time.monotonic()


async def leak():
    asyncio.create_task(asyncio.sleep(10))  # noqa: RUF006 -- fixture for the task-leak detector.


async def bounded():
    await asyncio.sleep(100)


async def spin():
    while True:
        await asyncio.sleep(0)


async def opaque():
    return object()


def invalid():
    return 123  # A valid zero-argument signature, but an invalid factory result.


async def exits():
    raise SystemExit(9)
