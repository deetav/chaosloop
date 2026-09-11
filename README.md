# chaosloop

Deterministic scheduler fuzzing for asyncio.

Your tests aren't flaky, rather opposite of flaky, and that's worse!

CPython's event loop is deterministic, so your test suite explores exactly one interleaving, every run and forever. Chaosloop takes all the other ones reproducibly.

## Quickstart

``````
python

import asyncio
import chaosloop

async def scenario() -> None:
    # Recreate mutable state INSIDE each trial.
    state = {"value": 0}

    async def reader() -> None:
        seen = state["value"]
        await asyncio.sleep(0)
        assert seen == state["value"], "value changed while reader was suspended"

    async def writer() -> None:
        await asyncio.sleep(0)
        state["value"] += 1
        
    await asyncio.gather(reader(), writer())

chaosloop.run(scenario(), scheduler=chaosloop.Fifo())

result = chaosloop.trial(scenario, seed=42)
if not result.ok:
    print(result.report())

    # A fresh Replay instance consumes the actual indices of the original run.
    replayed = chaosloop.trial(
        scenario,
        scheduler=chaosloop.Replay(result.decisions, strict=True),
    )
    assert replayed.digest == result.digest
    