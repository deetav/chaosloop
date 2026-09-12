"""Compare observable FIFO ordering with stock asyncio"""



import asyncio

import pytest

import chaosloop


async def scenario_gather():
    events = []

    async def worker(name, rounds):
        for i in range(rounds):
            events.append(f"{name}{i}")
            await asyncio.sleep(0)

    await asyncio.gather(worker("a", 3), worker("b", 3), worker("c", 2))
    return events


async def scenario_lock():
    events = []
    lock = asyncio.Lock()

    async def worker(name):
        async with lock:
            events.append(f"{name}:in")
            await asyncio.sleep(0)
            events.append(f"{name}:out")

    await asyncio.gather(*(worker(str(i)) for i in range(4)))
    return events


async def scenario_nested_gather():
    events = []

    async def leaf(name):
        events.append(f"{name}:start")
        await asyncio.sleep(0)
        events.append(f"{name}:end")
        return name

    async def branch(name):
        result = await asyncio.gather(leaf(name + "1"), leaf(name + "2"))
        events.append("".join(result))

    await asyncio.gather(branch("a"), branch("b"))
    return events


async def scenario_task_group():
    events = []

    async def worker(name):
        events.append(f"{name}:start")
        await asyncio.sleep(0)
        events.append(f"{name}:end")

    async with asyncio.TaskGroup() as group:
        group.create_task(worker("a"))
        group.create_task(worker("b"))
    events.append("group:closed")
    return events


async def scenario_timeout():
    events = ["start"]
    try:
        async with asyncio.timeout(0.01):
            await asyncio.Future()
    except TimeoutError:
        events.append("timeout")
    await asyncio.sleep(0)
    events.append("recovered")
    return events


async def scenario_queue():
    events = []
    queue = asyncio.Queue(maxsize=1)

    async def producer():
        for item in range(3):
            await queue.put(item)
            events.append(f"put:{item}")
        await queue.join()
        events.append("joined")

    async def consumer():
        for _ in range(3):
            item = await queue.get()
            events.append(f"get:{item}")
            await asyncio.sleep(0)
            queue.task_done()

    await asyncio.gather(producer(), consumer())
    return events


async def scenario_event():
    events = []
    ready = asyncio.Event()

    async def waiter(name):
        events.append(f"{name}:wait")
        await ready.wait()
        events.append(f"{name}:go")

    tasks = [asyncio.create_task(waiter(name)) for name in "abc"]
    await asyncio.sleep(0)
    events.append("set")
    ready.set()
    await asyncio.gather(*tasks)
    return events


async def scenario_semaphore():
    events = []
    semaphore = asyncio.Semaphore(2)

    async def worker(name):
        async with semaphore:
            events.append(f"{name}:in")
            await asyncio.sleep(0)
            events.append(f"{name}:out")

    await asyncio.gather(*(worker(name) for name in "abcd"))
    return events


async def scenario_cancellation():
    events = []

    async def worker():
        try:
            events.append("waiting")
            await asyncio.Future()
        finally:
            events.append("cleanup")
            await asyncio.sleep(0)
            events.append("cleaned")

    task = asyncio.create_task(worker())
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        events.append("cancelled")
    return events


async def scenario_distinct_timers():
    events = []

    async def worker(name, delay):
        await asyncio.sleep(delay)
        events.append(name)

    await asyncio.gather(worker("late", 0.06), worker("early", 0.01), worker("middle", 0.03))
    return events


async def scenario_wait_for():
    events = []

    async def worker():
        try:
            events.append("waiting")
            await asyncio.Future()
        finally:
            events.append("cleanup")

    try:
        await asyncio.wait_for(worker(), timeout=0.01)
    except TimeoutError:
        events.append("timeout")
    return events


async def scenario_callback_creates_zero_timer():
    events = []
    loop = asyncio.get_running_loop()

    def first():
        events.append("first")
        loop.call_later(0, events.append, "timer")
        loop.call_soon(events.append, "first-child")

    def second():
        events.append("second")
        loop.call_soon(events.append, "second-child")

    loop.call_soon(first)
    loop.call_soon(second)
    await asyncio.sleep(0)
    events.append("main")
    await asyncio.sleep(0.01)
    return events


SCENARIOS = [
    scenario_gather,
    scenario_lock,
    scenario_nested_gather,
    scenario_task_group,
    scenario_timeout,
    scenario_queue,
    scenario_event,
    scenario_semaphore,
    scenario_cancellation,
    scenario_distinct_timers,
    scenario_wait_for,
    scenario_callback_creates_zero_timer,
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_fifo_matches_asyncio(scenario):
    expected = asyncio.run(scenario())
    actual = chaosloop.run(scenario(), scheduler=chaosloop.Fifo())
    assert actual == expected
