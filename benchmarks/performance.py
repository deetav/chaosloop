"""Alternate full/compact runs under identical defaults; record honest timings"""

from __future__ import annotations

import asyncio
import json
import platform
import statistics
import time
from pathlib import Path

import chaosloop as c

# ruff: noqa: E501, RUF001


async def scenario():
    for _ in range(200):
        await asyncio.sleep(0)
    return 200


def measure(iterations: int = 200, repeats: int = 5) -> dict:
    original = c.trial(scenario, seed=42)
    samples: dict[str, list[float]] = {"full": [], "compact": []}
    for repeat in range(repeats):
        for recording in (True, False) if repeat % 2 == 0 else (False, True):
            start = time.perf_counter()
            for _ in range(iterations):
                result = c.trial(
                    scenario, scheduler=c.Replay.from_trace(original.trace), record_trace=recording
                )
                assert result.ok and result.decisions == original.decisions
            samples["full" if recording else "compact"].append(time.perf_counter() - start)
    compact = c.trial(scenario, scheduler=c.Replay.from_trace(original.trace), record_trace=False)
    assert compact.digest == original.digest and compact.trace.render() == ""
    before, after = (statistics.median(samples[name]) for name in ("full", "compact"))
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "iterations": iterations,
        "repeats": repeats,
        "steps": original.steps,
        "samples": samples,
        "full_seconds": before,
        "compact_seconds": after,
        "speedup": before / after,
    }


def render(data: dict) -> str:
    return f"""# Replay performance

Each sample runs {data["iterations"]} identity replays of the same {data["steps"]}-step scenario.
Five samples alternate full and compact order, with the same default oracles and scenario state.
The figures below are medians of those sample times; this is a microbenchmark, not a universal gain.

| Mode | Median batch seconds | Per replay milliseconds |
| --- | ---: | ---: |
| Before: full Step history | {data["full_seconds"]:.4f} | {1000 * data["full_seconds"] / data["iterations"]:.3f} |
| After: compact structural rows | {data["compact_seconds"]:.4f} | {1000 * data["compact_seconds"] / data["iterations"]:.3f} |

Observed speedup: **{data["speedup"]:.2f}×**. Raw samples are in `benchmarks/performance.json`.
Digest, decisions, executed step count and findings have separate parity tests across all 15 bugs × 50 seeds.

"""


if __name__ == "__main__":
    data = measure()
    Path(__file__).with_name("performance.json").write_text(json.dumps(data, indent=2) + "\n")
    text = render(data)
    (Path(__file__).resolve().parents[1] / "docs" / "performance.md").write_text(text)
    print(text)
