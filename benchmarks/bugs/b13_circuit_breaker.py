"""b13: 2 requests both claim the single HALF_OPEN recovery probe"""

import asyncio

import chaosloop

BUG_ID = "b13"
DESCRIPTION = "Stale HALF_OPEN state admits two recovery probes"
DEPTH = 1
EXPECTED_ORACLE = "invariant"


async def scenario() -> None:
    state = {"mode": "HALF_OPEN", "failures": 3, "probes": 0}
    chaosloop.invariant(
        "breaker state and single recovery probe are consistent",
        lambda: (
            state["mode"] in {"CLOSED", "OPEN", "HALF_OPEN"}
            and (state["failures"] == 0 if state["mode"] == "CLOSED" else state["failures"] >= 3)
            and state["probes"] <= 1
        ),
    )

    async def request(delayed: bool) -> None:
        if delayed:
            await asyncio.sleep(0)
        if state["mode"] == "HALF_OPEN":
            await asyncio.sleep(0)  # BUG: no reservation before async probe setup.
            state["mode"], state["failures"] = "CLOSED", 0
            state["probes"] += 1
            await asyncio.sleep(0)
            state["probes"] -= 1

    await asyncio.gather(request(False), request(True))


def invariants() -> list[chaosloop.Invariant]:
    return []
