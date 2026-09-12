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
    

``````


race.py
``````
stock asyncio: 0/1000 failures
chaosloop fifO: 0/1000 failures
chaosloop seeds: 46/200 failures

FAILED  seed=2  scheduler=Random

  AssertionError: changed under me: 0 -> 1

  3 deviations from the default schedule, 9 steps
  virtual time=0; digest=da82f56d189fa0f8

 step      vtime  task          action                                    at
    1      0.000  task-1        task_step<task-1>                         runner.py:98
    2      0.000  task-2        task_step<task-2>                         race.py:12
    3      0.000  task-3        task_step<task-3>                         race.py:17
    4      0.000  task-3        task_step<task-3>  ← chose #1 of 2        tasks.py:702
    5      0.000  task-2        task_step<task-2>                         tasks.py:702
    6      0.000  -             gather.<locals>._done_callback  ← chose #1 of 2  
    7      0.000  task-1        task_wakeup<task-1>  ← chose #1 of 2      race.py:21
    8      0.000  -             gather.<locals>._done_callback            
    9      0.000  -             _run_until_complete_cb                    
3 deviations from default in 9 steps

Reproduce: chaosloop.trial(scenario, seed=2, max_steps=1000000, max_time=None)
Use the same scenario factory, inputs, code, and Python version.
Verified strict replay: da82f56d189fa0f8