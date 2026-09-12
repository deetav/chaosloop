import asyncio

import chaosloop
from benchmarks.bugs.b03_transfer import scenario


def main() -> None:
    asyncio.run(scenario(check=False))
    print("stock asyncio + final assertion: passed")
    fifo = chaosloop.trial(scenario, scheduler=chaosloop.Fifo())
    print("FIFO + per step invariant:")
    print(fifo.report())
    result = chaosloop.fuzz(scenario, trials=200, fail_fast=False, corpus=None)
    print(result.report())

if __name__ == "__main__":
    main()

