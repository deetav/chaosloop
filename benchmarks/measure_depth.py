"""Measure the smallest observed FIFO deviation reproducer"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.bugs import BUGS, settings
from chaosloop import Finding, ShrinkBudget, shrink, trial
from chaosloop.shrink import failure_findings


@dataclass(frozen=True, slots=True)
class DepthMeasurement:
    bug_id: str
    declared: int
    empirical: int | None
    samples: int
    distribution: dict[int, int]
    min_steps: int
    signature_samples: int = 0
    unverified: int = 0

def measure_depth(bug, *, seeds=range(500), shrink_budget = None) -> DepthMeasurement:
    template = shrink_budget if shrink_budget is not None else ShrinkBudget(2000, 10)
    distribution = Counter()
    best = None
    signatures = unverified = 0
    seen = set()
    for seed in seeds:
        if seed in seen:
            continue
        seen.add(seed)
        original = trial(bug.scenario, seed=seed, invariants=bug.invariants(), **settings(bug))
        candidates = []
        distinct = {finding.signature: finding for finding in failure_findings(original)}
        for finding in distinct.values():
            reduced = shrink(
                bug.scenario,
                original,
                finding=finding,
                budget=ShrinkBudget(template.max_replays, template.max_seconds),
                invariants=bug.invariants(),
                oracles=settings(bug)["oracles"],
            )
            if not reduced.verified:
                unverified += 1
                continue
            signatures += 1
            candidates.append((reduced.minimal_deviations, reduced.final_trial.steps))
        if candidates:
            rank = min(candidates)
            distribution[rank[0]] += 1
            best = min(best, rank) if best is not None else rank

    return DepthMeasurement(
        bug.BUG_ID,
        bug.DEPTH,
        best[0] if best else None,
        sum(distribution.values()),
        dict(sorted(distribution.items())),
        best[1] if best else 0,
        signatures,
        unverified,
    )

def render_depth(rows, seeds: int) -> str:
    lines = [
        "# Observed FIFO-deviation complexity",
        "",
        f"Measured on CPython {platform.python_version()}; {seeds} seeds per bug.",
        "",
        "These measurements are best verified reproducers, not formal PCT bug depth. "
        "Budgeted greedy shrinking does not prove local or global minimality.",
        "",
        "| Bug | Previous declaration | Observed minimum | Failing seeds | Distribution | Steps |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.bug_id} | {row.declared} | {row.empirical} | {row.samples} | "
            f"{row.distribution} | {row.min_steps} |"
        )
    lines.extend(
        [
            "",
            "Distribution counts each failing seed once using its best verified "
            "signature. Raw JSON also records signature samples and unverified shrinks.",
            "Steps refers to the complete reproduced execution, including its FIFO tail.",
        ]
    )
    return "\n".join(lines) + "\n"

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=500)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be positive")
    rows = []
    for bug in BUGS:
        row = measure_depth(bug, seeds=range(args.seeds))
        rows.append(row)
        print(f"{row.bug_id}: {row.empirical} deviations, {row.samples} failing seeds", flush=True)
    root = Path(__file__).parent
    (root / "depth.md").write_text(render_depth(rows, args.seeds))
    (root / "depth.json").write_text(
        json.dumps(
            {
                "python": platform.python_version(),
                "seeds": args.seeds,
                "shrink_max_replays": 2000,
                "shrink_max_seconds": 10,
                "metric": "observed_fifo_deviations",
                "results": [asdict(row) for row in rows],
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
