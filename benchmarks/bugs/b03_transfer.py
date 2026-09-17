"""b03: end-state conservation hides a transient inconsistent balance.
This invariant also fails under FIFO.
"""

import asyncio

import chaosloop

BUG_ID = "b03"
DESCRIPTION = "Money disappears temporarily between debit and credit"
DEPTH = 0 # Observed FIFO deviation: 500seeds, NOT PCT DEPTH
EXPECTED_ORACLE = "invariant"

async def scenario(*, check: bool = True) -> None:
    balances = [500, 500]
    if check:
        chaosloop.invariant(
            "money conserved",
            lambda: sum(balances) == 1000,
            detail=lambda: f"balances={balances}, total={sum(balances)}",
        )
    balances[0] -= 100
    await asyncio.sleep(0)  # Other tasks could observe total=900 here.
    balances[1] += 100
    assert sum(balances) == 1000  # This passes if only the final state is inspected.


def invariants() -> list[chaosloop.Invariant]:
    return []
