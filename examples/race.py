"""A race condition stock asyncio cannot find"""

import asyncio

import chaosloop


async def scenario() -> None:
    """The reader assumes a shared value cannot change across an await"""
    state = {"value": 0}

    async def reader() -> None:
        seen = state["value"]
        await asyncio.sleep(0)
        assert seen == state["value"], f"changed under me: {seen} -> {state['value']}"

    async def writer() -> None:
        await asyncio.sleep(0)
        state["value"] += 1

    await asyncio.gather(reader(), writer())

def main() -> None:
    """Measures all three baselines, verify the discovered failure"""
    stock_failures = 0
    for _ in range(10_000):
        try:
            asyncio.run(scenario())
        except AssertionError:
            stock_failures += 1
    print(f"stock asyncio: {stock_failures}/1000 failures")

    fifo_failures = sum(
        not chaosloop.trial(scenario, scheduler=chaosloop.Fifo()).ok for _ in range(1000)
    )
    print(f"chaosloop fifO: {fifo_failures}/1000 failures")

    found = [
        result for seed in range(200) if not (result := chaosloop.trial(scenario, seed=seed)).ok
    ]
    print(f"chaosloop seeds: {len(found)}/200 failures")
    if found:
        first = found[0]
        print()
        print(first.report())
        replayed = chaosloop.trial(
            scenario, scheduler=chaosloop.Replay(first.decisions, strict=True)
        )
        assert not replayed.ok
        assert replayed.digest == first.digest
        assert type(replayed.error) is type(first.error)
        print(f"Verified strict replay: {replayed.digest}")

if __name__ == "__main__":
    main()
