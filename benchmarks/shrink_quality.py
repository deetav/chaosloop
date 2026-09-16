"""Measure all failing seeds 0..49; every accepted result is replay-verified"""

from __future__ import annotations

import json
import platform
import statistics
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chaosloop as c
from benchmarks.bugs import BUGS, settings
from benchmarks.bugs import b01_lost_update as race


async def long_scenario():
    """10,000 forced FIFO callbacks, then a schedule-sensitive lost update."""
    import asyncio

    for _ in range(10_000):
        await asyncio.sleep(0)
    await race.scenario()


def measure(seed_count: int = 50) -> dict:
    rows, before, after, costs, times = [], [], [], [], []
    for bug in BUGS:
        reductions = []
        for seed in range(seed_count):
            original = c.trial(bug.scenario, seed=seed, **settings(bug))
            if original.ok:
                continue
            reduced = c.shrink(
                bug.scenario,
                original,
                oracles=settings(bug)["oracles"],
                budget=c.ShrinkBudget(5000, 60),
            )
            assert reduced.verified and not reduced.hit_budget, bug.BUG_ID
            reductions.append(reduced)
        if not reductions:
            rows.append({"bug": bug.BUG_ID, "failures": 0})
            continue
        before.extend(r.original_deviations for r in reductions)
        after.extend(r.minimal_deviations for r in reductions)
        costs.extend(r.replays for r in reductions)
        times.extend(r.elapsed for r in reductions)
        rows.append(
            {
                "bug": bug.BUG_ID,
                "failures": len(reductions),
                "before": statistics.mean(r.original_deviations for r in reductions),
                "after": statistics.mean(r.minimal_deviations for r in reductions),
                "steps_before": statistics.mean(len(r.original) for r in reductions),
                "steps_after": statistics.mean(r.final_trial.steps for r in reductions),
                "prefix_after": statistics.mean(len(r.minimal) for r in reductions),
                "replays": statistics.mean(r.replays for r in reductions),
                "seconds": statistics.mean(r.elapsed for r in reductions),
            }
        )
    original = next(t for seed in range(50) if not (t := c.trial(long_scenario, seed=seed)).ok)
    large = c.shrink(long_scenario, original, budget=c.ShrinkBudget(5000, 60))
    assert large.verified and large.elapsed < 60
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seeds": seed_count,
        "rows": rows,
        "failures": len(after),
        "median_before": statistics.median(before),
        "median_after": statistics.median(after),
        "median_replays": statistics.median(costs),
        "median_seconds": statistics.median(times),
        "large": {
            "steps": original.steps,
            "before": large.original_deviations,
            "after": large.minimal_deviations,
            "prefix": len(large.minimal),
            "executed_steps": large.final_trial.steps,
            "replays": large.replays,
            "seconds": large.elapsed,
            "verified": large.verified,
        },
    }


def render(data: dict) -> str:
    lines = [
        "",
        f"All {data['seeds']} seeds per bug; only failing runs are shrunk. "
        "Each invocation has 5000 replays / 60 wall seconds, including guard, FIFO baseline "
        "and final verification. b06/b15 promote leaks; b11 uses max_time=60.",
        "",
        "Per-bug columns are arithmetic means across its failing seeds. "
        "The last row is the median across individual failures, not a mean of means.",
        "",
        "| Bug | Failures | Deviations before → after | Executed steps before → after | "
        "Saved prefix after | Replays | Seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["rows"]:
        if row["failures"]:
            lines.append(
                f"| {row['bug']} | {row['failures']} | {row['before']:.2f} → {row['after']:.2f} | "
                f"{row['steps_before']:.1f} → {row['steps_after']:.1f} | "
                f"{row['prefix_after']:.1f} | "
                f"{row['replays']:.1f} | {row['seconds']:.4f} |"
            )
        else:
            lines.append(f"| {row['bug']} | 0 | — | — | — | — | — |")
    lines += [
        f"| **Pooled median** | **{data['failures']}** | **{data['median_before']:g} → "
        f"{data['median_after']:g}** | — | — | **{data['median_replays']:g}** | "
        f"**{data['median_seconds']:.4f}** |",
        "",
    ]
    large = data["large"]
    lines += [
        f"The synthetic long run has **{large['steps']} executed steps**. "
        f"Shrinking took **{large['seconds']:.3f}s**, {large['replays']} replays, "
        f"{large['before']} → {large['after']} deviations. Its saved prefix still contains "
        f"{large['prefix']} choices because the long FIFO prefix precedes the race. "
        f"The final program still executes {large['executed_steps']} steps.",
        "",
        "These are measured bounded-search results, not proofs of global or exhaustive "
        "local minimality. FIFO already exposes b03 and b06, so zero deviations is correct. "
        "This corpus is deliberately small and does not establish performance on arbitrary "
        "applications. Wall timings vary by host.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    data = measure()
    text = render(data)
    Path(__file__).with_name("shrink.json").write_text(json.dumps(data, indent=2) + "\n")
    Path(__file__).with_name("shrink.md").write_text(text)
    print(text)
